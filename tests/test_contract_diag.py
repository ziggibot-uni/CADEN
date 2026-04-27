import json
import logging

from caden import diag
from caden.errors import CadenError
from caden.log import setup_logging
from caden.ui._error import ErrorBanner


def test_diag_writes_human_readable_records_to_documented_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CADEN_DIAG_DIR", str(tmp_path / ".caden"))
    diag._PATH = None

    diag.log("scheduler outcome", "scheduled block 10:00 -> 11:00")

    diag_path = tmp_path / ".caden" / "diag.log"
    assert diag.path() == str(diag_path)
    assert diag_path.is_file()

    text = diag_path.read_text(encoding="utf-8")
    assert "scheduler outcome" in text
    assert "scheduled block 10:00 -> 11:00" in text
    assert "------------------------------------------------------------------------" in text


def test_setup_logging_writes_json_lines_to_caden_log(tmp_path):
    root_logger = logging.getLogger()
    old_handlers = list(root_logger.handlers)
    old_level = root_logger.level
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    try:
        logger = setup_logging(tmp_path, log_level="INFO")
        logger.info("boot complete", step="config")

        for handler in logging.getLogger().handlers:
            handler.flush()

        log_path = tmp_path / "caden.log"
        assert log_path.is_file()

        lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert lines, "expected at least one JSON log line"
        payload = json.loads(lines[-1])
        assert payload["event"] == "boot complete"
        assert payload["step"] == "config"
        assert payload["level"] == "info"
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        root_logger.setLevel(old_level)
        for handler in old_handlers:
            root_logger.addHandler(handler)


def test_setup_logging_defaults_to_info_level(tmp_path):
    root_logger = logging.getLogger()
    old_handlers = list(root_logger.handlers)
    old_level = root_logger.level
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    try:
        logger = setup_logging(tmp_path)
        logger.debug("hidden debug")
        logger.info("visible info")

        for handler in logging.getLogger().handlers:
            handler.flush()

        log_path = tmp_path / "caden.log"
        lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        assert logging.getLogger().level == logging.INFO
        assert any(json.loads(line)["event"] == "visible info" for line in lines)
        assert all(json.loads(line)["event"] != "hidden debug" for line in lines)
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        root_logger.setLevel(old_level)
        for handler in old_handlers:
            root_logger.addHandler(handler)


def test_setup_logging_can_mirror_log_lines_into_low_priority_caden_log_events(tmp_path, db_conn):
    root_logger = logging.getLogger()
    old_handlers = list(root_logger.handlers)
    old_level = root_logger.level
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    try:
        logger = setup_logging(
            tmp_path,
            event_sink=lambda event: __import__("caden.log", fromlist=["make_libbie_event_sink"]).make_libbie_event_sink(db_conn)(event),
        )
        logger.info("boot complete", step="config")

        row = db_conn.execute(
            "SELECT source, raw_text, meta_json FROM events WHERE source='caden_log' ORDER BY id DESC LIMIT 1"
        ).fetchone()

        assert row is not None
        assert row["source"] == "caden_log"
        assert row["raw_text"] == "boot complete"
        meta = json.loads(row["meta_json"])
        assert meta["priority"] == "low"
        assert meta["step"] == "config"
        assert meta["level"] == "info"
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        root_logger.setLevel(old_level)
        for handler in old_handlers:
            root_logger.addHandler(handler)


def test_diag_failure_is_logged_via_structlog_without_raising(monkeypatch):
    captured: list[tuple[str, str]] = []

    class _BrokenPath:
        def open(self, *args, **kwargs):
            raise OSError("disk full")

    class _FakeLogger:
        def error(self, event, **kwargs):
            captured.append((event, kwargs["error"]))

    monkeypatch.setattr(diag, "logger", _FakeLogger())
    monkeypatch.setattr(diag, "_path", lambda: _BrokenPath())

    diag.log("scheduler outcome", "scheduled block")

    assert captured == [("diag_failed", "disk full")]


def test_error_banner_emits_diag_line_for_raised_caden_error(monkeypatch):
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "caden.ui._error.diag.log",
        lambda section, body: captured.append((section, body)),
    )

    ErrorBanner(CadenError("boom"), "scheduler")

    assert captured == [("caden_error", "context=scheduler\nerror=boom")]
