"""Configuration loader for CADEN.

Config lives in ``~/.config/caden/settings.toml`` by default, with data in
``~/.local/share/caden/``. Missing files, missing keys, or bad values raise
ConfigError. We do not silently invent operational defaults.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


def _user_home() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))).expanduser()


CONFIG_FILENAME = "settings.toml"
DB_FILENAME = "caden.db"


def _config_dir() -> Path:
    return _user_home() / ".config" / "caden"


def _data_dir() -> Path:
    return _user_home() / ".local" / "share" / "caden"


COMPLETION_POLL_SECONDS = 60
"""How often Google Tasks is polled for completions while CADEN is running."""

FOCAL_TEXT_CHAR_LIMIT = 2000
"""Per-prompt cap on the *focal* item being acted on (the event being rated,
the task description being scheduled / predicted, free-form preferences).
More generous than the per-memory cap because the focal item is the point
of the call, but still bounded so a 20k-char journal entry can't swamp the
model's attention."""

SCHEDULER_MAX_CALENDAR_EVENTS = 40
"""Hard cap on existing calendar events fed into the scheduler prompt. If
the window contains more, fail loudly — past this point the LLM's attention
is so diluted across conflicts that scheduling output is unreliable, and
the right answer is to narrow the window or summarise upstream."""

SCHEDULER_EVENT_SUMMARY_CHAR_LIMIT = 80
"""Per-event cap on the calendar event title shown to the scheduler. Long
meeting titles ('[ACME / Q3 planning] 3-of-7 cross-team sync — ...') waste
tokens; the start/end times and ownership flag are what matters."""

SCHEDULER_MAX_RETRIES = 3
"""How many times to re-prompt the scheduler LLM when its proposal violates
a deterministic constraint (overlap, ordering, forbidden move, malformed
time). Each retry repackages the prior attempt and the precise lesson into
the next prompt. Above this cap we give up and surface SchedulerError."""

STATE_RESIDUAL_WINDOW_MIN = 30
"""How far from a block boundary (start or end) a rating may lie and still
count as "the observed state at that boundary" when computing pre/post
state residuals. Too tight → most boundaries have no nearby rating and
residuals stay NULL forever, starving the learning signal. Too loose →
ratings of unrelated activity get attributed to the wrong block. 30 min
is the current operational window until the learning system can justify
replacing it from data."""


@dataclass(frozen=True)
class Config:
    config_dir: Path
    data_dir: Path
    db_path: Path

    ollama_url: str
    ollama_model: str

    embed_model: str
    embed_dim: int
    searxng_url: str | None

    google_credentials_path: Path
    google_token_path: Path
    google_read_calendar_ids: tuple[str, ...] = ("primary",)
    google_write_calendar_id: str = "primary"
    google_read_task_list_ids: tuple[str, ...] = ("@default",)
    google_write_task_list_id: str = "@default"
    display_tz: str | None = None

    @property
    def scratch_dir(self) -> Path:
        return self.data_dir / "scratch"


def _require(d: dict, key: str, kind: type) -> object:
    if key not in d:
        raise ConfigError(f"settings.toml is missing required key: {key!r}")
    value = d[key]
    if not isinstance(value, kind):
        raise ConfigError(
            f"settings.toml key {key!r} must be {kind.__name__}, got {type(value).__name__}"
        )
    return value


def _require_nested(d: dict, dotted_key: str, kind: type) -> object:
    current: object = d
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ConfigError(f"settings.toml is missing required key: {dotted_key!r}")
        current = current[part]
    if not isinstance(current, kind):
        raise ConfigError(
            f"settings.toml key {dotted_key!r} must be {kind.__name__}, got {type(current).__name__}"
        )
    return current


def load() -> Config:
    config_dir = _config_dir()
    data_dir = _data_dir()
    if not config_dir.exists():
        raise ConfigError(
            f"CADEN config directory does not exist: {config_dir}. "
            f"Create it and add settings.toml. See caden/config.py for the required schema."
        )
    cfg_path = config_dir / CONFIG_FILENAME
    if not cfg_path.is_file():
        raise ConfigError(
            f"Missing config file: {cfg_path}. See caden/config.py for the required schema."
        )
    try:
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"settings.toml is not valid TOML: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("settings.toml must be a TOML table at the top level.")

    ollama_url = str(_require(raw, "ollama_url", str)).rstrip("/")
    ollama_model = str(_require_nested(raw, "llm.model", str))
    embed_model = str(_require(raw, "embed_model", str))
    embed_dim = int(_require(raw, "embed_dim", int))
    if embed_dim <= 0:
        raise ConfigError("embed_dim must be a positive integer")
    searxng_url = raw.get("searxng_url")
    if searxng_url is not None and not isinstance(searxng_url, str):
        raise ConfigError("settings.toml key 'searxng_url' must be str when present")
    if isinstance(searxng_url, str):
        searxng_url = searxng_url.rstrip("/")

    creds = Path(str(_require(raw, "google_credentials_path", str))).expanduser()
    token = Path(str(_require(raw, "google_token_path", str))).expanduser()

    read_calendar_ids_raw = raw.get("google_read_calendar_ids", ["primary"])
    if not isinstance(read_calendar_ids_raw, list) or not all(
        isinstance(v, str) and v.strip() for v in read_calendar_ids_raw
    ):
        raise ConfigError("settings.toml key 'google_read_calendar_ids' must be a list[str] when present")
    read_calendar_ids = tuple(v.strip() for v in read_calendar_ids_raw)

    write_calendar_id_raw = raw.get("google_write_calendar_id", "primary")
    if not isinstance(write_calendar_id_raw, str) or not write_calendar_id_raw.strip():
        raise ConfigError("settings.toml key 'google_write_calendar_id' must be a non-empty str when present")
    write_calendar_id = write_calendar_id_raw.strip()

    read_task_list_ids_raw = raw.get("google_read_task_list_ids", ["@default"])
    if not isinstance(read_task_list_ids_raw, list) or not all(
        isinstance(v, str) and v.strip() for v in read_task_list_ids_raw
    ):
        raise ConfigError("settings.toml key 'google_read_task_list_ids' must be a list[str] when present")
    read_task_list_ids = tuple(v.strip() for v in read_task_list_ids_raw)

    write_task_list_id_raw = raw.get("google_write_task_list_id", "@default")
    if not isinstance(write_task_list_id_raw, str) or not write_task_list_id_raw.strip():
        raise ConfigError("settings.toml key 'google_write_task_list_id' must be a non-empty str when present")
    write_task_list_id = write_task_list_id_raw.strip()

    display_tz = raw.get("display_tz")
    if display_tz is not None and not isinstance(display_tz, str):
        raise ConfigError("settings.toml key 'display_tz' must be str when present")

    return Config(
        config_dir=config_dir,
        data_dir=data_dir,
        db_path=data_dir / DB_FILENAME,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        embed_model=embed_model,
        embed_dim=embed_dim,
        searxng_url=searxng_url,
        google_credentials_path=creds,
        google_token_path=token,
        google_read_calendar_ids=read_calendar_ids,
        google_write_calendar_id=write_calendar_id,
        google_read_task_list_ids=read_task_list_ids,
        google_write_task_list_id=write_task_list_id,
        display_tz=display_tz,
    )

