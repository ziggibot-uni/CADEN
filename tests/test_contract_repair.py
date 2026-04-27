import pytest
import pydantic

from caden.errors import LLMRepairError
from caden.llm.repair import parse_and_validate


class _ReplyModel(pydantic.BaseModel):
    mood: float | None = None
    energy: float | None = None
    productivity: float | None = None
    rationale: str


def test_repair_accepts_fields_in_different_order():
    raw = '{"rationale": "fine", "productivity": 0.8, "mood": 0.2, "energy": 0.1}'

    parsed = parse_and_validate(raw, _ReplyModel)

    assert parsed.rationale == "fine"
    assert parsed.productivity == 0.8
    assert parsed.mood == 0.2
    assert parsed.energy == 0.1


def test_repair_accepts_single_quotes_and_trailing_commas(monkeypatch):
    diag_calls: list[tuple[str, str]] = []
    raw = "```json\n{'mood': 0.2, 'energy': 0.1, 'productivity': 0.8, 'rationale': 'fine',}\n```"

    monkeypatch.setattr("caden.llm.repair.diag.log", lambda section, body: diag_calls.append((section, body)))

    parsed = parse_and_validate(raw, _ReplyModel)

    assert parsed.rationale == "fine"
    assert parsed.productivity == 0.8
    assert any(section == "llm.repair ✓ repaired" for section, _body in diag_calls)


def test_repair_accepts_slightly_wrong_field_names(monkeypatch):
    diag_calls: list[tuple[str, str]] = []
    raw = "```json\n{'mood': 0.2, 'energy': 0.1, 'productivty': 0.8, 'rationalee': 'fine'}\n```"

    monkeypatch.setattr("caden.llm.repair.diag.log", lambda section, body: diag_calls.append((section, body)))

    parsed = parse_and_validate(raw, _ReplyModel)

    assert parsed.mood == 0.2
    assert parsed.energy == 0.1
    assert parsed.productivity == 0.8
    assert parsed.rationale == "fine"
    assert any(section == "llm.repair ✓ repaired" for section, _body in diag_calls)


def test_repair_fails_loudly_when_required_content_is_missing():
    raw = "```json\n{'mood': 0.2, 'energy': 0.1, 'productivity': 0.8}\n```"

    with pytest.raises(LLMRepairError, match="Pydantic schema validation failed"):
        parse_and_validate(raw, _ReplyModel)


def test_repair_logs_validation_failures(monkeypatch):
    diag_calls: list[tuple[str, str]] = []
    raw = "```json\n{'mood': 0.2, 'energy': 0.1, 'productivity': 0.8}\n```"

    monkeypatch.setattr("caden.llm.repair.diag.log", lambda section, body: diag_calls.append((section, body)))

    with pytest.raises(LLMRepairError, match="Pydantic schema validation failed"):
        parse_and_validate(raw, _ReplyModel)

    assert any(section == "llm.repair ✗ validation" for section, _body in diag_calls)
