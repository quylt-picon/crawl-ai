"""High-level LLM service used by the workflow.

Three calls correspond to STEP 2, STEP 4, and STEP 6 of the workflow. Each
goes through a retry loop and a Pydantic validation pass — if the model
returns invalid JSON, we retry with a stricter "JSON ONLY" reminder.
"""
from __future__ import annotations

import json
from typing import Iterable, Type, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.llm import ManualLocator, ProductMatch, UIAnalysis
from app.services.llm.base import LLMProvider
from app.services.llm.gemini import GeminiProvider
from app.services.llm.prompts import (
    MANUAL_FINDER_SYSTEM,
    MANUAL_FINDER_TEMPLATE,
    PRODUCT_MATCH_SYSTEM,
    PRODUCT_MATCH_TEMPLATE,
    UI_ANALYSIS_SYSTEM,
    UI_ANALYSIS_TEMPLATE,
)
from app.utils.json_parse import JsonParseError, extract_json

_log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMServiceError(RuntimeError):
    pass


class LLMService:
    def __init__(self, provider: LLMProvider, max_retries: int = 3) -> None:
        self._provider = provider
        self._max_retries = max_retries

    async def analyze_ui(self, ui_data: dict) -> UIAnalysis:
        prompt = UI_ANALYSIS_TEMPLATE.format(
            ui_data=json.dumps(ui_data, ensure_ascii=False)[:18_000]
        )
        return await self._call_validated(prompt, UI_ANALYSIS_SYSTEM, UIAnalysis)

    async def match_product(
        self,
        product_name: str,
        product_code: str,
        results: Iterable[dict],
    ) -> ProductMatch:
        prompt = PRODUCT_MATCH_TEMPLATE.format(
            product_name=product_name,
            product_code=product_code,
            results=json.dumps(list(results), ensure_ascii=False)[:18_000],
        )
        return await self._call_validated(prompt, PRODUCT_MATCH_SYSTEM, ProductMatch)

    async def find_manual(
        self,
        product_name: str,
        product_code: str,
        markdown: str,
        links: list[dict],
    ) -> ManualLocator:
        prompt = MANUAL_FINDER_TEMPLATE.format(
            product_name=product_name,
            product_code=product_code,
            markdown=markdown[:18_000],
            links=json.dumps(links[:200], ensure_ascii=False)[:6_000],
        )
        return await self._call_validated(prompt, MANUAL_FINDER_SYSTEM, ManualLocator)

    # ------------------------------------------------------------------ internal

    async def _call_validated(
        self,
        prompt: str,
        system: str,
        schema: Type[T],
    ) -> T:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=5.0),
                retry=retry_if_exception_type((JsonParseError, ValidationError)),
                reraise=True,
            ):
                with attempt:
                    raw = await self._provider.generate(prompt, system=system)
                    payload = extract_json(raw)
                    return schema.model_validate(payload)
        except RetryError as exc:
            raise LLMServiceError("LLM exhausted retries") from exc
        except (JsonParseError, ValidationError) as exc:
            raise LLMServiceError(f"LLM returned invalid payload: {exc}") from exc
        raise LLMServiceError("LLM call did not return")  # pragma: no cover


# ----------------------------------------------------------------------- factory

_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _service
    if _service is None:
        settings = get_settings()
        provider = GeminiProvider(
            api_key=settings.gemini_api_token,
            model=settings.gemini_model,
        )
        _service = LLMService(provider, max_retries=settings.llm_max_retries)
        _log.info("LLM service initialized: provider=gemini model=%s", settings.gemini_model)
    return _service
