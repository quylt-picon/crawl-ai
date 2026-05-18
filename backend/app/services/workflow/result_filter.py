"""Heuristic filtering of links into "looks like a product detail page" set.

We feed this filtered list to the LLM in STEP 4 instead of every link on the
search results page — cuts tokens dramatically and improves match quality.
"""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

_NEGATIVE_PATH_SEGMENTS = {
    "login",
    "signin",
    "register",
    "cart",
    "account",
    "privacy",
    "terms",
    "cookie",
    "contact",
    "careers",
    "press",
}
_NEGATIVE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js")


def _looks_like_product_link(href: str, text: str, code: str) -> bool:
    if not href:
        return False
    href_l = href.lower()
    if any(href_l.endswith(ext) for ext in _NEGATIVE_EXTENSIONS):
        return False
    try:
        path = urlparse(href).path.lower()
    except ValueError:
        return False
    if any(seg in path.split("/") for seg in _NEGATIVE_PATH_SEGMENTS):
        return False
    code_l = (code or "").lower()
    if code_l and (code_l in href_l or code_l in text.lower()):
        return True
    # Product paths often contain something like /products/ or /product-detail/.
    return bool(re.search(r"/(product|products|consumer|appliance|appliances|home-appliances|item)/", path))


def filter_search_links(
    links: Iterable[dict],
    *,
    product_code: str,
    max_items: int = 60,
) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for link in links:
        href = (link.get("href") or "").strip()
        text = (link.get("text") or "").strip()
        if not href or href in seen:
            continue
        if not _looks_like_product_link(href, text, product_code):
            continue
        seen.add(href)
        out.append({"url": href, "title": text[:160]})
        if len(out) >= max_items:
            break
    return out
