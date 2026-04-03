"""
Real-Time DSP Engine — Converts validated circuit models into a real-time
audio processing chain. Handles audio I/O via sounddevice.

Architecture:
- Linear stages → IIR biquad filters
- Nonlinear stages → waveshaping functions
- Modulation stages → LFO + parameter modulation
- All coefficients update instantly when knobs change
"""

import numpy as np
import threading
from typing import Optional, Callable
from dataclasses import dataclass, field

try:
    import sounddevice as sd
except ImportError:
    sd = None


@dataclass
class DSPStage:
    """A single stage in the DSP processing chain."""
    name: str
    stage_index: int
    process: Callable  # (samples: np.ndarray, params: dict) -> np.ndarray
    params: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)  # persistent filter state


@dataclass
class AudioConfig:
    input_device: Optional[int] = None
    output_device: Optional[int] = None
    sample_rate: int = 48000
    buffer_size: int = 256
    channels: int = 1


class DSPChain:
    """
    Manages an ordered chain of DSP stages and processes audio through them.
    """

    def __init__(self):
        self.stages: list[DSPStage] = []
        self.bypass = False
        self.input_gain = 1.0
        self.output_gain = 1.0
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self.stages = []

    def add_stage(self, stage: DSPStage):
        with self._lock:
            self.stages.append(stage)

    def update_param(self, stage_index: int, param_name: str, value: float):
        """Update a parameter on a stage (e.g., pot position). Instant, no rebuild."""
        with self._lock:
            for stage in self.stages:
                if stage.stage_index == stage_index:
                    stage.params[param_name] = value
                    break

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Process a block of audio samples through the chain."""
        if self.bypass:
            return samples

        x = samples * self.input_gain

        with self._lock:
            for stage in self.stages:
                x = stage.process(x, stage.params, stage.state)

        return x * self.output_gain


# ============================================================
# DSP Processing Functions
# ============================================================

def make_biquad_lowpass(sample_rate: int = 48000):
    """Create a biquad lowpass filter processor."""
    def process(samples, params, state):
        fc = params.get("cutoff_hz", 5000)
        q = params.get("q", 0.707)

        # Coefficient calculation
        w0 = 2 * np.pi * fc / sample_rate
        alpha = np.sin(w0) / (2 * q)
        b0 = (1 - np.cos(w0)) / 2
        b1 = 1 - np.cos(w0)
        b2 = (1 - np.cos(w0)) / 2
        a0 = 1 + alpha
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha

        # Normalize
        b = np.array([b0/a0, b1/a0, b2/a0])
        a = np.array([1.0, a1/a0, a2/a0])

        # Process with state
        x1 = state.get("x1", 0.0)
        x2 = state.get("x2", 0.0)
        y1 = state.get("y1", 0.0)
        y2 = state.get("y2", 0.0)

        output = np.zeros_like(samples)
        for i in range(len(samples)):
            x = samples[i]
            y = b[0]*x + b[1]*x1 + b[2]*x2 - a[1]*y1 - a[2]*y2
            output[i] = y
            x2, x1 = x1, x
            y2, y1 = y1, y

        state["x1"], state["x2"] = x1, x2
        state["y1"], state["y2"] = y1, y2
        return output

    return process


def make_biquad_highpass(sample_rate: int = 48000):
    """Create a biquad highpass filter processor."""
    def process(samples, params, state):
        fc = params.get("cutoff_hz", 80)
        q = params.get("q", 0.707)

        w0 = 2 * np.pi * fc / sample_rate
        alpha = np.sin(w0) / (2 * q)
        b0 = (1 + np.cos(w0)) / 2
        b1 = -(1 + np.cos(w0))
        b2 = (1 + np.cos(w0)) / 2
        a0 = 1 + alpha
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha

        b = np.array([b0/a0, b1/a0, b2/a0])
        a = np.array([1.0, a1/a0, a2/a0])

        x1 = state.get("x1", 0.0)
        x2 = state.get("x2", 0.0)
        y1 = state.get("y1", 0.0)
        y2 = state.get("y2", 0.0)

        output = np.zeros_like(samples)
        for i in range(len(samples)):
            x = samples[i]
            y = b[0]*x + b[1]*x1 + b[2]*x2 - a[1]*y1 - a[2]*y2
            output[i] = y
            x2, x1 = x1, x
            y2, y1 = y1, y

        state["x1"], state["x2"] = x1, x2
        state["y1"], state["y2"] = y1, y2
        return output

    return process


def make_biquad_bandpass(sample_rate: int = 48000):
    """Create a biquad bandpass filter processor."""
    def process(samples, params, state):
        fc = params.get("center_hz", 1000)
        q = params.get("q", 1.0)
        gain_db = params.get("gain_db", 6)

        w0 = 2 * np.pi * fc / sample_rate
        alpha = np.sin(w0) / (2 * q)
        A = 10 ** (gain_db / 40)

        b0 = alpha * A
        b1 = 0
        b2 = -alpha * A
        a0 = 1 + alpha
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha

        b = np.array([b0/a0, b1/a0, b2/a0])
        a = np.array([1.0, a1/a0, a2/a0])

        x1 = state.get("x1", 0.0)
        x2 = state.get("x2", 0.0)
        y1 = state.get("y1", 0.0)
        y2 = state.get("y2", 0.0)

        output = np.zeros_like(samples)
        for i in range(len(samples)):
            x = samples[i]
            y = b[0]*x + b[1]*x1 + b[2]*x2 - a[1]*y1 - a[2]*y2
            output[i] = y
            x2, x1 = x1, x
            y2, y1 = y1, y

        state["x1"], state["x2"] = x1, x2
        state["y1"], state["y2"] = y1, y2
        return output

    return process


def make_gain(sample_rate: int = 48000):
    """Clean linear gain stage."""
    def process(samples, params, state):
        gain_db = params.get("gain_db", 0)
        gain_linear = 10 ** (gain_db / 20)
        return samples * gain_linear
    return process


def _shockley_diode(v: np.ndarray, Is: float, N: float, Vt: float = 0.026) -> np.ndarray:
    """
    Shockley diode equation: I = Is * (exp(V / (N * Vt)) - 1)
    Returns current through diode for given voltage.

    Parameters:
        v: voltage across diode (numpy array)
        Is: saturation current (amps) — defines diode type
            Silicon 1N4148: Is = 2.52e-9, N = 1.752
            Germanium 1N34A: Is = 2e-7, N = 1.3
            LED: Is = 93.2e-12, N = 3.73
        N: ideality factor (1.0-2.0 for normal diodes, higher for LEDs)
        Vt: thermal voltage (~26mV at room temperature)
    """
    # Clamp exponent to prevent overflow (exp(40) ≈ 2e17 is safe)
    exponent = np.clip(v / (N * Vt), -40, 40)
    return Is * (np.exp(exponent) - 1)


def _diode_clip_voltage(v_in: np.ndarray, Is: float, N: float, Rf: float,
                        Vt: float = 0.026) -> np.ndarray:
    """
    Compute output voltage for diode-in-feedback op-amp clipping.

    In the feedback clipping topology (like a Tube Screamer), the diodes
    are in parallel with Rf. The output voltage is determined by the
    voltage at which the diode current equals the signal current through Rf.

    For small signals: Vout ≈ Vin * (Rf/Ri) (normal op-amp gain)
    For large signals: Vout ≈ N*Vt*ln(Vin/(Ri*Is)) (diode-limited)

    This uses Newton-Raphson iteration to solve the implicit equation:
    V_out = V_in - I_diode(V_out) * Rf

    But for real-time we use a fast analytical approximation based on
    the Lambert W function approach.
    """
    # Fast approximation: blend between linear gain and diode-limited regions
    # using the Wright omega function approximation
    v_abs = np.abs(v_in)
    sign = np.sign(v_in)

    # Diode threshold voltage (where clipping begins)
    # This is where diode current starts to dominate: Is*exp(Vd/(N*Vt)) ≈ Vd/Rf
    # Approximate: Vd_threshold ≈ N*Vt*ln(1/(Is*Rf)) — but simplified to
    # the forward voltage at 1mA which is what matters in practice
    Vf = N * Vt * np.log(1e-3 / Is + 1)  # forward voltage at 1mA

    # Below threshold: linear
    # Above threshold: logarithmic compression (diode curve)
    # Smooth blend using the actual Shockley equation solved iteratively
    v_out = np.zeros_like(v_in)

    # Use 2 Newton-Raphson iterations (sufficient for audio)
    # Solving: v_out + Rf * Is * (exp(v_out/(N*Vt)) - 1) = v_abs
    # f(v) = v + Rf*Is*(exp(v/(N*Vt)) - 1) - v_abs
    # f'(v) = 1 + Rf*Is/(N*Vt) * exp(v/(N*Vt))

    # Initial guess: clamp to slightly below Vf
    v_guess = np.minimum(v_abs, Vf * 1.2)

    for _ in range(3):
        exp_term = np.exp(np.clip(v_guess / (N * Vt), -40, 40))
        f_val = v_guess + Rf * Is * (exp_term - 1) - v_abs
        f_deriv = 1.0 + Rf * Is / (N * Vt) * exp_term
        v_guess = v_guess - f_val / f_deriv
        v_guess = np.maximum(v_guess, 0)  # voltage across diode can't be negative in this topology

    v_out = sign * v_guess
    return v_out


# Diode parameters for different types (Is in amps, N = ideality factor)
DIODE_PARAMS = {
    "silicon": {"Is": 2.52e-9, "N": 1.752, "Vf_approx": 0.6},   # 1N4148
    "germanium": {"Is": 2e-7, "N": 1.3, "Vf_approx": 0.3},      # 1N34A
    "led": {"Is": 93.2e-12, "N": 3.73, "Vf_approx": 1.8},       # Red LED
    "schottky": {"Is": 1e-6, "N": 1.05, "Vf_approx": 0.25},     # BAT41
}


def make_soft_clip(sample_rate: int = 48000):
    """
    Soft clipping modeled with Shockley diode equation.
    Accurately models diode clipping in op-amp feedback topology.
    Different diode types produce different clipping curves.
    """
    def process(samples, params, state):
        gain_db = params.get("gain_db", 20)
        diode_type = params.get("diode_type", "silicon")
        asymmetry = params.get("asymmetry", 0.0)
        Rf = params.get("Rf", 100000)  # feedback resistor value

        diode = DIODE_PARAMS.get(diode_type, DIODE_PARAMS["silicon"])
        Is = diode["Is"]
        N = diode["N"]

        gain_linear = 10 ** (gain_db / 20)
        x = samples * gain_linear

        if asymmetry > 0:
            # Asymmetric clipping: different diode types for pos/neg
            # e.g., silicon on positive, germanium on negative
            diode_neg = DIODE_PARAMS.get("germanium", DIODE_PARAMS["silicon"])
            pos = np.maximum(x, 0)
            neg = np.minimum(x, 0)
            pos_clipped = _diode_clip_voltage(pos, Is, N, Rf)
            neg_clipped = _diode_clip_voltage(neg, diode_neg["Is"], diode_neg["N"], Rf)
            return pos_clipped + neg_clipped
        else:
            return _diode_clip_voltage(x, Is, N, Rf)

    return process


def make_hard_clip(sample_rate: int = 48000):
    """
    Hard clipping — diodes to ground (not in feedback).
    Models circuits like the RAT where diodes clip the output to ground.
    Sharper knee than soft clip because there's no feedback linearization.
    """
    def process(samples, params, state):
        gain_db = params.get("gain_db", 30)
        diode_type = params.get("diode_type", "silicon")

        diode = DIODE_PARAMS.get(diode_type, DIODE_PARAMS["silicon"])
        Is = diode["Is"]
        N = diode["N"]
        Vt = 0.026

        gain_linear = 10 ** (gain_db / 20)
        x = samples * gain_linear

        # Hard clip: signal is directly clamped by diode forward voltage
        # V_out = N*Vt*ln(|V_in|*R_load/(N*Vt*Is) + 1) * sign(V_in)
        # Simplified: the diode conducts sharply at Vf, so we model the
        # transition with a smooth clamp using the actual diode equation
        v_abs = np.abs(x)
        sign = np.sign(x)

        # For diodes to ground, the output is clamped near Vf
        # Use inverse Shockley: V = N*Vt*ln(I/Is + 1) where I ≈ V_in/R_series
        R_series = 4700  # typical output resistor before clipping diodes
        I_signal = v_abs / R_series
        V_diode = N * Vt * np.log(np.maximum(I_signal / Is + 1, 1))
        V_diode = np.minimum(V_diode, v_abs)  # can't exceed input

        return sign * V_diode

    return process


def make_fuzz(sample_rate: int = 48000):
    """
    Fuzz — BJT saturation modeled with Ebers-Moll transfer characteristic.
    Two-stage BJT fuzz with heavy saturation and filtering.
    """
    lp = make_biquad_lowpass(sample_rate)

    def process(samples, params, state):
        gain_db = params.get("gain_db", 45)
        tone_hz = params.get("tone_hz", 3000)
        bias = params.get("bias", 0.5)  # 0=starved/gated, 0.5=normal, 1=saturated
        transistor_type = params.get("transistor_type", "silicon")

        gain_linear = 10 ** (gain_db / 20)

        # BJT saturation model:
        # A BJT driven into saturation has a transfer characteristic
        # that looks like: Vout = Vcc * (1 - exp(-gain * Vin / Vt))
        # for positive input, and clips to Vce_sat ≈ 0.2V at the bottom
        Vt = 0.026
        Vcc = 9.0
        Vce_sat = 0.2 if transistor_type == "silicon" else 0.35  # germanium has higher Vce_sat

        # Bias affects the operating point — starved bias = gated fuzz
        bias_offset = (bias - 0.5) * 0.01  # small DC offset at input

        x = (samples + bias_offset) * gain_linear

        # First stage: BJT transfer function
        # Collector voltage swings between Vcc and Vce_sat
        # Approximation of Ebers-Moll in saturation:
        v_norm = x / (Vt * 50)  # normalized, scaled for typical BJT stage
        stage1 = (Vcc - Vce_sat) * np.tanh(v_norm) * 0.5

        # Second stage: inverted, harder saturation
        v_norm2 = stage1 * gain_linear * 0.1 / (Vt * 30)
        stage2 = -(Vcc - Vce_sat) * np.tanh(v_norm2) * 0.5

        # For gated fuzz (bias < 0.3): add crossover distortion
        if bias < 0.3:
            dead_zone = (0.3 - bias) * 0.5  # volts of dead zone
            mask = np.abs(stage2) < dead_zone
            stage2[mask] = 0

        # Tone filtering
        if "lp_state" not in state:
            state["lp_state"] = {}
        lp_params = {"cutoff_hz": tone_hz, "q": 0.707}
        output = lp(stage2, lp_params, state["lp_state"])

        # Normalize output level
        output = output * 0.3  # fuzz is loud, bring it down

        return output

    return process


def make_tremolo(sample_rate: int = 48000):
    """Tremolo — LFO modulates amplitude."""
    def process(samples, params, state):
        rate_hz = params.get("rate_hz", 5.0)
        depth = params.get("depth", 0.5)  # 0-1

        phase = state.get("phase", 0.0)
        phase_inc = 2 * np.pi * rate_hz / sample_rate

        output = np.zeros_like(samples)
        for i in range(len(samples)):
            lfo = 1.0 - depth * (0.5 + 0.5 * np.sin(phase))
            output[i] = samples[i] * lfo
            phase += phase_inc

        state["phase"] = phase % (2 * np.pi)
        return output

    return process


def make_compressor(sample_rate: int = 48000):
    """Simple envelope-following compressor."""
    def process(samples, params, state):
        threshold_db = params.get("threshold_db", -20)
        ratio = params.get("ratio", 4.0)
        attack_ms = params.get("attack_ms", 10)
        release_ms = params.get("release_ms", 100)

        threshold = 10 ** (threshold_db / 20)
        attack_coeff = np.exp(-1.0 / (sample_rate * attack_ms / 1000))
        release_coeff = np.exp(-1.0 / (sample_rate * release_ms / 1000))

        envelope = state.get("envelope", 0.0)

        output = np.zeros_like(samples)
        for i in range(len(samples)):
            abs_sample = abs(samples[i])
            if abs_sample > envelope:
                envelope = attack_coeff * envelope + (1 - attack_coeff) * abs_sample
            else:
                envelope = release_coeff * envelope + (1 - release_coeff) * abs_sample

            if envelope > threshold:
                gain_reduction = threshold * (envelope / threshold) ** (1 / ratio - 1)
                output[i] = samples[i] * (gain_reduction / (envelope + 1e-10))
            else:
                output[i] = samples[i]

        state["envelope"] = envelope
        return output

    return process


def make_shelf_filter(filter_type: str = "high", sample_rate: int = 48000):
    """High or low shelf filter."""
    def process(samples, params, state):
        fc = params.get("cutoff_hz", 3000 if filter_type == "high" else 300)
        gain_db = params.get("gain_db", 6)
        A = 10 ** (gain_db / 40)

        w0 = 2 * np.pi * fc / sample_rate
        alpha = np.sin(w0) / 2 * np.sqrt((A + 1/A) * (1/0.707 - 1) + 2)

        if filter_type == "high":
            b0 = A * ((A+1) + (A-1)*np.cos(w0) + 2*np.sqrt(A)*alpha)
            b1 = -2*A * ((A-1) + (A+1)*np.cos(w0))
            b2 = A * ((A+1) + (A-1)*np.cos(w0) - 2*np.sqrt(A)*alpha)
            a0 = (A+1) - (A-1)*np.cos(w0) + 2*np.sqrt(A)*alpha
            a1 = 2 * ((A-1) - (A+1)*np.cos(w0))
            a2 = (A+1) - (A-1)*np.cos(w0) - 2*np.sqrt(A)*alpha
        else:
            b0 = A * ((A+1) - (A-1)*np.cos(w0) + 2*np.sqrt(A)*alpha)
            b1 = 2*A * ((A-1) - (A+1)*np.cos(w0))
            b2 = A * ((A+1) - (A-1)*np.cos(w0) - 2*np.sqrt(A)*alpha)
            a0 = (A+1) + (A-1)*np.cos(w0) + 2*np.sqrt(A)*alpha
            a1 = -2 * ((A-1) + (A+1)*np.cos(w0))
            a2 = (A+1) + (A-1)*np.cos(w0) - 2*np.sqrt(A)*alpha

        b = np.array([b0/a0, b1/a0, b2/a0])
        a = np.array([1.0, a1/a0, a2/a0])

        x1 = state.get("x1", 0.0)
        x2 = state.get("x2", 0.0)
        y1 = state.get("y1", 0.0)
        y2 = state.get("y2", 0.0)

        output = np.zeros_like(samples)
        for i in range(len(samples)):
            x = samples[i]
            y = b[0]*x + b[1]*x1 + b[2]*x2 - a[1]*y1 - a[2]*y2
            output[i] = y
            x2, x1 = x1, x
            y2, y1 = y1, y

        state["x1"], state["x2"] = x1, x2
        state["y1"], state["y2"] = y1, y2
        return output

    return process


# ============================================================
# DSP Stage Factory — Maps block types to DSP processors
# ============================================================

DSP_FACTORY = {
    "buffer_input": lambda sr: make_gain(sr),
    "buffer_output": lambda sr: make_gain(sr),
    "gain_clean": lambda sr: make_gain(sr),
    "gain_soft_clip": lambda sr: make_soft_clip(sr),
    "gain_hard_clip": lambda sr: make_hard_clip(sr),
    "gain_asymmetric": lambda sr: make_soft_clip(sr),
    "gain_fuzz": lambda sr: make_fuzz(sr),
    "filter_lp": lambda sr: make_biquad_lowpass(sr),
    "filter_hp": lambda sr: make_biquad_highpass(sr),
    "filter_bp": lambda sr: make_biquad_bandpass(sr),
    "filter_notch": lambda sr: make_biquad_bandpass(sr),  # inverted in params
    "filter_tonestack": lambda sr: make_biquad_lowpass(sr),  # simplified for now
    "compress": lambda sr: make_compressor(sr),
    "modulate_tremolo": lambda sr: make_tremolo(sr),
}


def build_dsp_chain_from_plan(stages: list[dict], sample_rate: int = 48000) -> DSPChain:
    """
    Build a DSPChain from a list of stage definitions.
    Each stage dict has: transform, params, stage_index.
    """
    chain = DSPChain()

    for stage_def in stages:
        transform = stage_def["transform"]
        params = stage_def.get("params", {})
        stage_index = stage_def.get("stage_index", 0)

        factory = DSP_FACTORY.get(transform)
        if factory is None:
            continue

        processor = factory(sample_rate)

        # Map circuit params to DSP params
        dsp_params = _map_params_to_dsp(transform, params)

        dsp_stage = DSPStage(
            name=transform,
            stage_index=stage_index,
            process=processor,
            params=dsp_params,
        )
        chain.add_stage(dsp_stage)

    return chain


def _map_params_to_dsp(transform: str, circuit_params: dict) -> dict:
    """Map circuit-level parameters to DSP processor parameters."""
    dsp = {}

    if transform in ("buffer_input", "buffer_output"):
        dsp["gain_db"] = 0

    elif transform == "gain_clean":
        dsp["gain_db"] = circuit_params.get("gain_db", 10)

    elif transform in ("gain_soft_clip", "gain_asymmetric"):
        dsp["gain_db"] = circuit_params.get("gain_db", 20)
        dsp["diode_type"] = circuit_params.get("diode", "silicon")
        dsp["Rf"] = circuit_params.get("Rf", 100000)
        if transform == "gain_asymmetric" or circuit_params.get("clip_type") == "asymmetric":
            dsp["asymmetry"] = 0.5

    elif transform == "gain_hard_clip":
        dsp["gain_db"] = circuit_params.get("gain_db", 30)
        dsp["diode_type"] = circuit_params.get("diode", "silicon")

    elif transform == "gain_fuzz":
        dsp["gain_db"] = circuit_params.get("gain_db", 45)
        dsp["tone_hz"] = circuit_params.get("tone_hz", 3000)
        dsp["bias"] = circuit_params.get("bias", 0.5)
        dsp["transistor_type"] = circuit_params.get("transistor", "silicon")

    elif transform == "filter_lp":
        dsp["cutoff_hz"] = circuit_params.get("f_cutoff_hz", 5000)
        dsp["q"] = circuit_params.get("q", 0.707)

    elif transform == "filter_hp":
        dsp["cutoff_hz"] = circuit_params.get("f_cutoff_hz", 80)
        dsp["q"] = circuit_params.get("q", 0.707)

    elif transform == "filter_bp":
        dsp["center_hz"] = circuit_params.get("f_center_hz", 1000)
        dsp["q"] = circuit_params.get("q", 1.0)
        dsp["gain_db"] = circuit_params.get("gain_db", 6)

    elif transform == "filter_tonestack":
        dsp["cutoff_hz"] = circuit_params.get("f_cutoff_hz", 3000)
        dsp["q"] = 0.707

    elif transform == "compress":
        dsp["threshold_db"] = circuit_params.get("threshold_db", -20)
        dsp["ratio"] = circuit_params.get("ratio", 4.0)

    elif transform == "modulate_tremolo":
        dsp["rate_hz"] = circuit_params.get("rate_hz", 5.0)
        dsp["depth"] = circuit_params.get("depth", 0.5)

    return dsp


# ============================================================
# Audio Engine — Manages sounddevice I/O
# ============================================================

class AudioEngine:
    """Manages real-time audio I/O using sounddevice."""

    def __init__(self):
        self.config = AudioConfig()
        self.dsp_chain = DSPChain()
        self._stream: Optional[object] = None
        self._running = False
        self._level_callback: Optional[Callable] = None
        self._input_level = 0.0
        self._output_level = 0.0

    @staticmethod
    def list_devices() -> list[dict]:
        """List available audio devices."""
        if sd is None:
            return []
        devices = sd.query_devices()
        result = []
        for i, dev in enumerate(devices):
            result.append({
                "index": i,
                "name": dev["name"],
                "max_input_channels": dev["max_input_channels"],
                "max_output_channels": dev["max_output_channels"],
                "default_samplerate": dev["default_samplerate"],
            })
        return result

    def configure(self, config: AudioConfig):
        """Update audio configuration."""
        was_running = self._running
        if was_running:
            self.stop()
        self.config = config
        if was_running:
            self.start()

    def start(self):
        """Start the audio stream."""
        if sd is None:
            raise RuntimeError("sounddevice not available. Install with: pip install sounddevice")
        if self._running:
            return

        def callback(indata, outdata, frames, time, status):
            if status:
                pass  # Could log status messages
            # Get mono input
            audio_in = indata[:, 0].copy()

            # Track input level
            self._input_level = float(np.max(np.abs(audio_in)))

            # Process through DSP chain
            audio_out = self.dsp_chain.process(audio_in)

            # Track output level
            self._output_level = float(np.max(np.abs(audio_out)))

            # Write to output
            outdata[:, 0] = audio_out
            if outdata.shape[1] > 1:
                outdata[:, 1] = audio_out  # Duplicate to stereo

        out_channels = 2  # Stereo output for monitoring
        self._stream = sd.Stream(
            device=(self.config.input_device, self.config.output_device),
            samplerate=self.config.sample_rate,
            blocksize=self.config.buffer_size,
            channels=(self.config.channels, out_channels),
            callback=callback,
            dtype="float32",
        )
        self._stream.start()
        self._running = True

    def stop(self):
        """Stop the audio stream."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def input_level(self) -> float:
        return self._input_level

    @property
    def output_level(self) -> float:
        return self._output_level
