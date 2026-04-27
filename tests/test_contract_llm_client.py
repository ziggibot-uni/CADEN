import json
import threading
import time

import pytest

from caden.errors import LLMAborted
from caden.llm.client import OllamaClient


def test_ollama_client_serializes_calls_through_single_slot_semaphore():
    client = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    entered = threading.Event()
    released = threading.Event()
    order: list[str] = []

    def worker():
        with client._acquire("foreground"):
            order.append("worker")
            entered.set()
            released.wait(timeout=1)

    try:
        with client._acquire("foreground"):
            thread = threading.Thread(target=worker)
            thread.start()
            assert not entered.wait(timeout=0.05)
            assert thread.is_alive()
            order.append("main")

        assert entered.wait(timeout=1)
        released.set()
        thread.join(timeout=1)
    finally:
        client.close()

    assert order == ["main", "worker"]


def test_foreground_request_preempts_background_stream_and_aborts_it():
    client = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    first_chunk_seen = threading.Event()
    allow_second_line = threading.Event()
    foreground_acquired = threading.Event()
    background_result: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield json.dumps({"message": {"content": "first"}, "done": False})
            allow_second_line.wait(timeout=1)
            yield json.dumps({"message": {"content": "second"}, "done": False})

    class _FakeStream:
        def __enter__(self):
            return _FakeResponse()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeHttpClient:
        def stream(self, method, path, json=None):
            return _FakeStream()

        def close(self) -> None:
            return None

    client._client = _FakeHttpClient()

    def _run_background() -> None:
        try:
            client.chat_stream(
                "system",
                "user",
                priority="background",
                on_content=lambda chunk: first_chunk_seen.set(),
            )
        except BaseException as exc:  # store exact exception for assertion
            background_result["exc"] = exc

    def _foreground_waiter() -> None:
        with client._acquire("foreground"):
            foreground_acquired.set()

    try:
        bg_thread = threading.Thread(target=_run_background)
        bg_thread.start()
        assert first_chunk_seen.wait(timeout=1)

        fg_thread = threading.Thread(target=_foreground_waiter)
        fg_thread.start()
        deadline = time.monotonic() + 1.0
        while not client.fg_waiting() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert client.fg_waiting() is True

        allow_second_line.set()
        bg_thread.join(timeout=1)
        fg_thread.join(timeout=1)

        assert foreground_acquired.is_set()
        assert isinstance(background_result.get("exc"), LLMAborted)
    finally:
        client.close()


def test_llm_calls_emit_diag_request_and_response_lines(monkeypatch):
    client = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    diag_calls: list[tuple[str, str]] = []

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield json.dumps({"message": {"content": "hello"}, "done": True, "done_reason": "stop"})

    class _FakeStream:
        def __enter__(self):
            return _FakeResponse()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeHttpClient:
        def stream(self, method, path, json=None):
            return _FakeStream()

        def close(self) -> None:
            return None

    client._client = _FakeHttpClient()
    monkeypatch.setattr("caden.llm.client.diag.log", lambda section, body: diag_calls.append((section, body)))

    try:
        content, thinking = client.chat_stream("system", "user")
    finally:
        client.close()

    assert content == "hello"
    assert thinking == ""
    assert [call[0] for call in diag_calls] == [
        "llm.chat_stream → request",
        "llm.chat_stream ← response",
    ]
