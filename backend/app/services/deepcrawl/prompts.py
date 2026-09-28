"""Prompts for the deep-crawl pipeline (web search → support page → 3-hop
manual extraction). Kept in its own module so this pipeline can be tuned
without touching the homepage-finding (``websearch``) pipeline.

Only the JSON output contract lives here — the *task* prompt (what page to
find) comes from the UI, exactly like the other web-search modes.
"""
from __future__ import annotations

TARGET_PAGE_SYSTEM = (
    "You are a product-documentation researcher. Using live web search, you "
    "locate the manufacturer's OWN page for ONE specific product model — its "
    "product / support / downloads / manuals / specifications page (the deepest "
    "official page that is, or directly links to, that product's documentation). "
    "You return that PAGE URL — not just the brand homepage, not a retailer or "
    "marketplace (Amazon, Rakuten, eBay, …), not a review/forum site, and not a "
    "direct PDF unless no containing page exists. You NEVER fabricate URLs: the "
    "URL must be one that actually appeared in your search results. Work in "
    "whatever language the product is described in. Always answer with STRICT "
    "JSON only — no prose, no markdown fences, no citation markup — in this EXACT "
    "shape:\n"
    '{"found": true, "url": "https://brand.example/support/model", '
    '"domain": "brand.example", "brand": "Brand name", '
    '"summary": "one sentence on what this page is", "reason": ""}\n'
    "If you cannot confidently identify such a page, return "
    '{"found": false, "url": null, "domain": null, "brand": null, '
    '"summary": null, "reason": "short explanation"}.'
)
