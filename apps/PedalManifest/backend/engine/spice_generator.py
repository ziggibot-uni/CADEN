"""
SPICE Netlist Generator — Converts a CircuitGraph into an ngspice-compatible netlist.

Two generation paths:
  1. generate_netlist_from_templates() — uses per-stage SPICE templates from block JSONs
     (preferred, produces correct netlists)
  2. generate_netlist_from_components() — legacy per-component fallback
     (kept for backward compatibility when templates aren't available)

generate_netlist() auto-selects: templates if available, components otherwise.

Also handles running ngspice and parsing results.
"""

import subprocess
import tempfile
import re
import os
from pathlib import Path
from typing import Optional
from backend.models.circuit import CircuitGraph, CircuitComponent


# Standard semiconductor models for ngspice
SEMICONDUCTOR_MODELS = {
    "2N3904": ".model 2N3904 NPN(IS=6.734f BF=416.4 NF=1.259 VAF=74.03 IKF=66.78m ISE=6.734f NE=1.259 BR=.7389 NR=2 VAR=28 IKR=.1104 ISC=5.496f NC=2 RB=6.5 RE=.15 RC=.5 CJE=3.9p VJE=.75 MJE=.26 TF=301.2p CJC=4.614p VJC=.75 MJC=.307 XCJC=.6 TF=301.2p TR=239.5n)",
    "2N5457": ".model 2N5457 NJF(VTO=-1.8 BETA=1.04m LAMBDA=3m RD=1 RS=1 CGS=4.57p CGD=3.1p IS=33.57f)",
    "J201": ".model J201 NJF(VTO=-0.7 BETA=1.3m LAMBDA=2.5m RD=1 RS=1 CGS=4.5p CGD=3p IS=30f)",
    "BC549C": ".model BC549C NPN(IS=1.8e-14 BF=400 NF=.9955 VAF=80 IKF=.14 ISE=5e-14 NE=1.46 BR=35.5 NR=1.005 VAR=12.5 IKR=.03 ISC=1.72e-13 NC=1.27 RB=.56 RE=.6 RC=.25 CJE=1.3e-11 VJE=.58 MJE=.28 CJC=4e-12 VJC=.54 MJC=.3 TF=6.4e-10 TR=5e-8)",
    "1N4148": ".model 1N4148 D(IS=2.52n RS=.568 N=1.752 BV=100 IBV=100u CJO=4p VJ=.6158 M=.41 TT=20n)",
    "1N34A": ".model 1N34A D(IS=2e-7 RS=7 N=1.3 BV=60 IBV=15u CJO=.5p VJ=.1 M=.27)",
    "LED_RED": ".model LED_RED D(IS=93.2p RS=42m N=3.73 BV=5 IBV=100u CJO=2.97p VJ=.75 M=.333)",
    "TL071": "* TL071 modeled as ideal op-amp subcircuit\n.subckt TL071 inp inn out vcc vee\nE1 out 0 inp inn 200000\n.ends TL071",
    "TL072": "* TL072 dual - each half modeled\n.subckt TL072_half inp inn out vcc vee\nE1 out 0 inp inn 200000\n.ends TL072_half",
    "LM13700": "* LM13700 OTA simplified model\n.subckt LM13700 inp inn out iabc\nG1 0 out inp inn iabc 0 1m\n.ends LM13700",
    "AC128": ".model AC128 PNP(IS=2.6e-7 BF=80 NF=1.2 VAF=50 IKF=10m BR=4 NR=1.5 VAR=10 RB=10 RE=1 RC=2 CJE=25p CJC=15p TF=500p TR=50n)",
}


# ---------------------------------------------------------------------------
# Template-based netlist generation
# ---------------------------------------------------------------------------

def _has_templates(circuit: CircuitGraph) -> bool:
    """Check whether at least one stage carries a SPICE template."""
    return any(stage.spice_template for stage in circuit.stages)


def _extract_model_lines(template: str) -> tuple[list[str], str]:
    """
    Split a SPICE template into (model_lines, remaining_template).

    Model lines are `.model ...` (single-line) and `.subckt ... .ends` blocks.
    Returns them separately so they can be deduplicated and placed at the top
    of the netlist.
    """
    model_lines: list[str] = []
    remaining: list[str] = []

    lines = template.splitlines()
    in_subckt = False

    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith(".subckt"):
            in_subckt = True
            model_lines.append(line)
        elif stripped.startswith(".ends"):
            in_subckt = False
            model_lines.append(line)
        elif in_subckt:
            model_lines.append(line)
        elif stripped.startswith(".model"):
            model_lines.append(line)
        else:
            remaining.append(line)

    return model_lines, "\n".join(remaining)


def _is_vcc_line(line: str) -> bool:
    """Return True if the line is a Vcc supply definition that should be
    stripped (the global V_VCC handles it)."""
    stripped = line.strip().lower()
    # Match patterns like: Vcc vcc gnd DC {{Vcc}}  or  Vcc vcc 0 9
    if re.match(r"^v\w*\s+vcc\s+(gnd|0)\s+", stripped):
        return True
    # Also catch with placeholders still present
    if re.match(r"^vcc\s+vcc\s+(gnd|0)\s+", stripped):
        return True
    return False


def _substitute_values(template: str, values: dict) -> str:
    """Replace {{placeholder}} tokens with calculated values."""
    def _replace(match):
        key = match.group(1)
        if key in values:
            val = values[key]
            # Format floats: use scientific notation for very small / large
            if isinstance(val, float):
                return f"{val:g}"
            return str(val)
        # Leave unresolved placeholders as comments so ngspice doesn't choke
        return f"UNRESOLVED_{key}"
    return re.sub(r"\{\{(\w+)\}\}", _replace, template)


def _remap_nodes(template: str, node_map: dict) -> str:
    """Replace node names in SPICE component lines according to node_map.

    Strategy: for each line that looks like a component instantiation,
    tokenise and replace any token that appears in the node_map.
    We process tokens individually so that node names embedded in
    component names (which are prefixed separately) aren't double-mapped.
    """
    if not node_map:
        return template

    result_lines = []
    for line in template.splitlines():
        stripped = line.strip()
        # Skip blank lines and comments
        if not stripped or stripped.startswith("*") or stripped.startswith("."):
            result_lines.append(line)
            continue

        tokens = stripped.split()
        # First token is the component name — don't remap it
        new_tokens = [tokens[0]]
        for token in tokens[1:]:
            # Only remap if the token is an exact node-name match
            # (not a numeric value or model name)
            if token in node_map:
                new_tokens.append(node_map[token])
            else:
                new_tokens.append(token)
        result_lines.append(" ".join(new_tokens))

    return "\n".join(result_lines)


def _suffix_component_names(template: str, suffix: str) -> str:
    """Add a stage suffix to every component name to avoid collisions.

    SPICE component names are the first token on non-comment, non-directive
    lines. We append `_S{n}` to each.
    """
    result_lines = []
    for line in template.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*") or stripped.startswith("."):
            result_lines.append(line)
            continue
        tokens = stripped.split()
        # Suffix the component name (first token)
        tokens[0] = tokens[0] + suffix
        result_lines.append(" ".join(tokens))
    return "\n".join(result_lines)


def _process_stage_template(stage, stage_num: int) -> tuple[list[str], str]:
    """Process a single stage's SPICE template.

    Returns (model_lines, processed_component_lines).
    """
    template = stage.spice_template
    if not template:
        return [], ""

    # 1. Extract .model / .subckt lines
    model_lines, body = _extract_model_lines(template)

    # 2. Remove Vcc supply lines (handled globally)
    body_lines = [ln for ln in body.splitlines() if not _is_vcc_line(ln)]
    body = "\n".join(body_lines)

    # 3. Substitute calculated values
    body = _substitute_values(body, stage.component_values)

    # 4. Remap node names
    body = _remap_nodes(body, stage.node_map)

    # 5. Suffix component names to avoid collisions across stages
    suffix = f"_S{stage_num}"
    body = _suffix_component_names(body, suffix)

    return model_lines, body


def generate_netlist_from_templates(circuit: CircuitGraph, analysis: str = "ac") -> str:
    """Generate a complete ngspice netlist using per-stage SPICE templates.

    This is the preferred generation path — it uses the carefully written
    SPICE templates from block JSON files, producing correct node orderings,
    subcircuit instantiations, and internal connections.
    """
    lines: list[str] = ["* PedalForge Generated Netlist (template-based)", ""]

    # ------------------------------------------------------------------
    # Pass 1: collect model/subckt definitions from all stages + dedup
    # ------------------------------------------------------------------
    all_model_lines: list[str] = []
    stage_bodies: list[tuple[int, str, str]] = []  # (index, header_comment, body)

    for stage in circuit.stages:
        stage_num = stage.stage_index + 1
        model_lines, body = _process_stage_template(stage, stage_num)
        all_model_lines.extend(model_lines)

        header = f"* Stage {stage_num}: {stage.block_id} ({stage.transform})"
        stage_bodies.append((stage_num, header, body))

    # Deduplicate model lines (keyed by the normalised content)
    seen_models: set[str] = set()
    unique_model_lines: list[str] = []
    for ml in all_model_lines:
        key = ml.strip().lower()
        if key and key not in seen_models:
            seen_models.add(key)
            unique_model_lines.append(ml)

    # ------------------------------------------------------------------
    # Emit: model definitions
    # ------------------------------------------------------------------
    if unique_model_lines:
        lines.append("* --- Model / Subcircuit Definitions ---")
        lines.extend(unique_model_lines)
        lines.append("")

    # ------------------------------------------------------------------
    # Power supply
    # ------------------------------------------------------------------
    vcc = 9.0
    for stage in circuit.stages:
        if "supply_voltage" in stage.params:
            vcc = stage.params["supply_voltage"]
            break
        # Also check component_values for Vcc
        if "Vcc" in stage.component_values:
            vcc = stage.component_values["Vcc"]
            break

    lines.append("* --- Power Supply ---")
    lines.append(f"V_VCC vcc 0 {vcc}")
    lines.append("")

    # ------------------------------------------------------------------
    # Input source
    # ------------------------------------------------------------------
    lines.append("* --- Input Signal ---")
    if analysis == "ac":
        lines.append("V_IN input 0 DC 0 AC 1")
    elif analysis == "tran":
        lines.append("V_IN input 0 DC 0 AC 1 SIN(0 0.1 1000)")
    else:
        lines.append("V_IN input 0 DC 0 AC 1")
    lines.append("")

    # ------------------------------------------------------------------
    # Stage bodies
    # ------------------------------------------------------------------
    for stage_num, header, body in stage_bodies:
        if not body.strip():
            continue
        lines.append(header)
        lines.append(body)
        lines.append("")

    # ------------------------------------------------------------------
    # Coupling capacitors and other inter-stage components
    # These are stored in circuit.components with type "capacitor" and
    # role "coupling" (or similar). They are NOT part of any stage template.
    # ------------------------------------------------------------------
    coupling_lines = []
    stage_component_ids: set[str] = set()
    for stage in circuit.stages:
        stage_component_ids.update(stage.components)

    for comp in circuit.components:
        # Components not claimed by any stage are inter-stage elements
        if comp.id not in stage_component_ids and len(comp.nodes) >= 2:
            if comp.type == "capacitor":
                val = comp.value if comp.value is not None else 1e-6
                coupling_lines.append(f"C{comp.id} {comp.nodes[0]} {comp.nodes[1]} {val:g}")
            elif comp.type == "resistor":
                val = comp.value if comp.value is not None else 1000
                coupling_lines.append(f"R{comp.id} {comp.nodes[0]} {comp.nodes[1]} {val:g}")
            else:
                coupling_lines.append(f"* Inter-stage component: {comp.id} type={comp.type}")

    if coupling_lines:
        lines.append("* --- Inter-Stage Coupling ---")
        lines.extend(coupling_lines)
        lines.append("")

    # ------------------------------------------------------------------
    # Analysis directives
    # ------------------------------------------------------------------
    lines.append("* --- Analysis ---")
    if analysis == "ac":
        lines.append(".ac dec 100 20 20000")
    elif analysis == "op":
        lines.append(".op")
    elif analysis == "tran":
        lines.append(".tran 10u 10m")

    lines.append(".end")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Legacy component-based netlist generation (backward compatibility)
# ---------------------------------------------------------------------------

def _component_to_spice(comp: CircuitComponent) -> Optional[str]:
    """Convert a CircuitComponent to a SPICE netlist line (legacy fallback)."""
    if len(comp.nodes) < 2:
        return None

    cid = comp.id
    nodes = " ".join(comp.nodes)

    if comp.type == "resistor":
        return f"R{cid} {nodes} {comp.value or 1000}"
    elif comp.type == "capacitor":
        return f"C{cid} {nodes} {comp.value or 1e-6}"
    elif comp.type in ("NPN_BJT", "PNP_BJT"):
        model = comp.model or ("2N3904" if comp.type == "NPN_BJT" else "AC128")
        return f"Q{cid} {nodes} {model}"
    elif comp.type in ("N_JFET", "P_JFET"):
        model = comp.model or "J201"
        return f"J{cid} {nodes} {model}"
    elif comp.type in ("diode", "LED"):
        model = comp.model or "1N4148"
        return f"D{cid} {nodes} {model}"
    elif comp.type == "op_amp":
        model = comp.model or "TL071"
        return f"X{cid} {nodes} {model}"
    elif comp.type == "potentiometer":
        wiper = comp.value or 0.5
        total_r = 100000
        r_top = total_r * (1 - wiper)
        r_bot = total_r * wiper
        n = comp.nodes
        if len(n) >= 3:
            return f"R{cid}_top {n[0]} {n[1]} {r_top}\nR{cid}_bot {n[1]} {n[2]} {r_bot}"
    return f"* Unknown component: {cid} type={comp.type}"


def generate_netlist_from_components(circuit: CircuitGraph, analysis: str = "ac") -> str:
    """Generate a netlist from individual components (legacy fallback).

    Used when stage SPICE templates are not available.
    """
    lines = ["* PedalForge Generated Netlist (component-based)", ""]

    # Collect needed models
    needed_models = set()
    for comp in circuit.components:
        if comp.model and comp.model in SEMICONDUCTOR_MODELS:
            needed_models.add(comp.model)

    if needed_models:
        lines.append("* --- Semiconductor Models ---")
        for model_name in sorted(needed_models):
            lines.append(SEMICONDUCTOR_MODELS[model_name])
        lines.append("")

    # Power supply
    lines.append("* --- Power Supply ---")
    vcc = 9.0
    for stage in circuit.stages:
        if "supply_voltage" in stage.params:
            vcc = stage.params["supply_voltage"]
            break
    lines.append(f"V_VCC vcc 0 {vcc}")
    lines.append("")

    # Input source
    lines.append("* --- Input Signal ---")
    if analysis == "ac":
        lines.append("V_IN input 0 DC 0 AC 1")
    else:
        lines.append("V_IN input 0 DC 0 AC 1 SIN(0 0.1 1000)")
    lines.append("")

    # Components
    lines.append("* --- Circuit Components ---")
    for comp in circuit.components:
        line = _component_to_spice(comp)
        if line:
            lines.append(line)
    lines.append("")

    # Analysis directives
    lines.append("* --- Analysis ---")
    if analysis == "ac":
        lines.append(".ac dec 100 20 20000")
    elif analysis == "op":
        lines.append(".op")
    elif analysis == "tran":
        lines.append(".tran 10u 10m")

    lines.append(".end")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Auto-selecting entry point
# ---------------------------------------------------------------------------

def generate_netlist(circuit: CircuitGraph, analysis: str = "ac") -> str:
    """Generate a complete ngspice netlist from a CircuitGraph.

    Automatically selects the template-based path if any stage has a
    spice_template, otherwise falls back to the legacy component-based path.
    """
    if _has_templates(circuit):
        return generate_netlist_from_templates(circuit, analysis)
    return generate_netlist_from_components(circuit, analysis)


# ---------------------------------------------------------------------------
# ngspice runner and output parsing (unchanged)
# ---------------------------------------------------------------------------

def run_ngspice(netlist: str, timeout: int = 30) -> dict:
    """
    Run ngspice on a netlist and parse the results.
    Returns dict with frequency_response, gain_1khz, operating_point, etc.
    """
    results = {
        "success": False,
        "frequency_response": [],
        "gain_1khz_db": None,
        "f_low_3db_hz": None,
        "f_high_3db_hz": None,
        "current_draw_ma": None,
        "operating_point": {},
        "error": None,
        "raw_output": "",
    }

    # Write netlist to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cir", delete=False) as f:
        f.write(netlist)
        netlist_path = f.name

    output_path = netlist_path.replace(".cir", ".out")

    try:
        # Add print/write commands for output
        control_script = netlist.replace(
            ".end",
            f""".control
run
wrdata {output_path} v(output)
.endc
.end"""
        )

        with open(netlist_path, "w") as f:
            f.write(control_script)

        # Run ngspice
        proc = subprocess.run(
            ["ngspice", "-b", netlist_path],
            capture_output=True, text=True, timeout=timeout,
        )

        results["raw_output"] = proc.stdout + proc.stderr

        if proc.returncode != 0:
            # Tier 1: retry with relaxed tolerances
            results = _retry_with_relaxed_tolerances(netlist, netlist_path, output_path, timeout)
            if not results["success"]:
                results["error"] = f"ngspice failed: {proc.stderr[:500]}"
                return results

        # Parse output
        if os.path.exists(output_path):
            results["frequency_response"] = _parse_ac_output(output_path)
            if results["frequency_response"]:
                results["success"] = True
                results["gain_1khz_db"] = _extract_gain_at_freq(results["frequency_response"], 1000)
                results["f_low_3db_hz"], results["f_high_3db_hz"] = _extract_3db_points(results["frequency_response"])

        if not results["frequency_response"]:
            # Even without parsed output, check if sim ran
            if "run" in results["raw_output"].lower() or proc.returncode == 0:
                results["success"] = True

    except subprocess.TimeoutExpired:
        results["error"] = "Simulation timed out"
    except FileNotFoundError:
        results["error"] = "ngspice not found. Please install ngspice and ensure it's on your PATH."
    finally:
        for p in (netlist_path, output_path):
            if os.path.exists(p):
                os.unlink(p)

    return results


def _retry_with_relaxed_tolerances(netlist: str, netlist_path: str, output_path: str, timeout: int) -> dict:
    """Tier 1 non-convergence recovery: relax tolerances."""
    results = {"success": False, "frequency_response": [], "gain_1khz_db": None,
               "f_low_3db_hz": None, "f_high_3db_hz": None, "current_draw_ma": None,
               "operating_point": {}, "error": None, "raw_output": ""}

    relaxed = netlist.replace(
        ".end",
        """.options RELTOL=0.01 ABSTOL=1e-10 VNTOL=1e-4 GMIN=1e-10
.options ITL1=500 ITL2=200 ITL4=100
.end"""
    )

    with open(netlist_path, "w") as f:
        f.write(relaxed)

    try:
        proc = subprocess.run(
            ["ngspice", "-b", netlist_path],
            capture_output=True, text=True, timeout=timeout,
        )
        results["raw_output"] = proc.stdout + proc.stderr
        if proc.returncode == 0:
            results["success"] = True
            if os.path.exists(output_path):
                results["frequency_response"] = _parse_ac_output(output_path)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return results


def _parse_ac_output(filepath: str) -> list[dict]:
    """Parse ngspice wrdata output for AC analysis."""
    data = []
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("*"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        freq = float(parts[0])
                        magnitude = float(parts[1])
                        data.append({"frequency": freq, "magnitude": magnitude})
                    except ValueError:
                        continue
    except Exception:
        pass
    return data


def _extract_gain_at_freq(freq_response: list[dict], target_freq: float) -> Optional[float]:
    """Find gain at a specific frequency."""
    import math
    closest = None
    min_diff = float("inf")
    for point in freq_response:
        diff = abs(point["frequency"] - target_freq)
        if diff < min_diff:
            min_diff = diff
            closest = point
    if closest and closest["magnitude"] > 0:
        return 20 * math.log10(closest["magnitude"])
    return None


def _extract_3db_points(freq_response: list[dict]) -> tuple[Optional[float], Optional[float]]:
    """Find -3dB points from frequency response."""
    import math
    if not freq_response:
        return None, None

    # Find peak gain
    peak_mag = max(p["magnitude"] for p in freq_response if p["magnitude"] > 0)
    threshold = peak_mag / (10 ** (3 / 20))  # -3dB

    f_low = None
    f_high = None

    for i, point in enumerate(freq_response):
        if point["magnitude"] >= threshold:
            if f_low is None:
                f_low = point["frequency"]
            f_high = point["frequency"]

    return f_low, f_high
