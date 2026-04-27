import pytest

from caden.errors import GoogleSyncError
from caden.ui._error import ErrorBanner
from caden.ui.app import CadenApp


@pytest.mark.asyncio
async def test_error_banner_copy_details_and_dismiss(mock_services, monkeypatch):
    copied: list[str] = []
    notified: list[tuple[str, str]] = []

    def fake_copy(self, text: str) -> None:
        copied.append(text)

    def fake_notify(self, message: str, *, severity="information", **kwargs) -> None:
        notified.append((message, severity))

    monkeypatch.setattr(CadenApp, "copy_to_clipboard", fake_copy)
    monkeypatch.setattr(CadenApp, "notify", fake_notify)

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(ErrorBanner(exception=GoogleSyncError("token expired"), context="completion-poll"))
        await pilot.pause(0.2)

        await pilot.click("#copy")
        await pilot.pause(0.1)

        assert copied == ["Context: completion-poll\nError: token expired"]
        assert notified == [("Details copied to clipboard", "information")]

        await pilot.click("#dismiss")
        await pilot.pause(0.1)

        assert not isinstance(app.screen, ErrorBanner)


@pytest.mark.asyncio
async def test_completion_poll_failure_surfaces_error_banner_and_halts_subsystem(
    mock_services, monkeypatch
):
    cancelled: list[str] = []
    banners: list[ErrorBanner] = []
    bells: list[bool] = []
    worker_groups: list[str | None] = []

    async def fake_poll(self):
        return await CadenApp._poll_completions(self)

    def fake_cancel_group(name: str) -> None:
        cancelled.append(name)

    def fake_push_screen(self, screen, *args, **kwargs):
        banners.append(screen)
        return None

    def fake_bell(self) -> None:
        bells.append(True)

    def fake_run_worker(self, awaitable, *, group=None, **kwargs):
        worker_groups.append(group)
        awaitable.close()
        return None

    def raise_sync_error(conn, tasks, calendar):
        raise GoogleSyncError("google tasks offline")

    monkeypatch.setattr("caden.ui.app.poll_once", raise_sync_error)
    monkeypatch.setattr(CadenApp, "push_screen", fake_push_screen)
    monkeypatch.setattr(CadenApp, "bell", fake_bell)
    monkeypatch.setattr(CadenApp, "run_worker", fake_run_worker)

    mock_services.tasks = object()
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 24)) as pilot:
        monkeypatch.setattr(app.workers, "cancel_group", fake_cancel_group)
        await fake_poll(app)
        app.action_refresh()
        await pilot.pause(0.1)

    assert bells == [True]
    assert cancelled == ["completion-poll"]
    assert len(banners) == 1
    assert isinstance(banners[0], ErrorBanner)
    assert banners[0].err_context == "completion-poll"
    assert str(banners[0].exception) == "google tasks offline"
    assert worker_groups == ["refresh-panels"]