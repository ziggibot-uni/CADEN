"""
Datasheet lookup for components not in the local component_db.

Strategy:
  1. Local component_db (instant, authoritative)
  2. LCSC product search API (free, no key, good coverage of jellybean parts)
  3. Pattern-based type inference (last resort — tells the UI what fields to ask for)

The caller should always try component_db.lookup() first; call fetch() only
when that returns None.
"""

from __future__ import annotations
import re
from typing import Any

import httpx

from backend.physics import component_db as cdb

_LCSC_SEARCH = "https://wmsc.lcsc.com/wmsc/search/global"
_TIMEOUT = 6.0


async def fetch(part_number: str) -> dict[str, Any]:
    """Attempt to fetch specs for *part_number* from the web.

    Returns a dict with at minimum:
      - 'part'        : normalised part number
      - 'found'       : bool — True if any real spec data was retrieved
      - 'source'      : 'local_db' | 'lcsc' | 'inferred' | 'unknown'
      - (optional spec fields from component_db schema)
    """
    part = part_number.strip()

    # ── 1. Local DB ───────────────────────────────────────────────
    local = cdb.lookup(part)
    if local:
        return {**local, "found": True, "source": "local_db"}

    # ── 2. LCSC search ────────────────────────────────────────────
    lcsc_result = await _lcsc_search(part)
    if lcsc_result:
        return {**lcsc_result, "found": True, "source": "lcsc"}

    # ── 3. Pattern inference ──────────────────────────────────────
    inferred_type = cdb.infer_type_from_part_number(part)
    return {
        "part": part.upper(),
        "found": False,
        "source": "inferred" if inferred_type else "unknown",
        "type": inferred_type,
        "description": f"Unknown part — please enter specs manually",
        "missing_fields": _required_fields_for_type(inferred_type),
    }


async def _lcsc_search(part: str) -> dict[str, Any] | None:
    """Query LCSC's undocumented search API and parse the first result."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                _LCSC_SEARCH,
                params={"keyword": part, "currentPage": 1, "pageSize": 5},
                headers={"User-Agent": "PedalManifest/1.0"},
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    products = (
        data.get("result", {}).get("productSearchResultVO", {}).get("productList")
        or data.get("productList")
        or []
    )
    if not products:
        return None

    # Find best match: prefer exact part number match
    target = part.upper()
    match = None
    for p in products:
        model = (p.get("productModel") or "").upper()
        if model == target:
            match = p
            break
    if not match:
        match = products[0]

    return _parse_lcsc_product(match)


def _parse_lcsc_product(p: dict) -> dict[str, Any] | None:
    """Extract relevant specs from an LCSC product record."""
    if not p:
        return None

    desc = p.get("productDescription") or p.get("productIntroduction") or ""
    part = p.get("productModel") or ""
    datasheet = p.get("dataManualUrl") or p.get("pdfUrl") or ""

    # Infer component type from description / category
    cat = (p.get("catalogName") or p.get("parentCatalogName") or "").lower()
    comp_type = _infer_type_from_lcsc_category(cat, desc)

    result: dict[str, Any] = {
        "part": part,
        "description": desc[:120],
        "type": comp_type,
        "datasheet_url": datasheet,
        "manufacturer": p.get("brandNameEn") or "",
        "package": p.get("encapStandard") or p.get("packageModel") or "",
    }

    # Try to extract key specs from the parametric data LCSC sometimes includes
    params: list[dict] = p.get("paramVOList") or []
    param_map = {x.get("paramNameEn", "").lower(): x.get("paramValue", "") for x in params}

    def _parse_float(key: str) -> float | None:
        v = param_map.get(key, "")
        nums = re.findall(r"[-+]?\d*\.?\d+", str(v))
        return float(nums[0]) if nums else None

    if comp_type in ("NPN_BJT", "PNP_BJT"):
        result["vceo_v"] = _parse_float("collector-emitter voltage (vceo)")
        result["ic_max_ma"] = _parse_float("collector current (ic)")
        result["hfe_min"] = _parse_float("dc current gain (hfe) min")
        result["hfe_max"] = _parse_float("dc current gain (hfe) max")
        result["vbe_v"] = 0.65  # default silicon

    elif comp_type == "op_amp":
        result["gbw_mhz"] = _parse_float("gain bandwidth product (gbp)")
        result["slew_rate_v_us"] = _parse_float("slew rate")

    elif comp_type in ("diode", "LED"):
        result["vf_v"] = _parse_float("forward voltage (vf)")
        result["vr_max_v"] = _parse_float("reverse voltage (vr)")
        result["if_max_ma"] = _parse_float("continuous forward current (if)")

    # Remove None values
    result = {k: v for k, v in result.items() if v is not None}
    return result if result.get("part") else None


def _infer_type_from_lcsc_category(cat: str, desc: str) -> str | None:
    """Map LCSC category strings to our component type names."""
    text = f"{cat} {desc}".lower()
    if "npn" in text:
        return "NPN_BJT"
    if "pnp" in text:
        return "PNP_BJT"
    if "n-channel" in text and "jfet" in text:
        return "N_JFET"
    if "p-channel" in text and "jfet" in text:
        return "P_JFET"
    if any(x in text for x in ("op-amp", "op amp", "operational amplifier")):
        return "op_amp"
    if "ota" in text or "transconductance" in text:
        return "op_amp"
    if "schottky" in text:
        return "diode"
    if "germanium" in text and "diode" in text:
        return "diode"
    if "signal diode" in text or "switching diode" in text:
        return "diode"
    if "led" in text or "light emitting" in text:
        return "LED"
    if "transistor" in text or "bjt" in text:
        return "NPN_BJT"  # best guess
    if "diode" in text or "rectifier" in text:
        return "diode"
    return None


def _required_fields_for_type(comp_type: str | None) -> list[str]:
    """Return the spec fields a user must fill in for an unknown part of this type."""
    fields: dict[str, list[str]] = {
        "NPN_BJT":  ["vceo_v", "ic_max_ma", "hfe_min", "hfe_typ", "hfe_max", "vbe_v", "ft_mhz"],
        "PNP_BJT":  ["vceo_v", "ic_max_ma", "hfe_min", "hfe_typ", "hfe_max", "vbe_v", "ft_mhz"],
        "N_JFET":   ["vgs_off_min_v", "vgs_off_max_v", "idss_min_ma", "idss_max_ma", "vds_max_v"],
        "P_JFET":   ["vgs_off_min_v", "vgs_off_max_v", "idss_min_ma", "idss_max_ma", "vds_max_v"],
        "op_amp":   ["vcc_dual_max_v", "gbw_mhz", "slew_rate_v_us", "channels", "input_type"],
        "diode":    ["vf_v", "vr_max_v", "if_max_ma", "material"],
        "LED":      ["vf_v", "vr_max_v", "if_max_ma", "led_color"],
    }
    return fields.get(comp_type or "", [])
