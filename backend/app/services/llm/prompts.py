"""All LLM prompts in one place — easy to tune without touching service code."""
from __future__ import annotations

UI_ANALYSIS_SYSTEM = (
    "You are a website automation engineer. You read the rendered HTML of a "
    "homepage and decide (a) the CSS selectors for its product search input "
    "and submit/trigger button, and (b) a fallback URL to a dedicated search "
    "page. Always return STRICT JSON only — no prose, no markdown fences."
)

UI_ANALYSIS_TEMPLATE = """\
You are given the cleaned, post-render HTML of a website homepage. Popups,
cookie banners, and consent overlays have already been dismissed by the
crawler, and the page has been scrolled fully so lazy content is in the DOM.

Page URL  : {page_url}
Page title: {page_title}

Definitions:
- A "search box" is ANY <input>/<textarea> intended for product search —
  visible OR hidden. Strong signals: type="search", role="search",
  placeholder/aria-label containing "search", "find", "rechercher", "tìm",
  "tìm kiếm", OR the element living inside an ancestor whose class/id
  matches search/find/query/seek. Hidden inputs are valid candidates —
  sites often hide them behind a magnifier-icon trigger.
  Reject generic newsletter / email-signup / login inputs.
- A "search button" is the submit button OR a search-icon trigger that
  reveals/submits the input. Strong signals: type="submit" inside the same
  form, text/aria-label/title containing "search", aria-haspopup set,
  aria-controls pointing at a search region, OR an icon-only button with
  an SVG/i.icon-search inside no text.
- A "search page" is a separate page dedicated to product search — a link
  the user would click to *go to* a search experience when the homepage
  itself doesn't expose one. Strong signals on the anchor:
  * href patterns: /search, /find, /tim-kiem, /tim, /recherche, /suche,
    /buscar, ?q=, ?query=, ?keyword=, ?s= and similar query-style URLs;
  * visible text or aria-label: "search", "find", "find a product",
    "product finder", "tìm kiếm", "tìm sản phẩm", "tra cứu", "rechercher",
    "suchen", "buscar";
  * an icon-only link in the header with an aria-label of one of the above
    (magnifier-glass link).

Tasks:
1. Decide whether the homepage has a search box per the definition above.
2. If yes, return CSS selectors that document.querySelector can resolve:
   - search_input_selector: prefer #id (e.g. "#global-search-input"), then
     [name="..."], then a stable class chain. Hidden inputs are fine.
   - search_button_selector: prefer an explicit submit/search button. If
     only a magnifier-icon trigger exists, return it — the runtime will
     click it. If no button is needed (Enter alone submits), return an
     empty string.
3. ALWAYS try to return a search_page_url — even when has_search_box is
   true — so we have a fallback if the inline search fails. Look only for
   links to a dedicated search experience per the "search page"
   definition above. Tie-breaking: header/nav > footer when both match;
   same-host > external; an anchor with a search query parameter > a
   plain landing link. Resolve relative hrefs against the page URL above
   so the value is absolute. If no anchor on the page clearly points to a
   search experience, return an empty string — do NOT guess a support /
   products / category page just to fill the field.

Return JSON ONLY in this exact shape:

{{
  "has_search_box": true,
  "search_input_selector": "",
  "search_button_selector": "",
  "search_page_url": ""
}}

Use an empty string only when truly nothing fits.

HTML (cleaned; may be truncated if very long):
{html}
"""


PRODUCT_MATCH_SYSTEM = (
    "You match product search results to a target product. You receive the "
    "rendered markdown of a search-results page (header/footer/nav already "
    "stripped) plus the full list of links on it, and must pick the SINGLE "
    "URL that most likely points to that product's official detail page. "
    "Be conservative — if nothing is a clear match, return found=false. "
    "Return STRICT JSON only."
)

PRODUCT_MATCH_TEMPLATE = """\
The user is searching for the product detail page of:

- Name : {product_name}
- Code : {product_code}

You are given the full search-results page below: first the rendered markdown
(header/footer/nav already removed), then every link the crawler extracted.
Use both — the markdown gives context (which entry is a product card vs.
an ad / related-content tile), the link list gives the URLs you must choose
from.

Pick exactly ONE URL — the single most relevant link to the official detail
page of the exact product above. Prefer links whose surrounding markdown
clearly describes the target product (matching name and/or code). Reject
category / listing pages, login/cart/account pages, and pages for different
products. If no link is a confident match, return found=false.

Return JSON ONLY:
{{
  "found": true,
  "product_url": "",
  "confidence": 0.0
}}

SEARCH RESULTS MARKDOWN (truncated):
{markdown}

ALL LINKS ON THE PAGE (JSON array of {{href, text, ...}}):
{links}
"""


MANUAL_EXTRACTION_INSTRUCTION_TEMPLATE = """\
You are looking for the user manual / instruction guide / owner's manual for:

- Product name : {product_name}
- Product code : {product_code}

The current page's body has already been rendered to markdown (header,
footer, and nav stripped). The manual may not live on this page — sometimes
the page just links to a dedicated "Support", "Downloads", or "Manuals" hub
that holds the actual files. There may also be MULTIPLE manuals — different
languages (English, Vietnamese, …), variants (quick start vs. full manual),
or both.

Decide ONE of two outcomes:

A) You can already see the manual(s) here. Return final=true with every
   manual you find, one entry per item, in `manuals`:
   - type="link" for a downloadable file URL (.pdf, .doc, .docx) clearly
     labeled as a manual / instruction / guide / quick start;
   - type="html_url" for a dedicated HTML viewer page hosting the manual
     (e.g. "View online manual", "Online manual");
   - type="inline" if the manual text itself is written directly on this
     page — fill `content` with that markdown (keep concise).
   Always fill `language` when distinguishable ("en", "vi", or the language
   name) and `label` with the human-readable title shown on the page.

B) The manual is not on this page, but ONE link clearly leads to where the
   manual lives (a support / downloads / manuals page for THIS product).
   Return final=false and put that URL in `follow_url`. Pick at most one;
   prefer a link whose anchor text contains "manual", "downloads",
   "support", "documents", "hướng dẫn", "tài liệu", or the product code.
   Leave `manuals` empty in this case.

If neither A nor B applies, return final=true with an empty manuals list
and a short `reason` explaining what you saw.

NEVER invent URLs — every `url` value must appear in the markdown or links.
"""
