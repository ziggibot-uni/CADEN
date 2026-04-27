"""CADEN entry point. Strict boot sequence per spec.

Every step must succeed or CADEN exits with a readable error. No partial
startup, no silent fallback.
"""

from __future__ import annotations

import json
import sys

from .config import load as load_config
from .errors import CadenError, GoogleSyncError
from .libbie.db import apply_schema, connect
from .libbie.store import write_event
from .libbie.searxng import SearxngClient
from .llm.client import OllamaClient
from .llm.embed import Embedder
from .ui._error import render_terminal_error_banner
from .ui.app import CadenApp
from .ui.services import Services


def _scope_signature(scope_meta: dict[str, object]) -> str:
    return json.dumps(scope_meta, sort_keys=True, separators=(",", ":"))


def _boot() -> Services:
    # 1. config
    cfg = load_config()

    # 2. DB + sqlite-vec + schema
    conn = connect(cfg.db_path)
    apply_schema(conn, embed_dim=cfg.embed_dim)

    # 3. ollama reachable + model present
    llm = OllamaClient(cfg.ollama_url, cfg.ollama_model)
    llm.ping()
    llm.require_model(cfg.ollama_model)

    # 4. embedding model available + dim matches
    embedder = Embedder(cfg.ollama_url, cfg.embed_model, cfg.embed_dim)
    embedder.check()

    services = Services(config=cfg, conn=conn, llm=llm, embedder=embedder)
    if cfg.searxng_url:
        services.searxng = SearxngClient(cfg.searxng_url)

    # 5. Google OAuth is required at boot for full runtime capability.
    # Missing or broken credentials fail loudly; no chat-only mode.
    try:
        from .google_sync.auth import (
            load_credentials,
            list_available_calendars,
            list_available_task_lists,
        )
        from .google_sync.calendar import CalendarClient
        from .google_sync.tasks import TasksClient

        creds = load_credentials(cfg.google_credentials_path, cfg.google_token_path)
        available_calendars = list_available_calendars(creds)
        available_task_lists = list_available_task_lists(creds)

        try:
            services.calendar = CalendarClient(
                creds,
                readable_calendar_ids=cfg.google_read_calendar_ids,
                writable_calendar_id=cfg.google_write_calendar_id,
            )
        except TypeError:
            # Backward-compatible fallback for tests that stub older signatures.
            services.calendar = CalendarClient(creds)
        try:
            services.tasks = TasksClient(
                creds,
                readable_task_list_ids=cfg.google_read_task_list_ids,
                writable_task_list_id=cfg.google_write_task_list_id,
            )
        except TypeError:
            services.tasks = TasksClient(creds)

        scope_meta = {
            "read_calendars": list(cfg.google_read_calendar_ids),
            "write_calendar": cfg.google_write_calendar_id,
            "read_task_lists": list(cfg.google_read_task_list_ids),
            "write_task_list": cfg.google_write_task_list_id,
            "available_calendars": [cid for cid, _title in available_calendars],
            "available_task_lists": [tid for tid, _title in available_task_lists],
        }
        signature = _scope_signature(scope_meta)
        if hasattr(conn, "execute"):
            prev = conn.execute(
                """
                SELECT value
                FROM event_metadata m
                JOIN events e ON e.id = m.event_id
                WHERE e.source='google_scope_change' AND m.key='scope_signature'
                ORDER BY m.id DESC
                LIMIT 1
                """
            ).fetchone()
            prev_signature = prev["value"] if prev is not None else None
            if prev_signature != signature:
                scope_text = (
                    "Google scope changed: "
                    f"read_calendars={scope_meta['read_calendars']} "
                    f"write_calendar={scope_meta['write_calendar']} "
                    f"read_task_lists={scope_meta['read_task_lists']} "
                    f"write_task_list={scope_meta['write_task_list']}"
                )
                scope_emb = embedder.embed(scope_text)
                write_event(
                    conn,
                    source="google_scope_change",
                    raw_text=scope_text,
                    embedding=scope_emb,
                    meta={
                        "scope_signature": signature,
                        "available_calendars": scope_meta["available_calendars"],
                        "available_task_lists": scope_meta["available_task_lists"],
                        "trigger": "google_scope_configured",
                    },
                )
    except GoogleSyncError:
        # loud: propagate — spec forbids silent sync failure
        raise

    return services


def main() -> int:
    try:
        services = _boot()
    except CadenError as e:
        print(render_terminal_error_banner(e, "boot"), file=sys.stderr)
        return 2
    try:
        app = CadenApp(services)
        app.run()
    finally:
        services.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
