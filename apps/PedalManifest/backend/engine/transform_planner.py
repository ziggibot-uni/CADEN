"""
Transform Planner — Rule engine that maps DesignIntent to a TransformPlan.

This is purely deterministic. No AI. Maps desired sound characteristics
to an ordered list of signal transformation operations.
"""

from backend.models.design_intent import DesignIntent
from backend.models.transform_plan import TransformPlan, TransformStage

# Maps reference sounds to their typical transform chains
REFERENCE_PRESETS: dict[str, list[dict]] = {
    "tube screamer": [
        {"transform": "gain_soft_clip", "params": {"gain_db": 20, "clip_type": "symmetric", "diode": "silicon"}},
        {"transform": "filter_bp", "params": {"f_center_hz": 720, "q": 1.0}},
    ],
    "ts808": [
        {"transform": "gain_soft_clip", "params": {"gain_db": 20, "clip_type": "symmetric", "diode": "silicon"}},
        {"transform": "filter_bp", "params": {"f_center_hz": 720, "q": 1.0}},
    ],
    "rat": [
        {"transform": "gain_hard_clip", "params": {"gain_db": 40, "clip_type": "symmetric", "diode": "silicon"}},
        {"transform": "filter_lp", "params": {"f_cutoff_hz": 3000}},
    ],
    "big muff": [
        {"transform": "gain_soft_clip", "params": {"gain_db": 25, "clip_type": "symmetric", "diode": "silicon"}},
        {"transform": "gain_soft_clip", "params": {"gain_db": 25, "clip_type": "symmetric", "diode": "silicon"}},
        {"transform": "filter_tonestack", "params": {"type": "big_muff_tone"}},
    ],
    "fuzz face": [
        {"transform": "gain_fuzz", "params": {"gain_db": 45, "transistor": "germanium"}},
    ],
    "klon": [
        {"transform": "gain_clean", "params": {"gain_db": 10}},
        {"transform": "gain_soft_clip", "params": {"gain_db": 15, "clip_type": "asymmetric", "diode": "germanium"}},
        {"transform": "filter_tonestack", "params": {"type": "baxandall"}},
    ],
    "blues breaker": [
        {"transform": "gain_soft_clip", "params": {"gain_db": 20, "clip_type": "symmetric", "diode": "silicon"}},
        {"transform": "filter_tonestack", "params": {"type": "marshall"}},
    ],
    "boss ds-1": [
        {"transform": "gain_hard_clip", "params": {"gain_db": 35, "clip_type": "asymmetric", "diode": "silicon"}},
        {"transform": "filter_lp", "params": {"f_cutoff_hz": 4000}},
    ],
    "mxr distortion+": [
        {"transform": "gain_hard_clip", "params": {"gain_db": 30, "clip_type": "symmetric", "diode": "germanium"}},
    ],
    "tone bender": [
        {"transform": "gain_fuzz", "params": {"gain_db": 50, "transistor": "germanium"}},
    ],
}

# Maps character descriptors to parameter modifications
CHARACTER_MODIFIERS: dict[str, dict] = {
    "warm": {"avoid_transforms": ["filter_hp"], "prefer_diode": "germanium", "lp_cutoff_shift": -1000},
    "bright": {"prefer_presence": True, "lp_cutoff_shift": 2000},
    "dark": {"lp_cutoff_shift": -2000, "add_lp": True},
    "thick": {"hp_cutoff_shift": -50, "gain_boost_db": 5},
    "thin": {"hp_cutoff_shift": 100, "gain_reduce_db": 5},
    "aggressive": {"gain_boost_db": 10, "prefer_hard_clip": True},
    "smooth": {"prefer_soft_clip": True, "lp_cutoff_shift": -500},
    "sputtery": {"prefer_fuzz": True, "bias_shift": "starved"},
    "gated": {"prefer_fuzz": True, "bias_shift": "cutoff"},
    "asymmetric": {"prefer_asymmetric": True},
    "vintage": {"prefer_diode": "germanium", "prefer_transistor": "germanium"},
    "modern": {"prefer_diode": "silicon", "prefer_opamp": True},
    "compressed": {"add_compress": True},
    "open": {"avoid_transforms": ["compress"]},
    "creamy": {"prefer_soft_clip": True, "gain_boost_db": 5, "lp_cutoff_shift": -800},
    "crunchy": {"gain_boost_db": 8, "prefer_hard_clip": True},
    "fuzzy": {"prefer_fuzz": True, "gain_boost_db": 15},
    "clean": {"gain_reduce_db": 10, "avoid_transforms": ["gain_soft_clip", "gain_hard_clip", "gain_fuzz"]},
}

# Maps "avoid" descriptors to constraints
AVOID_RULES: dict[str, dict] = {
    "harsh highs": {"max_lp_cutoff": 5000},
    "fizzy": {"max_lp_cutoff": 4000},
    "thin low end": {"min_hp_cutoff": 60},
    "mud": {"max_hp_cutoff": 150},
    "muddy": {"max_hp_cutoff": 150},
    "ice pick": {"max_lp_cutoff": 4000},
    "boxy": {"notch_freq": 500},
    "honky": {"notch_freq": 800},
    "noise": {"prefer_low_gain": True},
    "fizz": {"max_lp_cutoff": 4000},
}

# Valid transform names
VALID_TRANSFORMS = {
    "buffer_input", "buffer_output",
    "gain_clean", "gain_soft_clip", "gain_hard_clip", "gain_asymmetric", "gain_fuzz",
    "filter_lp", "filter_hp", "filter_bp", "filter_notch", "filter_tonestack",
    "compress",
    "modulate_tremolo", "modulate_vibrato", "modulate_chorus",
}


def plan_transforms(intent: DesignIntent) -> TransformPlan:
    """
    Main entry point. Takes a DesignIntent and produces a TransformPlan.
    Purely rule-based, no AI.
    """
    stages: list[TransformStage] = []

    # Always start with input buffer
    stages.append(TransformStage(transform="buffer_input", params={}))

    # Build core stages from reference sounds + explicit transforms
    core_stages = _build_core_stages(intent)

    # Apply character modifiers
    core_stages = _apply_character(core_stages, intent.character)

    # Apply avoidance rules
    core_stages = _apply_avoidance(core_stages, intent.avoid)

    # Apply explicit transforms (override/supplement)
    if intent.transforms:
        core_stages = _merge_explicit_transforms(core_stages, intent.transforms)

    stages.extend(core_stages)

    # Ensure proper ordering
    stages = _enforce_ordering(stages)

    # Always end with output buffer
    stages.append(TransformStage(transform="buffer_output", params={}))

    # Cap at 8 stages
    if len(stages) > 8:
        # Keep buffers, trim middle
        stages = [stages[0]] + stages[1:-1][:6] + [stages[-1]]

    return TransformPlan(stages=stages)


def _build_core_stages(intent: DesignIntent) -> list[TransformStage]:
    """Build initial transform stages from reference sounds."""
    stages = []

    # Start from reference sounds
    for ref in intent.reference_sounds:
        ref_lower = ref.lower().strip()
        if ref_lower in REFERENCE_PRESETS:
            for stage_def in REFERENCE_PRESETS[ref_lower]:
                stages.append(TransformStage(
                    transform=stage_def["transform"],
                    params=stage_def.get("params", {}),
                ))
            break  # Use first matching reference as base

    # If no reference matched, build from transforms list
    if not stages and intent.transforms:
        for t in intent.transforms:
            if t in VALID_TRANSFORMS and t not in ("buffer_input", "buffer_output"):
                stages.append(TransformStage(transform=t, params={}))

    # Default: clean overdrive if nothing specified
    if not stages:
        stages = [
            TransformStage(transform="gain_soft_clip", params={"gain_db": 20, "clip_type": "symmetric"}),
            TransformStage(transform="filter_tonestack", params={"type": "baxandall"}),
        ]

    return stages


def _apply_character(stages: list[TransformStage], characters: list[str]) -> list[TransformStage]:
    """Modify stages based on character descriptors."""
    for char in characters:
        char_lower = char.lower().strip()
        if char_lower not in CHARACTER_MODIFIERS:
            continue

        mods = CHARACTER_MODIFIERS[char_lower]

        for stage in stages:
            # Adjust gain
            if "gain_boost_db" in mods and "gain_db" in stage.params:
                stage.params["gain_db"] = stage.params["gain_db"] + mods["gain_boost_db"]
            if "gain_reduce_db" in mods and "gain_db" in stage.params:
                stage.params["gain_db"] = max(0, stage.params["gain_db"] - mods["gain_reduce_db"])

            # Adjust filter cutoffs
            if "lp_cutoff_shift" in mods and "f_cutoff_hz" in stage.params and stage.transform == "filter_lp":
                stage.params["f_cutoff_hz"] = max(500, stage.params["f_cutoff_hz"] + mods["lp_cutoff_shift"])

            # Prefer diode type
            if "prefer_diode" in mods and "diode" in stage.params:
                stage.params["diode"] = mods["prefer_diode"]

            # Prefer asymmetric
            if mods.get("prefer_asymmetric") and "clip_type" in stage.params:
                stage.params["clip_type"] = "asymmetric"

            # Shift to hard clip
            if mods.get("prefer_hard_clip") and stage.transform == "gain_soft_clip":
                stage.transform = "gain_hard_clip"

            # Shift to soft clip
            if mods.get("prefer_soft_clip") and stage.transform == "gain_hard_clip":
                stage.transform = "gain_soft_clip"

            # Shift to fuzz
            if mods.get("prefer_fuzz") and stage.transform in ("gain_soft_clip", "gain_hard_clip"):
                stage.transform = "gain_fuzz"
                if "gain_db" in stage.params:
                    stage.params["gain_db"] = max(stage.params.get("gain_db", 30), 35)

        # Add compression if requested
        if mods.get("add_compress"):
            has_compress = any(s.transform == "compress" for s in stages)
            if not has_compress:
                stages.append(TransformStage(transform="compress", params={}))

        # Add lowpass if "dark" or similar
        if mods.get("add_lp"):
            has_lp = any(s.transform == "filter_lp" for s in stages)
            if not has_lp:
                stages.append(TransformStage(
                    transform="filter_lp",
                    params={"f_cutoff_hz": 3000},
                ))

    return stages


def _apply_avoidance(stages: list[TransformStage], avoid: list[str]) -> list[TransformStage]:
    """Apply avoidance rules to constrain the design."""
    for avoid_desc in avoid:
        avoid_lower = avoid_desc.lower().strip()
        if avoid_lower not in AVOID_RULES:
            continue

        rules = AVOID_RULES[avoid_lower]

        for stage in stages:
            if "max_lp_cutoff" in rules and stage.transform == "filter_lp":
                if "f_cutoff_hz" in stage.params:
                    stage.params["f_cutoff_hz"] = min(stage.params["f_cutoff_hz"], rules["max_lp_cutoff"])

        # If we need a lowpass and don't have one, add it
        if "max_lp_cutoff" in rules:
            has_lp = any(s.transform == "filter_lp" for s in stages)
            if not has_lp:
                stages.append(TransformStage(
                    transform="filter_lp",
                    params={"f_cutoff_hz": rules["max_lp_cutoff"]},
                ))

    return stages


def _merge_explicit_transforms(existing: list[TransformStage], transforms: list[str]) -> list[TransformStage]:
    """Merge explicitly requested transforms with existing stages."""
    existing_types = {s.transform for s in existing}
    for t in transforms:
        if t in VALID_TRANSFORMS and t not in existing_types and t not in ("buffer_input", "buffer_output"):
            existing.append(TransformStage(transform=t, params={}))
    return existing


def _enforce_ordering(stages: list[TransformStage]) -> list[TransformStage]:
    """
    Enforce correct signal chain ordering:
    1. buffer_input
    2. gain/clip stages
    3. filter/tone stages
    4. compression
    5. modulation
    6. buffer_output
    """
    buffers_in = [s for s in stages if s.transform == "buffer_input"]
    gain_stages = [s for s in stages if s.transform.startswith("gain_")]
    filter_stages = [s for s in stages if s.transform.startswith("filter_")]
    compress_stages = [s for s in stages if s.transform == "compress"]
    mod_stages = [s for s in stages if s.transform.startswith("modulate_")]
    buffers_out = [s for s in stages if s.transform == "buffer_output"]

    ordered = buffers_in + gain_stages + filter_stages + compress_stages + mod_stages + buffers_out
    return ordered
