"""Services bundle — what the UI needs in hand to do anything.

Grouping these avoids passing five arguments to every widget. The bundle is
built once by main.py's boot sequence and handed to the Textual app.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..config import Config
from ..libbie.store import close_write_queue
from ..llm.client import OllamaClient
from ..llm.embed import Embedder


@dataclass
class Services:
    config: Config
    conn: sqlite3.Connection
    llm: OllamaClient
    embedder: Embedder
    searxng: object | None = None
    # Google pieces are optional at v0 — main.py sets them when sync is live.
    calendar: object | None = None   # CalendarClient
    tasks: object | None = None      # TasksClient

    def close(self) -> None:
        try:
            if self.searxng is not None:
                self.searxng.close()
        finally:
            try:
                self.llm.close()
            finally:
                try:
                    self.embedder.close()
                finally:
                    close_write_queue(self.conn)
                    self.conn.close()
