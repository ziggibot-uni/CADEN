"""Configuration loader for CADEN.

Config lives in a single JSON file at ``$CADEN_HOME/config.json`` (or
``~/.caden/config.json`` by default). Missing files, missing keys, or
bad values raise ConfigError. We do not fall back to "reasonable defaults"
for things the user is supposed to have set — that would be a silent
fallback, which the spec forbids.

A minimal valid config.json looks like:

    {
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_model": "llama3.1:8b",
        "embed_model": "nomic-embed-text",
        "embed_dim": 768,
        "google_credentials_path": "~/.caden/google_credentials.json",
        "google_token_path": "~/.caden/google_token.json"
    }
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

DEFAULT_HOME = Path.home() / ".caden"
CONFIG_FILENAME = "config.json"
DB_FILENAME = "caden.sqlite3"


# ---- Bootstrap values (per CADEN_v0.md "Bootstrap values" section) -----------
#
# These are GATES, not rules: numbers that must exist before learning can kick
# in. Each is logged as an event the first time it is used (source =
# "bootstrap_value_used"). Learning is required to override them once there is
# enough data. None of them encodes a belief about Sean specifically; they are
# all about "data must exist before math can run."

BOOTSTRAP_COMPLETION_POLL_SECONDS = 60
"""How often Google Tasks is polled for completions while CADEN is running."""

BOOTSTRAP_PROMPT_TOKEN_BUDGET = 6000
"""Soft cap on total prompt tokens; retrieval is truncated to fit."""

BOOTSTRAP_RETRIEVAL_TOP_K = 20
"""How many memories Libbie returns per retrieval call (combined-score top-K)."""

BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS = 500
"""Per-memory raw_text cap when building a prompt context block."""

BOOTSTRAP_RETRIEVAL_MIN_K = 5
"""If truncation would drop retrieval below this, fail loudly (LLMError)."""

BOOTSTRAP_FOCAL_TEXT_TRUNCATE_CHARS = 2000
"""Per-prompt cap on the *focal* item being acted on (the event being rated,
the task description being scheduled / predicted, free-form preferences).
More generous than the per-memory cap because the focal item is the point
of the call, but still bounded so a 20k-char journal entry can't swamp the
model's attention."""

BOOTSTRAP_SCHEDULER_MAX_CALENDAR_EVENTS = 40
"""Hard cap on existing calendar events fed into the scheduler prompt. If
the window contains more, fail loudly — past this point the LLM's attention
is so diluted across conflicts that scheduling output is unreliable, and
the right answer is to narrow the window or summarise upstream."""

BOOTSTRAP_SCHEDULER_EVENT_SUMMARY_CHARS = 80
"""Per-event cap on the calendar event title shown to the scheduler. Long
meeting titles ('[ACME / Q3 planning] 3-of-7 cross-team sync — ...') waste
tokens; the start/end times and ownership flag are what matters."""

BOOTSTRAP_SCHEDULER_MAX_RETRIES = 3
"""How many times to re-prompt the scheduler LLM when its proposal violates
a deterministic constraint (overlap, ordering, forbidden move, malformed
time). Each retry repackages the prior attempt and the precise lesson into
the next prompt. Above this cap we give up and surface SchedulerError."""

BOOTSTRAP_STATE_RESIDUAL_WINDOW_MIN = 30
"""How far from a block boundary (start or end) a rating may lie and still
count as "the observed state at that boundary" when computing pre/post
state residuals. Too tight → most boundaries have no nearby rating and
residuals stay NULL forever, starving the learning signal. Too loose →
ratings of unrelated activity get attributed to the wrong block. 30 min
is the bootstrap; the learning system replaces it once residual density
is high enough to fit a window per axis from the data."""


@dataclass(frozen=True)
class Config:
    home: Path
    db_path: Path

    ollama_url: str
    ollama_model: str

    embed_model: str
    embed_dim: int

    google_credentials_path: Path
    google_token_path: Path


def _home() -> Path:
    override = os.environ.get("CADEN_HOME")
    return Path(override).expanduser() if override else DEFAULT_HOME


def _require(d: dict, key: str, kind: type) -> object:
    if key not in d:
        raise ConfigError(f"config.json is missing required key: {key!r}")
    value = d[key]
    if not isinstance(value, kind):
        raise ConfigError(
            f"config.json key {key!r} must be {kind.__name__}, got {type(value).__name__}"
        )
    return value


def load() -> Config:
    home = _home()
    if not home.exists():
        raise ConfigError(
            f"CADEN home directory does not exist: {home}. "
            f"Create it and add config.json. See caden/config.py for the required schema."
        )
    cfg_path = home / CONFIG_FILENAME
    if not cfg_path.is_file():
        raise ConfigError(
            f"Missing config file: {cfg_path}. See caden/config.py for the required schema."
        )
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"config.json is not valid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("config.json must be a JSON object at the top level.")

    ollama_url = str(_require(raw, "ollama_url", str)).rstrip("/")
    ollama_model = str(_require(raw, "ollama_model", str))
    embed_model = str(_require(raw, "embed_model", str))
    embed_dim = int(_require(raw, "embed_dim", int))
    if embed_dim <= 0:
        raise ConfigError("embed_dim must be a positive integer")

    creds = Path(str(_require(raw, "google_credentials_path", str))).expanduser()
    token = Path(str(_require(raw, "google_token_path", str))).expanduser()

    return Config(
        home=home,
        db_path=home / DB_FILENAME,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        embed_model=embed_model,
        embed_dim=embed_dim,
        google_credentials_path=creds,
        google_token_path=token,
    )


# ---- Bootstrap first-use log -------------------------------------------------
# Set of bootstrap names already logged this process. The first time a
# bootstrap is consulted we write an event documenting its value, so CADEN can
# later audit "what gates were active when I was behaving this way?".

_BOOTSTRAPS_LOGGED: set[str] = set()


def log_bootstrap_use(conn, name: str, value: object) -> None:
    """Write a 'bootstrap_value_used' event the first time `name` is used.

    Idempotent within a process. Does not embed — the value is structural,
    not semantic, so retrieval over it by similarity would be noise.
    """
    if name in _BOOTSTRAPS_LOGGED:
        return
    _BOOTSTRAPS_LOGGED.add(name)
    # Local import to avoid import cycle with libbie.
    from .libbie.store import write_event
    try:
        write_event(
            conn,
            source="bootstrap_value_used",
            raw_text=f"bootstrap {name} = {value!r}",
            embedding=None,
            meta={"name": name, "value": value},
        )
    except Exception:  # noqa: BLE001
        # If the DB isn't ready we don't want boot to die for a log row;
        # but we also don't silently swallow — re-mark so we retry.
        _BOOTSTRAPS_LOGGED.discard(name)
        raise
