"""PedalForge parameter calculation engine.

Provides E-series rounding, display formatting, common circuit calculations,
and inventory-aware component snapping for guitar pedal circuit design.
"""

import math

import numpy as np

# ---------------------------------------------------------------------------
# E-series base values (one decade, 1.0 .. <10.0)
# ---------------------------------------------------------------------------

E12_BASE: list[float] = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]

E24_BASE: list[float] = sorted(
    E12_BASE + [1.1, 1.3, 1.6, 2.0, 2.4, 3.0, 3.6, 4.3, 5.1, 6.2, 7.5, 9.1]
)


# ---------------------------------------------------------------------------
# E-series snapping
# ---------------------------------------------------------------------------

def snap_to_e_series(value: float, series: str = "E24") -> float:
    """Snap *value* to the nearest standard E-series value.

    Parameters
    ----------
    value : float
        The raw calculated component value (must be positive).
    series : str
        ``"E12"`` or ``"E24"``.

    Returns
    -------
    float
        The closest E-series value in the same decade.
    """
    if value <= 0:
        raise ValueError("Value must be positive")

    base = E12_BASE if series.upper() == "E12" else E24_BASE

    # Determine the decade: e.g. 4700 -> exponent 3, mantissa 4.7
    exponent = math.floor(math.log10(value))
    mantissa = value / (10 ** exponent)

    # Find closest base value
    best = min(base, key=lambda b: abs(b - mantissa))

    # Also check if wrapping to the next decade's 1.0 is closer
    if abs(10.0 - mantissa) < abs(best - mantissa):
        return round(1.0 * 10 ** (exponent + 1), 12)

    return round(best * 10 ** exponent, 12)


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------

def format_resistance(ohms: float) -> str:
    """Format a resistance value to a human-readable string.

    Examples: 470 -> ``"470Ω"``, 10000 -> ``"10kΩ"``, 4700000 -> ``"4.7MΩ"``
    """
    if ohms >= 1e6:
        v = ohms / 1e6
        return f"{v:g}MΩ"
    elif ohms >= 1e3:
        v = ohms / 1e3
        return f"{v:g}kΩ"
    else:
        v = ohms
        return f"{v:g}Ω"


def format_capacitance(farads: float) -> str:
    """Format a capacitance value to a human-readable string.

    Examples: 1e-6 -> ``"1µF"``, 4.7e-9 -> ``"4.7nF"``, 100e-12 -> ``"100pF"``
    """
    if farads >= 1e-6:
        v = farads / 1e-6
        return f"{v:g}µF"
    elif farads >= 1e-9:
        v = farads / 1e-9
        return f"{v:g}nF"
    else:
        v = farads / 1e-12
        return f"{v:g}pF"


# ---------------------------------------------------------------------------
# Circuit calculations
# ---------------------------------------------------------------------------

class CircuitCalc:
    """Static methods for common guitar-pedal circuit calculations."""

    # -- RC / coupling ---------------------------------------------------

    @staticmethod
    def coupling_cap(f_low_hz: float, impedance_ohm: float) -> float:
        """Coupling capacitor for a given -3 dB low-frequency roll-off.

        Returns capacitance in farads: ``1 / (2π f R)``.
        """
        return 1.0 / (2.0 * math.pi * f_low_hz * impedance_ohm)

    @staticmethod
    def rc_lowpass_cutoff(r_ohm: float, c_farad: float) -> float:
        """Cutoff frequency (Hz) of an RC low-pass filter."""
        return 1.0 / (2.0 * math.pi * r_ohm * c_farad)

    @staticmethod
    def rc_highpass_cutoff(r_ohm: float, c_farad: float) -> float:
        """Cutoff frequency (Hz) of an RC high-pass filter."""
        return 1.0 / (2.0 * math.pi * r_ohm * c_farad)

    # -- BJT -------------------------------------------------------------

    @staticmethod
    def bjt_collector_resistor(vcc: float, ic_ma: float) -> float:
        """Collector resistor for a BJT common-emitter stage.

        Sets the collector at roughly Vcc/2 for maximum swing.
        Returns resistance in ohms.
        """
        ic_a = ic_ma / 1000.0
        return vcc / (2.0 * ic_a)

    @staticmethod
    def bjt_bias_resistors(
        vcc: float, vbe: float, ic_ma: float, beta: float
    ) -> tuple[float, float]:
        """Voltage-divider bias resistors for a BJT CE stage.

        Returns ``(R_top, R_bottom)`` in ohms.

        Design rules:
        * Rc  = Vcc / (2 Ic)
        * Re  = Rc / 10
        * Vb  = Vbe + Ic * Re
        * Stability factor 10: divider current = 10 * Ib
        """
        ic_a = ic_ma / 1000.0
        ib = ic_a / beta
        rc = vcc / (2.0 * ic_a)
        re = rc / 10.0
        vb = vbe + ic_a * re
        i_div = 10.0 * ib  # current through the divider

        r_bottom = vb / i_div
        r_top = (vcc - vb) / i_div
        return (r_top, r_bottom)

    # -- Gain helpers ----------------------------------------------------

    @staticmethod
    def gain_from_resistors(rc: float, re: float) -> float:
        """Voltage gain of an un-bypassed common-emitter stage: Rc / Re."""
        return rc / re

    @staticmethod
    def resistors_for_gain(gain_linear: float, rc: float) -> float:
        """Emitter resistor needed for a target CE gain: Re = Rc / gain."""
        return rc / gain_linear

    # -- Op-amp ----------------------------------------------------------

    @staticmethod
    def opamp_noninverting_gain(rf: float, rg: float) -> float:
        """Non-inverting op-amp gain: 1 + Rf/Rg."""
        return 1.0 + rf / rg

    @staticmethod
    def opamp_noninverting_resistors(
        gain: float, rf: float = 100_000.0
    ) -> tuple[float, float]:
        """Resistor pair for non-inverting op-amp gain.

        Returns ``(Rf, Rg)`` where ``gain = 1 + Rf/Rg``.
        """
        rg = rf / (gain - 1.0)
        return (rf, rg)

    @staticmethod
    def opamp_inverting_gain(rf: float, ri: float) -> float:
        """Inverting op-amp gain: -Rf/Ri."""
        return -rf / ri

    @staticmethod
    def opamp_inverting_resistors(
        gain: float, rf: float = 100_000.0
    ) -> tuple[float, float]:
        """Resistor pair for inverting op-amp gain.

        *gain* is the desired magnitude (positive number).
        Returns ``(Rf, Ri)``.
        """
        ri = rf / gain
        return (rf, ri)

    # -- dB conversions --------------------------------------------------

    @staticmethod
    def db_to_linear(db: float) -> float:
        """Convert decibels to linear voltage ratio."""
        return 10.0 ** (db / 20.0)

    @staticmethod
    def linear_to_db(linear: float) -> float:
        """Convert linear voltage ratio to decibels."""
        return 20.0 * math.log10(linear)

    # -- Passive helpers -------------------------------------------------

    @staticmethod
    def parallel_resistance(r1: float, r2: float) -> float:
        """Parallel combination of two resistors."""
        return (r1 * r2) / (r1 + r2)

    @staticmethod
    def voltage_divider(vin: float, r1: float, r2: float) -> float:
        """Output voltage of a resistive divider: Vin * R2 / (R1 + R2)."""
        return vin * r2 / (r1 + r2)

    # -- Active filters --------------------------------------------------

    @staticmethod
    def sallen_key_components(
        f_cutoff_hz: float, q: float = 0.707
    ) -> dict[str, float]:
        """Component values for an equal-R Sallen-Key low-pass filter.

        Uses R = 10 kΩ as starting point and derives capacitor values.

        For equal-R design:
        * C2 = 1 / (4 π Q f R)  (adjusted from standard derivation)
        * C1 = C2 * (2Q)^2      (to maintain Q)

        The standard equal-R Sallen-Key relationships are:

            f = 1 / (2π R √(C1 C2))
            Q = √(C1 C2) / (C1 + C2 - C1)  ... simplified for equal R

        We use the textbook formulas:
            C1 = 2Q / (2π f R)
            C2 = 1 / (2Q * 2π f R)

        Returns a dict with keys ``R1``, ``R2``, ``C1``, ``C2``.
        """
        r = 10_000.0  # 10 kΩ starting point
        c1 = (2.0 * q) / (2.0 * math.pi * f_cutoff_hz * r)
        c2 = 1.0 / (2.0 * q * 2.0 * math.pi * f_cutoff_hz * r)
        return {"R1": r, "R2": r, "C1": c1, "C2": c2}

    @staticmethod
    def gyrator_components(
        f_center_hz: float, q: float, gain_db: float
    ) -> dict[str, float]:
        """Component values for an op-amp gyrator (inductor simulator) mid-boost.

        A gyrator simulates an inductor using an op-amp, a capacitor, and
        resistors, creating a resonant peak useful for mid-boost circuits.

        The virtual inductance is  L = R_gyr * R_gyr_feed * C_gyr.
        The resonant frequency is  f = 1 / (2π √(L C_gyr))  which simplifies
        when we pick equal resistors for the gyrator network.

        Design procedure (equal-R simplification):
        * Pick C = 100 nF as a practical starting cap.
        * R_gyr = 1 / (2π f C)  — sets the centre frequency.
        * R_series = R_gyr / Q  — sets the bandwidth.
        * R_gain controls the boost:  R_gain = R_series * (10^(gain_db/20) - 1).

        Returns a dict with keys:
        ``R_gyr``, ``C_gyr``, ``R_series``, ``R_gain``.
        """
        c_gyr = 100e-9  # 100 nF
        r_gyr = 1.0 / (2.0 * math.pi * f_center_hz * c_gyr)
        r_series = r_gyr / q
        linear_gain = 10.0 ** (gain_db / 20.0)
        r_gain = r_series * (linear_gain - 1.0)
        return {
            "R_gyr": r_gyr,
            "C_gyr": c_gyr,
            "R_series": r_series,
            "R_gain": r_gain,
        }


# ---------------------------------------------------------------------------
# Inventory-aware snapping
# ---------------------------------------------------------------------------

def snap_to_inventory(
    value: float,
    component_type: str,
    available_values: list[float],
    tolerance_percent: float = 20.0,
) -> float | None:
    """Snap a calculated value to the nearest item in an inventory list.

    Parameters
    ----------
    value : float
        The ideal calculated component value.
    component_type : str
        A label such as ``"resistor"`` or ``"capacitor"`` (reserved for
        future filtering logic; currently unused beyond documentation).
    available_values : list[float]
        The inventory of real component values to choose from.
    tolerance_percent : float
        Maximum acceptable deviation (as a percentage of *value*).
        If no inventory value falls within this window, ``None`` is returned.

    Returns
    -------
    float | None
        The closest inventory value within tolerance, or ``None``.
    """
    if not available_values:
        return None

    arr = np.array(available_values, dtype=np.float64)
    diffs = np.abs(arr - value)
    idx = int(np.argmin(diffs))
    closest = available_values[idx]

    if abs(closest - value) / value * 100.0 <= tolerance_percent:
        return closest
    return None
