from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..errors import WebSearchError

_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    content: str
    engine: str | None = None

    def summary_text(self) -> str:
        body = self.content.strip()
        if len(body) > 280:
            body = body[:277].rstrip() + "..."
        parts = [self.title.strip(), body, self.url.strip()]
        return " -- ".join(part for part in parts if part)


class SearxngClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=_TIMEOUT)

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        if not query.strip():
            raise WebSearchError("searxng search query must not be empty")
        try:
            r = self._client.get(
                "/search",
                params={"q": query, "format": "json"},
            )
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            raise WebSearchError(f"searxng request failed: {e}") from e
        except ValueError as e:
            raise WebSearchError(f"searxng returned invalid json: {e}") from e

        results = payload.get("results")
        if not isinstance(results, list):
            raise WebSearchError(f"searxng payload missing results list: {payload!r}")

        hits: list[SearchHit] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            content = str(item.get("content") or item.get("snippet") or "").strip()
            engine = item.get("engine")
            if not title and not content:
                continue
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    content=content,
                    engine=str(engine).strip() if engine else None,
                )
            )
            if len(hits) >= limit:
                break

        if not hits:
            raise WebSearchError(f"searxng returned no usable results for query {query!r}")
        return hits