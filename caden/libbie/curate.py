"""Libbie context curation.

Single responsibility: produce the LLM-ready *user prompt body* for a chat
turn. Everything CADEN needs to know — Libbie-retrieved memory, in-session
ephemeral context, and the live world (current time, Google Calendar, Google
Tasks) — is assembled here, in one place.

Why this lives in Libbie and not in the chat widget:
  Libbie is the curator of CADEN's knowledge. The chat widget is a transport
  surface (input box + output panel). Splitting "what does CADEN know right
  now" across both means two places to edit when the answer changes. The
  spec's "one central memory" stance applies to packaging too: callers ask
  Libbie for a context bundle and get one, no middlemen.

The live-world part takes Google clients as arguments rather than reaching
out itself — Libbie still does not own Google sessions, but it owns the
*shape* of the bundle and the formatting of every line in it. Failures in
either Google source are surfaced as ``(unavailable: ...)`` lines in the
prompt; this is a curation concern (CADEN must be told the truth about what
he can and cannot see), not a hidden fallback.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from ..errors import GoogleSyncError, LLMError
from . import retrieve


def package_chat_context(
    conn: sqlite3.Connection,
    query_embedding: Sequence[float],
    sources: Sequence[str],
    *,
    recent_exchanges: Iterable[tuple[str, str]] = (),
    calendar=None,
    tasks=None,
) -> str:
    """Return the fully-formed user-prompt body for a chat reply.

    Args:
        conn: open Libbie sqlite connection.
        query_embedding: embedding of Sean's incoming message; drives retrieval.
        sources: which event sources retrieval is allowed to draw from.
        recent_exchanges: in-session (sean_text, caden_reply) pairs to include
            as ephemeral context. Never persisted; never embedded. Spec rule:
            CADEN's responses are not stored as events.
        calendar: optional google_sync CalendarClient. None means sync isn't
            configured; the prompt will say so.
        tasks: optional google_sync TasksClient. Same.

    Returns:
        A single string ready to be concatenated with the trailing
        "Sean just said: …\\n\\nReply." segment by the caller.

    Raises:
        LLMError: if retrieval returned a non-empty result that is still
            below ``BOOTSTRAP_RETRIEVAL_MIN_K`` after filtering. Per spec,
            falling under the floor means the index is too thin and the
            right answer is to fix retrieval, not silently drop signal.
    """
    # Let the LLM see up to 15 memories, so it has to grapple with noise and
    # make bad calls, generating residuals we can learn from. No more
    # hard minimums.
    neighbours = retrieve.search(
        conn,
        query_embedding,
        30, # A dynamic cap rather than a rigid bootstrap limit 
        sources,
    )
    
    # We pass the full retrieved texts rather than rigidly truncating. 
    # The LLM will see real event sizes (which might be long unless the 
    # length bias in retrieval pushes shorter lessons to the top).
    
    memory_lines: list[str] = [
        f"- [{r.event.timestamp} / {r.event.source}] {r.event.raw_text}"
        for r in neighbours
    ] or ["(no prior memory yet)"]

    exchanges = list(recent_exchanges)
    thread_lines = []
    if exchanges:
        for prior_user, prior_reply in exchanges:
            # We don't artificially truncate the thread; it's the live context.
            thread_lines.append(f"sean: {prior_user}")
            thread_lines.append(f"caden: {prior_reply}")
        thread_lines.append("")

    live_lines = _live_world_lines(calendar, tasks)

    # PAST/NOW/THREAD framing places the live conversation front and center.
    # The current thread is the "spine", not a footnote.
    return (
        "THREAD — the current live conversation. This is what you are responding to right now:\n"
        + ("\n".join(thread_lines) if thread_lines else "(no prior messages in this session yet)\n")
        + "\n\nPAST — background memory Libbie retrieved. Each entry is a "
        "snapshot of a moment that has ALREADY HAPPENED. The bracketed "
        "timestamp is when it happened; compare against 'now:' in the NOW "
        "block below to see how long ago. Do not treat these as describing "
        "what is true right now unless NOW confirms it.\n"
        + "\n".join(memory_lines)
        + "\n\nNOW — Sean's actual current reality, pulled live from his "
        "Google account at the start of this turn:\n"
        + "\n".join(live_lines)
    )


def _live_world_lines(calendar, tasks) -> list[str]:
    """Render the live-world block.

    Google read failures are surfaced as ``(unavailable: ...)`` lines so
    CADEN can be honest about partial visibility instead of silently
    pretending sync is fine. The chat handler remains the loud-failure
    boundary for retrieval, the LLM, embedding, and the DB; only the
    documented ``GoogleSyncError`` is caught here, nothing broader.
    """
    now_local = datetime.now().astimezone()
    lines: list[str] = [
        f"- now: {now_local.strftime('%a %b %d %Y, %-I:%M %p %Z').strip()}"
    ]

    if calendar is None:
        lines.append("- calendar: (Google sync not configured)")
    else:
        try:
            start = now_local
            end = start.replace(hour=23, minute=59, second=59, microsecond=0)
            if end <= start:
                end = start + timedelta(hours=12)
            events = calendar.list_window(start, end)
        except GoogleSyncError as e:
            lines.append(f"- calendar: (unavailable: {e})")
        else:
            if not events:
                lines.append("- calendar (rest of today): (nothing scheduled)")
            else:
                lines.append("- calendar (rest of today):")
                for ev in events[:20]:
                    s = ev.start.astimezone().strftime('%-I:%M %p')
                    e2 = ev.end.astimezone().strftime('%-I:%M %p')
                    lines.append(f"    • {s}–{e2}  {ev.summary}")

    if tasks is None:
        lines.append("- tasks: (Google sync not configured)")
    else:
        try:
            open_tasks = tasks.list_open()
        except GoogleSyncError as e:
            lines.append(f"- tasks: (unavailable: {e})")
        else:
            if not open_tasks:
                lines.append("- open tasks: (none)")
            else:
                lines.append("- open tasks:")
                for t in open_tasks[:20]:
                    due = (
                        t.due.astimezone().strftime('%a %b %-d')
                        if t.due else "no due date"
                    )
                    lines.append(f"    • {t.title}  (due {due})")

    return lines
