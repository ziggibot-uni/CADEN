import os
import json
import sqlite3
import pytest
from pathlib import Path

from caden.config import Config, load
from caden.libbie.db import connect, apply_schema
from caden.llm.client import OllamaClient
from caden.llm.embed import Embedder
from caden.ui.services import Services

@pytest.fixture
def tmp_caden_home(tmp_path):
    os.environ["CADEN_HOME"] = str(tmp_path)
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_model": "llama3.1:8b",
        "embed_model": "nomic-embed-text",
        "embed_dim": 768,
        "google_credentials_path": str(tmp_path / "google_credentials.json"),
        "google_token_path": str(tmp_path / "google_token.json")
    }))
    yield tmp_path
    if "CADEN_HOME" in os.environ:
        del os.environ["CADEN_HOME"]

@pytest.fixture
def db_conn(tmp_caden_home):
    db_path = tmp_caden_home / "caden.sqlite3"
    conn = connect(db_path)
    apply_schema(conn, embed_dim=768)
    yield conn
    conn.close()

@pytest.fixture
def mock_services(tmp_caden_home, db_conn, monkeypatch):
    class MockEmbedder:
        def embed(self, text):
            return [0.1] * 768
        def close(self):
            pass

    class MockOllama:
        def chat_stream(self, system, user, **kwargs):
            return "Mock response", ""
        def close(self):
            pass

    cfg = load()
    svcs = Services(
        config=cfg,
        conn=db_conn,
        llm=MockOllama(),
        embedder=MockEmbedder()
    )
    yield svcs
    svcs.close()
