"""
Circuit Block Compiler -- Maps each TransformPlan stage to a concrete circuit block,
resolves component values against inventory, and assembles the full circuit graph.

Handles per-topology bias calculations (BJT, op-amp, JFET), parses SPICE templates
for correct node assignment, and recalculates dependent values after inventory
substitution.
"""

import json
import math
import re
from pathlib import Path
from typing import Any, Optional

from backend.models.transform_plan import TransformPlan, TransformStage
from backend.models.circuit import CircuitGraph, CircuitComponent, CircuitNode, StageInfo
from backend.engine.parameter_engine import (
    snap_to_e_series,
    snap_to_inventory,
    format_resistance,
    format_capacitance,
    CircuitCalc,
)

BLOCKS_DIR = Path(__file__).parent.parent / "blocks"

# ---------------------------------------------------------------------------
# Transform-to-block mapping (unchanged)
# ---------------------------------------------------------------------------

TRANSFORM_TO_BLOCKS: dict[str, list[dict]] = {
    "buffer_input": [
        {"dir": "buffers", "id": "jfet_source_follower", "priority": 1},
        {"dir": "buffers", "id": "bjt_emitter_follower", "priority": 2},
    ],
    "buffer_output": [
        {"dir": "buffers", "id": "opamp_voltage_follower", "priority": 1},
        {"dir": "buffers", "id": "bjt_emitter_follower", "priority": 2},
    ],
    "gain_clean": [
        {"dir": "gain", "id": "opamp_noninverting", "priority": 1},
        {"dir": "gain", "id": "bjt_common_emitter", "priority": 2},
        {"dir": "gain", "id": "jfet_common_source", "priority": 3},
    ],
    "gain_soft_clip": [
        {"dir": "clipping", "id": "opamp_silicon_soft_clip", "priority": 1, "match": {"diode": "silicon"}},
        {"dir": "clipping", "id": "opamp_germanium_soft_clip", "priority": 1, "match": {"diode": "germanium"}},
        {"dir": "clipping", "id": "opamp_led_soft_clip", "priority": 1, "match": {"diode": "led"}},
        {"dir": "clipping", "id": "opamp_silicon_soft_clip", "priority": 2},
    ],
    "gain_hard_clip": [
        {"dir": "clipping", "id": "opamp_hard_clip", "priority": 1},
    ],
    "gain_asymmetric": [
        {"dir": "clipping", "id": "opamp_asymmetric_clip", "priority": 1},
    ],
    "gain_fuzz": [
        {"dir": "clipping", "id": "germanium_fuzz", "priority": 1, "match": {"transistor": "germanium"}},
        {"dir": "clipping", "id": "bjt_fuzz", "priority": 1},
    ],
    "filter_lp": [
        {"dir": "filters", "id": "rc_lowpass", "priority": 1},
        {"dir": "filters", "id": "sallen_key_lowpass", "priority": 2},
    ],
    "filter_hp": [
        {"dir": "filters", "id": "rc_highpass", "priority": 1},
    ],
    "filter_bp": [
        {"dir": "filters", "id": "gyrator_mid_boost", "priority": 1},
    ],
    "filter_tonestack": [
        {"dir": "filters", "id": "baxandall_tonestack", "priority": 1, "match": {"type": "baxandall"}},
        {"dir": "filters", "id": "fender_tonestack", "priority": 1, "match": {"type": "fender"}},
        {"dir": "filters", "id": "marshall_tonestack", "priority": 1, "match": {"type": "marshall"}},
        {"dir": "filters", "id": "baxandall_tonestack", "priority": 2},
    ],
    "filter_notch": [
        {"dir": "filters", "id": "gyrator_mid_boost", "priority": 1},  # reconfigured as notch
    ],
    "compress": [
        {"dir": "compression", "id": "ota_compressor", "priority": 1},
        {"dir": "compression", "id": "jfet_gain_cell", "priority": 2},
    ],
    "modulate_tremolo": [
        {"dir": "modulation", "id": "tremolo", "priority": 1},
    ],
}

# ---------------------------------------------------------------------------
# External / global node names that do NOT get namespaced
# ---------------------------------------------------------------------------

_GLOBAL_NODES = frozenset({"in", "out", "vcc", "gnd"})

# Roles considered bias-critical -- if inventory changes these, the stage
# must be recalculated and the operating point re-verified.
_BIAS_CRITICAL_ROLES = frozenset({
    "collector_load", "emitter_degeneration", "emitter",
    "bias_top", "bias_bottom", "bias_divider_upper", "bias_divider_lower",
    "source_load", "drain_load",
})

# Default next-stage input impedance for output coupling cap calculation
_DEFAULT_RLOAD = 10_000.0  # 10 kohm

# ---------------------------------------------------------------------------
# Block loading and selection (unchanged)
# ---------------------------------------------------------------------------


def load_block(subdir: str, block_id: str) -> Optional[dict]:
    """Load a block definition JSON file."""
    path = BLOCKS_DIR / subdir / f"{block_id}.json"
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)


def select_block(transform: str, params: dict, available_inventory: Optional[dict] = None) -> Optional[dict]:
    """
    Select the best block for a transform, considering params and inventory.
    Returns the loaded block definition.
    """
    candidates = TRANSFORM_TO_BLOCKS.get(transform, [])
    if not candidates:
        return None

    # Sort by priority
    candidates = sorted(candidates, key=lambda c: c["priority"])

    # Try matching candidates with param preferences first
    for candidate in candidates:
        match = candidate.get("match")
        if match:
            if all(params.get(k) == v for k, v in match.items()):
                block = load_block(candidate["dir"], candidate["id"])
                if block:
                    return block

    # Fall back to first available
    for candidate in candidates:
        if "match" not in candidate:
            block = load_block(candidate["dir"], candidate["id"])
            if block:
                return block

    # Last resort: try any
    for candidate in candidates:
        block = load_block(candidate["dir"], candidate["id"])
        if block:
            return block

    return None


# ---------------------------------------------------------------------------
# Top-level compiler
# ---------------------------------------------------------------------------


def compile_circuit(plan: TransformPlan, inventory_values: Optional[dict] = None,
                    supply_voltage: float = 9.0) -> CircuitGraph:
    """
    Compile a TransformPlan into a full CircuitGraph.

    Args:
        plan: The transform plan to compile
        inventory_values: Dict mapping component types to lists of available values
        supply_voltage: Power supply voltage

    Returns:
        Complete CircuitGraph with all components, nodes, and connections
    """
    graph = CircuitGraph()
    all_components: list[CircuitComponent] = []
    all_stages: list[StageInfo] = []
    pots: list[dict] = []
    prev_output_node = "input"

    for stage_idx, stage in enumerate(plan.stages):
        prefix = f"S{stage_idx}"

        # Select block
        block = select_block(stage.transform, stage.params, inventory_values)
        if block is None:
            # Create a pass-through if no block found
            all_stages.append(StageInfo(
                stage_index=stage_idx,
                block_id="passthrough",
                transform=stage.transform,
                params=stage.params,
            ))
            continue

        # Calculate component values and assign correct nodes
        stage_components, component_values, stage_node_map = _instantiate_block(
            block, stage.params, prefix, supply_voltage, inventory_values
        )

        # Wire up: connect input of this stage to output of previous
        stage_input_node = f"{prefix}_in"
        stage_output_node = f"{prefix}_out"

        # Add coupling cap between stages (except first/last)
        if stage_idx > 0 and stage.transform != "buffer_input":
            coupling_cap = CircuitComponent(
                id=f"{prefix}_Cc",
                type="capacitor",
                value=1e-6,  # 1uF default coupling
                value_display="1uF",
                role="coupling",
                nodes=[prev_output_node, stage_input_node],
            )
            all_components.append(coupling_cap)

        # Remap component nodes: namespace internal nodes, map external nodes
        for comp in stage_components:
            remapped_nodes = []
            for node in comp.nodes:
                if node == "in":
                    remapped_nodes.append(stage_input_node)
                elif node == "out":
                    remapped_nodes.append(stage_output_node)
                elif node == "vcc":
                    remapped_nodes.append("vcc")
                elif node == "gnd":
                    remapped_nodes.append("gnd")
                else:
                    remapped_nodes.append(f"{prefix}_{node}")
            comp.nodes = remapped_nodes
            all_components.append(comp)

        # Track pots
        for comp in stage_components:
            if comp.type == "potentiometer":
                pots.append({
                    "component_id": comp.id,
                    "stage_index": stage_idx,
                    "role": comp.role,
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.5,
                    "label": comp.role.replace("_", " ").title(),
                })

        stage_info = StageInfo(
            stage_index=stage_idx,
            block_id=block.get("id", "unknown"),
            transform=stage.transform,
            params=stage.params,
            components=[c.id for c in stage_components],
            spice_template=block.get("spice_template", ""),
            component_values=component_values,
            node_map=stage_node_map,
        )
        all_stages.append(stage_info)

        prev_output_node = stage_output_node

    # Connect final stage output to circuit output
    if prev_output_node != "output":
        coupling_out = CircuitComponent(
            id="Cout",
            type="capacitor",
            value=10e-6,
            value_display="10uF",
            role="output_coupling",
            nodes=[prev_output_node, "output"],
        )
        all_components.append(coupling_out)

    graph.components = all_components
    graph.stages = all_stages
    graph.pots = pots

    return graph


# ---------------------------------------------------------------------------
# SPICE template node parsing
# ---------------------------------------------------------------------------

# Regex for a SPICE component line.  Matches lines like:
#   Rc vcc collector {{Rc}}
#   Q1 collector base emitter Q2N3904
#   XU1 noninv inv out vcc vee TL071_model
# Ignores .model / .subckt / .ends / + continuation / Vcc source lines.
_SPICE_COMPONENT_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9_]*)\s+(.+)$"
)

# Placeholder pattern  {{Rc}}
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _parse_spice_template_nodes(spice_template: str) -> dict[str, list[str]]:
    """Parse a SPICE template and return a mapping of component id -> node list.

    For two-terminal passives (R, C, L) the line is:
        <id> <node1> <node2> <value>
    For BJTs (Q):
        Q1 collector base emitter <model>
    For JFETs (J):
        J1 drain gate source <model>
    For MOSFETs (M):
        M1 drain gate source body <model>
    For subcircuit instances (X):
        XU1 node1 node2 ... nodeN <subckt_name>
    For diodes (D):
        D1 anode cathode <model>
    For voltage sources (V):
        Vcc node+ node- DC <value>  -- skip these (power supply)

    Returns dict keyed by component id (e.g. "Rc", "Q1") with list of node
    name strings.
    """
    node_map: dict[str, list[str]] = {}

    for raw_line in spice_template.splitlines():
        line = raw_line.strip()

        # Skip directives, continuations, blank lines
        if not line or line.startswith(".") or line.startswith("+") or line.startswith("*"):
            continue

        m = _SPICE_COMPONENT_RE.match(line)
        if not m:
            continue

        comp_id = m.group(1)
        rest = m.group(2).split()
        prefix_char = comp_id[0].upper()

        # Skip voltage/current sources (power supply lines)
        if prefix_char == "V" or prefix_char == "I":
            continue

        if prefix_char in ("R", "C", "L"):
            # Two-terminal: <node1> <node2> <value/placeholder>
            if len(rest) >= 3:
                node_map[comp_id] = [rest[0], rest[1]]
            elif len(rest) == 2:
                node_map[comp_id] = [rest[0], rest[1]]

        elif prefix_char == "Q":
            # BJT: collector base emitter model
            if len(rest) >= 4:
                node_map[comp_id] = [rest[0], rest[1], rest[2]]

        elif prefix_char == "J":
            # JFET: drain gate source model
            if len(rest) >= 4:
                node_map[comp_id] = [rest[0], rest[1], rest[2]]

        elif prefix_char == "M":
            # MOSFET: drain gate source body model
            if len(rest) >= 5:
                node_map[comp_id] = [rest[0], rest[1], rest[2], rest[3]]

        elif prefix_char == "D":
            # Diode: anode cathode model
            if len(rest) >= 3:
                node_map[comp_id] = [rest[0], rest[1]]

        elif prefix_char == "X":
            # Subcircuit instance: nodes... subckt_name
            # Last token is the subcircuit name; everything else is a node.
            if len(rest) >= 2:
                node_map[comp_id] = rest[:-1]  # all but last

        else:
            # Generic two-terminal fallback
            if len(rest) >= 3:
                node_map[comp_id] = [rest[0], rest[1]]

    return node_map


def _get_component_nodes(comp_id: str, node_map: dict[str, list[str]],
                         block: dict) -> list[str]:
    """Return the correct node list for a component.

    Looks up *comp_id* in the parsed node_map.  Falls back to the block-level
    ``nodes`` list for components not found in the template (e.g. pots that
    are only represented in the DSP model).
    """
    if comp_id in node_map:
        return list(node_map[comp_id])

    # Fallback: use block-level node list
    return list(block.get("nodes", ["in", "out"]))


# ---------------------------------------------------------------------------
# Topology-specific value calculators
# ---------------------------------------------------------------------------


def _calculate_bjt_ce_values(block: dict, params: dict,
                             vcc: float) -> dict[str, float]:
    """Calculate all component values for a BJT common-emitter stage.

    Uses beta-independent voltage-divider bias with stability factor S ~= 10.

    Design procedure:
    1. Choose Ic from params (default 1 mA).
    2. Vc = Vcc/2 for maximum output swing.
    3. Rc = (Vcc - Vc) / Ic = Vcc / (2 * Ic).
    4. Re: if gain is specified, Re = Rc / gain_linear.
       Enforce a minimum Re for stability: Re >= Vcc / (20 * Ic).
    5. Ve = Ic * Re.
    6. Vb = Ve + 0.65 (silicon Vbe at ~1 mA).
    7. Beta-independent divider: I_div = 10 * Ic / beta_min (beta_min = 100).
       Rb2 = Vb / I_div.
       Rb1 = (Vcc - Vb) / I_div.
    8. Coupling caps from actual impedances.
    9. Bypass cap from Re.
    """
    gain_db = params.get("gain_db", block.get("parameters", {}).get("gain_db", {}).get("default", 20))
    gain_linear = 10.0 ** (gain_db / 20.0)
    f_low = params.get("f_low_hz", params.get("f_low", block.get("parameters", {}).get("f_low", {}).get("default", 20)))
    f_bypass = params.get("f_bypass", block.get("parameters", {}).get("f_bypass", {}).get("default", 100))
    ic_ma = params.get("bias_current_ma", block.get("parameters", {}).get("bias_current_ma", {}).get("default", 1.0))

    ic = ic_ma / 1000.0  # amps
    vbe = 0.65
    beta_min = 100.0  # worst-case beta for 2N3904

    # Collector voltage target: Vcc/2
    vc = vcc / 2.0

    # Collector resistor
    rc = (vcc - vc) / ic  # = Vcc / (2 * Ic)

    # Emitter resistor from gain: gain ~= Rc / Re  (bypassed Ce case)
    re_from_gain = rc / gain_linear
    # Minimum Re for bias stability: at least Vcc / (20 * Ic) so Ve >= 0.45 V
    re_min = vcc / (20.0 * ic)
    re = max(re_from_gain, re_min)

    # DC voltages
    ve = ic * re
    vb = ve + vbe

    # Beta-independent bias divider
    # Divider current = 10 * Ib_max where Ib_max = Ic / beta_min
    i_div = 10.0 * ic / beta_min

    rb2 = vb / i_div           # bottom resistor
    rb1 = (vcc - vb) / i_div   # top resistor

    # Input impedance seen by Cin: Rb1 || Rb2 || (beta_min * Re)
    z_base = beta_min * re
    z_in = CircuitCalc.parallel_resistance(
        CircuitCalc.parallel_resistance(rb1, rb2),
        z_base,
    )

    # Coupling caps
    cin = 1.0 / (2.0 * math.pi * f_low * z_in)
    cout = 1.0 / (2.0 * math.pi * f_low * _DEFAULT_RLOAD)

    # Emitter bypass cap: makes Re invisible at AC above f_bypass
    ce = 1.0 / (2.0 * math.pi * f_bypass * re)

    return {
        "Rc": rc,
        "Re": re,
        "Rb1": rb1,
        "Rb2": rb2,
        "Cin": cin,
        "Cout": cout,
        "Ce": ce,
        # Metadata for operating-point verification
        "_Vc": vc,
        "_Ve": ve,
        "_Vb": vb,
        "_Ic_mA": ic_ma,
        "_Vcc": vcc,
    }


def _calculate_opamp_clip_values(block: dict, params: dict,
                                 vcc: float) -> dict[str, float]:
    """Calculate values for an op-amp clipping stage (soft or hard).

    Inverting topology:
    - Ri = 10 kohm (input impedance)
    - Rf = Ri * gain_linear
    - Bias: Rb1 = Rb2 = 47 kohm, Cb = 100 uF (Vref = Vcc/2)
    - Coupling caps from actual R values
    """
    gain_db = params.get("gain_db", block.get("parameters", {}).get("gain_db", {}).get("default", 30))
    gain_linear = 10.0 ** (gain_db / 20.0)
    f_low = params.get("f_low_hz", params.get("f_low", block.get("parameters", {}).get("f_low", {}).get("default", 50)))
    f_lp = params.get("f_lp", block.get("parameters", {}).get("f_lp", {}).get("default", 5000))

    ri = 10_000.0  # 10 kohm input impedance
    rf = ri * gain_linear

    # Bias divider
    rb1 = 47_000.0
    rb2 = 47_000.0
    cb = 100e-6  # 100 uF bypass

    # Output resistor (hard-clip topology)
    rout = 4_700.0

    # Coupling caps
    cin = 1.0 / (2.0 * math.pi * f_low * ri)
    cout = 1.0 / (2.0 * math.pi * f_low * _DEFAULT_RLOAD)

    # Feedback cap (optional bandwidth limiter for hard-clip)
    cf = 1.0 / (2.0 * math.pi * f_lp * rf) if rf > 0 else 100e-12

    return {
        "Rf": rf,
        "Ri": ri,
        "Rb1": rb1,
        "Rb2": rb2,
        "Cb": cb,
        "Cin": cin,
        "Cout": cout,
        "Cf": cf,
        "Rout": rout,
        "_Vcc": vcc,
    }


def _calculate_opamp_gain_values(block: dict, params: dict,
                                 vcc: float) -> dict[str, float]:
    """Calculate values for an op-amp non-inverting gain stage.

    Non-inverting: gain = 1 + Rf/Rg
    - Rf: feedback resistor (start at 100 kohm)
    - Rg = Rf / (gain - 1)
    - Rin: DC return to bias point, 1 Mohm
    - Bias: Rb1 = Rb2 = 47 kohm, Cb = 100 uF
    """
    gain_db = params.get("gain_db", block.get("parameters", {}).get("gain_db", {}).get("default", 20))
    gain_linear = 10.0 ** (gain_db / 20.0)
    f_low = params.get("f_low_hz", params.get("f_low", block.get("parameters", {}).get("f_low", {}).get("default", 20)))

    rf = 100_000.0  # 100 kohm
    rg = rf / max(gain_linear - 1.0, 0.01)  # protect against gain <= 1
    rin = 1_000_000.0  # 1 Mohm

    rb1 = 47_000.0
    rb2 = 47_000.0
    cb = 100e-6

    cin = 1.0 / (2.0 * math.pi * f_low * rin)
    cout = 1.0 / (2.0 * math.pi * f_low * _DEFAULT_RLOAD)

    return {
        "Rf": rf,
        "Rg": rg,
        "Rin": rin,
        "Rb1": rb1,
        "Rb2": rb2,
        "Cb": cb,
        "Cin": cin,
        "Cout": cout,
        "_Vcc": vcc,
    }


def _calculate_jfet_buffer_values(block: dict, params: dict,
                                  vcc: float) -> dict[str, float]:
    """Calculate values for a JFET source follower buffer.

    Design:
    - R1 (gate bias) = 1 Mohm (high input Z)
    - Id target: use bias_current_ma param, default 1.5 mA
    - Vds target = Vcc / 2
    - Rs = Vs / Id where Vs = Id * Rs is solved from Vgs = -Id * Rs for self-bias
      Simpler: Rs = Vcc / (2 * Id) puts the source at roughly Vcc/4 with Vds ~ Vcc/2
    - Rd = (Vcc - Vd) / Id; for pure source follower, set Rd to put drain
      at about 0.7 * Vcc
    - Coupling caps from actual impedances
    """
    f_low = params.get("f_low_hz", params.get("f_low", block.get("parameters", {}).get("f_low", {}).get("default", 10)))
    id_ma = params.get("bias_current_ma", block.get("parameters", {}).get("bias_current_ma", {}).get("default", 1.5))
    id_a = id_ma / 1000.0

    r1 = 1_000_000.0  # 1 Mohm gate bias

    # Source resistor: we want Vs ~ Vcc * 0.3 for good swing
    vs_target = vcc * 0.3
    rs = vs_target / id_a

    # Drain resistor: Vd target ~ Vcc * 0.7
    vd_target = vcc * 0.7
    rd = (vcc - vd_target) / id_a
    # If Rd comes out negative or tiny, connect drain directly to Vcc (Rd ~ 0)
    if rd < 10.0:
        rd = 0.0

    # Coupling caps
    cin = 1.0 / (2.0 * math.pi * f_low * r1)
    # Output Z of source follower ~ Rs || (1/gm), approximate as Rs
    cout = 1.0 / (2.0 * math.pi * f_low * max(rs, 100.0))

    return {
        "R1": r1,
        "Rs": rs,
        "Rd": rd if rd > 0 else 100.0,  # small value if effectively 0
        "Cin": cin,
        "Cout": cout,
        "_Vcc": vcc,
    }


def _calculate_filter_values(block: dict, params: dict,
                             vcc: float) -> dict[str, float]:
    """Calculate values for filter blocks (RC, Sallen-Key, tonestack, gyrator).

    Dispatches based on the block id.
    """
    block_id = block.get("id", "")
    values: dict[str, float] = {}

    if block_id in ("rc_lowpass", "rc_highpass"):
        fc = params.get("cutoff_hz", block.get("parameters", {}).get("cutoff_hz", {}).get("default", 5000))
        # Choose R = 10 kohm, derive C
        r1 = 10_000.0
        c1 = 1.0 / (2.0 * math.pi * fc * r1)
        values = {"R1": r1, "C1": c1}

    elif block_id == "sallen_key_lowpass":
        fc = params.get("cutoff_hz", block.get("parameters", {}).get("cutoff_hz", {}).get("default", 3000))
        q = params.get("Q", block.get("parameters", {}).get("Q", {}).get("default", 0.707))
        sk = CircuitCalc.sallen_key_components(fc, q)
        values = {
            "R1": sk["R1"],
            "R2": sk["R2"],
            "C1": sk["C1"],
            "C2": sk["C2"],
            "Rb1": 47_000.0,
            "Rb2": 47_000.0,
            "Cb": 100e-6,
        }

    elif block_id == "gyrator_mid_boost":
        fc = params.get("center_hz", params.get("cutoff_hz", 1000))
        q = params.get("Q", 2.0)
        gain_db = params.get("gain_db", 6)
        gyr = CircuitCalc.gyrator_components(fc, q, gain_db)
        values = {
            "R_gyr": gyr["R_gyr"],
            "C_gyr": gyr["C_gyr"],
            "R_series": gyr["R_series"],
            "R_gain": gyr["R_gain"],
        }

    elif "tonestack" in block_id:
        # Tonestacks have fixed standard values; use the block component
        # formulas as defaults.  These are well-known circuits with specific
        # component values (Fender, Marshall, Baxandall).
        # Return empty -- the generic fallback in _instantiate_block will
        # handle individual component formulas.
        pass

    values["_Vcc"] = vcc
    return values


# ---------------------------------------------------------------------------
# Operating point verification
# ---------------------------------------------------------------------------


def _verify_operating_point(values: dict[str, float], vcc: float) -> bool:
    """Check that the BJT operating point is within acceptable bounds.

    Returns True if Vc is between 0.3*Vcc and 0.7*Vcc.
    """
    vc = values.get("_Vc")
    if vc is None:
        # Not a BJT stage or metadata not present -- assume OK
        return True
    return 0.3 * vcc <= vc <= 0.7 * vcc


def _recalculate_bjt_after_substitution(
    values: dict[str, float], snapped: dict[str, float], vcc: float,
) -> dict[str, float]:
    """Re-derive dependent BJT values after an inventory substitution changed
    a bias-critical resistor.

    If Rc was snapped to a different value, recalculate Re (to maintain gain),
    then recalculate bias divider, then recalculate coupling caps.  Returns
    updated values dict.
    """
    ic_ma = values.get("_Ic_mA", 1.0)
    ic = ic_ma / 1000.0
    vbe = 0.65
    beta_min = 100.0

    # Use the snapped Rc if available, else original
    rc = snapped.get("Rc", values.get("Rc", vcc / (2.0 * ic)))

    # Actual Vc from snapped Rc
    vc = vcc - ic * rc

    # If Re was also snapped, use it; otherwise recalculate from Rc and
    # original gain ratio
    if "Re" in snapped and "Re" in values and values["Re"] > 0:
        original_gain = values.get("Rc", rc) / values["Re"]
        re_target = rc / original_gain
        re_min = vcc / (20.0 * ic)
        re = max(snapped.get("Re", re_target), re_min)
    else:
        re = snapped.get("Re", values.get("Re", rc / 10.0))

    ve = ic * re
    vb = ve + vbe

    # Recalculate bias divider
    i_div = 10.0 * ic / beta_min
    rb2 = vb / i_div
    rb1 = (vcc - vb) / i_div

    result = dict(values)
    result["Rc"] = rc
    result["Re"] = re
    result["Rb1"] = rb1
    result["Rb2"] = rb2
    result["_Vc"] = vc
    result["_Ve"] = ve
    result["_Vb"] = vb

    # Recalculate coupling caps with new impedances
    z_base = beta_min * re
    z_in = CircuitCalc.parallel_resistance(
        CircuitCalc.parallel_resistance(rb1, rb2),
        z_base,
    )
    # Preserve original f_low (encoded in original Cin value)
    if values.get("Cin") and values.get("Cin") > 0 and z_in > 0:
        # Back-derive f_low from original values then recalc
        old_z_in_approx = max(z_in, 1000)
        # Keep the same f_low intent
        f_low_approx = 1.0 / (2.0 * math.pi * values["Cin"] * old_z_in_approx)
        result["Cin"] = 1.0 / (2.0 * math.pi * max(f_low_approx, 1.0) * z_in)

    if values.get("Ce") and re > 0:
        f_bypass_approx = 1.0 / (2.0 * math.pi * values["Ce"] * values.get("Re", re))
        result["Ce"] = 1.0 / (2.0 * math.pi * max(f_bypass_approx, 1.0) * re)

    return result


def _recalculate_after_substitution(
    block_id: str,
    raw_values: dict[str, float],
    snapped_values: dict[str, float],
    changed_critical: set[str],
    vcc: float,
) -> dict[str, float]:
    """Re-derive dependent values when inventory substitution changed a
    bias-critical component.

    Returns a new values dict with recalculated dependents.
    """
    if not changed_critical:
        return snapped_values

    if block_id == "bjt_common_emitter":
        return _recalculate_bjt_after_substitution(raw_values, snapped_values, vcc)

    # For other topologies, pass through unchanged
    return snapped_values


# ---------------------------------------------------------------------------
# Topology detection helpers
# ---------------------------------------------------------------------------

def _detect_topology(block: dict) -> str:
    """Return a topology tag used to select the right calculator."""
    block_id = block.get("id", "")

    # BJT common emitter / fuzz
    if block_id in ("bjt_common_emitter", "jfet_common_source"):
        return "bjt_ce"
    if block_id in ("bjt_fuzz", "germanium_fuzz"):
        return "bjt_ce"

    # Op-amp clipping
    if "soft_clip" in block_id or "hard_clip" in block_id or "asymmetric_clip" in block_id:
        return "opamp_clip"

    # Op-amp gain (non-inverting / inverting)
    if block_id in ("opamp_noninverting", "opamp_inverting"):
        return "opamp_gain"

    # Op-amp voltage follower (buffer)
    if block_id == "opamp_voltage_follower":
        return "opamp_gain"

    # JFET buffer
    if block_id in ("jfet_source_follower", "bjt_emitter_follower"):
        return "jfet_buffer"

    # Filters
    if any(kw in block_id for kw in ("lowpass", "highpass", "tonestack",
                                      "gyrator", "presence", "notch")):
        return "filter"

    # Compression / modulation -- use generic fallback
    return "generic"


# ---------------------------------------------------------------------------
# Generic / fallback component value resolution
# ---------------------------------------------------------------------------

def _resolve_generic_value(comp_def: dict, calculated: dict[str, float],
                           vcc: float, gain_linear: float,
                           f_low: float) -> Optional[float]:
    """Resolve a component value from the formula field or role heuristics
    when no topology-specific calculator produced a value.

    This handles components in blocks that don't have a dedicated calculator
    (compression, modulation, tonestacks, etc.).
    """
    comp_id = comp_def["id"]
    comp_type = comp_def["type"]
    role = comp_def.get("role", "").lower()
    formula_str = comp_def.get("formula", "")

    # If the calculator already produced a value, use it
    if comp_id in calculated:
        val = calculated[comp_id]
        if val is not None:
            return val

    # Try to evaluate simple numeric formulas
    if formula_str:
        try:
            val = float(formula_str)
            return val
        except (ValueError, TypeError):
            pass

    # Role-based defaults
    if comp_type == "resistor":
        if "gate_bias" in role or "input impedance" in role:
            return 1_000_000.0
        if "bias_divider" in role or "bias divider" in role:
            return 47_000.0
        if "feedback" in role:
            return 100_000.0
        if "input" in role:
            return 10_000.0
        if "collector" in role or "drain" in role:
            return vcc / (2.0 * 0.001)
        if "emitter" in role or "source" in role:
            return vcc / (2.0 * 0.001) / gain_linear
        if "output" in role:
            return 4_700.0
        return 10_000.0

    if comp_type == "capacitor":
        if "coupling" in role or "input" in role or "output" in role:
            return 1.0 / (2.0 * math.pi * f_low * 10_000.0)
        if "bypass" in role or "decoupling" in role:
            return 100e-6
        if "tone" in role or "filter" in role:
            return 1.0 / (2.0 * math.pi * 3000.0 * 10_000.0)
        if "power" in role:
            return 100e-6
        return 100e-9

    return None


# ---------------------------------------------------------------------------
# Block instantiation (main rewrite)
# ---------------------------------------------------------------------------


def _instantiate_block(block: dict, params: dict, prefix: str,
                       supply_voltage: float,
                       inventory_values: Optional[dict] = None,
                       ) -> tuple[list[CircuitComponent], dict[str, float], dict[str, str]]:
    """
    Instantiate a block definition into concrete components with calculated
    values and correctly assigned nodes from the SPICE template.

    Returns:
        Tuple of (components, component_values, stage_node_map) where
        component_values maps component IDs to their final snapped values
        and stage_node_map maps template node names to prefixed global names.
    """
    components: list[CircuitComponent] = []
    vcc = supply_voltage
    gain_db = params.get(
        "gain_db",
        block.get("parameters", {}).get("gain_db", {}).get("default", 20),
    )
    gain_linear = 10.0 ** (gain_db / 20.0)
    f_low = params.get(
        "f_low_hz",
        params.get("f_low",
                    block.get("parameters", {}).get("f_low", {}).get("default", 80)),
    )

    # ---- Step 1: Parse SPICE template for node assignments ----------------
    spice_template = block.get("spice_template", "")
    node_map = _parse_spice_template_nodes(spice_template)

    # ---- Step 2: Calculate topology-specific values -----------------------
    topology = _detect_topology(block)
    calculated: dict[str, float] = {}

    if topology == "bjt_ce":
        calculated = _calculate_bjt_ce_values(block, params, vcc)
    elif topology == "opamp_clip":
        calculated = _calculate_opamp_clip_values(block, params, vcc)
    elif topology == "opamp_gain":
        calculated = _calculate_opamp_gain_values(block, params, vcc)
    elif topology == "jfet_buffer":
        calculated = _calculate_jfet_buffer_values(block, params, vcc)
    elif topology == "filter":
        calculated = _calculate_filter_values(block, params, vcc)

    # ---- Step 3: Snap to E-series, then attempt inventory substitution ----
    raw_values: dict[str, float] = {}  # pre-snap values for recalc reference
    snapped_values: dict[str, float] = {}
    changed_critical: set[str] = set()
    block_id = block.get("id", "")

    for comp_def in block.get("components", []):
        comp_id = comp_def["id"]
        comp_type = comp_def["type"]

        if comp_type not in ("resistor", "capacitor"):
            continue

        # Get raw calculated value
        value = calculated.get(comp_id)
        if value is None:
            value = _resolve_generic_value(comp_def, calculated, vcc, gain_linear, f_low)
        if value is None or value <= 0:
            continue

        raw_values[comp_id] = value

        # Snap to E-series
        series = comp_def.get("e_series", "E24" if comp_type == "resistor" else "E12")
        e_value = snap_to_e_series(value, series)

        # Try inventory substitution
        inv_value = None
        if inventory_values and comp_type in inventory_values:
            inv_value = snap_to_inventory(value, comp_type, inventory_values[comp_type])

        if inv_value is not None:
            # Check if this is a bias-critical role
            role_lower = comp_def.get("role", "").lower()
            is_critical = any(kw in role_lower for kw in (
                "collector", "emitter", "bias", "source", "drain",
            ))
            if is_critical and abs(inv_value - e_value) / max(e_value, 1) > 0.05:
                changed_critical.add(comp_id)
            snapped_values[comp_id] = inv_value
        else:
            snapped_values[comp_id] = e_value

    # ---- Step 4: Recalculate if bias-critical values changed --------------
    if changed_critical and topology == "bjt_ce":
        recalced = _recalculate_after_substitution(
            block_id, raw_values, snapped_values, changed_critical, vcc,
        )
        # Re-snap recalculated values
        for comp_def in block.get("components", []):
            comp_id = comp_def["id"]
            comp_type = comp_def["type"]
            if comp_id in recalced and comp_id not in changed_critical:
                val = recalced[comp_id]
                if isinstance(val, (int, float)) and val > 0 and not comp_id.startswith("_"):
                    series = comp_def.get("e_series", "E24" if comp_type == "resistor" else "E12")
                    snapped_values[comp_id] = snap_to_e_series(val, series)

        # Verify operating point
        if not _verify_operating_point(recalced, vcc):
            # Reject inventory substitutions for critical components;
            # revert to E-series values
            for cid in changed_critical:
                if cid in raw_values:
                    for cd in block.get("components", []):
                        if cd["id"] == cid:
                            s = cd.get("e_series", "E24")
                            snapped_values[cid] = snap_to_e_series(raw_values[cid], s)
                            break

    # ---- Step 5: Build CircuitComponent objects ---------------------------
    for comp_def in block.get("components", []):
        comp_id = comp_def["id"]
        comp_type = comp_def["type"]
        value = None
        value_display = ""

        if comp_type in ("resistor", "capacitor"):
            value = snapped_values.get(comp_id)
            if value is None:
                # Wasn't in calculated or snapped -- resolve generically
                raw = _resolve_generic_value(comp_def, calculated, vcc, gain_linear, f_low)
                if raw and raw > 0:
                    series = comp_def.get("e_series", "E24" if comp_type == "resistor" else "E12")
                    value = snap_to_e_series(raw, series)
                    # Try inventory
                    if inventory_values and comp_type in inventory_values:
                        inv_val = snap_to_inventory(raw, comp_type, inventory_values[comp_type])
                        if inv_val is not None:
                            value = inv_val

            if value and value > 0:
                if comp_type == "resistor":
                    value_display = format_resistance(value)
                else:
                    value_display = format_capacitance(value)

        elif comp_type == "potentiometer":
            value = 0.5  # default wiper position

        # Node assignment from SPICE template
        comp_nodes = _get_component_nodes(comp_id, node_map, block)

        # Check inventory membership
        in_inventory = False
        if inventory_values and comp_type in inventory_values:
            if value is not None and value in inventory_values[comp_type]:
                in_inventory = True

        component = CircuitComponent(
            id=f"{prefix}_{comp_id}",
            type=comp_type,
            value=value,
            value_display=value_display,
            model=comp_def.get("model"),
            role=comp_def.get("role", ""),
            nodes=comp_nodes,
            voltage_rating=comp_def.get("max_voltage"),
            in_inventory=in_inventory,
        )
        components.append(component)

    # Build the final component_values dict (only real values, no metadata)
    final_values = {k: v for k, v in snapped_values.items() if not k.startswith("_")}

    # Build stage node map: template node names -> prefixed global names
    stage_node_map: dict[str, str] = {}
    for node_name in block.get("nodes", ["in", "out"]):
        if node_name == "in":
            stage_node_map["in"] = f"{prefix}_in"
        elif node_name == "out":
            stage_node_map["out"] = f"{prefix}_out"
        elif node_name in ("vcc", "gnd"):
            stage_node_map[node_name] = node_name
        else:
            stage_node_map[node_name] = f"{prefix}_{node_name}"

    return components, final_values, stage_node_map
