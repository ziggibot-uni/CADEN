"""
Static component specification database for PedalManifest.

Covers the ~150 most common guitar pedal components with full datasheet specs.
This is the physics engine's ground truth — every bias calculation, operating
point check, and DSP waveshaper pulls parameters from here.

Spec fields by type:
  NPN_BJT / PNP_BJT:  vceo_v, ic_max_ma, pd_mw, hfe_min, hfe_typ, hfe_max,
                       vbe_v, vce_sat_v, ft_mhz, leakage_icbo_ua, material
  N_JFET / P_JFET:    vgs_off_min_v, vgs_off_max_v, idss_min_ma, idss_max_ma,
                       vds_max_v, vgs_max_v, rd_ohm, ft_mhz, channel, material
  op_amp:              vcc_dual_min_v, vcc_dual_max_v, gbw_mhz, slew_rate_v_us,
                       input_bias_pa, input_offset_mv, noise_nv_rtHz,
                       output_current_ma, input_type, channels, rail_to_rail, is_ota
  diode / LED:         vf_v, vf_low_v, vr_max_v, if_max_ma, trr_ns, is_ua,
                       material, led_color (LEDs only)
"""

from __future__ import annotations
import re
from typing import Any

# ── Database ──────────────────────────────────────────────────────────────────
# Keys are normalised upper-case part numbers (see _norm below).

_DB: dict[str, dict[str, Any]] = {

    # ──────────────────────────────────────────────────────────────
    # NPN Silicon BJTs
    # ──────────────────────────────────────────────────────────────
    "2N3904": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon Transistor — ubiquitous small-signal",
        "vceo_v": 40, "vcbo_v": 60, "vebo_v": 6,
        "ic_max_ma": 200, "pd_mw": 625,
        "hfe_min": 100, "hfe_typ": 200, "hfe_max": 300,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 300,
        "leakage_icbo_ua": 0.05,
        "spice_model": "2N3904",
        "pedal_notes": "The go-to NPN. Works in CE gain stages, fuzz with right biasing, emitter followers. Very predictable hFE.",
    },
    "2N3903": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon Transistor — lower gain variant of 2N3904",
        "vceo_v": 40, "ic_max_ma": 200, "pd_mw": 625,
        "hfe_min": 50, "hfe_typ": 100, "hfe_max": 150,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 250,
        "leakage_icbo_ua": 0.05, "spice_model": "2N3904",
        "pedal_notes": "Lower-gain sibling to 2N3904. Good when you want predictable modest gain.",
    },
    "2N5088": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — high gain, low noise, low current",
        "vceo_v": 25, "ic_max_ma": 50, "pd_mw": 350,
        "hfe_min": 300, "hfe_typ": 450, "hfe_max": 900,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 50,
        "leakage_icbo_ua": 0.05, "spice_model": "2N5088",
        "pedal_notes": "Very high hFE, ideal for fuzz stages needing maximum gain. Used in many boutique fuzz designs.",
    },
    "2N5089": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — very high gain, low noise, audio-grade",
        "vceo_v": 25, "ic_max_ma": 50, "pd_mw": 350,
        "hfe_min": 400, "hfe_typ": 550, "hfe_max": 1200,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 300,
        "leakage_icbo_ua": 0.02, "spice_model": "2N5089",
        "pedal_notes": "Highest gain in the 2N508x family. Very low noise. Used in input stages and fuzz.",
    },
    "BC549C": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — low noise, high gain (C grade)",
        "vceo_v": 30, "ic_max_ma": 100, "pd_mw": 500,
        "hfe_min": 420, "hfe_typ": 540, "hfe_max": 800,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 150,
        "leakage_icbo_ua": 0.02, "spice_model": "BC549C",
        "pedal_notes": "Excellent low-noise audio transistor. C-grade = highest hFE bin. Common in MXR/Dynacomp style compressors, preamps.",
    },
    "BC549B": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — low noise (B grade, mid hFE)",
        "vceo_v": 30, "ic_max_ma": 100, "pd_mw": 500,
        "hfe_min": 240, "hfe_typ": 350, "hfe_max": 500,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 150,
        "leakage_icbo_ua": 0.02, "spice_model": "BC549C",
        "pedal_notes": "Mid-gain BC549. Good all-rounder when C grade is unavailable.",
    },
    "BC547A": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — general purpose (A grade, lower hFE)",
        "vceo_v": 45, "ic_max_ma": 100, "pd_mw": 500,
        "hfe_min": 110, "hfe_typ": 165, "hfe_max": 220,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 300,
        "leakage_icbo_ua": 0.05, "spice_model": "2N3904",
        "pedal_notes": "European equivalent to 2N3904 (lower gain). A suffix = 110-220 hFE range.",
    },
    "BC547B": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — general purpose (B grade, mid hFE)",
        "vceo_v": 45, "ic_max_ma": 100, "pd_mw": 500,
        "hfe_min": 200, "hfe_typ": 325, "hfe_max": 450,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 300,
        "leakage_icbo_ua": 0.05, "spice_model": "2N3904",
        "pedal_notes": "B suffix = 200-450 hFE. Good general-purpose gain stage transistor.",
    },
    "BC547C": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — general purpose (C grade, high hFE)",
        "vceo_v": 45, "ic_max_ma": 100, "pd_mw": 500,
        "hfe_min": 420, "hfe_typ": 600, "hfe_max": 800,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 300,
        "leakage_icbo_ua": 0.05, "spice_model": "BC549C",
        "pedal_notes": "High-gain NPN. Good for high-sensitivity fuzz and gain stages.",
    },
    "BC548B": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — 30V, mid gain",
        "vceo_v": 30, "ic_max_ma": 100, "pd_mw": 500,
        "hfe_min": 200, "hfe_typ": 290, "hfe_max": 450,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 150,
        "leakage_icbo_ua": 0.05, "spice_model": "2N3904",
        "pedal_notes": "30V-rated NPN. Slightly lower Vce than BC547, same pinout.",
    },
    "BC550C": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — very low noise, very high gain",
        "vceo_v": 45, "ic_max_ma": 100, "pd_mw": 500,
        "hfe_min": 420, "hfe_typ": 600, "hfe_max": 900,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 150,
        "leakage_icbo_ua": 0.01, "spice_model": "BC549C",
        "pedal_notes": "Lowest noise in BC5xx family. Excellent for microphone preamp / input stages.",
    },
    "MPSA18": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — very high gain audio",
        "vceo_v": 45, "ic_max_ma": 50, "pd_mw": 625,
        "hfe_min": 500, "hfe_typ": 700, "hfe_max": 1200,
        "vbe_v": 0.65, "vce_sat_v": 0.25, "ft_mhz": 50,
        "leakage_icbo_ua": 0.02, "spice_model": "2N5088",
        "pedal_notes": "Very high hFE with good noise. Used in preamp and some fuzz designs.",
    },
    "MPSA06": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — medium power, high voltage",
        "vceo_v": 80, "ic_max_ma": 500, "pd_mw": 625,
        "hfe_min": 100, "hfe_typ": 200, "hfe_max": 400,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 100,
        "leakage_icbo_ua": 0.1, "spice_model": "2N3904",
        "pedal_notes": "Higher current/voltage NPN. Good for boost outputs and drivers.",
    },
    "2SC828": {
        "type": "NPN_BJT", "material": "silicon", "package": "TO-92",
        "description": "NPN Silicon — Japanese, high gain, low noise",
        "vceo_v": 25, "ic_max_ma": 50, "pd_mw": 200,
        "hfe_min": 200, "hfe_typ": 350, "hfe_max": 700,
        "vbe_v": 0.65, "vce_sat_v": 0.20, "ft_mhz": 150,
        "leakage_icbo_ua": 0.02, "spice_model": "BC549C",
        "pedal_notes": "Japanese NPN used in vintage Univox / Roland fuzz pedals. Low Vce, good for starved-supply fuzzes.",
    },

    # ──────────────────────────────────────────────────────────────
    # PNP Silicon BJTs
    # ──────────────────────────────────────────────────────────────
    "2N3906": {
        "type": "PNP_BJT", "material": "silicon", "package": "TO-92",
        "description": "PNP Silicon Transistor — complement to 2N3904",
        "vceo_v": -40, "ic_max_ma": -200, "pd_mw": 625,
        "hfe_min": 100, "hfe_typ": 200, "hfe_max": 300,
        "vbe_v": -0.65, "vce_sat_v": -0.20, "ft_mhz": 250,
        "leakage_icbo_ua": 0.05, "spice_model": "2N3906",
        "pedal_notes": "PNP complement to 2N3904. Used where positive-ground/PNP topology needed (vintage fuzz, Fuzz Face variants).",
    },
    "2N5087": {
        "type": "PNP_BJT", "material": "silicon", "package": "TO-92",
        "description": "PNP Silicon — high gain audio",
        "vceo_v": -40, "ic_max_ma": -50, "pd_mw": 350,
        "hfe_min": 250, "hfe_typ": 350, "hfe_max": 600,
        "vbe_v": -0.65, "vce_sat_v": -0.20, "ft_mhz": 50,
        "leakage_icbo_ua": 0.05, "spice_model": "2N3906",
        "pedal_notes": "PNP complement to 2N5088/5089. High-gain PNP for fuzz and gain stages.",
    },
    "BC557B": {
        "type": "PNP_BJT", "material": "silicon", "package": "TO-92",
        "description": "PNP Silicon — complement to BC547B",
        "vceo_v": -45, "ic_max_ma": -100, "pd_mw": 500,
        "hfe_min": 200, "hfe_typ": 290, "hfe_max": 450,
        "vbe_v": -0.65, "vce_sat_v": -0.20, "ft_mhz": 150,
        "leakage_icbo_ua": 0.05, "spice_model": "2N3906",
        "pedal_notes": "European PNP complement to BC547B.",
    },
    "BC559C": {
        "type": "PNP_BJT", "material": "silicon", "package": "TO-92",
        "description": "PNP Silicon — low noise, high gain (C grade)",
        "vceo_v": -30, "ic_max_ma": -100, "pd_mw": 500,
        "hfe_min": 420, "hfe_typ": 600, "hfe_max": 900,
        "vbe_v": -0.65, "vce_sat_v": -0.20, "ft_mhz": 150,
        "leakage_icbo_ua": 0.01, "spice_model": "2N3906",
        "pedal_notes": "Low-noise PNP complement to BC549C. Excellent for symmetrical push-pull stages.",
    },

    # ──────────────────────────────────────────────────────────────
    # PNP Germanium BJTs  (positive-ground / vintage fuzz)
    # ──────────────────────────────────────────────────────────────
    "AC128": {
        "type": "PNP_BJT", "material": "germanium", "package": "TO-1",
        "description": "PNP Germanium — classic Fuzz Face transistor",
        "vceo_v": -32, "ic_max_ma": -140, "pd_mw": 135,
        "hfe_min": 40, "hfe_typ": 70, "hfe_max": 130,
        "vbe_v": -0.18, "vce_sat_v": -0.10, "ft_mhz": 1,
        "leakage_icbo_ua": 400,
        "spice_model": "AC128",
        "pedal_notes": "The original Dallas Arbiter Fuzz Face transistor. PNP germanium means POSITIVE GROUND circuit. High leakage (Icbo ~400µA) is normal and part of the character. Select for hFE 70-100 for best Fuzz Face tone.",
    },
    "AC125": {
        "type": "PNP_BJT", "material": "germanium", "package": "TO-1",
        "description": "PNP Germanium — Fuzz Face / Tonebender era",
        "vceo_v": -40, "ic_max_ma": -80, "pd_mw": 100,
        "hfe_min": 40, "hfe_typ": 65, "hfe_max": 120,
        "vbe_v": -0.18, "vce_sat_v": -0.12, "ft_mhz": 1,
        "leakage_icbo_ua": 300,
        "spice_model": "AC128",
        "pedal_notes": "Similar character to AC128, used in Tonebender Mk1/2. Select pairs with close hFE.",
    },
    "NKT275": {
        "type": "PNP_BJT", "material": "germanium", "package": "TO-1",
        "description": "PNP Germanium — original Fuzz Face NKT275, now very rare",
        "vceo_v": -18, "ic_max_ma": -150, "pd_mw": 150,
        "hfe_min": 80, "hfe_typ": 115, "hfe_max": 150,
        "vbe_v": -0.15, "vce_sat_v": -0.08, "ft_mhz": 1,
        "leakage_icbo_ua": 200,
        "spice_model": "AC128",
        "pedal_notes": "The holy grail Fuzz Face transistor. Tighter hFE spread and lower leakage than AC128. Positive-ground circuit required.",
    },
    "OC44": {
        "type": "PNP_BJT", "material": "germanium", "package": "TO-1",
        "description": "PNP Germanium — vintage, very low voltage",
        "vceo_v": -15, "ic_max_ma": -20, "pd_mw": 75,
        "hfe_min": 50, "hfe_typ": 70, "hfe_max": 100,
        "vbe_v": -0.15, "vce_sat_v": -0.10, "ft_mhz": 1,
        "leakage_icbo_ua": 500,
        "spice_model": "AC128",
        "pedal_notes": "Very old British germanium. Low Vce — must use with low supply (3-6V). Very sensitive to temperature.",
    },
    "OC75": {
        "type": "PNP_BJT", "material": "germanium", "package": "TO-1",
        "description": "PNP Germanium — medium-power vintage",
        "vceo_v": -20, "ic_max_ma": -100, "pd_mw": 100,
        "hfe_min": 45, "hfe_typ": 80, "hfe_max": 160,
        "vbe_v": -0.18, "vce_sat_v": -0.10, "ft_mhz": 1,
        "leakage_icbo_ua": 600,
        "spice_model": "AC128",
        "pedal_notes": "British germanium. High leakage — best paired with leakage compensation. Warm character.",
    },
    "2SB175": {
        "type": "PNP_BJT", "material": "germanium", "package": "TO-1",
        "description": "PNP Germanium — Japanese, moderate gain",
        "vceo_v": -35, "ic_max_ma": -150, "pd_mw": 200,
        "hfe_min": 40, "hfe_typ": 80, "hfe_max": 140,
        "vbe_v": -0.18, "vce_sat_v": -0.10, "ft_mhz": 1,
        "leakage_icbo_ua": 350,
        "spice_model": "AC128",
        "pedal_notes": "Japanese PNP germanium. Good AC128 substitute. Select for hFE 70-100.",
    },

    # ──────────────────────────────────────────────────────────────
    # N-Channel JFETs
    # ──────────────────────────────────────────────────────────────
    "J201": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — ultra-low Idss, popular input buffer",
        "vgs_off_min_v": -0.1, "vgs_off_max_v": -0.9,
        "idss_min_ma": 0.1, "idss_max_ma": 1.5,
        "vds_max_v": 40, "vgs_max_v": -40,
        "rd_ohm": 3000, "ft_mhz": 45,
        "spice_model": "J201",
        "pedal_notes": "Very low Idss means it operates near pinch-off at 9V with no gate bias. Perfect high-impedance input buffer for guitar. Widely available from Small Bear Electronics.",
    },
    "MPF102": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — general purpose, wide Idss spread",
        "vgs_off_min_v": -0.5, "vgs_off_max_v": -4.0,
        "idss_min_ma": 2.0, "idss_max_ma": 20.0,
        "vds_max_v": 25, "vgs_max_v": -25,
        "rd_ohm": 400, "ft_mhz": 400,
        "spice_model": "MPF102",
        "pedal_notes": "The standard N-JFET. Very wide hFE spread — always characterise before using in bias-critical circuits. Good for oscillators, buffers, and VCA applications.",
    },
    "2N5457": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — medium Idss, general audio",
        "vgs_off_min_v": -0.5, "vgs_off_max_v": -6.0,
        "idss_min_ma": 1.0, "idss_max_ma": 5.0,
        "vds_max_v": 25, "vgs_max_v": -25,
        "rd_ohm": 600, "ft_mhz": 100,
        "spice_model": "2N5457",
        "pedal_notes": "Tighter Idss spread than MPF102. Good all-purpose N-JFET. Used in many buffer and gain stage designs.",
    },
    "2N5458": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — medium-high Idss",
        "vgs_off_min_v": -1.0, "vgs_off_max_v": -7.0,
        "idss_min_ma": 2.0, "idss_max_ma": 9.0,
        "vds_max_v": 25, "vgs_max_v": -25,
        "rd_ohm": 400, "ft_mhz": 100,
        "spice_model": "2N5457",
        "pedal_notes": "Higher pinch-off voltage than 2N5457. Needs more negative gate bias to cut off.",
    },
    "2N5484": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — low noise, low Idss",
        "vgs_off_min_v": -0.3, "vgs_off_max_v": -3.0,
        "idss_min_ma": 1.0, "idss_max_ma": 5.0,
        "vds_max_v": 25, "vgs_max_v": -25,
        "rd_ohm": 500, "ft_mhz": 300,
        "spice_model": "2N5457",
        "pedal_notes": "Low-noise version. Good in preamp input stages where noise floor matters.",
    },
    "2N5485": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — medium-high Idss, low noise",
        "vgs_off_min_v": -0.5, "vgs_off_max_v": -4.0,
        "idss_min_ma": 4.0, "idss_max_ma": 10.0,
        "vds_max_v": 25, "vgs_max_v": -25,
        "rd_ohm": 350, "ft_mhz": 300,
        "spice_model": "2N5457",
        "pedal_notes": "Higher Idss than 2N5484. More headroom before clipping in gain stages.",
    },
    "2SK170": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — ultra-low noise, boutique audio grade",
        "vgs_off_min_v": -0.08, "vgs_off_max_v": -0.60,
        "idss_min_ma": 2.6, "idss_max_ma": 6.5,
        "vds_max_v": 12, "vgs_max_v": -4,
        "rd_ohm": 250, "ft_mhz": 800,
        "spice_model": "2SK170",
        "pedal_notes": "Exceptional low-noise N-JFET (GR grade: 2.6-6.5mA). Low Vds_max = 12V — must use with care in 9V circuits. Very popular in boutique preamps and buffers.",
    },
    "BF245A": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — European, medium Idss",
        "vgs_off_min_v": -0.5, "vgs_off_max_v": -4.0,
        "idss_min_ma": 2.0, "idss_max_ma": 12.0,
        "vds_max_v": 30, "vgs_max_v": -30,
        "rd_ohm": 400, "ft_mhz": 200,
        "spice_model": "2N5457",
        "pedal_notes": "European N-JFET. Good MPF102 substitute with higher Vds_max.",
    },
    "2N3819": {
        "type": "N_JFET", "material": "silicon", "package": "TO-92",
        "description": "N-Channel JFET — classic, wide spread",
        "vgs_off_min_v": -1.0, "vgs_off_max_v": -8.0,
        "idss_min_ma": 2.0, "idss_max_ma": 20.0,
        "vds_max_v": 25, "vgs_max_v": -25,
        "rd_ohm": 400, "ft_mhz": 100,
        "spice_model": "MPF102",
        "pedal_notes": "Older standard N-JFET. Very wide spread — characterise before use.",
    },

    # ──────────────────────────────────────────────────────────────
    # P-Channel JFETs
    # ──────────────────────────────────────────────────────────────
    "J175": {
        "type": "P_JFET", "material": "silicon", "package": "TO-92",
        "description": "P-Channel JFET — complement to J111/J112",
        "vgs_off_min_v": 0.5, "vgs_off_max_v": 6.0,
        "idss_min_ma": -1.0, "idss_max_ma": -5.0,
        "vds_max_v": -30, "vgs_max_v": 30,
        "rd_ohm": 600, "ft_mhz": 100,
        "spice_model": "J175",
        "pedal_notes": "P-channel complement for push-pull JFET circuits.",
    },
    "2N5460": {
        "type": "P_JFET", "material": "silicon", "package": "TO-92",
        "description": "P-Channel JFET — audio, complement to 2N5457",
        "vgs_off_min_v": 0.75, "vgs_off_max_v": 9.0,
        "idss_min_ma": -1.0, "idss_max_ma": -5.0,
        "vds_max_v": -40, "vgs_max_v": 40,
        "rd_ohm": 600, "ft_mhz": 100,
        "spice_model": "J175",
        "pedal_notes": "P-channel audio JFET. Used in complementary gain stages.",
    },

    # ──────────────────────────────────────────────────────────────
    # Op-Amps
    # ──────────────────────────────────────────────────────────────
    "TL071": {
        "type": "op_amp", "package": "DIP-8", "channels": 1, "input_type": "JFET",
        "description": "Single JFET-Input Op-Amp",
        "vcc_dual_min_v": 3.5, "vcc_dual_max_v": 18.0,
        "vcc_single_min_v": 7.0, "vcc_single_max_v": 36.0,
        "gbw_mhz": 3.0, "slew_rate_v_us": 13.0,
        "input_bias_pa": 65000, "input_offset_mv": 3.0,
        "noise_nv_rtHz": 18.0, "output_current_ma": 40,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "TL071",
        "pedal_notes": "Single version of TL072. High slew rate for an op-amp of its era. Works at 9V with split ±4.5V supply. Standard for drives and tone controls.",
    },
    "TL072": {
        "type": "op_amp", "package": "DIP-8", "channels": 2, "input_type": "JFET",
        "description": "Dual JFET-Input Op-Amp — most common guitar pedal op-amp",
        "vcc_dual_min_v": 3.5, "vcc_dual_max_v": 18.0,
        "vcc_single_min_v": 7.0, "vcc_single_max_v": 36.0,
        "gbw_mhz": 3.0, "slew_rate_v_us": 13.0,
        "input_bias_pa": 65000, "input_offset_mv": 3.0,
        "noise_nv_rtHz": 18.0, "output_current_ma": 40,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "TL072",
        "pedal_notes": "The standard guitar pedal op-amp. Used in Tube Screamer, countless drives. Two op-amps in one package. At 9V use with charge pump for ±4.5V or ICL7660 for true ±9V.",
    },
    "TL074": {
        "type": "op_amp", "package": "DIP-14", "channels": 4, "input_type": "JFET",
        "description": "Quad JFET-Input Op-Amp",
        "vcc_dual_min_v": 3.5, "vcc_dual_max_v": 18.0,
        "vcc_single_min_v": 7.0, "vcc_single_max_v": 36.0,
        "gbw_mhz": 3.0, "slew_rate_v_us": 13.0,
        "input_bias_pa": 65000, "input_offset_mv": 3.0,
        "noise_nv_rtHz": 18.0, "output_current_ma": 40,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "TL072",
        "pedal_notes": "Quad TL072. Four op-amps in one package. Efficient for multi-stage designs (Baxandall + gain + buffer all in one chip).",
    },
    "LM741": {
        "type": "op_amp", "package": "DIP-8", "channels": 1, "input_type": "BJT",
        "description": "Single BJT-Input Op-Amp — classic, slow",
        "vcc_dual_min_v": 5.0, "vcc_dual_max_v": 22.0,
        "vcc_single_min_v": 10.0, "vcc_single_max_v": 44.0,
        "gbw_mhz": 1.0, "slew_rate_v_us": 0.5,
        "input_bias_pa": 80_000_000, "input_offset_mv": 1.0,
        "noise_nv_rtHz": 20.0, "output_current_ma": 25,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "LM741",
        "pedal_notes": "The classic op-amp. Very low slew rate (0.5V/µs) causes slew-induced distortion on high-frequency signals — some guitarists like this character. Not recommended for clean hi-fi designs.",
    },
    "LM358": {
        "type": "op_amp", "package": "DIP-8", "channels": 2, "input_type": "BJT",
        "description": "Dual Single-Supply Op-Amp",
        "vcc_dual_min_v": 1.5, "vcc_dual_max_v": 16.0,
        "vcc_single_min_v": 3.0, "vcc_single_max_v": 32.0,
        "gbw_mhz": 1.0, "slew_rate_v_us": 0.6,
        "input_bias_pa": 45_000_000, "input_offset_mv": 2.0,
        "noise_nv_rtHz": 40.0, "output_current_ma": 40,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "LM358",
        "pedal_notes": "Single-supply dual op-amp. Can work rail-to-rail on input (output swings to near rail). Useful for battery-powered circuits at 9V without bias splitting.",
    },
    "NE5532": {
        "type": "op_amp", "package": "DIP-8", "channels": 2, "input_type": "BJT",
        "description": "Dual Audio Op-Amp — low noise, high drive",
        "vcc_dual_min_v": 5.0, "vcc_dual_max_v": 15.0,
        "vcc_single_min_v": 10.0, "vcc_single_max_v": 30.0,
        "gbw_mhz": 10.0, "slew_rate_v_us": 9.0,
        "input_bias_pa": 200_000_000, "input_offset_mv": 0.5,
        "noise_nv_rtHz": 5.0, "output_current_ma": 38,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "NE5532",
        "pedal_notes": "Industry-standard audio op-amp. Much lower noise than TL072 and 10× the GBW. Ideal for clean preamps, compressors, and high-quality drives. Needs ±5V minimum — use 18V supply or charge pump.",
    },
    "RC4558": {
        "type": "op_amp", "package": "DIP-8", "channels": 2, "input_type": "BJT",
        "description": "Dual General-Purpose Op-Amp — used in Tube Screamer",
        "vcc_dual_min_v": 5.0, "vcc_dual_max_v": 15.0,
        "vcc_single_min_v": 10.0, "vcc_single_max_v": 30.0,
        "gbw_mhz": 3.0, "slew_rate_v_us": 1.5,
        "input_bias_pa": 1_500_000_000, "input_offset_mv": 2.0,
        "noise_nv_rtHz": 8.0, "output_current_ma": 25,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "RC4558",
        "pedal_notes": "The famous Tube Screamer op-amp. High input bias current (1.5µA) rolls off low bass — intentional part of the TS sound. Lower slew rate than TL072 adds a touch of harmonic colour.",
    },
    "MC1458": {
        "type": "op_amp", "package": "DIP-8", "channels": 2, "input_type": "BJT",
        "description": "Dual General-Purpose Op-Amp — vintage, similar to RC4558",
        "vcc_dual_min_v": 5.0, "vcc_dual_max_v": 15.0,
        "vcc_single_min_v": 10.0, "vcc_single_max_v": 30.0,
        "gbw_mhz": 1.0, "slew_rate_v_us": 0.7,
        "input_bias_pa": 500_000_000, "input_offset_mv": 5.0,
        "noise_nv_rtHz": 25.0, "output_current_ma": 20,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "LM741",
        "pedal_notes": "Older dual op-amp, similar to uA741 doubled. Slow slew rate. Used in vintage distortion circuits.",
    },
    "LM4562": {
        "type": "op_amp", "package": "DIP-8", "channels": 2, "input_type": "BJT",
        "description": "Dual Hi-Fi Audio Op-Amp — ultra-low distortion",
        "vcc_dual_min_v": 2.5, "vcc_dual_max_v": 17.0,
        "vcc_single_min_v": 5.0, "vcc_single_max_v": 34.0,
        "gbw_mhz": 55.0, "slew_rate_v_us": 20.0,
        "input_bias_pa": 72_000_000, "input_offset_mv": 0.1,
        "noise_nv_rtHz": 2.7, "output_current_ma": 26,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "NE5532",
        "pedal_notes": "Modern hi-fi op-amp. Extremely low noise and distortion. Drop-in upgrade for NE5532 or TL072 in clean signal paths. Not free: ~$1-2 each.",
    },
    "OPA2134": {
        "type": "op_amp", "package": "DIP-8", "channels": 2, "input_type": "JFET",
        "description": "Dual FET Hi-Fi Audio Op-Amp",
        "vcc_dual_min_v": 2.5, "vcc_dual_max_v": 18.0,
        "vcc_single_min_v": 5.0, "vcc_single_max_v": 36.0,
        "gbw_mhz": 8.0, "slew_rate_v_us": 20.0,
        "input_bias_pa": 5000, "input_offset_mv": 0.5,
        "noise_nv_rtHz": 8.0, "output_current_ma": 35,
        "rail_to_rail": False, "is_ota": False,
        "spice_model": "TL072",
        "pedal_notes": "Premium JFET op-amp. Ultra-low input bias (5pA) — no DC blocking needed at input. High slew rate. Popular in boutique overdrive upgrades.",
    },
    "LM13700": {
        "type": "op_amp", "package": "DIP-16", "channels": 2, "input_type": "BJT",
        "description": "Dual OTA (Operational Transconductance Amplifier)",
        "vcc_dual_min_v": 5.0, "vcc_dual_max_v": 15.0,
        "vcc_single_min_v": 10.0, "vcc_single_max_v": 30.0,
        "gbw_mhz": 2.0, "slew_rate_v_us": 50.0,
        "input_bias_pa": 0, "input_offset_mv": 2.0,
        "noise_nv_rtHz": 150.0, "output_current_ma": 20,
        "rail_to_rail": False, "is_ota": True,
        "iabc_max_ma": 2.0,  # max bias current for gm control
        "gm_per_iabc_ua": 19.2,  # transconductance: gm = 19.2 × Iabc (µA → mA/V)
        "spice_model": "LM13700",
        "pedal_notes": "Voltage-controlled gain element. Used in compressors (MXR Dynacomp), tremolo, and voltage-controlled filters. Two OTAs + buffer Darlingtons in one package. Key: gm is proportional to Iabc.",
    },
    "CA3080": {
        "type": "op_amp", "package": "DIP-8", "channels": 1, "input_type": "BJT",
        "description": "Single OTA — vintage, used in classic compressors",
        "vcc_dual_min_v": 2.0, "vcc_dual_max_v": 15.0,
        "vcc_single_min_v": 4.0, "vcc_single_max_v": 30.0,
        "gbw_mhz": 2.0, "slew_rate_v_us": 50.0,
        "input_bias_pa": 0, "input_offset_mv": 5.0,
        "noise_nv_rtHz": 200.0, "output_current_ma": 10,
        "rail_to_rail": False, "is_ota": True,
        "iabc_max_ma": 1.0, "gm_per_iabc_ua": 19.2,
        "spice_model": "CA3080",
        "pedal_notes": "Classic OTA. Used in Mu-Tron, Ross Compressor, early MXR Dynacomp. Single OTA without built-in buffer. Now discontinued — LM13700 is the modern equivalent.",
    },

    # ──────────────────────────────────────────────────────────────
    # Silicon Signal Diodes
    # ──────────────────────────────────────────────────────────────
    "1N4148": {
        "type": "diode", "material": "silicon", "package": "DO-35",
        "description": "Silicon Fast Switching Diode — standard clipping diode",
        "vf_v": 0.715, "vf_low_v": 0.62, "vr_max_v": 100,
        "if_max_ma": 300, "trr_ns": 4, "is_ua": 0.025,
        "spice_model": "1N4148",
        "pedal_notes": "The standard silicon clipping diode. Vf ~0.7V. Used in soft clipping op-amp circuits (Tube Screamer style). Symmetrical pair for symmetric clipping, mixed pair for asymmetric.",
    },
    "1N914": {
        "type": "diode", "material": "silicon", "package": "DO-35",
        "description": "Silicon Signal Diode — essentially identical to 1N4148",
        "vf_v": 0.71, "vf_low_v": 0.62, "vr_max_v": 75,
        "if_max_ma": 200, "trr_ns": 4, "is_ua": 0.025,
        "spice_model": "1N4148",
        "pedal_notes": "Older designation, same electrical character as 1N4148 in practice.",
    },
    "1N4448": {
        "type": "diode", "material": "silicon", "package": "DO-35",
        "description": "Silicon Fast Switching Diode — slightly lower Vf",
        "vf_v": 0.70, "vf_low_v": 0.60, "vr_max_v": 100,
        "if_max_ma": 500, "trr_ns": 4, "is_ua": 0.02,
        "spice_model": "1N4148",
        "pedal_notes": "Very similar to 1N4148 but slightly lower Vf. Higher current rating.",
    },

    # ──────────────────────────────────────────────────────────────
    # Germanium Signal Diodes
    # ──────────────────────────────────────────────────────────────
    "1N34A": {
        "type": "diode", "material": "germanium", "package": "DO-7",
        "description": "Germanium Signal Diode — warm, asymmetric character",
        "vf_v": 0.30, "vf_low_v": 0.20, "vr_max_v": 60,
        "if_max_ma": 50, "trr_ns": 1000, "is_ua": 100.0,
        "spice_model": "1N34A",
        "pedal_notes": "Low Vf (~0.3V) means clipping begins much sooner than silicon. High reverse leakage is characteristic. Warm, soft asymmetric character. Use in op-amp clipping for 'vintage fuzz' flavour.",
    },
    "1N60P": {
        "type": "diode", "material": "germanium", "package": "DO-7",
        "description": "Germanium Signal Diode — similar to 1N34A",
        "vf_v": 0.30, "vf_low_v": 0.18, "vr_max_v": 40,
        "if_max_ma": 35, "trr_ns": 1000, "is_ua": 120.0,
        "spice_model": "1N34A",
        "pedal_notes": "Close relative to 1N34A. Slightly lower Vr_max. Same warm character.",
    },
    "1N270": {
        "type": "diode", "material": "germanium", "package": "DO-7",
        "description": "Germanium Detector Diode",
        "vf_v": 0.25, "vf_low_v": 0.15, "vr_max_v": 40,
        "if_max_ma": 35, "trr_ns": 1000, "is_ua": 150.0,
        "spice_model": "1N34A",
        "pedal_notes": "Even lower Vf than 1N34A. Very soft clipping onset.",
    },

    # ──────────────────────────────────────────────────────────────
    # Schottky Diodes
    # ──────────────────────────────────────────────────────────────
    "BAT41": {
        "type": "diode", "material": "schottky", "package": "DO-35",
        "description": "Small Signal Schottky — low Vf, fast",
        "vf_v": 0.35, "vf_low_v": 0.28, "vr_max_v": 100,
        "if_max_ma": 100, "trr_ns": 5, "is_ua": 2.0,
        "spice_model": "BAT41",
        "pedal_notes": "Low Vf Schottky (~0.35V). Clips earlier than silicon, cleaner than germanium. Used for asymmetric clipping (Schottky + silicon pair). More repeatable than germanium.",
    },
    "BAT42": {
        "type": "diode", "material": "schottky", "package": "DO-35",
        "description": "Small Signal Schottky — 30V, medium current",
        "vf_v": 0.35, "vf_low_v": 0.27, "vr_max_v": 30,
        "if_max_ma": 200, "trr_ns": 5, "is_ua": 2.0,
        "spice_model": "BAT41",
        "pedal_notes": "Lower Vr_max than BAT41 (30V vs 100V) but higher current. Good for 9V circuits.",
    },
    "BAT46": {
        "type": "diode", "material": "schottky", "package": "DO-35",
        "description": "Small Signal Schottky — low Vf, 100V",
        "vf_v": 0.35, "vf_low_v": 0.27, "vr_max_v": 100,
        "if_max_ma": 150, "trr_ns": 5, "is_ua": 0.5,
        "spice_model": "BAT41",
        "pedal_notes": "Lower reverse leakage than BAT42. 100V rating. Good all-around Schottky for pedal clipping.",
    },
    "1N5817": {
        "type": "diode", "material": "schottky", "package": "DO-41",
        "description": "Power Schottky — 1A, 20V",
        "vf_v": 0.45, "vf_low_v": 0.35, "vr_max_v": 20,
        "if_max_ma": 1000, "trr_ns": 10, "is_ua": 1000.0,
        "spice_model": "1N5817",
        "pedal_notes": "Power Schottky, higher Vf than small-signal types. Used for reverse-polarity protection, not clipping. Very high reverse leakage.",
    },
    "1N5819": {
        "type": "diode", "material": "schottky", "package": "DO-41",
        "description": "Power Schottky — 1A, 40V",
        "vf_v": 0.60, "vf_low_v": 0.45, "vr_max_v": 40,
        "if_max_ma": 1000, "trr_ns": 10, "is_ua": 500.0,
        "spice_model": "1N5817",
        "pedal_notes": "Higher voltage rating than 1N5817. Used for power supply protection.",
    },

    # ──────────────────────────────────────────────────────────────
    # LEDs (used as clipping diodes — Vf ~1.8-3.5V)
    # ──────────────────────────────────────────────────────────────
    "LED_RED": {
        "type": "LED", "material": "LED", "package": "T-1.75",
        "description": "Red LED — low Vf, warm soft clipping",
        "vf_v": 1.9, "vf_low_v": 1.7, "vr_max_v": 5,
        "if_max_ma": 20, "trr_ns": 50, "is_ua": 0.01,
        "led_color": "red", "wavelength_nm": 630,
        "spice_model": "DLED",
        "pedal_notes": "Red LEDs (Vf ~1.9V) used in clipping circuits instead of signal diodes. Higher clipping threshold = more headroom = softer/smoother character. Used in MXR Distortion+, DOD 250.",
    },
    "LED_GREEN": {
        "type": "LED", "material": "LED", "package": "T-1.75",
        "description": "Green LED — slightly higher Vf than red",
        "vf_v": 2.1, "vf_low_v": 1.9, "vr_max_v": 5,
        "if_max_ma": 20, "trr_ns": 50, "is_ua": 0.01,
        "led_color": "green", "wavelength_nm": 530,
        "spice_model": "DLED",
        "pedal_notes": "GaP green LEDs. Slightly higher Vf → even softer clipping. Available in standard T-1.75 package.",
    },
    "LED_BLUE": {
        "type": "LED", "material": "LED", "package": "T-1.75",
        "description": "Blue LED — high Vf, very soft clipping",
        "vf_v": 3.3, "vf_low_v": 3.0, "vr_max_v": 5,
        "if_max_ma": 20, "trr_ns": 50, "is_ua": 0.01,
        "led_color": "blue", "wavelength_nm": 470,
        "spice_model": "DLED",
        "pedal_notes": "High Vf (~3.3V). Very high clipping threshold — nearly clean with slight soft clipping. Gives maximum headroom in clipping network.",
    },
    "LED_YELLOW": {
        "type": "LED", "material": "LED", "package": "T-1.75",
        "description": "Yellow LED — medium Vf",
        "vf_v": 2.1, "vf_low_v": 1.9, "vr_max_v": 5,
        "if_max_ma": 20, "trr_ns": 50, "is_ua": 0.01,
        "led_color": "yellow", "wavelength_nm": 590,
        "spice_model": "DLED",
        "pedal_notes": "Similar Vf to green. Old-style yellow GaAsP LEDs have slightly higher Vf than modern ones.",
    },

    # ──────────────────────────────────────────────────────────────
    # Rectifier diodes
    # ──────────────────────────────────────────────────────────────
    "1N4001": {
        "type": "diode", "material": "silicon", "package": "DO-41",
        "description": "Silicon Rectifier — 1A, 50V",
        "vf_v": 1.1, "vf_low_v": 0.85, "vr_max_v": 50,
        "if_max_ma": 1000, "trr_ns": 5000, "is_ua": 5.0,
        "spice_model": "1N4001",
        "pedal_notes": "Not for audio clipping (Vf too high, too slow). Used for reverse-polarity protection and power supply rectification.",
    },
    "1N4007": {
        "type": "diode", "material": "silicon", "package": "DO-41",
        "description": "Silicon Rectifier — 1A, 1000V",
        "vf_v": 1.1, "vf_low_v": 0.85, "vr_max_v": 1000,
        "if_max_ma": 1000, "trr_ns": 5000, "is_ua": 5.0,
        "spice_model": "1N4001",
        "pedal_notes": "1kV rating overkill for guitar pedals. Same as 1N4001 for 9V use. Often used for polarity protection.",
    },
}

# ── Aliases ────────────────────────────────────────────────────────────────────
# Maps alternate part numbers / suffixes to canonical entries.

_ALIASES: dict[str, str] = {
    "BC549": "BC549C",   # treat un-suffixed as C grade (most common)
    "BC547": "BC547B",
    "BC548": "BC548B",
    "BC557": "BC557B",
    "BC559": "BC559C",
    "1N914B": "1N914",
    "1N4148W": "1N4148",  # SOD-323 SMD variant
    "BAT43": "BAT41",
    "BAT48": "BAT46",
    "J201A": "J201",
    "2N5457A": "2N5457",
    "BF245": "BF245A",
    "BF244": "BF245A",
    "BF244A": "BF245A",
    "BF256A": "BF245A",
    "BF256": "BF245A",
    "MPSA05": "MPSA06",
    "AC127": "AC128",
    "AC153": "AC128",
    "OC45": "OC44",
    "2SB171": "2SB175",
    "2SK170BL": "2SK170",
    "2SK170GR": "2SK170",
    "TL071CP": "TL071",
    "TL072CP": "TL072",
    "TL074CN": "TL074",
    "NE5532P": "NE5532",
    "NE5532AN": "NE5532",
    "RC4558P": "RC4558",
    "RC4558D": "RC4558",
    "LM741CN": "LM741",
    "LM358N": "LM358",
    "LM358P": "LM358",
    "LM13700N": "LM13700",
    "CA3080E": "CA3080",
    "LED": "LED_RED",          # generic "LED" → red
    "REDLED": "LED_RED",
    "GREENLED": "LED_GREEN",
    "BLUELED": "LED_BLUE",
}


def _norm(part: str) -> str:
    """Normalise a part number: strip whitespace, uppercase."""
    return part.strip().upper().replace(" ", "")


def lookup(part_number: str) -> dict | None:
    """Return specs dict for *part_number*, or None if not found.

    Checks exact match, then aliases, then case-insensitive scan.
    Returns a copy so callers can safely mutate.
    """
    key = _norm(part_number)
    if key in _DB:
        return {"part": key, **_DB[key]}
    if key in _ALIASES:
        canonical = _ALIASES[key]
        return {"part": canonical, **_DB[canonical]}
    # Case-insensitive scan (slower, last resort)
    for db_key, spec in _DB.items():
        if db_key.upper() == key:
            return {"part": db_key, **spec}
    return None


def search(
    query: str = "",
    type_filter: str | None = None,
    material: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """Search the component database.

    Parameters
    ----------
    query : str
        Part number prefix or description keyword (case-insensitive).
    type_filter : str | None
        Component type: 'NPN_BJT', 'diode', 'op_amp', etc.
    material : str | None
        'silicon', 'germanium', 'schottky', 'LED', etc.
    limit : int
        Maximum results to return.
    """
    q = query.upper()
    results: list[dict] = []

    for key, spec in _DB.items():
        if type_filter and spec.get("type") != type_filter:
            continue
        if material and spec.get("material", "").lower() != material.lower():
            continue
        if q and q not in key and q not in spec.get("description", "").upper():
            continue
        results.append({"part": key, **spec})
        if len(results) >= limit:
            break

    return results


def suggest_substitutes(
    part_number: str,
    relax_ratings: bool = False,
) -> list[dict]:
    """Return parts that could substitute for *part_number*.

    Matches on type + material, then ranks by hFE/Vf similarity.
    *relax_ratings* allows substitutes with lower absolute-max ratings
    (emit a warning flag).
    """
    spec = lookup(part_number)
    if not spec:
        return []

    candidates = search(type_filter=spec["type"], material=spec.get("material"))
    own_key = _norm(part_number)
    substitutes: list[dict] = []

    for cand in candidates:
        if _norm(cand["part"]) == own_key:
            continue
        # Score similarity
        score = 0.0
        warning = False
        if spec["type"] in ("NPN_BJT", "PNP_BJT"):
            hfe_diff = abs(cand.get("hfe_typ", 0) - spec.get("hfe_typ", 0))
            score = -hfe_diff
            vce_ok = abs(cand.get("vceo_v", 0)) >= abs(spec.get("vceo_v", 0))
            ic_ok = abs(cand.get("ic_max_ma", 0)) >= abs(spec.get("ic_max_ma", 0))
            if not vce_ok or not ic_ok:
                warning = True
                if not relax_ratings:
                    continue
        elif spec["type"] in ("diode", "LED"):
            vf_diff = abs(cand.get("vf_v", 0) - spec.get("vf_v", 0))
            score = -vf_diff * 10
        elif spec["type"] in ("N_JFET", "P_JFET"):
            idss_diff = abs(cand.get("idss_min_ma", 0) - spec.get("idss_min_ma", 0))
            score = -idss_diff
        substitutes.append({**cand, "_score": score, "_warning": warning})

    substitutes.sort(key=lambda x: -x["_score"])
    return substitutes[:6]


def infer_type_from_part_number(part: str) -> str | None:
    """Best-effort inference of component type from part number pattern.
    Used as a hint when the part is not in the local database.
    """
    p = part.upper()
    patterns = [
        (r"^2N\d{3,4}$", None),  # ambiguous — need lookup
        (r"^BC5[3-6]\d[ABC]?$", "NPN_BJT"),
        (r"^BC5[5-9]\d[ABC]?$", "NPN_BJT"),
        (r"^BC55\d[ABC]?$", "NPN_BJT"),
        (r"^BC56\d[ABC]?$", "PNP_BJT"),
        (r"^2N39\d\d$", "NPN_BJT"),
        (r"^2N35\d\d$", "PNP_BJT"),
        (r"^2N508\d$", "NPN_BJT"),
        (r"^AC1\d\d$", "PNP_BJT"),   # germanium PNP
        (r"^OC\d+$", "PNP_BJT"),      # vintage germanium
        (r"^NKT\d+$", "PNP_BJT"),
        (r"^J\d{3}$", "N_JFET"),
        (r"^MPF\d+$", "N_JFET"),
        (r"^2N5[4-9]\d\d$", "N_JFET"),
        (r"^2SK\d+$", "N_JFET"),
        (r"^BF2\d\d[ABC]?$", "N_JFET"),
        (r"^TL07\d", "op_amp"),
        (r"^LM\d{3}", "op_amp"),
        (r"^NE55\d\d", "op_amp"),
        (r"^RC\d{4}", "op_amp"),
        (r"^MC\d{4}", "op_amp"),
        (r"^OPA\d+", "op_amp"),
        (r"^CA\d{4}", "op_amp"),
        (r"^1N34", "diode"),   # germanium
        (r"^1N60", "diode"),   # germanium
        (r"^1N27\d", "diode"), # germanium
        (r"^1N4148", "diode"),
        (r"^1N914", "diode"),
        (r"^BAT\d+", "diode"),  # schottky
        (r"^1N58\d\d", "diode"), # schottky
        (r"^1N4\d{3}", "diode"), # rectifier
    ]
    for pattern, comp_type in patterns:
        if re.match(pattern, p):
            return comp_type
    return None
