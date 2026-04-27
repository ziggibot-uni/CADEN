from datetime import datetime, timedelta, timezone

import pytest

from caden.errors import LLMError, SchedulerError
from caden.learning.schema import CadenContext, Ligand, RecallPacket
from caden.scheduler.schedule import ExistingEvent, ScheduleBundle, _PlanRejection, _attempt_plan, plan


class _FakeLLM:
    def __init__(self, raw: str):
        self.raw = raw

    def chat_stream(self, *args, **kwargs):
        return self.raw, ""


def _local_tz():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _local_text(dt: datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def test_scheduler_rejects_moving_external_events(db_conn):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=2)).astimezone(tz)
    end = start + timedelta(hours=1)
    moved_start = end + timedelta(hours=1)
    moved_end = moved_start + timedelta(hours=1)

    raw = (
        "{"
        f'"start": "{_local_text(start, tz)}", '
        f'"end": "{_local_text(end, tz)}", '
        f'"moves": [{{"google_event_id": "external_1", "new_start": "{_local_text(moved_start, tz)}", '
        f'"new_end": "{_local_text(moved_end, tz)}"}}], '
        '"rationale": "move the external block"}'
    )

    with pytest.raises(_PlanRejection, match="External events MUST NOT be moved"):
        _attempt_plan(
            raw,
            conn=db_conn,
            llm=_FakeLLM(raw),
            local_tz=tz,
            now=now,
            deadline=(end + timedelta(days=1)).astimezone(timezone.utc),
            existing_events=[
                ExistingEvent(
                    google_event_id="external_1",
                    summary="Doctor appointment",
                    start=start.astimezone(timezone.utc),
                    end=end.astimezone(timezone.utc),
                    caden_owned=False,
                )
            ],
            on_open=None,
            on_thinking=None,
            on_content=None,
        )


def test_scheduler_rejects_overlapping_external_events(db_conn):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    event_start = (now + timedelta(hours=2)).astimezone(tz)
    event_end = event_start + timedelta(hours=1)
    overlapping_start = event_start + timedelta(minutes=15)
    overlapping_end = overlapping_start + timedelta(hours=1)

    raw = (
        "{"
        f'"start": "{_local_text(overlapping_start, tz)}", '
        f'"end": "{_local_text(overlapping_end, tz)}", '
        '"moves": [], '
        '"rationale": "that slot looks open"}'
    )

    with pytest.raises(_PlanRejection, match="External events MUST NOT be overlapped"):
        _attempt_plan(
            raw,
            conn=db_conn,
            llm=_FakeLLM(raw),
            local_tz=tz,
            now=now,
            deadline=(event_end + timedelta(days=1)).astimezone(timezone.utc),
            existing_events=[
                ExistingEvent(
                    google_event_id="external_1",
                    summary="Non-movable meeting",
                    start=event_start.astimezone(timezone.utc),
                    end=event_end.astimezone(timezone.utc),
                    caden_owned=False,
                )
            ],
            on_open=None,
            on_thinking=None,
            on_content=None,
        )


def test_scheduler_allows_valid_early_morning_slot_without_working_hours_rule(db_conn):
    tz = _local_tz()
    now_local = (datetime.now(timezone.utc) + timedelta(days=1)).astimezone(tz).replace(
        hour=1,
        minute=0,
        second=0,
        microsecond=0,
    )
    now = now_local.astimezone(timezone.utc)
    start_local = now_local.replace(hour=2)
    end_local = now_local.replace(hour=3)
    deadline = now_local.replace(hour=8).astimezone(timezone.utc)

    raw = (
        "{"
        f'"start": "{_local_text(start_local, tz)}", '
        f'"end": "{_local_text(end_local, tz)}", '
        '"moves": [], '
        '"rationale": "early morning is still before the deadline"}'
    )

    plan = _attempt_plan(
        raw,
        conn=db_conn,
        llm=_FakeLLM(raw),
        local_tz=tz,
        now=now,
        deadline=deadline,
        existing_events=[],
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert plan.total_minutes == 60
    assert plan.block.start == start_local.astimezone(timezone.utc)
    assert plan.block.end == end_local.astimezone(timezone.utc)


def test_scheduler_uses_libbie_packaged_recall_context(db_conn, monkeypatch):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=1)).astimezone(tz)
    end = start + timedelta(hours=1)
    deadline = (end + timedelta(hours=2)).astimezone(timezone.utc)
    seen: dict[str, str] = {}

    class _CapturingLLM:
        def chat_stream(self, system, user, **kwargs):
            seen["user"] = user
            return (
                "{"
                f'"start": "{_local_text(start, tz)}", '
                f'"end": "{_local_text(end, tz)}", '
                '"moves": [], '
                '"rationale": "fits cleanly"}'
            ), ""

    monkeypatch.setattr(
        "caden.scheduler.schedule.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (
            Ligand(domain="task", intent="plan this", themes=(), risk=(), outcome_focus="finish"),
            CadenContext(
                task="write the draft",
                recalled_memories=[
                    RecallPacket(
                        mem_id="mem_1",
                        summary="Sean focuses best in one-hour blocks.",
                        relevance="high",
                        reason="semantic=1.0",
                    )
                ],
            ),
            [],
        ),
    )
    monkeypatch.setattr(
        "caden.scheduler.schedule.curate.package_recall_context",
        lambda task_text, recalled_memories: "PACKAGED-BY-LIBBIE",
    )

    plan(
        "write the draft",
        deadline,
        conn=db_conn,
        llm=_CapturingLLM(),
        existing_events=[],
        description_embedding=[0.1] * 768,
        now=now,
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert "PACKAGED-BY-LIBBIE" in seen["user"]


def test_scheduler_success_emits_diag_outcome_line(db_conn, monkeypatch):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=1)).astimezone(tz)
    end = start + timedelta(hours=1)
    deadline = (end + timedelta(hours=2)).astimezone(timezone.utc)
    diag_calls: list[tuple[str, str]] = []

    class _CapturingLLM:
        def chat_stream(self, system, user, **kwargs):
            return (
                "{"
                f'"start": "{_local_text(start, tz)}", '
                f'"end": "{_local_text(end, tz)}", '
                '"moves": [], '
                '"rationale": "fits cleanly"}'
            ), ""

    monkeypatch.setattr("caden.scheduler.schedule.diag.log", lambda section, body: diag_calls.append((section, body)))

    plan(
        "write the draft",
        deadline,
        conn=db_conn,
        llm=_CapturingLLM(),
        existing_events=[],
        description_embedding=None,
        now=now,
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert any(section == "scheduler ✓ plan" for section, _body in diag_calls)


def test_scheduler_requests_and_returns_a_single_plan_not_alternative_options(db_conn):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=1)).astimezone(tz)
    end = start + timedelta(hours=1)
    deadline = (end + timedelta(hours=2)).astimezone(timezone.utc)
    captured: dict[str, str] = {}

    class _CapturingLLM:
        def chat_stream(self, system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return (
                "{"
                f'"start": "{_local_text(start, tz)}", '
                f'"end": "{_local_text(end, tz)}", '
                '"moves": [], '
                '"rationale": "pick one concrete slot"}'
            ), ""

    sched = plan(
        "write the draft",
        deadline,
        conn=db_conn,
        llm=_CapturingLLM(),
        existing_events=[],
        description_embedding=None,
        now=now,
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert sched.block.start == start.astimezone(timezone.utc)
    assert sched.block.end == end.astimezone(timezone.utc)
    assert sched.displacements == []
    assert not hasattr(sched, "alternatives")
    assert not hasattr(sched, "scores")
    assert '"start": "YYYY-MM-DD HH:MM"' in captured["system"]
    assert '"end": "YYYY-MM-DD HH:MM"' in captured["system"]
    assert '"moves": [' in captured["system"]
    assert "alternative" not in captured["system"].lower()
    assert "optimiz" not in captured["system"].lower()


def test_scheduler_prompt_includes_description_deadline_calendar_events_and_libbie_context(db_conn, monkeypatch):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=2)).astimezone(tz)
    end = start + timedelta(minutes=90)
    deadline = end.astimezone(timezone.utc)
    captured: dict[str, str] = {}

    class _CapturingLLM:
        def chat_stream(self, system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return (
                "{"
                f'"start": "{_local_text(start, tz)}", '
                f'"end": "{_local_text(end, tz)}", '
                '"moves": [], '
                '"rationale": "fits cleanly"}'
            ), ""

    monkeypatch.setattr(
        "caden.scheduler.schedule.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (
            Ligand(domain="task", intent="plan this", themes=(), risk=(), outcome_focus="finish"),
            CadenContext(
                task="write the draft",
                recalled_memories=[
                    RecallPacket(
                        mem_id="mem_1",
                        summary="Sean focuses best after lunch.",
                        relevance="high",
                        reason="semantic=1.0",
                    )
                ],
            ),
            [],
        ),
    )
    monkeypatch.setattr(
        "caden.scheduler.schedule.curate.package_recall_context",
        lambda task_text, recalled_memories: "PACKAGED-BY-LIBBIE",
    )

    plan(
        "write the draft",
        deadline,
        conn=db_conn,
        llm=_CapturingLLM(),
        existing_events=[
            ExistingEvent(
                google_event_id="evt_1",
                summary="Doctor appointment",
                start=(now + timedelta(hours=1)),
                end=(now + timedelta(hours=1, minutes=30)),
                caden_owned=False,
            )
        ],
        description_embedding=[0.1] * 768,
        now=now,
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert "Description:   write the draft" in captured["user"]
    assert "Deadline:" in captured["user"]
    assert "Doctor appointment" in captured["user"]
    assert "PACKAGED-BY-LIBBIE" in captured["user"]


def test_scheduler_derives_duration_from_end_minus_start_and_allows_slot_up_to_deadline(db_conn):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=1)).astimezone(tz)
    deadline = (now + timedelta(hours=2, minutes=30)).astimezone(timezone.utc)
    end = deadline.astimezone(tz)
    captured: dict[str, str] = {}

    class _CapturingLLM:
        def chat_stream(self, system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return (
                "{"
                f'"start": "{_local_text(start, tz)}", '
                f'"end": "{_local_text(end, tz)}", '
                '"moves": [], '
                '"rationale": "use the last open slot before the deadline"}'
            ), ""

    sched = plan(
        "finish the report",
        deadline,
        conn=db_conn,
        llm=_CapturingLLM(),
        existing_events=[],
        description_embedding=None,
        now=now,
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert sched.block.start == start.astimezone(timezone.utc)
    assert sched.block.end == deadline
    assert sched.total_minutes == 90
    assert "duration" not in captured["system"].lower()


def test_scheduler_routes_raw_llm_output_through_shared_repair_layer(db_conn, monkeypatch):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=1)).astimezone(tz)
    end = start + timedelta(hours=1)
    deadline = end.astimezone(timezone.utc)
    captured: dict[str, object] = {}

    class _LLM:
        def chat_stream(self, system, user, **kwargs):
            return "MESSY RAW SCHEDULE OUTPUT", ""

    def _fake_parse(raw, model):
        captured["raw"] = raw
        captured["model"] = model
        return ScheduleBundle.model_validate(
            {
                "start": _local_text(start, tz),
                "end": _local_text(end, tz),
                "moves": [],
                "rationale": "repair path used",
            }
        )

    monkeypatch.setattr("caden.scheduler.schedule.parse_and_validate", _fake_parse)

    sched = plan(
        "write the draft",
        deadline,
        conn=db_conn,
        llm=_LLM(),
        existing_events=[],
        description_embedding=None,
        now=now,
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert sched.total_minutes == 60
    assert captured == {"raw": "MESSY RAW SCHEDULE OUTPUT", "model": ScheduleBundle}


def test_scheduler_handles_large_calendar_windows_without_fixed_event_cap(db_conn):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=1)).astimezone(tz)
    end = start + timedelta(hours=1)
    deadline = (now + timedelta(days=3)).astimezone(timezone.utc)

    class _CapturingLLM:
        def chat_stream(self, system, user, **kwargs):
            return (
                "{"
                f'"start": "{_local_text(start, tz)}", '
                f'"end": "{_local_text(end, tz)}", '
                '"moves": [], '
                '"rationale": "fits cleanly"}'
            ), ""

    existing_events = [
        ExistingEvent(
            google_event_id=f"evt_{idx}",
            summary=f"Existing calendar item {idx}",
            start=(now + timedelta(hours=3 + idx * 2)),
            end=(now + timedelta(hours=4 + idx * 2)),
            caden_owned=False,
        )
        for idx in range(120)
    ]

    sched = plan(
        "plan a deep work block",
        deadline,
        conn=db_conn,
        llm=_CapturingLLM(),
        existing_events=existing_events,
        description_embedding=None,
        now=now,
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert sched.total_minutes == 60


def test_scheduler_prompt_keeps_full_description_and_preferences_without_char_cap(db_conn):
    tz = _local_tz()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = (now + timedelta(hours=1)).astimezone(tz)
    end = start + timedelta(hours=1)
    deadline = (end + timedelta(hours=2)).astimezone(timezone.utc)
    captured: dict[str, str] = {}
    marker_desc = "DESC-TAIL-DO-NOT-TRUNCATE"
    marker_pref = "PREF-TAIL-DO-NOT-TRUNCATE"
    long_description = "x" * 5000 + marker_desc
    long_preferences = "y" * 5000 + marker_pref

    class _CapturingLLM:
        def chat_stream(self, system, user, **kwargs):
            captured["user"] = user
            return (
                "{"
                f'"start": "{_local_text(start, tz)}", '
                f'"end": "{_local_text(end, tz)}", '
                '"moves": [], '
                '"rationale": "fits cleanly"}'
            ), ""

    plan(
        long_description,
        deadline,
        conn=db_conn,
        llm=_CapturingLLM(),
        existing_events=[],
        description_embedding=None,
        now=now,
        preferences=long_preferences,
        on_open=None,
        on_thinking=None,
        on_content=None,
    )

    assert marker_desc in captured["user"]
    assert marker_pref in captured["user"]


def test_scheduler_requires_aware_deadline_and_chains_llm_errors(db_conn):
    with pytest.raises(SchedulerError, match="deadline must be timezone-aware"):
        plan(
            "write the draft",
            datetime(2026, 5, 1, 12, 0),
            conn=db_conn,
            llm=_FakeLLM("{}"),
            existing_events=[],
            description_embedding=None,
            now=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )

    class _BoomLLM:
        def chat_stream(self, system, user, **kwargs):
            raise LLMError("ollama unavailable")

    with pytest.raises(SchedulerError, match="scheduler LLM call failed: ollama unavailable") as exc_info:
        plan(
            "write the draft",
            datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
            conn=db_conn,
            llm=_BoomLLM(),
            existing_events=[],
            description_embedding=None,
            now=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )
    assert isinstance(exc_info.value.__cause__, LLMError)
