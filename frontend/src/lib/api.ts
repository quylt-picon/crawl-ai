import type {
  CrawlSearchResponse,
  JobCreatedResponse,
} from "@/types/events";

export interface SearchInput {
  /** Preferred website. Optional on the web-search tab — omit to search the
   * open web with just the product name + code; required by the crawl tab. */
  website_url?: string;
  product_name: string;
  product_code: string;
  /** Optional Gemini model id (web-search tab only); ignored by the crawl tab. */
  model?: string;
  /** When true, search via SerpAPI then let the LLM filter/extract the links. */
  use_serpapi?: boolean;
}

export interface ModelInfo {
  name: string;
  display_name: string;
  description: string;
}

export interface ModelListResponse {
  models: ModelInfo[];
  default: string;
  serpapi_available: boolean;
  error: string | null;
}

export async function startSearch(input: SearchInput): Promise<JobCreatedResponse> {
  const res = await fetch("/api/crawl/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await safeJson(res);
    throw new Error(body?.detail || `start_search failed (${res.status})`);
  }
  return res.json();
}

export async function getResult(jobId: string): Promise<CrawlSearchResponse> {
  const res = await fetch(`/api/crawl/result/${jobId}`);
  if (!res.ok) throw new Error(`result fetch failed (${res.status})`);
  return res.json();
}

/** Start an LLM web-search job. Same input shape as {@link startSearch}. */
export async function startWebSearch(input: SearchInput): Promise<JobCreatedResponse> {
  const res = await fetch("/api/websearch/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await safeJson(res);
    throw new Error(body?.detail || `start_web_search failed (${res.status})`);
  }
  return res.json();
}

export async function getWebSearchResult(jobId: string): Promise<CrawlSearchResponse> {
  const res = await fetch(`/api/websearch/result/${jobId}`);
  if (!res.ok) throw new Error(`web-search result fetch failed (${res.status})`);
  return res.json();
}

/** Input for the combined web-search → crawl pipeline. No website_url: the
 * official site is discovered by the web search. ``search_prompt`` is the
 * UI-supplied instruction that drives the site-finding search. */
export interface SiteCrawlInput {
  product_name: string;
  product_code: string;
  search_prompt: string;
  model?: string;
}

/** Result of persisting the run history to the frontend public/ folder. */
export interface ExportResult {
  path: string;
  filename: string;
  served_url: string;
  count: number;
  bytes: number;
}

/** Write the (localStorage) run history to a JSON file in the FE public/ folder. */
export async function exportSiteCrawlHistory(
  runs: unknown[],
  filename?: string
): Promise<ExportResult> {
  const res = await fetch("/api/sitecrawl/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ runs, filename }),
  });
  if (!res.ok) {
    const body = await safeJson(res);
    throw new Error(body?.detail || `export failed (${res.status})`);
  }
  return res.json();
}

/** Start a combined job: web-search the official site, then crawl it. */
export async function startSiteCrawl(input: SiteCrawlInput): Promise<JobCreatedResponse> {
  const res = await fetch("/api/sitecrawl/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await safeJson(res);
    throw new Error(body?.detail || `start_sitecrawl failed (${res.status})`);
  }
  return res.json();
}

export async function getSiteCrawlResult(jobId: string): Promise<CrawlSearchResponse> {
  const res = await fetch(`/api/sitecrawl/result/${jobId}`);
  if (!res.ok) throw new Error(`sitecrawl result fetch failed (${res.status})`);
  return res.json();
}

/** Start a deep-crawl job: web-search the product's support/detail page, then
 * run the 3-hop manual extraction directly against it. Same input shape as
 * {@link startSiteCrawl}. */
export async function startDeepCrawl(input: SiteCrawlInput): Promise<JobCreatedResponse> {
  const res = await fetch("/api/sitecrawl/deep/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await safeJson(res);
    throw new Error(body?.detail || `start_deepcrawl failed (${res.status})`);
  }
  return res.json();
}

export async function getDeepCrawlResult(jobId: string): Promise<CrawlSearchResponse> {
  const res = await fetch(`/api/sitecrawl/deep/result/${jobId}`);
  if (!res.ok) throw new Error(`deepcrawl result fetch failed (${res.status})`);
  return res.json();
}

/** Input for the SerpAPI pipeline: an LLM generates the search queries
 * (``query_prompt``), SerpAPI runs them, then an LLM selects the results that
 * satisfy the rules (``eval_rule``). Both instructions are typed in the UI;
 * ``{product_name}`` / ``{product_code}`` placeholders are substituted on the
 * server. */
export interface SerpCrawlInput {
  product_name: string;
  product_code: string;
  query_prompt: string;
  eval_rule: string;
  model?: string;
}

/** Start a SerpAPI job: LLM query-gen → SerpAPI search → LLM evaluate/select. */
export async function startSerpCrawl(input: SerpCrawlInput): Promise<JobCreatedResponse> {
  const res = await fetch("/api/sitecrawl/serp/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await safeJson(res);
    throw new Error(body?.detail || `start_serpcrawl failed (${res.status})`);
  }
  return res.json();
}

export async function getSerpCrawlResult(jobId: string): Promise<CrawlSearchResponse> {
  const res = await fetch(`/api/sitecrawl/serp/result/${jobId}`);
  if (!res.ok) throw new Error(`serpcrawl result fetch failed (${res.status})`);
  return res.json();
}

/** Fetch the list of usable Gemini models (live, via the server's API key). */
export async function listWebSearchModels(): Promise<ModelListResponse> {
  const res = await fetch("/api/websearch/models");
  if (!res.ok) throw new Error(`models fetch failed (${res.status})`);
  return res.json();
}

async function safeJson(res: Response): Promise<any | null> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}
