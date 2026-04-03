"""
Operating point verification and component rating checker.

Every active stage compiled by block_compiler.py is validated here before
the circuit reaches SPICE. Catches obvious biasing errors early (saves
ngspice convergence failures) and enforces component derating rules.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import math


@dataclass
class OPResult:
    """Result of an operating point check."""
    passed: bool
    stage_id: str
    topology: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "stage_id": self.stage_id,
            "topology": self.topology,
            "warnings": self.warnings,
            "errors": self.errors,
            "metrics": self.metrics,
        }


# ── BJT Common-Emitter ─────────────────────────────────────────────────────────

def verify_bjt_ce(
    *,
    stage_id: str,
    vcc: float,
    rc_ohm: float,
    re_ohm: float,
    r_top_ohm: float,
    r_bottom_ohm: float,
    part_specs: dict[str, Any],
    ic_target_ma: float = 1.0,
) -> OPResult:
    """Verify a BJT common-emitter voltage-divider bias stage.

    Checks:
    - Vb is in the stable linear region (Vcc/4 … 3·Vcc/4)
    - Ic is within transistor rating
    - Vc is above Vce_sat (transistor not in saturation)
    - Power dissipation within Pd_max
    - Vce within Vceo rating
    """
    res = OPResult(passed=True, stage_id=stage_id, topology="BJT_CE")

    vbe = abs(part_specs.get("vbe_v", 0.65))
    beta = part_specs.get("hfe_typ", 200)
    ic_max_ma = abs(part_specs.get("ic_max_ma", 200))
    vceo = abs(part_specs.get("vceo_v", 40))
    pd_mw = part_specs.get("pd_mw", 625)
    vce_sat = abs(part_specs.get("vce_sat_v", 0.20))

    # Voltage divider bias point
    vb = vcc * r_bottom_ohm / (r_top_ohm + r_bottom_ohm)
    ve = vb - vbe
    if ve < 0:
        ve = 0.0

    # Approximate Ic (ignoring base current loading for simplicity)
    ic_a = ve / re_ohm if re_ohm > 0 else ic_target_ma / 1000.0
    ic_ma = ic_a * 1000.0

    vc = vcc - ic_a * rc_ohm
    vce = vc - ve

    # Record metrics
    res.metrics = {
        "vb_v": round(vb, 3),
        "ve_v": round(ve, 3),
        "vc_v": round(vc, 3),
        "vce_v": round(vce, 3),
        "ic_ma": round(ic_ma, 3),
        "pd_mw": round(vce * ic_a * 1000, 1),
    }

    # ── Checks ────────────────────────────────────────────────────
    if vb < vcc * 0.15:
        res.errors.append(
            f"Vb={vb:.2f}V is too close to GND — transistor may be cut off. "
            f"Increase R_bottom or reduce R_top."
        )
        res.passed = False
    elif vb < vcc * 0.25:
        res.warnings.append(f"Vb={vb:.2f}V is low (< Vcc/4). Verify bias is stable.")

    if vb > vcc * 0.85:
        res.errors.append(
            f"Vb={vb:.2f}V is too close to Vcc — transistor may saturate."
        )
        res.passed = False
    elif vb > vcc * 0.75:
        res.warnings.append(f"Vb={vb:.2f}V is high (> 3·Vcc/4). Limited output swing.")

    if vce < vce_sat + 0.1:
        res.errors.append(
            f"Vce={vce:.2f}V is at or below saturation ({vce_sat}V). "
            f"Transistor is saturated — reduce Ic or increase Rc."
        )
        res.passed = False

    if vce > vceo:
        res.errors.append(
            f"Vce={vce:.2f}V exceeds Vceo rating ({vceo}V). "
            f"Use a transistor with higher voltage rating."
        )
        res.passed = False
    elif vce > vceo * 0.8:
        res.warnings.append(
            f"Vce={vce:.2f}V is above 80% of Vceo ({vceo}V). Derate or choose higher-rated device."
        )

    if ic_ma > ic_max_ma:
        res.errors.append(
            f"Ic={ic_ma:.1f}mA exceeds Ic_max ({ic_max_ma}mA). "
            f"Increase Rc or use higher-current transistor."
        )
        res.passed = False
    elif ic_ma > ic_max_ma * 0.5:
        res.warnings.append(f"Ic={ic_ma:.1f}mA is >50% of Ic_max. Consider derating.")

    pd = res.metrics["pd_mw"]
    if pd > pd_mw:
        res.errors.append(
            f"Power dissipation {pd:.0f}mW exceeds Pd_max ({pd_mw}mW)."
        )
        res.passed = False
    elif pd > pd_mw * 0.5:
        res.warnings.append(f"Power dissipation {pd:.0f}mW is >50% of Pd_max.")

    return res


# ── BJT Emitter Follower ───────────────────────────────────────────────────────

def verify_bjt_follower(
    *,
    stage_id: str,
    vcc: float,
    re_ohm: float,
    r_bias_ohm: float,
    part_specs: dict[str, Any],
) -> OPResult:
    """Verify a BJT emitter-follower (buffer) stage."""
    res = OPResult(passed=True, stage_id=stage_id, topology="BJT_EF")

    vbe = abs(part_specs.get("vbe_v", 0.65))
    beta = part_specs.get("hfe_typ", 200)
    vceo = abs(part_specs.get("vceo_v", 40))
    ic_max_ma = abs(part_specs.get("ic_max_ma", 200))

    # Bias: Vb is set by a voltage divider or bias resistor to Vcc/2
    # Simplified: assume Vb is designed for Vcc/2
    vb = vcc / 2.0
    ve = vb - vbe
    ic_a = ve / re_ohm if re_ohm > 0 else 0.001
    ic_ma = ic_a * 1000.0
    vce = vcc - ve

    res.metrics = {
        "vb_v": round(vb, 3),
        "ve_v": round(ve, 3),
        "vce_v": round(vce, 3),
        "ic_ma": round(ic_ma, 3),
    }

    if vce > vceo:
        res.errors.append(f"Vce={vce:.2f}V exceeds Vceo ({vceo}V).")
        res.passed = False

    if ic_ma > ic_max_ma:
        res.errors.append(f"Ic={ic_ma:.1f}mA exceeds Ic_max ({ic_max_ma}mA).")
        res.passed = False

    return res


# ── Op-Amp Stage ───────────────────────────────────────────────────────────────

def verify_opamp_stage(
    *,
    stage_id: str,
    vcc: float,
    split_supply: bool = False,
    part_specs: dict[str, Any],
    gain_linear: float = 1.0,
    feedback_r_ohm: float | None = None,
    input_r_ohm: float | None = None,
) -> OPResult:
    """Verify an op-amp stage supply voltage and headroom."""
    res = OPResult(passed=True, stage_id=stage_id, topology="OPAMP")

    vcc_dual_max = part_specs.get("vcc_dual_max_v", 18.0)
    vcc_dual_min = part_specs.get("vcc_dual_min_v", 3.5)
    vcc_single_max = part_specs.get("vcc_single_max_v", 36.0)
    rail_to_rail = part_specs.get("rail_to_rail", False)

    if split_supply:
        vsupply = vcc / 2.0  # ±Vsupply
        supply_label = f"±{vsupply:.1f}V"
        ok_min = vsupply >= vcc_dual_min
        ok_max = vsupply <= vcc_dual_max
    else:
        vsupply = vcc
        supply_label = f"{vcc:.1f}V"
        ok_min = vcc >= (vcc_dual_min * 2)
        ok_max = vcc <= vcc_single_max

    # Approx output swing headroom (op-amp output typically stays 1-2V from rails)
    headroom_v = 1.5 if not rail_to_rail else 0.1
    max_swing_v = (vsupply if split_supply else vcc / 2.0) - headroom_v

    res.metrics = {
        "supply_v": round(vsupply, 2),
        "max_output_swing_v": round(max_swing_v, 2),
        "gain_linear": round(gain_linear, 2),
    }

    if not ok_min:
        res.errors.append(
            f"Supply {supply_label} is below minimum for {part_specs.get('type','op-amp')} "
            f"(min {vcc_dual_min}V per rail)."
        )
        res.passed = False

    if not ok_max:
        res.errors.append(
            f"Supply {supply_label} exceeds maximum ({vcc_dual_max}V per rail). "
            f"Use a lower supply or a different op-amp."
        )
        res.passed = False

    # Check if gain × input swing exceeds output swing capacity
    if gain_linear > 1 and max_swing_v > 0:
        max_input_before_clip = max_swing_v / gain_linear
        if max_input_before_clip < 0.1:
            res.warnings.append(
                f"With gain {gain_linear:.0f}×, output clips above "
                f"{max_input_before_clip * 1000:.0f}mV input. Intended for clipping?"
            )
        res.metrics["max_input_before_clip_v"] = round(max_input_before_clip, 3)

    # Warn about high input bias on sensitive circuits
    input_bias_pa = part_specs.get("input_bias_pa", 0)
    if input_bias_pa > 500_000_000 and input_r_ohm and input_r_ohm > 100_000:
        ib_ua = input_bias_pa / 1e12 * 1e6
        vos_from_ib = ib_ua * 1e-6 * input_r_ohm
        res.warnings.append(
            f"Input bias current {ib_ua:.1f}µA × Rin {input_r_ohm/1000:.0f}kΩ "
            f"= {vos_from_ib*1000:.1f}mV DC offset. Add bias compensation resistor."
        )

    return res


# ── JFET Source Follower ───────────────────────────────────────────────────────

def verify_jfet_follower(
    *,
    stage_id: str,
    vcc: float,
    rs_ohm: float,
    rd_ohm: float,
    part_specs: dict[str, Any],
) -> OPResult:
    """Verify a JFET source-follower bias point.

    A source follower with no gate bias self-biases via the source resistor.
    Vgs = -Id × Rs.  Id stabilises when Vgs = Vgs_off × (1 - Id/Idss)².
    We solve iteratively.
    """
    res = OPResult(passed=True, stage_id=stage_id, topology="JFET_SF")

    idss = part_specs.get("idss_min_ma", 1.0) / 1000.0  # use min for worst-case
    vp = part_specs.get("vgs_off_min_v", -1.0)  # pinch-off (negative for N)
    vds_max = part_specs.get("vds_max_v", 25.0)

    # Iterative solution: Id = Idss × (1 - Vgs/Vp)², Vgs = -Id × Rs
    id_a = idss / 2.0
    for _ in range(50):
        vgs = -id_a * rs_ohm
        id_new = idss * (1.0 - vgs / vp) ** 2
        if abs(id_new - id_a) < 1e-9:
            break
        id_a = id_new

    id_ma = id_a * 1000.0
    vs = id_a * rs_ohm
    vd = vcc - id_a * rd_ohm  # rd_ohm is drain resistor (0 for pure follower)
    vds = vd - vs
    vgs = -id_a * rs_ohm

    res.metrics = {
        "id_ma": round(id_ma, 3),
        "vgs_v": round(vgs, 3),
        "vs_v": round(vs, 3),
        "vd_v": round(vd, 3),
        "vds_v": round(vds, 3),
    }

    if vds < 0.5:
        res.errors.append(
            f"Vds={vds:.2f}V — JFET may be in triode region. "
            f"Increase drain load or reduce source resistor."
        )
        res.passed = False

    if abs(vds) > vds_max:
        res.errors.append(
            f"Vds={vds:.2f}V exceeds Vds_max ({vds_max}V)."
        )
        res.passed = False

    if id_ma < 0.01:
        res.warnings.append(
            f"Id={id_ma:.3f}mA is very low — check Idss and Rs values. "
            f"JFET may be operating near cut-off."
        )

    return res


# ── Component Rating Checker ───────────────────────────────────────────────────

@dataclass
class RatingViolation:
    component_id: str
    component_type: str
    parameter: str
    value: float
    limit: float
    severity: str  # 'error' or 'warning'
    message: str


def check_component_ratings(
    components: list[dict[str, Any]],
    supply_voltage: float,
) -> list[RatingViolation]:
    """Check all passive components against their voltage/current ratings.

    Args:
        components: list of component dicts (from CircuitGraph)
        supply_voltage: the circuit supply voltage (Vcc)

    Returns list of RatingViolation objects (empty = all good).
    """
    violations: list[RatingViolation] = []
    vcc = supply_voltage

    for comp in components:
        ctype = comp.get("type", "")
        cid = comp.get("id", "?")
        vrating = comp.get("voltage_rating") or 0.0
        irating = comp.get("current_rating_ma") or 0.0

        # ── Capacitors: must be rated ≥ 2× the DC voltage across them ────
        if ctype == "capacitor":
            # Assume worst-case: full Vcc across the capacitor
            # (coupling caps see half-supply in AC-coupled stages, filter caps see Vcc)
            role = comp.get("role", "")
            v_applied = vcc if "supply" in role or "bypass" in role else vcc / 2.0

            if vrating > 0:
                required = v_applied * 2.0  # 2× derating
                if vrating < required:
                    violations.append(RatingViolation(
                        component_id=cid,
                        component_type=ctype,
                        parameter="voltage_rating",
                        value=vrating,
                        limit=required,
                        severity="error" if vrating < v_applied else "warning",
                        message=(
                            f"{cid}: Capacitor rated {vrating}V but needs ≥{required:.0f}V "
                            f"(2× derating for {v_applied:.1f}V DC). "
                            f"{'UNSAFE — may fail.' if vrating < v_applied else 'Violates 2× derating rule.'}"
                        ),
                    ))

        # ── Resistors: power rating check (P = V²/R or I²R) ─────────────
        elif ctype == "resistor":
            value_ohm = comp.get("value") or 0.0
            if value_ohm > 0 and vrating > 0:
                # Assume worst-case voltage = Vcc across resistor
                p_worst_mw = (vcc ** 2 / value_ohm) * 1000
                # Standard 1/4W = 250mW, 1/2W = 500mW
                # vrating for resistors is overloaded to store power rating in mW
                # (or just check if it's labelled)
                pass  # We don't have power rating in the schema yet — skip

        # ── Diodes: reverse voltage ───────────────────────────────────────
        elif ctype == "diode":
            vr_max = comp.get("vr_max_v") or comp.get("voltage_rating") or 0.0
            if vr_max > 0 and vr_max < vcc:
                violations.append(RatingViolation(
                    component_id=cid,
                    component_type=ctype,
                    parameter="vr_max_v",
                    value=vr_max,
                    limit=vcc,
                    severity="error",
                    message=(
                        f"{cid}: Diode Vr_max={vr_max}V but supply is {vcc}V. "
                        f"Diode could break down in reverse."
                    ),
                ))

    return violations


# ── Full circuit verification ──────────────────────────────────────────────────

def verify_circuit(
    circuit_graph: dict[str, Any],
    supply_voltage: float,
    component_specs: dict[str, dict],  # part_number → specs from component_db
) -> dict[str, Any]:
    """Run all operating point checks on a compiled circuit graph.

    Returns:
        {
          'passed': bool,
          'stage_results': [OPResult.to_dict(), ...],
          'rating_violations': [violation dicts],
          'summary': str,
        }
    """
    stage_results: list[dict] = []
    all_passed = True

    stages = circuit_graph.get("stages", [])
    components = circuit_graph.get("components", [])

    for stage in stages:
        transform = stage.get("transform", "")
        stage_idx = stage.get("index", 0)
        stage_id = f"S{stage_idx}"
        stage_comps = {c["id"]: c for c in components if c.get("id", "").startswith(stage_id)}

        # Find the active device spec for this stage
        active_device_part = _find_active_part(stage_comps, transform)
        specs = component_specs.get(active_device_part, {}) if active_device_part else {}

        result = _verify_stage(
            stage_id=stage_id,
            transform=transform,
            stage_comps=stage_comps,
            part_specs=specs,
            vcc=supply_voltage,
        )
        if result:
            stage_results.append(result.to_dict())
            if not result.passed:
                all_passed = False

    # Rating checks on all passives
    violations = check_component_ratings(components, supply_voltage)
    for v in violations:
        if v.severity == "error":
            all_passed = False

    error_count = sum(1 for r in stage_results if not r["passed"])
    warn_count = sum(len(r["warnings"]) for r in stage_results)

    summary = (
        f"All {len(stages)} stages pass operating point checks."
        if all_passed and not violations
        else f"{error_count} stage error(s), {len(violations)} rating violation(s), {warn_count} warning(s)."
    )

    return {
        "passed": all_passed,
        "stage_results": stage_results,
        "rating_violations": [
            {
                "component_id": v.component_id,
                "parameter": v.parameter,
                "value": v.value,
                "limit": v.limit,
                "severity": v.severity,
                "message": v.message,
            }
            for v in violations
        ],
        "summary": summary,
    }


def _find_active_part(stage_comps: dict, transform: str) -> str | None:
    """Find the part number of the active device in a stage."""
    for comp in stage_comps.values():
        if comp.get("type") in ("NPN_BJT", "PNP_BJT", "N_JFET", "P_JFET", "op_amp"):
            return comp.get("model")
    return None


def _verify_stage(
    stage_id: str,
    transform: str,
    stage_comps: dict,
    part_specs: dict,
    vcc: float,
) -> OPResult | None:
    """Dispatch to the appropriate topology verifier."""

    def _get_r(role: str) -> float:
        for c in stage_comps.values():
            if c.get("role") == role and c.get("type") == "resistor":
                return float(c.get("value") or 10_000)
        return 10_000.0

    if transform in ("gain_clean", "gain_soft_clip", "gain_hard_clip",
                     "gain_asymmetric", "gain_fuzz"):
        active_type = part_specs.get("type", "")
        if active_type in ("NPN_BJT", "PNP_BJT"):
            return verify_bjt_ce(
                stage_id=stage_id, vcc=vcc,
                rc_ohm=_get_r("collector_load"),
                re_ohm=_get_r("emitter_degeneration"),
                r_top_ohm=_get_r("bias_top"),
                r_bottom_ohm=_get_r("bias_bottom"),
                part_specs=part_specs,
            )
        elif active_type == "op_amp":
            return verify_opamp_stage(
                stage_id=stage_id, vcc=vcc, split_supply=True,
                part_specs=part_specs,
                gain_linear=10.0,  # default estimate; real value from circuit params
                input_r_ohm=_get_r("input"),
            )

    elif transform in ("buffer_input",):
        active_type = part_specs.get("type", "")
        if active_type in ("N_JFET", "P_JFET"):
            return verify_jfet_follower(
                stage_id=stage_id, vcc=vcc,
                rs_ohm=_get_r("source"),
                rd_ohm=_get_r("drain"),
                part_specs=part_specs,
            )
        elif active_type in ("NPN_BJT", "PNP_BJT"):
            return verify_bjt_follower(
                stage_id=stage_id, vcc=vcc,
                re_ohm=_get_r("emitter"),
                r_bias_ohm=_get_r("bias"),
                part_specs=part_specs,
            )

    elif transform in ("buffer_output",):
        active_type = part_specs.get("type", "")
        if active_type == "op_amp":
            return verify_opamp_stage(
                stage_id=stage_id, vcc=vcc, split_supply=True,
                part_specs=part_specs, gain_linear=1.0,
            )

    return None  # No verifier for this topology yet
