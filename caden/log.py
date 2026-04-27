"""Structured logging configuration for CADEN.

Per spec: log lines are written as JSON lines to ~/.local/share/caden/logs/caden.log.
They are also emitted as 'caden_log' events into the memory store.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, MutableMapping

import structlog


def make_libbie_event_sink(conn, embedder=None) -> Callable[[MutableMapping[str, Any]], None]:
    """Build a sink that mirrors log lines into Libbie as `caden_log` events."""
    from .libbie.store import write_event

    def _sink(event_dict: MutableMapping[str, Any]) -> None:
        try:
            raw_text = str(event_dict.get("event") or "")
            meta = {
                "priority": "low",
                **{
                    key: value
                    for key, value in event_dict.items()
                    if key != "event"
                },
            }
            embedding = embedder.embed(raw_text) if (embedder is not None and raw_text) else None
            write_event(
                conn,
                source="caden_log",
                raw_text=raw_text,
                embedding=embedding,
                meta=meta,
            )
        except Exception:
            return

    return _sink


def setup_logging(
    log_dir: Path,
    log_level: str = "INFO",
    *,
    event_sink: Callable[[MutableMapping[str, Any]], None] | None = None,
):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "caden.log"

    level = getattr(logging, log_level.upper(), logging.INFO)

    def _emit_sink(_logger, _method_name: str, event_dict: MutableMapping[str, Any]):
        if event_sink is not None:
            event_sink(dict(event_dict))
        return event_dict

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _emit_sink,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stderr)
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(),
        ],
    )
    console_handler.setFormatter(console_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    # root_logger.addHandler(console_handler) # UI handles console mostly, but we can log to stderr before UI starts

    return structlog.get_logger()
