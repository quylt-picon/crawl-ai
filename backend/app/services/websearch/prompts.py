"""Prompts for the LLM web-search manual finder — kept separate from the
crawl prompts so the two pipelines can be tuned independently.
"""
from __future__ import annotations

WEB_SEARCH_SYSTEM = (
    "You are a product-documentation researcher. Using live web search, you "
    "find the official user manual / instruction guide / owner's manual / "
    "datasheet for a specific product. You prefer the manufacturer's own "
    "website and other authoritative sources, and you NEVER fabricate URLs — "
    "every link you return must be one that actually appeared in your search "
    "results. Always answer with STRICT JSON only: no prose, no markdown "
    "fences, no citations markup."
)

WEB_SEARCH_MANUAL_TEMPLATE = """\
Find the user manual / instruction guide / documentation for this product by
searching the web.

- Product name : {product_name}
- Product code : {product_code}
- Manufacturer / preferred website : {website_url}

Instructions:
1. Search the web for the official documentation of THIS exact product
   (match both the name and the code). Strongly prefer pages on the
   manufacturer / preferred website above; accept other authoritative sources
   (official distributors, the brand's support/download portal) only when the
   manufacturer site does not host the document.
2. Collect EVERY distinct manual/document you find — different languages
   (e.g. English, Vietnamese, Japanese), and different variants (quick-start guide vs.
   full manual vs. datasheet). One entry per document.
3. For each entry choose a ``type``:
   - "link"     — a direct downloadable file (.pdf/.doc/.docx) of the manual;
   - "html_url" — an online HTML manual/viewer page hosting the manual;
   - "inline"   — only when the manual text itself is reproduced on a page and
                  there is no file/URL to link; put a concise excerpt in
                  ``content``.
4. Fill ``language`` when distinguishable ("en", "vi", or the language name)
   and ``label`` with the human-readable document title.
5. If after searching you cannot confidently find documentation for this exact
   product, return found=false with an empty ``manuals`` list and a short
   ``reason``.

NEVER invent URLs — every ``url`` must be a real link from your search results.

Return JSON ONLY in this exact shape:
{{
  "found": true,
  "summary": "one sentence on what you found",
  "manuals": [
    {{
      "type": "link",
      "url": "https://...",
      "content": null,
      "language": "en",
      "label": "User Manual (PDF)"
    }}
  ],
  "reason": ""
}}
"""


# ── SerpAPI mode: the search is done by SerpAPI; the LLM only filters the
#    returned results and extracts the manual URLs from them. ──────────────────

SERPAPI_FILTER_SYSTEM = (
    "You are a product-documentation analyst. You are given the organic results "
    "of a real web search (title, link, snippet) for a specific product, and you "
    "must (a) filter to the results that genuinely lead to that product's manual "
    "/ instruction guide / documentation, and (b) extract the document URLs. You "
    "may ONLY return URLs that appear in the provided results — never invent or "
    "guess a URL. Always answer with STRICT JSON only: no prose, no markdown "
    "fences."
)

SERPAPI_FILTER_TEMPLATE = """\
A web search was run for the documentation of this product. Filter the search
results below and extract the manual/documentation links.

- Product name : {product_name}
- Product code : {product_code}
- Manufacturer / preferred website : {website_url}

Search queries that were run:
{queries}

Instructions:
1. Keep only results that clearly lead to the official user manual / instruction
   guide / owner's manual / datasheet for THIS exact product (match name and
   code). Prefer results on the manufacturer / preferred website; accept other
   authoritative sources (official distributors, the brand's support/download
   portal). Reject unrelated products, marketplaces/ads, forums, and reviews.
2. For each kept result, output one entry and choose a ``type``:
   - "link"     — the URL is a direct downloadable file (.pdf/.doc/.docx);
   - "html_url" — the URL is an online HTML manual/viewer page;
   - "inline"   — almost never here (only if the snippet itself is the manual).
3. Set ``url`` to the result's link EXACTLY as given (do not modify it). Fill
   ``language`` when distinguishable ("en", "vi", or the language name) and
   ``label`` with the result title or a concise human-readable document title.
4. If none of the results are a confident match, return found=false with an
   empty ``manuals`` list and a short ``reason``.

NEVER invent URLs — every ``url`` must be one of the links listed below.

SEARCH RESULTS (JSON array of {{index, title, link, snippet}}):
{results}

Return JSON ONLY in this exact shape:
{{
  "found": true,
  "summary": "one sentence on what you found",
  "manuals": [
    {{
      "type": "link",
      "url": "https://...",
      "content": null,
      "language": "en",
      "label": "User Manual (PDF)"
    }}
  ],
  "reason": ""
}}
"""
