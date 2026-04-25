"""Tolerant JSON extraction / repair between the LLM client and callers.

Per spec: the LLM is allowed to be messy. This layer accepts prose-wrapped
JSON, code-fenced JSON, single quotes, trailing commas. It does NOT
fabricate missing fields and it does NOT guess defaults — if after repair a
required field is still missing, we raise LLMRepairError so the failure is
loud.

Pipeline: raw text -> strip code fences -> json_repair.loads -> pydantic
validate against expected model -> return typed object, or raise LLMError
with original text + repair attempts attached.
"""

from __future__ import annotations

import re
from typing import TypeVar, Type

import pydantic
import json_repair

from ..errors import LLMRepairError

_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*(?P<body>[\s\S]+?)\s*```", re.IGNORECASE
)

T = TypeVar("T", bound=pydantic.BaseModel)

def parse_and_validate(raw: str, model: Type[T]) -> T:
    """Best-effort: pull JSON out, repair via json_repair, validate via Pydantic."""
    if not isinstance(raw, str) or not raw.strip():
        raise LLMRepairError("LLM returned empty output")

    # 1. strip code fences if present at top-level
    text_to_parse = raw
    fence = _CODE_FENCE_RE.search(raw)
    if fence:
        text_to_parse = fence.group("body")

    # 2. json_repair.loads
    try:
        parsed_obj = json_repair.loads(text_to_parse)
    except Exception as e:
        raise LLMRepairError(
            f"json_repair could not parse output: {e}\n"
            f"raw output was: {raw[:500]!r}"
        ) from e
        
    if not parsed_obj:
        raise LLMRepairError(f"json_repair parsed empty object from raw: {raw[:500]!r}")

    # 3. pydantic validation
    try:
        return model.model_validate(parsed_obj)
    except pydantic.ValidationError as e:
        raise LLMRepairError(
            f"Pydantic schema validation failed: {e}\n"
            f"parsed object was: {parsed_obj}\n"
            f"raw output was: {raw[:500]!r}"
        ) from e
