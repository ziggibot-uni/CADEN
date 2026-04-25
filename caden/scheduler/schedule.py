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
    BOOTSTRAP_DEFAULT_DURATION_MIN,
    BOOTSTRAP_RETRIEVAL_TOP_K,
    BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
    log_bootstrap_use,
)
from ..errors import LLMError, LLMRepairError, SchedulerError
from .. import diag
from ..libbie import retrieve
from ..llm.client import OllamaClient
from ..llm.repair import extract_json, require_fields, require_float


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
  - If you genuinely have nothing to base a duration on, emit null for
    duration_min and the framework will fall back to a bootstrap default.

Return JSON with this exact shape:

{
  "start": "YYYY-MM-DD HH:MM",
  "end":   "YYYY-MM-DD HH:MM",
  "duration_min": number | null,
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
    for e in events:
        tag = "caden_owned" if e.caden_owned else "external"
        lines.append(
            f"- id={e.google_event_id!r} {tag} "
            f"{_fmt_local(e.start, tz)} → {_fmt_local(e.end, tz)}  {e.summary!r}"
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
    on_thinking: Callable[[str], None] | None = None,
    on_content: Callable[[str], None] | None = None,
    on_open: Callable[[], None] | None = None,
) -> SchedulePlan:
    """Ask the LLM where to put this task. Return a SchedulePlan.

    Raises SchedulerError if the LLM violates hard constraints: before-now,
    past deadline, malformed times, or a proposed move of an external event.

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

    user_prompt = (
        f"Sean's timezone: {tz_label}  (all times below are local wall-clock)\n"
        f"Now:           {_fmt_local(now, local_tz)}  ({now.astimezone(local_tz).strftime('%A')})\n"
        f"Deadline:      {_fmt_local(deadline, local_tz)}  ({deadline.astimezone(local_tz).strftime('%A')})\n"
        f"Description:   {description}\n\n"
        f"Existing events between now and deadline:\n{_fmt_events(existing_events, local_tz)}\n\n"
        f"Relevant memory from Libbie:\n{ctx_block}\n\n"
        f"Emit a JSON schedule per the system instructions. "
        f"Use 'YYYY-MM-DD HH:MM' for every timestamp."
    )

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
        obj = extract_json(raw)
        require_fields(obj, ("start", "end", "duration_min", "moves", "rationale"))
        start = _parse_local(obj["start"], "start", local_tz)
        end = _parse_local(obj["end"], "end", local_tz)
        duration_min_raw = require_float(obj, "duration_min", allow_none=True)
        moves_raw = obj["moves"] or []
        if not isinstance(moves_raw, list):
            raise LLMRepairError("moves must be a list")
        rationale = str(obj.get("rationale") or "").strip()
    except LLMRepairError as e:
        raise SchedulerError(f"scheduler output could not be parsed: {e}") from e

    # Hard constraints (loud).
    if end <= start:
        raise SchedulerError(
            f"LLM proposed end ≤ start ({end.isoformat()} ≤ {start.isoformat()})"
        )
    if start < now:
        raise SchedulerError(
            f"LLM proposed start {start.isoformat()} before now {now.isoformat()}"
        )
    if end > deadline:
        raise SchedulerError(
            f"LLM proposed end {end.isoformat()} past deadline {deadline.isoformat()}"
        )

    # Validate moves: only caden_owned events may be moved.
    allowed_ids = {e.google_event_id for e in existing_events if e.caden_owned}
    displacements: list[Displacement] = []
    for m in moves_raw:
        if not isinstance(m, dict):
            raise SchedulerError(f"malformed move entry: {m!r}")
        gid = m.get("google_event_id")
        if not isinstance(gid, str) or not gid:
            raise SchedulerError(f"move is missing google_event_id: {m!r}")
        if gid not in allowed_ids:
            raise SchedulerError(
                f"LLM proposed moving {gid!r}, which is not a CADEN-owned event. "
                f"External events must not be moved."
            )
        ns = _parse_local(m.get("new_start"), f"moves[].new_start ({gid})", local_tz)
        ne = _parse_local(m.get("new_end"), f"moves[].new_end ({gid})", local_tz)
        if ne <= ns:
            raise SchedulerError(f"move for {gid!r} has end ≤ start")
        if ns < now:
            raise SchedulerError(f"move for {gid!r} would start before now")
        displacements.append(Displacement(google_event_id=gid, new_start=ns, new_end=ne))

    duration_min = duration_min_raw
    if duration_min is None:
        log_bootstrap_use(
            conn,
            "BOOTSTRAP_DEFAULT_DURATION_MIN",
            BOOTSTRAP_DEFAULT_DURATION_MIN,
        )
        duration_min = float(BOOTSTRAP_DEFAULT_DURATION_MIN)

    chunks = [Chunk(index=0, count=1, start=start, end=end)]
    return SchedulePlan(
        total_minutes=int(round(duration_min)),
        chunks=chunks,
        displacements=displacements,
        rationale=rationale,
    )
