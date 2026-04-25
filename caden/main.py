"""CADEN entry point. Strict boot sequence per spec.

Every step must succeed or CADEN exits with a readable error. No partial
startup, no silent fallback.
"""

from __future__ import annotations

import sys

from .config import load as load_config
from .errors import CadenError, GoogleSyncError
from .libbie.db import apply_schema, connect
from .llm.client import OllamaClient
from .llm.embed import Embedder
from .ui.app import CadenApp
from .ui.services import Services


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

    # 5. Google OAuth — optional in v0. If credentials file exists we load
    # them; if not, we run chat-only and the dashboard says so. This is the
    # single softening mentioned in spec's v0 scope: chat works before
    # Google is wired up. Everything else remains loud.
    if cfg.google_credentials_path.is_file():
        try:
            from .google_sync.auth import load_credentials
            from .google_sync.calendar import CalendarClient
            from .google_sync.tasks import TasksClient

            creds = load_credentials(cfg.google_credentials_path, cfg.google_token_path)
            services.calendar = CalendarClient(creds)
            services.tasks = TasksClient(creds)
        except GoogleSyncError:
            # loud: propagate — spec forbids silent sync failure
            raise

    return services


def main() -> int:
    try:
        services = _boot()
    except CadenError as e:
        print(f"CADEN boot failed: {e}", file=sys.stderr)
        return 2
    try:
        app = CadenApp(services)
        app.run()
    finally:
        services.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
