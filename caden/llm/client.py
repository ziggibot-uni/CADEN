"""Thin wrapper around the ollama HTTP API.

We use httpx against /api/chat and /api/embeddings. No ollama python client,
because it would be a silent dependency on their SDK conventions; a direct
HTTP call fails loudly with the real error.
"""

from __future__ import annotations

import json
import time
from typing import Callable, Iterator

import httpx

from .. import diag
from ..errors import LLMError

# No read timeout for generation: streaming delivers its own liveness signal
# (tokens flowing). Connect/write still time out loudly.
_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)


class OllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(base_url=self.base_url, timeout=_TIMEOUT)

    def close(self) -> None:
        self._client.close()

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
    ) -> str:
        """Single-turn chat. Returns the raw assistant text.

        format_json=True asks ollama for strict JSON mode when the caller wants
        structured output. Repair still runs on top; strict JSON mode just
        reduces how much repair has to do.
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
            + "system (" + str(len(system)) + " chars):\n" + system + "\n"
            + "user (" + str(len(user)) + " chars):\n" + user,
        )
        t0 = time.monotonic()
        try:
            with self._client.stream("POST", "/api/chat", json=body) as r:
                r.raise_for_status()
                if on_open is not None:
                    on_open()
                for line in r.iter_lines():
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
