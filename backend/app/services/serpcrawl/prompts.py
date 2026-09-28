"""Prompts for the SerpAPI pipeline (LLM query-gen → SerpAPI → LLM evaluate).

Only the JSON *output contracts* live here — the task instructions (how to
build the queries, and the rules for selecting results) come from the UI, just
like the other web-search modes. Kept separate so this pipeline can be tuned
without touching the websearch / deepcrawl prompts.
"""
from __future__ import annotations

# ── STEP 1: query generation. The operator's instruction (query_prompt) is the
#    task; this system message only pins the JSON output shape. ───────────────

SERP_QUERY_SYSTEM = (
    "You are a web-search query strategist for finding product documentation. "
    "Given a product (name + model code) and the operator's instruction, you "
    "produce a concise set of Google search queries that will surface the "
    "product's official manual / instruction guide / documentation. Write the "
    "queries in the product's own language when appropriate, combine the exact "
    "model code with documentation keywords, and keep the set small and "
    "high-signal (no near-duplicates). Always answer with STRICT JSON only — no "
    "prose, no markdown fences — in this EXACT shape:\n"
    '{"queries": ["query one", "query two"]}'
)


# ── STEP 2: result evaluation/selection. The operator's RULES come from the UI;
#    this system message only pins the JSON output shape and the no-fabrication
#    guarantee. ────────────────────────────────────────────────────────────────

SERP_EVAL_SYSTEM = (
    "You are a product-documentation analyst. You are given the organic results "
    "of a real web search (title, link, snippet) together with a set of RULES "
    "written by the operator. You apply those rules to evaluate and select which "
    "results genuinely lead to the product's manual / instruction guide / "
    "documentation, and you extract the document URLs. You may ONLY return URLs "
    "that appear in the provided results — never invent or guess a URL. Always "
    "answer with STRICT JSON only: no prose, no markdown fences."
)

SERP_EVAL_TEMPLATE = """\
Evaluate the web-search results below for this product and select the ones that
satisfy the RULES.

- Product name : {product_name}
- Product code : {product_code}

RULES (operator-supplied — follow them exactly):
{rule}

Search queries that were run:
{queries}

SEARCH RESULTS (JSON array of {{index, title, link, snippet}}):
{results}

For each result you SELECT, output one entry and choose a ``type``:
- "link"     — the URL is a direct downloadable file (.pdf/.doc/.docx);
- "html_url" — the URL is an online HTML manual/viewer page;
- "inline"   — almost never (only if the snippet itself is the manual text).
Set ``url`` to the result's link EXACTLY as given (do not modify it). Fill
``language`` when distinguishable ("en", "vi", or the language name) and
``label`` with the result title or a concise human-readable document title.
If no result satisfies the rules, return found=false with an empty ``manuals``
list and a short ``reason``.

NEVER invent URLs — every ``url`` must be one of the links listed above.

Return JSON ONLY in this exact shape:
{{
  "found": true,
  "summary": "one sentence on what you selected",
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
