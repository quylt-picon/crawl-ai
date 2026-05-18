"""All LLM prompts in one place — easy to tune without touching service code."""
from __future__ import annotations

UI_ANALYSIS_SYSTEM = (
    "You are a website automation engineer. You analyze homepage UI structure "
    "to locate product search functionality. Always return STRICT JSON only — "
    "no prose, no markdown fences."
)

UI_ANALYSIS_TEMPLATE = """\
Analyze the following UI data extracted from a website homepage. The crawler
has already dismissed cookie banners and clicked search/menu triggers, so
inputs that were initially hidden may now be present in the snapshot.

Definitions:
- A "search box" is ANY input element (visible OR hidden) intended for product
  search. Strong signals: type="search", role="search", placeholder/aria-label
  containing "search", "tìm", "tìm kiếm", "find", "rechercher", OR a
  `parent_hint` matching `search/find/query` (the input lives inside a
  search-* container). Hidden inputs are still valid candidates — sites often
  hide them behind a search-icon button.
- A "search button" is the submit button OR a search-icon trigger that
  reveals/submits the input. Strong signals: text/aria-label containing
  "search", `aria_haspopup` set, `aria_controls` pointing at a search region,
  or `has_icon=true` with no text (icon-only magnifier).

Tasks:
1. Decide whether the homepage has a search box per the definition above.
   Prefer inputs whose `parent_hint` or attributes clearly tie them to search,
   over generic text inputs (newsletter, email signup, etc.).
2. If yes, return CSS selectors:
   - search_input_selector: prefer #id, then [name="..."], then a stable class
     chain. Hidden inputs are fine.
   - search_button_selector: prefer an explicit submit/search button. If only
     an icon trigger exists (`has_icon=true`, no text, `aria_haspopup` set),
     return it — the runtime will click it. If no button exists, leave empty
     and the runtime will press Enter inside the input.
3. ALWAYS return a support_url, even when has_search_box is true. Pick from
   nav_links — each entry has a `source` field of 'header', 'nav', or
   'footer'. Footer entries are valid (Support / Manuals / Downloads links
   are often footer-only). Look for keywords:
   support, products, consumer, appliance, downloads, manuals, find, search,
   "where to buy", "tài liệu", "hỗ trợ", "sản phẩm". Tie-breaking:
   header/nav > footer when both match; same-host > external; product-
   category specific > generic. If absolutely none match, return the most
   prominent product-facing link of any source.

Return JSON ONLY in this exact shape:

{{
  "has_search_box": true,
  "search_input_selector": "",
  "search_button_selector": "",
  "support_url": ""
}}

Use null or empty string only when truly nothing fits.

UI DATA (truncated if very long):
{ui_data}
"""


PRODUCT_MATCH_SYSTEM = (
    "You match product search results to a target product. Be conservative — "
    "if you are unsure, mark found=false. Return STRICT JSON only."
)

PRODUCT_MATCH_TEMPLATE = """\
The user is searching for the product detail page of:

- Name : {product_name}
- Code : {product_code}

Below are search result entries (title + url). Choose ONLY the URL that points
to the official detail page of this exact product. If none clearly match,
return found=false.

Return JSON ONLY:
{{
  "found": true,
  "product_url": "",
  "confidence": 0.0
}}

RESULTS:
{results}
"""


MANUAL_FINDER_SYSTEM = (
    "You find user manuals on product pages. A manual can be a downloadable "
    "file (PDF/DOC), a dedicated HTML page (manual viewer), or inline text on "
    "the current page. Return STRICT JSON only."
)

MANUAL_FINDER_TEMPLATE = """\
You are looking for the user manual / instruction guide / owner's manual for
this product:

- Name : {product_name}
- Code : {product_code}

The product page has been crawled (markdown + links provided).

Decision rules:
- If you can identify a downloadable file URL (.pdf, .doc, .docx) clearly
  named as a manual/instruction/guide, return type="link" with the URL.
- If you find a link to a dedicated HTML page that hosts the manual (often
  labeled "View online manual", "Online manual", "Instruction manual"), return
  type="html_url" with that URL.
- If the manual content appears inline directly on the page (instructions
  written in the markdown), return type="inline" with the relevant content
  (markdown allowed, keep concise).
- Else return type="not_found".

Return JSON ONLY:
{{
  "type": "link" | "html_url" | "inline" | "not_found",
  "url": "" ,
  "content": ""
}}

PRODUCT PAGE LINKS:
{links}

PRODUCT PAGE MARKDOWN (truncated):
{markdown}
"""
