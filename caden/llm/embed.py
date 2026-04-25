"""Embeddings via ollama /api/embeddings with nomic-embed-text (by default).

Loud failure if the model is missing or the dimension drifts from config.
"""

from __future__ import annotations

import httpx

from ..errors import EmbedError

_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0)


class Embedder:
    def __init__(self, base_url: str, model: str, expected_dim: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.expected_dim = expected_dim
        self._client = httpx.Client(base_url=self.base_url, timeout=_TIMEOUT)

    def close(self) -> None:
        self._client.close()

    def check(self) -> None:
        """Hit the embedding endpoint with a short probe and verify the dim."""
        vec = self.embed("caden boot embedding dimension probe")
        if len(vec) != self.expected_dim:
            raise EmbedError(
                f"embedding dim mismatch: model {self.model!r} returned "
                f"{len(vec)} dims, config says embed_dim={self.expected_dim}. "
                f"Fix config.json or pull a matching model."
            )

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str):
            raise EmbedError(f"embed() requires str, got {type(text).__name__}")
        body = {"model": self.model, "prompt": text}
        try:
            r = self._client.post("/api/embeddings", json=body)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            raise EmbedError(
                f"ollama /api/embeddings failed for model {self.model!r}: {e}"
            ) from e
        vec = data.get("embedding")
        if not isinstance(vec, list) or not vec or not all(isinstance(x, (int, float)) for x in vec):
            raise EmbedError(f"ollama returned malformed embedding: {data!r}")
        return [float(x) for x in vec]
