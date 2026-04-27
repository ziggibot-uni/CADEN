"""Deterministic time-format normalisation for CADEN's chat output.

Sean reads chat in 12-hour AM/PM. The LLM happily mixes 24-hour ('14:30'),
ISO ('2026-04-25T14:30'), and bare 12-hour ('2:30') in the same paragraph.
We post-process every chat reply with ``to_12hr`` to remove that drift.

Rules — chosen for determinism, not cleverness:

  - Hour 0      → "12:MM AM"   (unambiguously 24-hour midnight hour)
  - Hour 13–23  → "{h-12}:MM PM"   (unambiguously 24-hour afternoon)
  - Hour 1–12   → LEFT ALONE   (ambiguous between 12-hour and 24-hour;
                                we will not invent a meridiem we cannot
                                prove. The system prompt instead asks the
                                model to always include AM or PM itself.)

  - Already-meridiemed times ("2:30 PM", "9am", "11:00 a.m.") are left
    alone via a negative lookahead.
  - Seconds, when present, are dropped from the rendered form. Sean wants
    to read the time, not stopwatch it.
  - Surrounding context (ISO 'T' separator, dashes in ranges, etc.) is
    preserved by only rewriting the HH:MM[:SS] span.

This module is chat-only. The scheduler, predictor, and any other path
that needs machine-readable timestamps MUST NOT use this — they want
ISO / canonical formats so the repair layer can parse them.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_DISPLAY_TZ = "America/Detroit"

# Pattern walks left-to-right, matching:
#   (?<!\d)            no digit immediately before  → blocks "1234:56"
#   (\d{1,2})          hour, validated in code below
#   :(\d{2})           minute (2 digits)
#   (?::\d{2})?        optional :SS, dropped from output
#   (?!\s*[AaPp]\.?[Mm]\.?)   not already followed by am/pm
#   (?!\d)             not followed by another digit (avoids weird IDs)
#
# The hour range filter (0, 13–23) is enforced in the substitution
# function rather than the regex, so that ambiguous matches still get
# captured for inspection but not rewritten.
_TIME_RE = re.compile(
    r"(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?(?!\s*[AaPp]\.?[Mm]\.?)(?!\d)"
)


def _convert(match: re.Match[str]) -> str:
    hour = int(match.group(1))
    minute = match.group(2)  # already 2 digits, keep as string
    if hour == 0:
        return f"12:{minute} AM"
    if 13 <= hour <= 23:
        return f"{hour - 12}:{minute} PM"
    # Ambiguous (1–12) — leave the original span untouched.
    return match.group(0)


def to_12hr(text: str) -> str:
    """Return ``text`` with every unambiguous 24-hour time rewritten as 12-hour AM/PM.

    Idempotent: running it twice produces the same output as running it
    once (the negative lookahead rejects already-converted spans).
    """
    if not text:
        return text
    return _TIME_RE.sub(_convert, text)


def resolve_display_tz(tz_name: str | None = None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or DEFAULT_DISPLAY_TZ)
    except ZoneInfoNotFoundError as e:
        raise ValueError(f"unknown display timezone: {tz_name!r}") from e


def format_display_time(
    when: datetime,
    *,
    tz_name: str | None = None,
    include_weekday: bool = False,
) -> str:
    target = when.astimezone(resolve_display_tz(tz_name))
    fmt = "%a %-I:%M %p" if include_weekday else "%-I:%M %p"
    return target.strftime(fmt).lower()
