from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from caden.config import Config
from caden.errors import ConfigError, DBError, EmbedError, GoogleSyncError, LLMError
from caden import main


def _cfg(tmp_path: Path, *, creds_exists: bool = False) -> Config:
    config_dir = tmp_path / ".config" / "caden"
    data_dir = tmp_path / ".local" / "share" / "caden"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    creds = config_dir / "google_credentials.json"
    token = config_dir / "google_token.json"
    if creds_exists:
        creds.write_text("{}", encoding="utf-8")
    return Config(
        config_dir=config_dir,
        data_dir=data_dir,
        db_path=data_dir / "caden.db",
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3.1:8b",
        embed_model="nomic-embed-text",
        embed_dim=768,
        searxng_url=None,
        google_credentials_path=creds,
        google_token_path=token,
        display_tz=None,
    )


def test_boot_runs_prerequisites_in_documented_order_then_fails_loudly_without_google_credentials(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, creds_exists=False)
    calls: list[tuple[str, object | None]] = []
    conn = SimpleNamespace(close=lambda: None)

    class FakeLLM:
        def __init__(self, base_url: str, model: str) -> None:
            calls.append(("llm_init", (base_url, model)))

        def ping(self) -> None:
            calls.append(("ping", None))

        def require_model(self, model: str) -> None:
            calls.append(("require_model", model))

        def close(self) -> None:
            return None

    class FakeEmbedder:
        def __init__(self, base_url: str, model: str, dim: int) -> None:
            calls.append(("embed_init", (base_url, model, dim)))

        def check(self) -> None:
            calls.append(("embed_check", None))

        def close(self) -> None:
            return None

    monkeypatch.setattr(main, "load_config", lambda: calls.append(("config", None)) or cfg)
    monkeypatch.setattr(main, "connect", lambda path: calls.append(("connect", path)) or conn)
    monkeypatch.setattr(
        main,
        "apply_schema",
        lambda connection, embed_dim: calls.append(("schema", (connection, embed_dim))),
    )
    monkeypatch.setattr(main, "OllamaClient", FakeLLM)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)

    with pytest.raises(GoogleSyncError, match="Google OAuth client JSON not found"):
        main._boot()

    assert [name for name, _ in calls] == [
        "config",
        "connect",
        "schema",
        "llm_init",
        "ping",
        "require_model",
        "embed_init",
        "embed_check",
    ]


def test_boot_loads_google_clients_when_credentials_exist(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, creds_exists=True)
    conn = SimpleNamespace(close=lambda: None)
    creds = object()

    class FakeLLM:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def ping(self) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def check(self) -> None:
            return None

        def close(self) -> None:
            return None

    auth_module = ModuleType("caden.google_sync.auth")
    auth_module.load_credentials = lambda credentials_path, token_path: creds
    auth_module.list_available_calendars = lambda loaded_creds: [("primary", "Primary")]
    auth_module.list_available_task_lists = lambda loaded_creds: [("@default", "Tasks")]
    calendar_module = ModuleType("caden.google_sync.calendar")
    calendar_module.CalendarClient = lambda loaded_creds: ("calendar", loaded_creds)
    tasks_module = ModuleType("caden.google_sync.tasks")
    tasks_module.TasksClient = lambda loaded_creds: ("tasks", loaded_creds)

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "connect", lambda path: conn)
    monkeypatch.setattr(main, "apply_schema", lambda connection, embed_dim: None)
    monkeypatch.setattr(main, "OllamaClient", FakeLLM)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)
    monkeypatch.setitem(sys.modules, "caden.google_sync.auth", auth_module)
    monkeypatch.setitem(sys.modules, "caden.google_sync.calendar", calendar_module)
    monkeypatch.setitem(sys.modules, "caden.google_sync.tasks", tasks_module)

    services = main._boot()

    assert services.calendar == ("calendar", creds)
    assert services.tasks == ("tasks", creds)


def test_boot_raises_loudly_when_google_credentials_exist_but_loading_fails(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, creds_exists=True)
    conn = SimpleNamespace(close=lambda: None)

    class FakeLLM:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def ping(self) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def check(self) -> None:
            return None

        def close(self) -> None:
            return None

    auth_module = ModuleType("caden.google_sync.auth")

    def _fail_load(credentials_path, token_path):
        raise GoogleSyncError("oauth refresh failed")

    auth_module.load_credentials = _fail_load
    auth_module.list_available_calendars = lambda loaded_creds: [("primary", "Primary")]
    auth_module.list_available_task_lists = lambda loaded_creds: [("@default", "Tasks")]
    calendar_module = ModuleType("caden.google_sync.calendar")
    calendar_module.CalendarClient = lambda loaded_creds: loaded_creds
    tasks_module = ModuleType("caden.google_sync.tasks")
    tasks_module.TasksClient = lambda loaded_creds: loaded_creds

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "connect", lambda path: conn)
    monkeypatch.setattr(main, "apply_schema", lambda connection, embed_dim: None)
    monkeypatch.setattr(main, "OllamaClient", FakeLLM)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)
    monkeypatch.setitem(sys.modules, "caden.google_sync.auth", auth_module)
    monkeypatch.setitem(sys.modules, "caden.google_sync.calendar", calendar_module)
    monkeypatch.setitem(sys.modules, "caden.google_sync.tasks", tasks_module)

    try:
        main._boot()
        assert False, "expected GoogleSyncError"
    except GoogleSyncError as exc:
        assert str(exc) == "oauth refresh failed"


def test_main_launches_textual_app_only_after_boot_and_closes_services(monkeypatch):
    calls: list[str] = []

    class FakeServices:
        def close(self) -> None:
            calls.append("close")

    class FakeApp:
        def __init__(self, services) -> None:
            assert calls == ["boot"]
            calls.append("app_init")

        def run(self) -> None:
            calls.append("run")

    monkeypatch.setattr(main, "_boot", lambda: calls.append("boot") or FakeServices())
    monkeypatch.setattr(main, "CadenApp", FakeApp)

    code = main.main()

    assert code == 0
    assert calls == ["boot", "app_init", "run", "close"]


def test_main_returns_nonzero_and_prints_boot_failure(monkeypatch, capsys):
    monkeypatch.setattr(main, "_boot", lambda: (_ for _ in ()).throw(ConfigError("bad config")))

    code = main.main()

    captured = capsys.readouterr()
    assert code == 2
    assert "Subsystem Failed: boot" in captured.err
    assert "bad config" in captured.err


def test_main_boot_failure_uses_shared_error_banner_formatter(monkeypatch, capsys):
    monkeypatch.setattr(main, "_boot", lambda: (_ for _ in ()).throw(ConfigError("boom")))
    monkeypatch.setattr(
        main,
        "render_terminal_error_banner",
        lambda exception, context: f"BANNER[{context}]::{exception}",
    )

    code = main.main()

    captured = capsys.readouterr()
    assert code == 2
    assert "BANNER[boot]::boom" in captured.err


def test_boot_fails_loudly_when_ollama_is_unreachable(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, creds_exists=False)
    conn = SimpleNamespace(close=lambda: None)

    class FakeLLM:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def ping(self) -> None:
            raise LLMError("ollama unreachable")

        def require_model(self, model: str) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def check(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "connect", lambda path: conn)
    monkeypatch.setattr(main, "apply_schema", lambda connection, embed_dim: None)
    monkeypatch.setattr(main, "OllamaClient", FakeLLM)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)

    with pytest.raises(LLMError, match="ollama unreachable"):
        main._boot()


def test_boot_fails_loudly_when_db_or_schema_setup_fails(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, creds_exists=False)

    class FakeLLM:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def ping(self) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def check(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "connect", lambda path: (_ for _ in ()).throw(DBError("db corrupted")))
    monkeypatch.setattr(main, "OllamaClient", FakeLLM)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)

    with pytest.raises(DBError, match="db corrupted"):
        main._boot()


def test_boot_fails_loudly_when_embedding_model_is_unavailable(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, creds_exists=False)
    conn = SimpleNamespace(close=lambda: None)

    class FakeLLM:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def ping(self) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def check(self) -> None:
            raise EmbedError("embedding model missing")

        def close(self) -> None:
            return None

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "connect", lambda path: conn)
    monkeypatch.setattr(main, "apply_schema", lambda connection, embed_dim: None)
    monkeypatch.setattr(main, "OllamaClient", FakeLLM)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)

    with pytest.raises(EmbedError, match="embedding model missing"):
        main._boot()


def test_boot_persists_google_scope_change_as_event(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, creds_exists=True)
    from caden.libbie.db import apply_schema as real_apply_schema
    from caden.libbie.db import connect as real_connect

    conn = real_connect(cfg.db_path)
    real_apply_schema(conn, embed_dim=768)

    class FakeLLM:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def ping(self) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def check(self) -> None:
            return None

        def embed(self, text: str):
            return [0.1] * 768

        def close(self) -> None:
            return None

    auth_module = ModuleType("caden.google_sync.auth")
    auth_module.load_credentials = lambda credentials_path, token_path: object()
    auth_module.list_available_calendars = lambda loaded_creds: [("primary", "Primary")]
    auth_module.list_available_task_lists = lambda loaded_creds: [("@default", "Tasks")]
    calendar_module = ModuleType("caden.google_sync.calendar")
    calendar_module.CalendarClient = lambda loaded_creds, **kwargs: ("calendar", loaded_creds, kwargs)
    tasks_module = ModuleType("caden.google_sync.tasks")
    tasks_module.TasksClient = lambda loaded_creds, **kwargs: ("tasks", loaded_creds, kwargs)

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "connect", lambda path: conn)
    monkeypatch.setattr(main, "apply_schema", lambda connection, embed_dim: None)
    monkeypatch.setattr(main, "OllamaClient", FakeLLM)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)
    monkeypatch.setitem(sys.modules, "caden.google_sync.auth", auth_module)
    monkeypatch.setitem(sys.modules, "caden.google_sync.calendar", calendar_module)
    monkeypatch.setitem(sys.modules, "caden.google_sync.tasks", tasks_module)

    services = main._boot()
    try:
        row = conn.execute(
            "SELECT source FROM events WHERE source='google_scope_change' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["source"] == "google_scope_change"
    finally:
        services.close()


def test_cmd_054_boot_wires_searxng_client_when_configured(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, creds_exists=True)
    cfg = Config(
        config_dir=cfg.config_dir,
        data_dir=cfg.data_dir,
        db_path=cfg.db_path,
        ollama_url=cfg.ollama_url,
        ollama_model=cfg.ollama_model,
        embed_model=cfg.embed_model,
        embed_dim=cfg.embed_dim,
        searxng_url="http://127.0.0.1:8080",
        google_credentials_path=cfg.google_credentials_path,
        google_token_path=cfg.google_token_path,
        display_tz=cfg.display_tz,
    )

    conn = SimpleNamespace(close=lambda: None)
    captured: dict[str, object] = {}

    class FakeLLM:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def ping(self) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeEmbedder:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def check(self) -> None:
            return None

        def close(self) -> None:
            return None

    auth_module = ModuleType("caden.google_sync.auth")
    auth_module.load_credentials = lambda credentials_path, token_path: object()
    auth_module.list_available_calendars = lambda loaded_creds: [("primary", "Primary")]
    auth_module.list_available_task_lists = lambda loaded_creds: [("@default", "Tasks")]
    calendar_module = ModuleType("caden.google_sync.calendar")
    calendar_module.CalendarClient = lambda loaded_creds, **kwargs: ("calendar", loaded_creds, kwargs)
    tasks_module = ModuleType("caden.google_sync.tasks")
    tasks_module.TasksClient = lambda loaded_creds, **kwargs: ("tasks", loaded_creds, kwargs)

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "connect", lambda path: conn)
    monkeypatch.setattr(main, "apply_schema", lambda connection, embed_dim: None)
    monkeypatch.setattr(main, "OllamaClient", FakeLLM)
    monkeypatch.setattr(main, "Embedder", FakeEmbedder)
    monkeypatch.setattr(main, "SearxngClient", lambda url: captured.update({"url": url}) or "searxng-client")
    monkeypatch.setitem(sys.modules, "caden.google_sync.auth", auth_module)
    monkeypatch.setitem(sys.modules, "caden.google_sync.calendar", calendar_module)
    monkeypatch.setitem(sys.modules, "caden.google_sync.tasks", tasks_module)

    services = main._boot()

    assert captured["url"] == "http://127.0.0.1:8080"
    assert services.searxng == "searxng-client"