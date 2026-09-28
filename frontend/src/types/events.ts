export type StepStatus = "pending" | "running" | "success" | "error" | "skipped";

export type StepId =
  | "crawl_homepage"
  | "analyze_ui"
  | "search_product"
  | "filter_results"
  | "find_manual"
  | "finalize"
  // Combined (web-search → crawl) pipeline: locate the official site first.
  | "find_site"
  // Deep-crawl pipeline: locate the product's support/detail page first.
  | "find_page"
  // Web-search pipeline steps (shared by the websearch tab).
  | "web_search"
  | "review_results"
  // SerpAPI pipeline: an LLM first generates the search queries.
  | "generate_queries";

export type ManualEntryType = "link" | "html_url" | "inline";

export interface ManualEntry {
  type: ManualEntryType;
  url?: string | null;
  content?: string | null;
  language?: string | null;
  label?: string | null;
}

export interface ProgressEvent {
  job_id: string;
  step: StepId;
  status: StepStatus;
  message: string;
  timestamp: string;
  data?: Record<string, unknown> | null;
}

export interface LogEvent {
  job_id: string;
  level: "info" | "warning" | "error" | "debug";
  message: string;
  timestamp: string;
  step?: StepId | null;
}

export interface CompletionEvent {
  job_id: string;
  success: boolean;
  manual_type?: "link" | "html_url" | "inline" | "not_found" | null;
  manual_url?: string | null;
  has_content?: boolean;
  error?: string | null;
  timestamp: string;
}

export interface ManualResult {
  type: "link" | "html_url" | "inline" | "not_found";
  url?: string | null;
  content?: string | null;
  manuals?: ManualEntry[];
}

export interface JobCreatedResponse {
  job_id: string;
  stream_url: string;
}

export interface CrawlSearchResponse {
  success: boolean;
  job_id: string;
  manual: ManualResult;
  error?: string | null;
}
