"""Gemini provider that answers with live Google Search grounding.

Distinct from ``app.services.llm.gemini.GeminiProvider``: that one forces a
JSON mime-type and takes no tools, whereas grounding-with-search cannot be
combined with a forced ``response_mime_type``. Here we enable the
``google_search`` tool, return the raw text (the caller parses JSON out of it),
and surface the grounding metadata (the queries the model ran and the source
links it cited) so the workflow can show its work.

Calls run in a thread executor — the google.genai client is blocking and we
want the FastAPI event loop free for SSE consumers.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types as gtypes

from app.core.logging import get_logger

_log = get_logger(__name__)


@dataclass
class WebSearchRaw:
    """Raw output of one grounded generation."""

    text: str
    queries: list[str] = field(default_factory=list)
    # Each source: {"title": ..., "uri": ..., "domain": ...}
    sources: list[dict[str, str]] = field(default_factory=list)


class GeminiWebSearchProvider:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise ValueError("Gemini api_key is required")
        self._client = genai.Client(api_key=api_key)
        self._model_name = model

    @property
    def default_model(self) -> str:
        return self._model_name

    async def search(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 8192,
    ) -> WebSearchRaw:
        model_name = model or self._model_name
        # Pro models (e.g. gemini-2.5-pro, gemini-3-pro) run in thinking-only
        # mode and reject thinking_budget=0 ("Budget 0 is invalid"), so we leave
        # thinking at the model default for them. On flash-class models we
        # disable thinking to save tokens/latency.
        is_pro = "pro" in model_name.lower()
        config = gtypes.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system,
            tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
            thinking_config=None if is_pro else gtypes.ThinkingConfig(thinking_budget=0),
        )

        def _call() -> WebSearchRaw:
            resp = self._client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            text = (resp.text or "").strip()
            queries, sources = _extract_grounding(resp)
            return WebSearchRaw(text=text, queries=queries, sources=sources)

        _log.debug(
            "Gemini web-search call: model=%s, prompt_chars=%d", model_name, len(prompt)
        )
        return await asyncio.to_thread(_call)

    async def generate_json(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 8192,
    ) -> str:
        """Plain JSON generation — no search grounding.

        Used by the SerpAPI mode, where the search has already been done and the
        model only filters/extracts from the supplied results. Forcing a JSON
        mime-type (safe to do here since there is no ``google_search`` tool)
        makes the response reliably parseable.

        Thinking is left at the model default (disabling it is rejected by
        thinking-only models); ``max_output_tokens`` caps the response.
        """
        model_name = model or self._model_name
        config = gtypes.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system,
            response_mime_type="application/json",
        )

        def _call() -> str:
            resp = self._client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return (resp.text or "").strip()

        _log.debug(
            "Gemini filter call: model=%s, prompt_chars=%d", model_name, len(prompt)
        )
        return await asyncio.to_thread(_call)

    async def list_models(self) -> list[dict[str, str]]:
        """List models usable for grounded generation (support generateContent).

        Returns dicts of ``{name, display_name, description}`` with the
        ``models/`` prefix stripped from ``name`` so it can be passed straight
        back into :meth:`search`. Embedding/other non-generative models are
        filtered out.
        """

        def _call() -> list[dict[str, str]]:
            out: list[dict[str, str]] = []
            seen: set[str] = set()
            for m in self._client.models.list():
                actions = list(getattr(m, "supported_actions", None) or [])
                if "generateContent" not in actions:
                    continue
                name = _strip_models_prefix(getattr(m, "name", "") or "")
                if not name or name in seen:
                    continue
                # The API's supported_actions is unreliable: deep-research /
                # image / tts / robotics models advertise "generateContent" but
                # only work via other APIs or emit non-text. Keep only standard
                # Gemini text models, which are what web-search + JSON need.
                if not _is_usable_text_model(name):
                    continue
                seen.add(name)
                out.append(
                    {
                        "name": name,
                        "display_name": (getattr(m, "display_name", None) or name),
                        "description": (getattr(m, "description", None) or ""),
                    }
                )
            out.sort(key=lambda d: d["name"])
            return out

        return await asyncio.to_thread(_call)


def _strip_models_prefix(name: str) -> str:
    return name[len("models/"):] if name.startswith("models/") else name


# Substrings flagging a non-text / non-generateContent Gemini variant that the
# model-listing endpoint nonetheless tags as supporting "generateContent".
_NON_TEXT_MARKERS = (
    "image",
    "tts",
    "audio",
    "robotics",
    "computer-use",
    "embedding",
    "live",
    "dialog",
)


def _is_usable_text_model(name: str) -> bool:
    """True for standard Gemini text models usable for web-search + JSON.

    Excludes non-Gemini families (deep-research, gemma, lyria, nano-banana, …)
    and Gemini image/tts/audio/robotics/computer-use variants — all of which
    either reject ``generateContent`` at call time or emit non-text output.
    """
    lowered = name.lower()
    if not lowered.startswith("gemini-"):
        return False
    return not any(marker in lowered for marker in _NON_TEXT_MARKERS)


def _extract_grounding(resp: object) -> tuple[list[str], list[dict[str, str]]]:
    """Pull the search queries and cited sources out of grounding metadata.

    The shape is defensive — different model/SDK versions populate slightly
    different fields, and any of them can be absent on a non-grounded reply.
    """
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        return [], []
    meta = getattr(candidates[0], "grounding_metadata", None)
    if meta is None:
        return [], []

    queries = list(getattr(meta, "web_search_queries", None) or [])

    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for chunk in getattr(meta, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        if web is None:
            continue
        uri = (getattr(web, "uri", None) or "").strip()
        if not uri or uri in seen:
            continue
        seen.add(uri)
        sources.append(
            {
                "title": (getattr(web, "title", None) or "").strip(),
                "uri": uri,
                "domain": (getattr(web, "domain", None) or "").strip(),
            }
        )
    return queries, sources
