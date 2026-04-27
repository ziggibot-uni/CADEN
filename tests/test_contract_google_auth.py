from pathlib import Path

import pytest

from caden.errors import GoogleSyncError
from caden.google_sync.auth import (
    SCOPES,
    list_available_calendars,
    list_available_task_lists,
    load_credentials,
)


def test_load_credentials_fails_loudly_when_oauth_client_json_is_missing(tmp_path):
    credentials_path = tmp_path / "google_credentials.json"
    token_path = tmp_path / "google_token.json"

    with pytest.raises(GoogleSyncError, match="Google OAuth client JSON not found"):
        load_credentials(credentials_path, token_path)


def test_load_credentials_runs_local_oauth_flow_and_persists_token(tmp_path, monkeypatch):
    credentials_path = tmp_path / "google_credentials.json"
    token_path = tmp_path / "nested" / "google_token.json"
    credentials_path.write_text("{}", encoding="utf-8")

    class FakeCreds:
        valid = True
        expired = False
        refresh_token = None

        def to_json(self) -> str:
            return '{"token": "fresh-token"}'

    class FakeFlow:
        def run_local_server(self, port: int):
            assert port == 0
            return FakeCreds()

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "caden.google_sync.auth.InstalledAppFlow.from_client_secrets_file",
        lambda path, scopes: captured.update({"path": path, "scopes": scopes}) or FakeFlow(),
    )

    creds = load_credentials(credentials_path, token_path)

    assert isinstance(creds, FakeCreds)
    assert captured == {"path": str(credentials_path), "scopes": SCOPES}
    assert token_path.read_text(encoding="utf-8") == '{"token": "fresh-token"}'


def test_load_credentials_refreshes_cached_token_and_rewrites_token_file(tmp_path, monkeypatch):
    credentials_path = tmp_path / "google_credentials.json"
    token_path = tmp_path / "google_token.json"
    credentials_path.write_text("{}", encoding="utf-8")
    token_path.write_text('{"token": "stale"}', encoding="utf-8")

    class FakeCreds:
        valid = False
        expired = True
        refresh_token = "refresh-token"

        def __init__(self) -> None:
            self.refreshed = False

        def refresh(self, request) -> None:
            self.refreshed = True
            self.valid = True

        def to_json(self) -> str:
            return '{"token": "refreshed-token"}'

    creds = FakeCreds()
    monkeypatch.setattr(
        "caden.google_sync.auth.Credentials.from_authorized_user_file",
        lambda path, scopes: creds,
    )

    loaded = load_credentials(credentials_path, token_path)

    assert loaded is creds
    assert creds.refreshed is True
    assert token_path.read_text(encoding="utf-8") == '{"token": "refreshed-token"}'


def test_google_auth_enumerates_available_calendars_and_task_lists(monkeypatch):
    class _Exec:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class _CalendarList:
        def list(self):
            return _Exec(
                {
                    "items": [
                        {"id": "primary", "summary": "Primary"},
                        {"id": "team", "summary": "Team"},
                    ]
                }
            )

    class _TaskLists:
        def list(self, maxResults=100):
            return _Exec(
                {
                    "items": [
                        {"id": "@default", "title": "Tasks"},
                        {"id": "proj", "title": "Project"},
                    ]
                }
            )

    class _CalendarService:
        def calendarList(self):
            return _CalendarList()

    class _TasksService:
        def tasklists(self):
            return _TaskLists()

    monkeypatch.setattr(
        "googleapiclient.discovery.build",
        lambda api, version, credentials, cache_discovery=False: (
            _CalendarService() if api == "calendar" else _TasksService()
        ),
    )

    calendars = list_available_calendars(object())
    task_lists = list_available_task_lists(object())

    assert calendars == [("primary", "Primary"), ("team", "Team")]
    assert task_lists == [("@default", "Tasks"), ("proj", "Project")]