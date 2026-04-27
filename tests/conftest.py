import os
import pytest

from caden.config import Config, load
from caden.libbie.db import connect, apply_schema
from caden.llm.client import OllamaClient
from caden.llm.embed import Embedder
from caden.ui.services import Services

@pytest.fixture
def tmp_caden_home(tmp_path, monkeypatch):
    monkeypatch.delenv("CADEN_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    config_dir = tmp_path / ".config" / "caden"
    data_dir = tmp_path / ".local" / "share" / "caden"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    cfg_file = config_dir / "settings.toml"
    cfg_file.write_text(
        """
ollama_url = "http://127.0.0.1:11434"
embed_model = "nomic-embed-text"
embed_dim = 768
google_credentials_path = "~/.config/caden/google_credentials.json"
google_token_path = "~/.config/caden/google_token.json"

[llm]
model = "llama3.1:8b"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    yield tmp_path

@pytest.fixture
def db_conn(tmp_caden_home):
    db_path = load().db_path
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
