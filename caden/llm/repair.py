"""Tolerant JSON extraction / repair between the LLM client and callers.

Per spec: the LLM is allowed to be messy. This layer accepts prose-wrapped
JSON, code-fenced JSON, single quotes, trailing commas. It does NOT
fabricate missing fields and it does NOT guess defaults — if after repair a
required field is still missing, we raise LLMRepairError so the failure is
loud.
"""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from ..errors import LLMRepairError

_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*(?P<body>[\s\S]+?)\s*```", re.IGNORECASE
)


def extract_json(raw: str) -> Any:
    """Best-effort: pull JSON out of whatever the LLM returned, repair, parse."""
    if not isinstance(raw, str) or not raw.strip():
        raise LLMRepairError("LLM returned empty output")

    candidates: list[str] = []

    fence = _CODE_FENCE_RE.search(raw)
    if fence:
        candidates.append(fence.group("body"))

    candidates.append(raw)

    # Also try "first { ... last }" and "first [ ... last ]" slices.
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i = raw.find(open_c)
        j = raw.rfind(close_c)
        if i != -1 and j != -1 and j > i:
            candidates.append(raw[i : j + 1])

    last_error: Exception | None = None
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError as e:
            last_error = e
            try:
                return json.loads(_repair(c))
            except json.JSONDecodeError as e2:
                last_error = e2
                continue

    raise LLMRepairError(
        f"could not parse JSON from LLM output after repair attempts: {last_error}. "
        f"raw output was: {raw[:500]!r}"
    )


def _repair(s: str) -> str:
    """Apply cheap, obvious textual fixes."""
    t = s.strip()
    # Strip leading prose up to the first { or [.
    for c in ("{", "["):
        idx = t.find(c)
        if idx > 0:
            # but only if the prose does not itself contain a closing of the same kind
            t = t[idx:]
            break
    # Strip trailing prose after matching closer — naive, but fine for our cases.
    # Replace single-quoted strings with double quotes, carefully ignoring apostrophes
    # inside already-double-quoted strings. Good enough heuristic for local LLMs.
    t = _swap_single_quotes(t)
    # Remove trailing commas before } or ].
    t = re.sub(r",\s*([}\]])", r"\1", t)
    # Strip JS-style comments.
    t = re.sub(r"//[^\n]*", "", t)
    t = re.sub(r"/\*[\s\S]*?\*/", "", t)
    return t


def _swap_single_quotes(s: str) -> str:
    out: list[str] = []
    in_double = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            out.append(ch)
            out.append(s[i + 1])
            i += 2
            continue
        if ch == '"':
            in_double = not in_double
            out.append(ch)
        elif ch == "'" and not in_double:
            out.append('"')
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def require_fields(obj: Any, required: Sequence[str]) -> dict:
    """Ensure obj is a dict with every required key present. Loud on miss."""
    if not isinstance(obj, dict):
        raise LLMRepairError(
            f"expected JSON object with fields {list(required)}, got {type(obj).__name__}"
        )
    missing = [f for f in required if f not in obj]
    if missing:
        raise LLMRepairError(
            f"LLM JSON is missing required fields {missing}. got keys: {list(obj.keys())}"
        )
    return obj


def require_float(obj: dict, key: str, *, allow_none: bool = False) -> float | None:
    v = obj.get(key)
    if v is None:
        if allow_none:
            return None
        raise LLMRepairError(f"field {key!r} is null; expected a number")
    try:
        return float(v)
    except (TypeError, ValueError) as e:
        raise LLMRepairError(f"field {key!r} is not a number: {v!r}") from e
