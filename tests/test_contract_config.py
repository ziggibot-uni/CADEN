import tomllib

import pytest

from caden.config import load
from caden.errors import ConfigError, EmbedError
from caden.llm.embed import Embedder


def test_config_uses_documented_settings_and_data_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("CADEN_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    config_dir = tmp_path / ".config" / "caden"
    data_dir = tmp_path / ".local" / "share" / "caden"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (config_dir / "settings.toml").write_text(
        """
ollama_url = "http://127.0.0.1:11434"
embed_model = "nomic-embed-text"
embed_dim = 768
searxng_url = "http://127.0.0.1:8080"
display_tz = "America/Chicago"
google_credentials_path = "~/.config/caden/google_credentials.json"
google_token_path = "~/.config/caden/google_token.json"
google_read_calendar_ids = ["primary", "team-calendar@example.com"]
google_write_calendar_id = "primary"
google_read_task_list_ids = ["@default", "project-list-id"]
google_write_task_list_id = "@default"

[llm]
model = "llama3.1:8b"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    cfg = load()

    assert cfg.db_path == data_dir / "caden.db"
    assert cfg.scratch_dir == data_dir / "scratch"
    assert cfg.ollama_model == "llama3.1:8b"
    assert cfg.embed_model == "nomic-embed-text"
    assert cfg.embed_dim == 768
    assert cfg.searxng_url == "http://127.0.0.1:8080"
    assert cfg.google_credentials_path == config_dir / "google_credentials.json"
    assert cfg.google_token_path == config_dir / "google_token.json"
    assert cfg.google_read_calendar_ids == ("primary", "team-calendar@example.com")
    assert cfg.google_write_calendar_id == "primary"
    assert cfg.google_read_task_list_ids == ("@default", "project-list-id")
    assert cfg.google_write_task_list_id == "@default"
    assert cfg.display_tz == "America/Chicago"


def test_embedder_check_fails_loudly_on_dimension_mismatch(httpx_mock):
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/embeddings",
        json={"embedding": [0.1] * 32},
    )

    embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)
    try:
        with pytest.raises(EmbedError, match="embedding dim mismatch"):
            embedder.check()
    finally:
        embedder.close()


def test_config_invalid_toml_preserves_original_parse_error(tmp_path, monkeypatch):
    monkeypatch.delenv("CADEN_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    config_dir = tmp_path / ".config" / "caden"
    data_dir = tmp_path / ".local" / "share" / "caden"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (config_dir / "settings.toml").write_text(
        "ollama_url = 'http://127.0.0.1:11434'\n[llm\nmodel = 'llama3.1:8b'\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="settings.toml is not valid TOML") as exc_info:
        load()

    assert isinstance(exc_info.value.__cause__, tomllib.TOMLDecodeError)
