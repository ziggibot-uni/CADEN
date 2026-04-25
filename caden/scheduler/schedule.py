"""v0 scheduling: LLM-driven block placement against the real calendar.

Per spec ("Concrete v0 first-time scheduling rule"):
  - CADEN reads existing Google Calendar items between now and the deadline
  - the LLM is given the task description, the deadline, existing events
    (both CADEN-owned task blocks and external events), and recent Libbie
    memory
  - the LLM picks a window [start, end] for the task and, if it needs to
    displace CADEN-owned task blocks to make room, returns a list of moves
    for those blocks
  - external (non-CADEN) events are NEVER moved
  - no hand-written heuristics about timing (no top-of-hour rounding, no
    buffer-from-now, no hard-coded max chunk count). If the LLM has no
    evidence for a duration, it is allowed to emit null and the bootstrap
    default is used with a loud first-use event.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

from ..config import (
    BOOTSTRAP_FOCAL_TEXT_TRUNCATE_CHARS,
    BOOTSTRAP_RETRIEVAL_TOP_K,
    BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
    BOOTSTRAP_SCHEDULER_EVENT_SUMMARY_CHARS,
    BOOTSTRAP_SCHEDULER_MAX_CALENDAR_EVENTS,
    BOOTSTRAP_SCHEDULER_MAX_RETRIES,
    log_bootstrap_use,
)
from ..errors import LLMError, LLMRepairError, SchedulerError
from .. import diag
from ..libbie import retrieve
from ..libbie.store import write_event
from ..llm.client import OllamaClient
from ..llm.repair import parse_and_validate
import pydantic


class _PlanRejection(Exception):
    """Internal: the LLM's proposal violated a deterministic constraint.

    Carries a `lesson` string written for the model — a single concrete fact
    in second person ("Your proposed start 14:00 overlaps the external event
    'standup' 13:30 → 14:30. Pick a window that does not overlap any
    external event, or move a caden_owned event out of the way."). The
    retry loop appends this verbatim to the next prompt.
    """
    def __init__(self, lesson: str) -> None:
        super().__init__(lesson)
        self.lesson = lesson



class MoveRequest(pydantic.BaseModel):
    google_event_id: str
    new_start: str
    new_end: str

class ScheduleBundle(pydantic.BaseModel):
    start: str
    end: str
    moves: list[MoveRequest] = pydantic.Field(default_factory=list)
    rationale: str | None = ""

# ---- data classes ------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """One scheduled block. v0 does not split tasks, so chunk_count is always 1."""
    index: int
    count: int
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Displacement:
    """An existing CADEN-owned task event the LLM wants to move out of the way."""
    google_event_id: str
    new_start: datetime
    new_end: datetime


@dataclass(frozen=True)
class SchedulePlan:
    total_minutes: int
    chunks: list[Chunk]
    displacements: list[Displacement]
    rationale: str


@dataclass(frozen=True)
class ExistingEvent:
    """What the scheduler needs to know about an event in the window.

    `caden_owned` is True for task blocks CADEN itself scheduled (i.e. rows
    in `task_events`); only those may be displaced. External events are
    reference-only.
    """
    google_event_id: str
    summary: str
    start: datetime
    end: datetime
    caden_owned: bool


# ---- LLM prompt --------------------------------------------------------------

# All times shown to the LLM are in Sean's local timezone, formatted as
# "YYYY-MM-DD HH:MM" (24-hour, no offset). The framework — not the LLM —
# is responsible for converting to/from UTC and ISO-8601. The LLM should
# only ever see and emit local wall-clock times. This keeps the model out
# of the timezone-arithmetic business, which it gets wrong.

_SYSTEM_PROMPT = """You are CADEN's scheduler. Given a task description, a deadline, \
and the list of events already on Sean's calendar between now and that deadline, \
pick a concrete start/end time for the task.

All times shown to you are in Sean's LOCAL wall-clock time, formatted as
"YYYY-MM-DD HH:MM" (24-hour). Emit your times in exactly the same format.
Do NOT include timezone offsets, "Z", "UTC", or AM/PM. The framework
attaches the timezone for you.

Rules:
  - Respect any time Sean states in the description (e.g. "take a shower at 8pm"
    means the start must be 20:00). If Sean does not state a time, you choose.
  - The end must not be after the deadline.
  - The start must not be before "now".
  - You MAY displace existing events marked caden_owned=true by proposing a
    new start/end for them in the "moves" list. You MUST NOT propose moves
    for events with caden_owned=false — those are external commitments Sean
    already has.
  - You MAY overlap a caden_owned event only if you also move it out of the
    way via "moves".

Return JSON with this exact shape:

{
  "start": "YYYY-MM-DD HH:MM",
  "end":   "YYYY-MM-DD HH:MM",
  "moves": [
    {"google_event_id": "...", "new_start": "YYYY-MM-DD HH:MM", "new_end": "YYYY-MM-DD HH:MM"}
  ],
  "rationale": "one or two sentences"
}

JSON only. No prose outside the object.
"""


# ---- helpers -----------------------------------------------------------------

# The format the LLM sees and emits. Local wall-clock, no offset.
_LOCAL_FMT = "%Y-%m-%d %H:%M"


def _fmt_local(dt: datetime, tz) -> str:
    """Render an aware datetime in Sean's local timezone, no offset."""
    return dt.astimezone(tz).strftime(_LOCAL_FMT)


def _fmt_events(events: Sequence[ExistingEvent], tz) -> str:
    if not events:
        return "(none)"
    lines = []
    cap = BOOTSTRAP_SCHEDULER_EVENT_SUMMARY_CHARS
    for e in events:
        tag = "caden_owned" if e.caden_owned else "external"
        summary = e.summary or ""
        if len(summary) > cap:
            summary = summary[:cap] + "…"
        lines.append(
            f"- id={e.google_event_id!r} {tag} "
            f"{_fmt_local(e.start, tz)} → {_fmt_local(e.end, tz)}  {summary!r}"
        )
    return "\n".join(lines)


def _parse_local(s: object, field: str, tz) -> datetime:
    """Parse a local wall-clock string from the LLM into an aware UTC datetime.

    Accepts the canonical "YYYY-MM-DD HH:MM" form. Also accepts ISO-8601
    with a "T" separator and seconds, and tolerates an explicit offset or
    "Z" (in which case the offset wins over the local tz). Anything else
    is a hard repair error.
    """
    if not isinstance(s, str):
        raise LLMRepairError(f"field {field!r} must be a string timestamp")
    text = s.strip().replace("T", " ").replace("Z", "+00:00")
    # Strip seconds if the model emitted "HH:MM:SS".
    # We try strict local form first.
    for fmt in (_LOCAL_FMT, "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=tz)
    # Fall back: accept ISO with offset (and warn nobody — just use it).
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as e:
        raise LLMRepairError(
            f"field {field!r} is not in 'YYYY-MM-DD HH:MM' form: {s!r}"
        ) from e
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt


# ---- entry point -------------------------------------------------------------

def plan(
    description: str,
    deadline: datetime,
    *,
    conn: sqlite3.Connection,
    llm: OllamaClient,
    existing_events: Sequence[ExistingEvent],
    description_embedding: Sequence[float] | None = None,
    now: datetime | None = None,
    preferences: str | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_content: Callable[[str], None] | None = None,
    on_open: Callable[[], None] | None = None,
) -> SchedulePlan:
    """Ask the LLM where to put this task. Return a SchedulePlan.

    Raises SchedulerError if the LLM violates hard constraints: before-now,
    past deadline, malformed times, or a proposed move of an external event.

    ``preferences`` is Sean's free-form note for this specific task: ordering
    constraints, blockers, time-of-day preferences, anything he wants the
    scheduler to weight. It is not parsed; it is forwarded verbatim to the
    LLM as additional context. Empty / None is a no-op.

    `on_thinking` / `on_content` let the caller surface live progress from
    the streaming model into the UI. `on_open` fires when the HTTP stream
    actually opens. All three callbacks are optional.
    """
    if deadline.tzinfo is None:
        raise SchedulerError("deadline must be timezone-aware")
    now = now or datetime.now(timezone.utc)
    if deadline <= now:
        raise SchedulerError(f"deadline {deadline.isoformat()} is not in the future")

    # Sean's local timezone, derived from the system. Everything the LLM
    # sees and emits is in this zone; we convert at the boundary.
    local_tz = now.astimezone().tzinfo
    if local_tz is None:
        # Cannot happen: astimezone() with no args attaches the system tz.
        raise SchedulerError("could not determine local timezone")
    tz_label = datetime.now(local_tz).strftime("%Z") or str(local_tz)

    # Recent Libbie memory (so the LLM can see past similar tasks).
    ctx_block = "(none)"
    if description_embedding is not None:
        log_bootstrap_use(conn, "BOOTSTRAP_RETRIEVAL_TOP_K", BOOTSTRAP_RETRIEVAL_TOP_K)
        log_bootstrap_use(
            conn,
            "BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS",
            BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
        )
        neighbours = retrieve.search(
            conn,
            description_embedding,
            k=BOOTSTRAP_RETRIEVAL_TOP_K,
            sources=(
                "task",
                "prediction",
                "residual",
                "rating",
                "sean_chat",
                "intake_self_knowledge",
            ),
        )
        trunc = BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS
        if neighbours:
            # Reasoning models loop when fed pages of memory. Take only the
            # top 5 most-relevant neighbours and truncate each more
            # aggressively for the scheduler's prompt — the chat surface
            # gets the full retrieval budget elsewhere.
            ctx_block = "\n".join(
                f"- [{r.event.timestamp} / {r.event.source}] "
                f"{(r.event.raw_text[:200] + '…') if len(r.event.raw_text) > 200 else r.event.raw_text}"
                for r in neighbours[:5]
            )

    # Refuse to swamp the model with a window full of meetings. Past this
    # cap the prompt is so dense the LLM can't reliably reason about
    # conflicts; surface it as a hard error so upstream can narrow the
    # window or summarise.
    if len(existing_events) > BOOTSTRAP_SCHEDULER_MAX_CALENDAR_EVENTS:
        raise SchedulerError(
            f"scheduler window contains {len(existing_events)} events, "
            f"above BOOTSTRAP_SCHEDULER_MAX_CALENDAR_EVENTS="
            f"{BOOTSTRAP_SCHEDULER_MAX_CALENDAR_EVENTS}; narrow the window "
            f"or pre-summarise before calling plan()."
        )
    log_bootstrap_use(
        conn,
        "BOOTSTRAP_SCHEDULER_MAX_CALENDAR_EVENTS",
        BOOTSTRAP_SCHEDULER_MAX_CALENDAR_EVENTS,
    )
    log_bootstrap_use(
        conn,
        "BOOTSTRAP_FOCAL_TEXT_TRUNCATE_CHARS",
        BOOTSTRAP_FOCAL_TEXT_TRUNCATE_CHARS,
    )

    focal_cap = BOOTSTRAP_FOCAL_TEXT_TRUNCATE_CHARS
    desc_block = description if len(description) <= focal_cap else description[:focal_cap] + "…"
    prefs_raw = (preferences or "").strip()
    if not prefs_raw:
        prefs_block = "(none)"
    elif len(prefs_raw) > focal_cap:
        prefs_block = prefs_raw[:focal_cap] + "…"
    else:
        prefs_block = prefs_raw

    user_prompt = (
        f"Sean's timezone: {tz_label}  (all times below are local wall-clock)\n"
        f"Now:           {_fmt_local(now, local_tz)}  ({now.astimezone(local_tz).strftime('%A')})\n"
        f"Deadline:      {_fmt_local(deadline, local_tz)}  ({deadline.astimezone(local_tz).strftime('%A')})\n"
        f"Description:   {desc_block}\n\n"
        f"Sean's preferences for THIS task (free-form; honour what you can,\n"
        f"ignore what conflicts with hard constraints, surface conflicts in\n"
        f"your rationale):\n{prefs_block}\n\n"
        f"Existing events between now and deadline:\n{_fmt_events(existing_events, local_tz)}\n\n"
        f"Relevant memory from Libbie:\n{ctx_block}\n\n"
        f"Emit a JSON schedule per the system instructions. "
        f"Use 'YYYY-MM-DD HH:MM' for every timestamp."
    )

    log_bootstrap_use(
        conn,
        "BOOTSTRAP_SCHEDULER_MAX_RETRIES",
        BOOTSTRAP_SCHEDULER_MAX_RETRIES,
    )
    max_attempts = max(1, int(BOOTSTRAP_SCHEDULER_MAX_RETRIES) + 1)
    lessons: list[str] = []
    last_attempt_summary: str | None = None
    for attempt in range(1, max_attempts + 1):
        attempt_prompt = user_prompt
        if lessons:
            # Prior attempts violated a deterministic constraint. Tell the
            # model exactly what was wrong, in order, and ask it to fix all
            # listed problems at once. The model has no memory across calls
            # so we re-state every prior lesson, not just the latest.
            lesson_block = "\n".join(
                f"  attempt {i + 1}: {ls}" for i, ls in enumerate(lessons)
            )
            attempt_prompt = (
                f"{user_prompt}\n\n"
                f"PRIOR ATTEMPTS WERE REJECTED BY THE FRAMEWORK FOR THE FOLLOWING\n"
                f"DETERMINISTIC REASONS. You must fix ALL of these in your next\n"
                f"answer. Do not repeat the same mistake.\n"
                f"{lesson_block}\n"
            )
            if last_attempt_summary:
                attempt_prompt += (
                    f"\nYour previous JSON was:\n{last_attempt_summary}\n"
                )
        try:
            sched = _attempt_plan(
                attempt_prompt,
                conn=conn,
                llm=llm,
                local_tz=local_tz,
                now=now,
                deadline=deadline,
                existing_events=existing_events,
                # Live UI callbacks only fire on the first attempt to avoid
                # confusing the user with reset-then-restart flicker on retry.
                on_open=on_open if attempt == 1 else None,
                on_thinking=on_thinking if attempt == 1 else None,
                on_content=on_content if attempt == 1 else None,
            )
        except _PlanRejection as rj:
            diag.log(
                "scheduler ✗ attempt rejected",
                f"attempt={attempt}/{max_attempts}\n{rj.lesson}",
            )
            lessons.append(rj.lesson)
            last_attempt_summary = rj.__cause__.args[0] if (rj.__cause__ and rj.__cause__.args) else None
            if attempt >= max_attempts:
                # Persist the failure into Libbie so future scheduler calls
                # retrieve it and can learn from the pattern.
                write_event(
                        conn,
                        source="scheduler_lesson",
                        raw_text=(
                            f"scheduler gave up after {attempt} attempts. "
                            f"description={desc_block!r}. lessons:\n"
                            + "\n".join(f"- {ls}" for ls in lessons)
                        ),
                        embedding=None,
                        meta={
                            "outcome": "failed",
                            "attempts": attempt,
                            "lessons": lessons,
                        },
                    )
                raise SchedulerError(
                    f"scheduler could not produce a valid plan after "
                    f"{attempt} attempt(s). last lesson: {rj.lesson}"
                ) from rj
            continue

        # Success. If we needed retries to get here, persist the lesson
        # trail so future scheduling can retrieve it.
        if lessons:
            write_event(
                    conn,
                    source="scheduler_lesson",
                    raw_text=(
                        f"scheduler recovered on attempt {attempt}/{max_attempts}. "
                        f"description={desc_block!r}. lessons that were needed:\n"
                        + "\n".join(f"- {ls}" for ls in lessons)
                    ),
                    embedding=None,
                    meta={
                        "outcome": "recovered",
                        "attempts": attempt,
                        "lessons": lessons,
                    },
                )
        return sched
    # Unreachable: the loop either returns or raises.
    raise SchedulerError("scheduler retry loop exited without a result")


def _attempt_plan(
    user_prompt: str,
    *,
    conn: sqlite3.Connection,
    llm: OllamaClient,
    local_tz,
    now: datetime,
    deadline: datetime,
    existing_events: Sequence[ExistingEvent],
    on_open: Callable[[], None] | None,
    on_thinking: Callable[[str], None] | None,
    on_content: Callable[[str], None] | None,
) -> SchedulePlan:
    """Run one scheduler LLM attempt and validate it deterministically.

    Returns a SchedulePlan on success.
    Raises _PlanRejection with a model-facing `lesson` when the LLM violates
    a deterministic constraint (so the retry loop can re-prompt).
    Raises SchedulerError for things the LLM can't be expected to fix
    (transport failure, malformed JSON the repair layer couldn't fix).
    """
    try:
        # Note: we deliberately do NOT pass format_json=True here. Ollama's
        # strict JSON mode tends to buffer the entire response, defeating
        # streaming. The repair layer below will extract JSON from prose.
        # We also leave think=False (default) so the model produces visible
        # tokens immediately rather than reasoning silently first.
        #
        # Temperature 0.6 (not 0.1) and repeat_penalty 1.15 are anti-loop
        # measures: reasoning models like qwen3 get stuck in "wait, let me
        # reconsider..." cycles at low temperature. max_tokens caps that
        # loop hard so the UI never hangs forever.
        raw, _thinking = llm.chat_stream(
            _SYSTEM_PROMPT,
            user_prompt,
            temperature=0.6,
            max_tokens=4000,
            repeat_penalty=1.15,
            on_open=on_open,
            on_thinking=on_thinking,
            on_content=on_content,
        )
    except LLMError as e:
        diag.log("scheduler ✗ llm error", repr(e))
        raise SchedulerError(f"scheduler LLM call failed: {e}") from e

    try:
        obj = parse_and_validate(raw, ScheduleBundle)
    except LLMRepairError as e:
        # Malformed JSON: the model can usually fix this if we tell it
        # exactly what was wrong, so route through the retry loop rather
        # than failing immediately.
        rj = _PlanRejection(
            f"your previous output could not be parsed as the required JSON "
            f"shape ({e}). Re-emit the JSON object exactly as specified, "
            f"with no prose outside it."
        )
        rj.__cause__ = ValueError(raw[:400])
        raise rj from e

    try:
        start = _parse_local(obj.start, "start", local_tz)
        end = _parse_local(obj.end, "end", local_tz)
    except LLMRepairError as e:
        raise _PlanRejection(
            f"one of your timestamps was not in the required "
            f"'YYYY-MM-DD HH:MM' form: {e}. Emit local wall-clock with no "
            f"timezone offset, no 'Z', and no AM/PM."
        ) from e

    moves_raw = obj.moves
    rationale = obj.rationale.strip() if obj.rationale else ""

    # Hard constraints on the proposed block itself.
    if end <= start:
        raise _PlanRejection(
            f"you proposed end {_fmt_local(end, local_tz)} ≤ start "
            f"{_fmt_local(start, local_tz)}. The end must be strictly after "
            f"the start."
        )
    # The LLM emits minute-precision times; floor `now` to the minute so a
    # proposal at the current minute is not rejected for sub-minute drift.
    now_floor = now.replace(second=0, microsecond=0)
    if start < now_floor:
        raise _PlanRejection(
            f"you proposed start {_fmt_local(start, local_tz)} which is "
            f"before now ({_fmt_local(now, local_tz)}). The start must not "
            f"be before now."
        )
    if end > deadline:
        raise _PlanRejection(
            f"you proposed end {_fmt_local(end, local_tz)} which is past "
            f"the deadline ({_fmt_local(deadline, local_tz)}). The end must "
            f"not be after the deadline."
        )

    # Validate moves: only caden_owned events may be moved, no malformed
    # times, no past-now starts.
    allowed_ids = {e.google_event_id for e in existing_events if e.caden_owned}
    by_id = {e.google_event_id: e for e in existing_events}
    displacements: list[Displacement] = []
    for m in moves_raw:
        gid = m.google_event_id
        if not gid:
            raise _PlanRejection(
                "one of your moves is missing google_event_id. Each move "
                "must reference an existing caden_owned event by its id."
            )
        if gid not in by_id:
            raise _PlanRejection(
                f"you proposed moving {gid!r}, but no event with that id "
                f"exists in the window. You can only move events listed in "
                f"the 'Existing events' block."
            )
        if gid not in allowed_ids:
            raise _PlanRejection(
                f"you proposed moving {gid!r}, which is an external event "
                f"(caden_owned=false). External events MUST NOT be moved. "
                f"Pick a window that does not overlap external events, or "
                f"only move caden_owned events."
            )
        try:
            ns = _parse_local(m.new_start, f"moves[].new_start ({gid})", local_tz)
            ne = _parse_local(m.new_end, f"moves[].new_end ({gid})", local_tz)
        except LLMRepairError as e:
            raise _PlanRejection(
                f"a move timestamp for {gid!r} was malformed: {e}. Use "
                f"'YYYY-MM-DD HH:MM' for every timestamp in moves."
            ) from e
        if ne <= ns:
            raise _PlanRejection(
                f"your move for {gid!r} has new_end "
                f"{_fmt_local(ne, local_tz)} ≤ new_start "
                f"{_fmt_local(ns, local_tz)}."
            )
        if ns < now_floor:
            raise _PlanRejection(
                f"your move for {gid!r} would start "
                f"{_fmt_local(ns, local_tz)}, before now "
                f"({_fmt_local(now, local_tz)}). Moves must not start in "
                f"the past."
            )
        if ne > deadline:
            # Soft: a moved caden_owned block past the deadline is suspect
            # but not strictly forbidden; only the focal task's end is
            # bound by the deadline. Skip — we don't reject on this.
            pass
        displacements.append(Displacement(google_event_id=gid, new_start=ns, new_end=ne))

    # Deterministic conflict detection. This is the core of the
    # belt-and-braces check the LLM does not get to skip:
    #
    #   1. Build the "effective" event timeline = external events as-is +
    #      caden_owned events at their (possibly moved) positions.
    #   2. The proposed block must not overlap any of those.
    #   3. Each move's new position must not overlap an external event,
    #      the proposed task block, or another move.
    #
    # Overlap convention: half-open intervals — [a, b) overlaps [c, d) iff
    # a < d and c < b. Touching at a single instant (a == d) is fine.
    moved_ids = {d.google_event_id for d in displacements}
    move_by_id = {d.google_event_id: d for d in displacements}

    def _overlaps(a_start: datetime, a_end: datetime,
                  b_start: datetime, b_end: datetime) -> bool:
        return a_start < b_end and b_start < a_end

    # Build the effective timeline.
    effective: list[tuple[str, datetime, datetime, bool]] = []  # (label, s, e, is_external)
    for ev in existing_events:
        if ev.caden_owned and ev.google_event_id in moved_ids:
            mv = move_by_id[ev.google_event_id]
            effective.append((
                f"caden_owned {ev.google_event_id!r} (moved to "
                f"{_fmt_local(mv.new_start, local_tz)} → "
                f"{_fmt_local(mv.new_end, local_tz)})",
                mv.new_start, mv.new_end, False,
            ))
        else:
            tag = "external" if not ev.caden_owned else "caden_owned (NOT moved)"
            effective.append((
                f"{tag} {ev.google_event_id!r} "
                f"({ev.summary!r}) "
                f"{_fmt_local(ev.start, local_tz)} → "
                f"{_fmt_local(ev.end, local_tz)}",
                ev.start, ev.end, not ev.caden_owned,
            ))

    # 2. Proposed block vs every effective event.
    for label, es, ee, is_external in effective:
        if _overlaps(start, end, es, ee):
            if is_external:
                raise _PlanRejection(
                    f"your proposed block "
                    f"{_fmt_local(start, local_tz)} → "
                    f"{_fmt_local(end, local_tz)} overlaps the {label}. "
                    f"External events MUST NOT be overlapped. Pick a "
                    f"different window."
                )
            raise _PlanRejection(
                f"your proposed block "
                f"{_fmt_local(start, local_tz)} → "
                f"{_fmt_local(end, local_tz)} overlaps the {label}. "
                f"You may overlap a caden_owned event ONLY if you also move "
                f"it via the 'moves' list. Either include a move for it or "
                f"pick a different window."
            )

    # 3. Each move's new position vs externals, the task block, and other moves.
    for d in displacements:
        for label, es, ee, is_external in effective:
            # Skip the displaced event's own moved entry (that's the move itself).
            if (not is_external) and label.startswith(
                f"caden_owned {d.google_event_id!r} (moved to"
            ):
                continue
            if _overlaps(d.new_start, d.new_end, es, ee):
                if is_external:
                    raise _PlanRejection(
                        f"your move of {d.google_event_id!r} to "
                        f"{_fmt_local(d.new_start, local_tz)} → "
                        f"{_fmt_local(d.new_end, local_tz)} overlaps the "
                        f"{label}. Moved blocks must not land on external "
                        f"events. Pick a different new_start/new_end."
                    )
                # Two caden_owned blocks overlapping each other after moves
                # is also a hard error — pick a different slot.
                raise _PlanRejection(
                    f"your move of {d.google_event_id!r} to "
                    f"{_fmt_local(d.new_start, local_tz)} → "
                    f"{_fmt_local(d.new_end, local_tz)} overlaps the "
                    f"{label}. Move the displaced block to a slot that is "
                    f"actually free."
                )
        if _overlaps(d.new_start, d.new_end, start, end):
            raise _PlanRejection(
                f"your move of {d.google_event_id!r} to "
                f"{_fmt_local(d.new_start, local_tz)} → "
                f"{_fmt_local(d.new_end, local_tz)} overlaps your own "
                f"proposed task block "
                f"{_fmt_local(start, local_tz)} → "
                f"{_fmt_local(end, local_tz)}. The whole point of moving it "
                f"is to free that window — pick a different destination."
            )

    # Duration is end - start by definition. Not an LLM field, not a fallback.
    total_minutes = int(round((end - start).total_seconds() / 60.0))

    chunks = [Chunk(index=0, count=1, start=start, end=end)]
    return SchedulePlan(
        total_minutes=total_minutes,
        chunks=chunks,
        displacements=displacements,
        rationale=rationale,
    )
