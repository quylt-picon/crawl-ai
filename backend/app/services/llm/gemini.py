"""Gemini provider using google.genai (the current Google SDK).

Calls run in a thread executor — the sync client uses blocking HTTP, and we
want the FastAPI event loop free for SSE consumers.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from google import genai
from google.genai import types as gtypes

from app.core.logging import get_logger
from app.services.llm.base import LLMProvider

_log = get_logger(__name__)


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise ValueError("Gemini api_key is required")
        self._client = genai.Client(api_key=api_key)
        self._model_name = model

    async def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> str:
        config = gtypes.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            system_instruction=system,
        )

        def _call() -> str:
            resp = self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=config,
            )
            return (resp.text or "").strip()

        _log.debug("Gemini call: model=%s, prompt_chars=%d", self._model_name, len(prompt))
        return await asyncio.to_thread(_call)
