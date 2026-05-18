# Product Manual Finder

AI agent that crawls a product website, locates the search box, finds the right
product page, then extracts its user manual (PDF link, online HTML manual, or
inline content). The workflow runs as a streamed pipeline — every step is
broadcast to the frontend over SSE.

## Stack

- **Backend** — Python 3.10+, FastAPI, Crawl4AI, Pydantic, Gemini (`google.genai`), SSE
- **Frontend** — React 18 + Vite + TypeScript + Tailwind + Zustand
- **Realtime** — Server-Sent Events (`/api/crawl/stream/{job_id}`)

## Layout

```
crawl-ai/
├── backend/
│   ├── app/
│   │   ├── api/          # Routes, dependencies, in-memory job registry
│   │   ├── core/         # Config, logging, constants
│   │   ├── events/       # Pub/sub bus + per-job emitter for SSE
│   │   ├── schemas/      # Pydantic DTOs (requests, responses, events, LLM)
│   │   ├── services/
│   │   │   ├── crawl/    # Crawl4AI wrapper + JS snippets
│   │   │   ├── llm/      # Provider-agnostic LLM service (Gemini ships)
│   │   │   └── workflow/ # 7-step orchestrator
│   │   ├── utils/        # JSON parsing helpers
│   │   └── main.py       # FastAPI app factory
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/   # SearchForm, Stepper, Timeline, ManualResultPanel
│   │   ├── hooks/        # useCrawlJob (submit + SSE binding)
│   │   ├── lib/          # api.ts, sse.ts, cn.ts
│   │   ├── pages/App.tsx
│   │   ├── store/        # Zustand store
│   │   └── types/
│   └── package.json
└── script/                 # Original Crawl4AI demo scripts (kept as reference)
```

## Workflow (7 steps)

| # | Step | What it does |
|---|------|--------------|
| 1 | Crawl homepage | Open URL, extract forms/inputs/buttons/nav-links only (low token cost). |
| 2 | Analyze UI | LLM decides if there is a search box. If not, picks the support URL. |
| 3 | Search product | Types the product code into the search input and submits. Falls back to support-page search if the homepage has none. |
| 4 | Filter results | Heuristically narrow candidate links, then ask the LLM to pick the matching product detail URL. |
| 5 | Open product page | Crawl the product page. |
| 6 | Expand sections | Re-crawl with JS that auto-clicks tabs / accordions / "support" / "manuals" / "downloads". |
| 7 | Find manual | LLM classifies the manual as `link` (downloadable file), `html_url` (online viewer), `inline` (markdown), or `not_found`. Finalize accordingly. |

Each transition emits a `ProgressEvent` on SSE; in-step details flow as
`LogEvent`s; one `CompletionEvent` ends the stream.

## Running

### Backend

```bash
# from repo root
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
crawl4ai-setup            # one-time: installs Playwright browsers

cp backend/.env.example backend/.env
# edit backend/.env → set GEMINI_API_TOKEN

cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Health check: <http://localhost:8080/api/health>
Swagger UI: <http://localhost:8080/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to the backend at port 8080.

## API

### `POST /api/crawl/search`

```json
{
  "website_url": "https://www.panasonic.com/vn",
  "product_name": "Máy giặt cửa trên",
  "product_code": "NA-F85S11BRV"
}
```

Returns `202 Accepted` with a `job_id` and `stream_url`:

```json
{
  "job_id": "5d9b9...",
  "stream_url": "/api/crawl/stream/5d9b9..."
}
```

### `GET /api/crawl/stream/{job_id}` — SSE

Three named events:

- `progress` — `ProgressEvent` (one per step transition)
- `log` — `LogEvent` (intra-step detail)
- `completion` — `CompletionEvent` (terminal, server closes the stream)

### `GET /api/crawl/result/{job_id}`

Blocking fetch of the final `ManualResult` (used by the frontend to grab
inline/HTML manual content after the stream closes).

```json
{
  "success": true,
  "job_id": "5d9b9...",
  "manual": {
    "type": "link",
    "url": "https://.../manual.pdf",
    "content": null
  }
}
```

## Architecture notes

- **Crawl service knows nothing about LLMs.** It exposes `extract_ui`,
  `search_via_selectors`, and `crawl(expand_sections=…)`. Swap engines by
  rewriting this module — call sites are unchanged.
- **LLM service is provider-agnostic.** `LLMProvider` is one method
  (`generate`). `GeminiProvider` is the shipped implementation. Add OpenAI or
  Anthropic by writing a sibling class and updating `get_llm_service()`.
- **Event bus is in-process.** One asyncio queue per `job_id`. For
  multi-worker deployments swap `EventBus` for Redis pub/sub — no call sites
  change.
- **JSON parsing is defensive.** `utils/json_parse.py` recovers JSON from
  markdown fences and prose-wrapped responses; combined with Pydantic
  validation and `tenacity` retries, transient LLM hiccups don't fail the run.

## Coding standards in use

- Fully async backend; blocking SDK calls are pushed to `asyncio.to_thread`.
- Full type hints, Pydantic schemas for every boundary.
- Dependency injection via `Depends()` — singletons live behind `get_*()`
  factories.
- Routes are thin controllers; all business logic lives in services.
- TypeScript on the frontend; Zustand for state.
