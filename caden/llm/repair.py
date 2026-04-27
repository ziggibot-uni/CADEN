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

import difflib
import json
import re
from typing import Any, TypeVar, Type, get_args, get_origin

import pydantic
import json_repair

from .. import diag
from ..errors import LLMRepairError

_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*(?P<body>[\s\S]+?)\s*```", re.IGNORECASE
)

T = TypeVar("T", bound=pydantic.BaseModel)


def _canonical_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _field_model(field: pydantic.fields.FieldInfo) -> type[pydantic.BaseModel] | None:
    annotation = field.annotation
    if annotation is None:
        return None
    if isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
        return annotation
    origin = get_origin(annotation)
    if origin is None:
        return None
    for arg in get_args(annotation):
        if isinstance(arg, type) and issubclass(arg, pydantic.BaseModel):
            return arg
    return None


def _coerce_keys_for_model(parsed_obj: Any, model: Type[pydantic.BaseModel]) -> Any:
    if not isinstance(parsed_obj, dict):
        return parsed_obj

    fields = model.model_fields
    canonical_to_name = {
        _canonical_key(field_name): field_name for field_name in fields.keys()
    }
    corrected: dict[str, Any] = {}
    used_names: set[str] = set()

    for key, value in parsed_obj.items():
        if key in fields:
            target_name = key
        else:
            canonical_key = _canonical_key(str(key))
            target_name = canonical_to_name.get(canonical_key)
            if target_name is None:
                matches = difflib.get_close_matches(
                    canonical_key,
                    list(canonical_to_name.keys()),
                    n=1,
                    cutoff=0.85,
                )
                if matches:
                    target_name = canonical_to_name[matches[0]]
        if target_name is None or target_name in used_names:
            corrected[str(key)] = value
            continue

        used_names.add(target_name)
        nested_model = _field_model(fields[target_name])
        if nested_model is not None:
            corrected[target_name] = _coerce_keys_for_model(value, nested_model)
        else:
            corrected[target_name] = value

    return corrected

def parse_and_validate(raw: str, model: Type[T]) -> T:
    """Best-effort: pull JSON out, repair via json_repair, validate via Pydantic."""
    if not isinstance(raw, str) or not raw.strip():
        diag.log("llm.repair ✗ empty", f"model={model.__name__}")
        raise LLMRepairError("LLM returned empty output")

    # 1. strip code fences if present at top-level
    text_to_parse = raw
    fence = _CODE_FENCE_RE.search(raw)
    needed_repair = False
    if fence:
        text_to_parse = fence.group("body")
        needed_repair = True

    if not needed_repair:
        try:
            json.loads(text_to_parse)
        except Exception:
            needed_repair = True

    # 2. json_repair.loads
    try:
        parsed_obj = json_repair.loads(text_to_parse)
    except Exception as e:
        diag.log(
            "llm.repair ✗ parse",
            f"model={model.__name__}\nraw={raw[:500]!r}\nerror={e}",
        )
        raise LLMRepairError(
            f"json_repair could not parse output: {e}\n"
            f"raw output was: {raw[:500]!r}"
        ) from e
        
    if not parsed_obj:
        diag.log(
            "llm.repair ✗ empty-object",
            f"model={model.__name__}\nraw={raw[:500]!r}",
        )
        raise LLMRepairError(f"json_repair parsed empty object from raw: {raw[:500]!r}")

    parsed_obj = _coerce_keys_for_model(parsed_obj, model)

    # 3. pydantic validation
    try:
        validated = model.model_validate(parsed_obj)
    except pydantic.ValidationError as e:
        diag.log(
            "llm.repair ✗ validation",
            f"model={model.__name__}\nparsed={parsed_obj!r}\nerror={e}",
        )
        raise LLMRepairError(
            f"Pydantic schema validation failed: {e}\n"
            f"parsed object was: {parsed_obj}\n"
            f"raw output was: {raw[:500]!r}"
        ) from e

    if needed_repair:
        diag.log(
            "llm.repair ✓ repaired",
            f"model={model.__name__}\nraw={raw[:500]!r}\nparsed={parsed_obj!r}",
        )
    return validated
