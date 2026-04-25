"""Thin wrapper around the ollama HTTP API.

We use httpx against /api/chat and /api/embeddings. No ollama python client,
because it would be a silent dependency on their SDK conventions; a direct
HTTP call fails loudly with the real error.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator

import httpx

from .. import diag
from ..errors import LLMAborted, LLMError

# No read timeout for generation: streaming delivers its own liveness signal
# (tokens flowing). Connect/write still time out loudly.
_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)

# How long a background call sleeps between attempts to acquire the slot
# while a foreground waiter is queued ahead of it. Short enough that the
# rater feels responsive when chat finishes, long enough not to spin.
_BACKGROUND_POLL_INTERVAL_S = 0.05


class OllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(base_url=self.base_url, timeout=_TIMEOUT)
        # Ollama serves one inference at a time per model by default
        # (OLLAMA_NUM_PARALLEL=1). Without our own gate, a long-running
        # background call (the rater) would queue ahead of a chat request
        # at Ollama itself, with no way to preempt. We serialise here so
        # we can implement priority + abort in the client.
        self._slot = threading.Lock()
        # Set whenever a foreground caller is waiting for or holding the
        # slot. Background streaming calls poll this between chunks and
        # abort (raising LLMAborted) when it goes high, releasing the slot
        # so the foreground caller goes through immediately.
        self._fg_waiting = threading.Event()
        # Count of foreground waiters so concurrent fg requests don't
        # clear the flag while another fg is still queued.
        self._fg_waiters = 0
        self._fg_waiters_lock = threading.Lock()

    def close(self) -> None:
        self._client.close()

    # --- priority gate -------------------------------------------------------

    def fg_waiting(self) -> bool:
        """True when a foreground caller is queued or active.

        Background streaming loops consult this to decide whether to abort
        and yield the slot.
        """
        return self._fg_waiting.is_set()

    @contextmanager
    def _acquire(self, priority: str) -> Iterator[None]:
        """Acquire the single Ollama inference slot.

        priority="foreground": signal intent immediately, then block on the
        slot. Other foregrounds will queue behind us in lock-acquire order;
        any background already holding the slot will see ``fg_waiting`` go
        high and abort within one chunk.

        priority="background": never hold the slot while a foreground is
        waiting. Yields cooperatively until the slot is free AND no fg is
        queued.
        """
        if priority == "foreground":
            with self._fg_waiters_lock:
                self._fg_waiters += 1
                self._fg_waiting.set()
            try:
                self._slot.acquire()
            except BaseException:
                with self._fg_waiters_lock:
                    self._fg_waiters -= 1
                    if self._fg_waiters == 0:
                        self._fg_waiting.clear()
                raise
            try:
                with self._fg_waiters_lock:
                    self._fg_waiters -= 1
                    if self._fg_waiters == 0:
                        self._fg_waiting.clear()
                yield
            finally:
                self._slot.release()
        elif priority == "background":
            while True:
                if self._fg_waiting.is_set():
                    time.sleep(_BACKGROUND_POLL_INTERVAL_S)
                    continue
                if not self._slot.acquire(timeout=_BACKGROUND_POLL_INTERVAL_S):
                    continue
                # Re-check after acquire: a fg waiter could have set the
                # flag between our check and our acquire. Yield if so.
                if self._fg_waiting.is_set():
                    self._slot.release()
                    continue
                break
            try:
                yield
            finally:
                self._slot.release()
        else:
            raise ValueError(f"unknown priority: {priority!r}")

    # --- health checks used by boot sequence ---------------------------------

    def ping(self) -> None:
        """Raise LLMError if ollama is unreachable."""
        try:
            r = self._client.get("/api/tags")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(
                f"ollama unreachable at {self.base_url}: {e}. "
                f"Is the ollama daemon running?"
            ) from e

    def require_model(self, model: str) -> None:
        """Raise LLMError if the named model is not pulled locally."""
        try:
            r = self._client.get("/api/tags")
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            raise LLMError(f"failed to list ollama models: {e}") from e
        models = {m.get("name") for m in payload.get("models", []) if isinstance(m, dict)}
        # ollama tags include a ":tag"; accept either exact match or model:latest
        if model in models or f"{model}:latest" in models:
            return
        raise LLMError(
            f"required ollama model {model!r} is not installed. "
            f"Pull it with: ollama pull {model}. Installed models: {sorted(models)}"
        )

    # --- chat ----------------------------------------------------------------

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        format_json: bool = False,
        priority: str = "foreground",
    ) -> str:
        """Single-turn chat. Returns the raw assistant text.

        format_json=True asks ollama for strict JSON mode when the caller wants
        structured output. Repair still runs on top; strict JSON mode just
        reduces how much repair has to do.

        priority controls the priority lock; see ``_acquire``. Background
        non-streaming calls cannot be aborted mid-flight (the HTTP request
        is one blocking round-trip), so prefer ``chat_stream`` for anything
        that needs to yield to chat.
        """
        body = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if format_json:
            body["format"] = "json"
        with self._acquire(priority):
            try:
                r = self._client.post("/api/chat", json=body)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPError as e:
                raise LLMError(f"ollama /api/chat failed: {e}") from e
        msg = data.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMError(f"ollama /api/chat returned no content: {data!r}")
        return content

    def chat_stream(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.5,
        format_json: bool = False,
        think: bool = False,
        max_tokens: int | None = None,
        repeat_penalty: float | None = None,
        priority: str = "foreground",
        on_open: Callable[[], None] | None = None,
        on_content: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """Streaming chat. Returns (content, thinking).

        `think=True` asks ollama to surface reasoning-model thoughts as a
        separate stream. Default is False because non-thinking models may
        respond oddly to it AND thinking-models will spend a long time
        reasoning before emitting any content tokens — bad for UX where
        the caller wants visible progress fast.

        `max_tokens` caps generation (ollama option `num_predict`). Without
        it, a looping reasoning model can keep emitting "wait, ..." forever
        until context fills. Set this for any structured-output call.

        `repeat_penalty` (>1.0) discourages the model from repeating the
        same phrases — recommended for reasoning models that get stuck in
        self-correction loops.

        `on_open` fires once when the HTTP response starts (before any
        tokens arrive) so the caller can tell the difference between
        "ollama hasn't responded yet" and "ollama is responding but
        producing nothing visible".

        Raises LLMError if the stream closes without any content.
        """
        options: dict = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if repeat_penalty is not None:
            options["repeat_penalty"] = repeat_penalty
        body = {
            "model": self.model,
            "stream": True,
            # Always send `think` explicitly. Reasoning models (qwen3, qwq,
            # deepseek-r1) default to thinking when this key is absent,
            # which buries our content stream behind minutes of internal
            # monologue. Setting it to False forces them into direct mode.
            "think": bool(think),
            "options": options,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if format_json:
            body["format"] = "json"
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        chunk_count = 0
        thinking_chunk_count = 0
        last_done_event: dict | None = None

        diag.log(
            "llm.chat_stream → request",
            "model: " + self.model + "\n"
            + "options: " + json.dumps(options) + "\n"
            + "think: " + str(bool(think)) + "\n"
            + "format_json: " + str(bool(format_json)) + "\n"
            + "priority: " + priority + "\n"
            + "system (" + str(len(system)) + " chars):\n" + system + "\n"
            + "user (" + str(len(user)) + " chars):\n" + user,
        )
        t0 = time.monotonic()
        aborted = False
        try:
            with self._acquire(priority):
                with self._client.stream("POST", "/api/chat", json=body) as r:
                    r.raise_for_status()
                    if on_open is not None:
                        on_open()
                    for line in r.iter_lines():
                        # Background calls yield mid-stream when a
                        # foreground caller queues up. We close the HTTP
                        # stream by breaking out of the with-block and
                        # raise LLMAborted so the caller can re-queue.
                        if priority == "background" and self._fg_waiting.is_set():
                            aborted = True
                            break
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError as e:
                            raise LLMError(
                                f"ollama stream sent non-JSON line: {line!r} ({e})"
                            ) from e
                        if "error" in event:
                            raise LLMError(f"ollama stream error: {event['error']!r}")
                        msg = event.get("message") or {}
                        thought = msg.get("thinking") or ""
                        chunk = msg.get("content") or ""
                        if thought:
                            thinking_parts.append(thought)
                            thinking_chunk_count += 1
                            if on_thinking is not None:
                                on_thinking(thought)
                        if chunk:
                            content_parts.append(chunk)
                            chunk_count += 1
                            if on_content is not None:
                                on_content(chunk)
                        if event.get("done"):
                            last_done_event = event
                            break
        except httpx.HTTPError as e:
            diag.log("llm.chat_stream ✗ http error", repr(e))
            raise LLMError(f"ollama /api/chat stream failed: {e}") from e
        content = "".join(content_parts)
        thinking = "".join(thinking_parts)
        elapsed = time.monotonic() - t0
        done_reason = (last_done_event or {}).get("done_reason", "?")

        if aborted:
            diag.log(
                "llm.chat_stream ⏸ aborted (yielded to foreground)",
                f"elapsed: {elapsed:.1f}s\n"
                f"content_chunks: {chunk_count}  ({len(content)} chars)\n"
                f"thinking_chunks: {thinking_chunk_count}  ({len(thinking)} chars)",
            )
            raise LLMAborted(
                f"background LLM call aborted after {elapsed:.1f}s "
                f"({chunk_count} content chunks, {thinking_chunk_count} "
                f"thinking chunks) so a foreground call could take the slot."
            )

        diag.log(
            "llm.chat_stream ← response",
            f"elapsed: {elapsed:.1f}s\n"
            f"done_reason: {done_reason}\n"
            f"content_chunks: {chunk_count}  ({len(content)} chars)\n"
            f"thinking_chunks: {thinking_chunk_count}  ({len(thinking)} chars)\n"
            f"--- thinking ---\n{thinking}\n"
            f"--- content ---\n{content}",
        )
        if not content.strip():
            raise LLMError(
                "ollama stream closed without any visible content. "
                f"done_reason={done_reason!r}, "
                f"thinking={len(thinking)} chars, content=0 chars, "
                f"elapsed={elapsed:.1f}s. "
                f"Likely causes: (a) model is reasoning-only and ran out of "
                f"max_tokens before emitting an answer (raise max_tokens or "
                f"lower temperature so it commits faster), or (b) model only "
                f"supports thinking and never produced a content stream "
                f"(disable think=True). See {diag.path()} for the full thinking trace."
            )
        return content, thinking
