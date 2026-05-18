"""Robust JSON extraction from LLM responses.

LLMs sometimes wrap JSON in markdown fences or prepend prose. This helper
tries hard to recover a parseable object from common shapes before giving up.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class JsonParseError(ValueError):
    """Raised when no JSON object could be recovered from an LLM payload."""


def extract_json(text: str) -> Any:
    if not text:
        raise JsonParseError("empty payload")

    text = text.strip()

    # 1. Direct parse.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip ```json fences.
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidate = fenced.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 3. Slice from first { to last } (handles prose before/after).
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise JsonParseError(f"sliced JSON still invalid: {exc}") from exc

    raise JsonParseError("no JSON object found in payload")
