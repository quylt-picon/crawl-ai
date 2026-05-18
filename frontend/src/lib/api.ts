import type {
  CrawlSearchResponse,
  JobCreatedResponse,
} from "@/types/events";

export interface SearchInput {
  website_url: string;
  product_name: string;
  product_code: string;
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

async function safeJson(res: Response): Promise<any | null> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}
