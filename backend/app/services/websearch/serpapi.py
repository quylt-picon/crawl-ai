"""Thin async SerpAPI (Google engine) client.

Used by the "Use Web Search API (SerpAPI)" mode: SerpAPI does the actual web
search, then the LLM filters the organic results and extracts manual URLs.
Only the organic results we care about are surfaced.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger

_log = get_logger(__name__)

_SERPAPI_URL = "https://serpapi.com/search.json"


@dataclass
class SerpResult:
    title: str
    link: str
    snippet: str
    source: str = ""  # displayed_link / source host

    def to_source(self) -> dict[str, str]:
        """Shape used by ManualSearchResult.sources / the frontend panel."""
        return {
            "title": self.title,
            "uri": self.link,
            "domain": self.source or _host(self.link),
        }


class SerpApiError(RuntimeError):
    pass


class SerpApiClient:
    def __init__(self, api_key: str, timeout_s: int = 30) -> None:
        if not api_key:
            raise ValueError("SerpAPI api_key is required")
        self._api_key = api_key
        self._timeout_s = timeout_s

    async def search(
        self,
        query: str,
        *,
        num: int = 10,
        hl: str = "en",
        gl: str = "us",
    ) -> list[SerpResult]:
        """Run one Google search via SerpAPI and return its organic results."""
        params = {
            "engine": "google",
            "q": query,
            "api_key": self._api_key,
            "num": num,
            "hl": hl,
            "gl": gl,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.get(_SERPAPI_URL, params=params)
        except httpx.HTTPError as exc:
            raise SerpApiError(f"SerpAPI request failed: {exc}") from exc

        if resp.status_code != 200:
            # SerpAPI returns an `error` field with a human-readable reason.
            detail = _safe_error(resp)
            raise SerpApiError(f"SerpAPI returned {resp.status_code}: {detail}")

        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise SerpApiError(f"SerpAPI error: {data['error']}")

        organic = (data or {}).get("organic_results") or []
        results: list[SerpResult] = []
        for item in organic:
            if not isinstance(item, dict):
                continue
            link = (item.get("link") or "").strip()
            if not link:
                continue
            results.append(
                SerpResult(
                    title=(item.get("title") or "").strip(),
                    link=link,
                    snippet=(item.get("snippet") or "").strip(),
                    source=(item.get("displayed_link") or item.get("source") or "").strip(),
                )
            )
        _log.debug("SerpAPI query %r -> %d organic result(s)", query, len(results))
        return results


def _safe_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
    except Exception:
        pass
    return resp.text[:200]


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc
    except ValueError:
        return ""
