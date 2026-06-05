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
