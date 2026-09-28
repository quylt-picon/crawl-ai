import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Compass,
  Cpu,
  Download,
  FileDown,
  FileSearch,
  FileText,
  Filter,
  Globe,
  Link2,
  Loader2,
  Search,
  Trash2,
  X,
} from "lucide-react";
import {
  exportSiteCrawlHistory,
  getDeepCrawlResult,
  getSerpCrawlResult,
  getSiteCrawlResult,
  listWebSearchModels,
  startDeepCrawl,
  startSerpCrawl,
  startSiteCrawl,
  type ModelInfo,
  type SerpCrawlInput,
  type SiteCrawlInput,
} from "@/lib/api";
import type {
  CompletionEvent,
  JobCreatedResponse,
  LogEvent,
  ManualEntry,
  ManualEntryType,
  ManualResult,
  ProgressEvent,
} from "@/types/events";

// ─── The default site-finding prompt shipped in the UI ────────────────────────
// The backend keeps NO task prompt of its own — it uses whatever the UI sends.
// {product_name} / {product_code} are substituted server-side. The prompt is
// language-neutral: the product fields (which may be Japanese, etc.) carry the
// language, so this works for any dataset.
const DEFAULT_SEARCH_PROMPT = `Find the OFFICIAL manufacturer / brand website for this product.
Return the homepage (root domain) of the official site — not a manual page,
not a retailer or marketplace (Amazon, Rakuten, …), not a review or forum site.

- Product name: {product_name}
- Product code / model: {product_code}`;

// Used when the "support/detail page" toggle is on: the search must reach the
// manufacturer's own page for THIS model (support / downloads / manuals /
// detail) so the crawler can extract manuals directly from it — not the
// brand homepage.
const DEFAULT_SUPPORT_PROMPT = `ROLE: Find the official manufacturer page for this EXACT product model that contains, or directly links to, its documentation (manuals, instructions, downloads).

PRODUCT
* Name: {product_name}
* Model: {product_code}

HOW TO SEARCH
1. Identify the current official manufacturer/brand and its official website from the name and model code (prefer the regional site for the product's market, e.g. panasonic.jp / sony.jp for a Japan model).
2. Run several targeted searches that surface THIS model's own page on that site — combine the exact model code with support/manual keywords AND restrict to the manufacturer domain with the site: operator. In the product's language, e.g.:
   - "{product_code}" site:<manufacturer-domain>
   - "{product_code}" 取扱説明書 OR サポート OR ダウンロード 
   - "{product_code}" support OR manual OR downloads
3. In the results, locate the entry that belongs to this exact model — a product / support / downloads / manuals page whose link or title contains "{product_code}". Open it to confirm it is this model's page.

WHICH PAGE
* Prefer the deepest official documentation page (Support / Downloads / Manuals) over a marketing or category page.
* Reject a different model/series/family, and any retailer, marketplace, review, forum, blog, or manual-aggregator (ManualsLib, …) site.

URL RULES
* Output the URL EXACTLY as it appears in the search result — copy the full path character-for-character.
* NEVER invent, complete, shorten, normalize, or pattern-guess a path (e.g. do not reuse another model's URL format, and do not build "/.../{product_code}_manualsite.html" style paths). The path you output must be one you actually saw in a result.
* If your searches did not surface a real page for THIS exact model, report not-found — do NOT output a guessed URL.

OUTPUT
Return exactly ONE real URL that you saw in the results — the model's documentation page (or the direct manual file if that is what the results give) — or not-found. Nothing else.`;

// ─── SerpAPI mode defaults ─────────────────────────────────────────────────────
// In SerpAPI mode the LLM is used twice: (1) to GENERATE the SerpAPI queries
// from the product, and (2) to EVALUATE/SELECT the returned results against an
// operator rule set. Both texts are editable in the UI and sent verbatim;
// {product_name} / {product_code} are substituted server-side.

const DEFAULT_SERP_QUERY_PROMPT = `Generate a small set of Google search queries to find the OFFICIAL user manual / instruction guide / documentation for this product.
Write the queries in the product's own language where appropriate (e.g. Japanese: 取扱説明書 / サポート / ダウンロード), and combine the EXACT model code with documentation keywords. Avoid near-duplicates.

- Product name: {product_name}
- Product code / model: {product_code}`;

const DEFAULT_SERP_EVAL_RULE = `Select a search result only if ALL of the following hold:
1. It clearly corresponds to THIS exact model ({product_code}) — reject other models, series, or families.
2. It is an official manufacturer / authorized source (brand site, official support / downloads / manuals portal) — reject marketplaces (Amazon, Rakuten, eBay, …), forums, reviews, blogs, and manual-aggregators (ManualsLib, …).
3. It is, or directly links to, the product's manual / instruction guide / owner's manual / datasheet.

Prefer direct document files (PDF) and the deepest official documentation page. If nothing satisfies the rules, select nothing.`;

// ─── Types ──────────────────────────────────────────────────────────────────

interface WsSource {
  title?: string;
  uri: string;
  domain?: string;
}

interface OfficialSite {
  found?: boolean;
  url?: string | null;
  domain?: string | null;
  brand?: string | null;
  summary?: string | null;
  reason?: string | null;
}

/** A quick-fill example for the form. Unlike the crawl tab's presets there is
 * no website_url — this pipeline discovers the official site itself. */
interface Preset {
  label: string;
  product_name: string;
  product_code: string;
}

interface RunLog {
  kind: "progress" | "log";
  step?: string;
  status?: string; // progress: running | success | error
  level?: string; // log: info | warning | error | debug
  message: string;
  ts: string;
}

type RunStatus = "running" | "done" | "error";

type RunMode = "site" | "deep" | "serpapi";

/** The three selectable pipelines, rendered as a segmented control. */
const MODE_OPTIONS: {
  id: RunMode;
  title: string;
  desc: string;
  icon: typeof Compass;
  activeClass: string;
  iconClass: string;
}[] = [
  {
    id: "site",
    title: "Trang chính chủ → crawl",
    desc: "Web search tìm trang chủ thương hiệu, rồi cào trang đó để lấy manual.",
    icon: Compass,
    activeClass: "border-brand-300 bg-brand-50/60",
    iconClass: "text-brand-600",
  },
  {
    id: "deep",
    title: "Trang hỗ trợ/chi tiết → 3 hop",
    desc: "Web search tìm trang hỗ trợ/chi tiết đúng model, rồi trích manual (3 hop).",
    icon: FileSearch,
    activeClass: "border-indigo-200 bg-indigo-50/60",
    iconClass: "text-indigo-600",
  },
  {
    id: "serpapi",
    title: "SerpAPI + LLM (query + đánh giá)",
    desc: "LLM sinh query → SerpAPI → LLM chọn theo rule → crawl 3 hop ra link manual cuối.",
    icon: Filter,
    activeClass: "border-amber-200 bg-amber-50/60",
    iconClass: "text-amber-600",
  },
];

/** Form payload stored on a run for display + reproducibility. ``search_prompt``
 * is used by site/deep modes; ``query_prompt`` + ``eval_rule`` by SerpAPI mode. */
interface ScInput {
  product_name: string;
  product_code: string;
  search_prompt?: string;
  query_prompt?: string;
  eval_rule?: string;
  model?: string;
}

interface ScRun {
  id: string;
  jobId?: string;
  startedAt: string;
  mode: RunMode;
  input: ScInput;
  logs: RunLog[];
  manuals: ManualEntry[];
  site?: OfficialSite | null;
  sources: WsSource[];
  queries: string[];
  status: RunStatus;
  error?: string | null;
  collapsed: boolean;
}

/** Shape of the `data` payload we care about across the pipeline's steps. */
interface ScProgressData {
  site?: OfficialSite;
  manuals?: ManualEntry[];
  sources?: WsSource[];
  queries?: string[];
}

// ─── State management ─────────────────────────────────────────────────────────

type Action =
  | { type: "ADD_RUN"; run: ScRun }
  | { type: "APPEND_LOG"; id: string; log: RunLog }
  | { type: "PATCH"; id: string; patch: Partial<ScRun> }
  | { type: "TOGGLE"; id: string }
  | { type: "REMOVE"; id: string }
  | { type: "CLEAR_ALL" };

function reducer(state: ScRun[], action: Action): ScRun[] {
  switch (action.type) {
    case "ADD_RUN":
      return [action.run, ...state];
    case "APPEND_LOG":
      return state.map((r) =>
        r.id === action.id ? { ...r, logs: [...r.logs, action.log] } : r
      );
    case "PATCH":
      return state.map((r) => (r.id === action.id ? { ...r, ...action.patch } : r));
    case "TOGGLE":
      return state.map((r) =>
        r.id === action.id ? { ...r, collapsed: !r.collapsed } : r
      );
    case "REMOVE":
      return state.filter((r) => r.id !== action.id);
    case "CLEAR_ALL":
      return [];
    default:
      return state;
  }
}

// ─── Persistence (so the log history survives reloads / tab switches) ──────────

const STORAGE_KEY = "sitecrawl-runs-v1";

function loadRuns(): ScRun[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const runs = JSON.parse(raw) as ScRun[];
    if (!Array.isArray(runs)) return [];
    return runs.map((r) =>
      r.status === "running"
        ? { ...r, status: "error", error: "Interrupted (page reloaded)" }
        : r
    );
  } catch {
    return [];
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function generateId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("vi-VN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const ICON_FOR_TYPE: Record<ManualEntryType, typeof FileDown> = {
  link: FileDown,
  html_url: Globe,
  inline: FileText,
};

const LEVEL_COLOR: Record<string, string> = {
  info: "text-slate-600",
  warning: "text-amber-600",
  error: "text-rose-600",
  debug: "text-slate-400",
};

const STATUS_COLOR: Record<string, string> = {
  running: "text-blue-600",
  success: "text-emerald-600",
  error: "text-rose-600",
};

// ─── Log line ───────────────────────────────────────────────────────────────

function LogLine({ log, hideStep }: { log: RunLog; hideStep?: boolean }) {
  const isProgress = log.kind === "progress";
  const accent = isProgress
    ? STATUS_COLOR[log.status ?? ""] ?? "text-slate-600"
    : LEVEL_COLOR[log.level ?? "info"] ?? "text-slate-600";
  const tag = isProgress ? log.status ?? "·" : log.level ?? "log";
  const weight = isProgress ? "font-medium text-slate-800" : "text-slate-600";

  return (
    <div className="group flex items-start gap-0 rounded px-1 py-[1.5px] font-mono text-[11px] leading-5 hover:bg-slate-200/40">
      <span className="w-[64px] shrink-0 pr-2 text-right tabular-nums text-cyan-600/70">
        {new Date(log.ts).toLocaleTimeString("vi-VN", { hour12: false })}
      </span>
      <span className={`w-[60px] shrink-0 pr-2 font-bold uppercase ${accent}`}>{tag}</span>
      {!hideStep && log.step && (
        <span className="w-[110px] shrink-0 truncate pr-2 text-slate-500">{log.step}</span>
      )}
      <span className={`whitespace-pre-wrap break-words ${weight}`}>{log.message}</span>
    </div>
  );
}

// ─── Step grouping for the log timeline ───────────────────────────────────────

// Steps from both modes (homepage-crawl and deep support-page). The timeline
// only renders the steps that actually fire, in arrival order.
const STEP_LABELS: Record<string, string> = {
  find_site: "Find official site",
  find_page: "Find support page",
  generate_queries: "Generate queries (LLM)",
  web_search: "SerpAPI search",
  review_results: "Evaluate results (LLM)",
  crawl_homepage: "Crawl homepage",
  analyze_ui: "Analyze UI",
  search_product: "Search product",
  filter_results: "Filter results",
  find_manual: "Extract manual (3 hops)",
  finalize: "Finalize",
};

type StepState = "running" | "success" | "error" | "none";

interface StepGroup {
  step: string;
  state: StepState;
  logs: RunLog[];
}

function groupByStep(logs: RunLog[]): StepGroup[] {
  const groups: StepGroup[] = [];
  for (const log of logs) {
    const step = log.step ?? "—";
    let g = groups[groups.length - 1];
    if (!g || g.step !== step) {
      g = { step, state: "none", logs: [] };
      groups.push(g);
    }
    g.logs.push(log);
    if (log.kind === "progress" && log.status) g.state = log.status as StepState;
  }
  return groups;
}

const STEP_DOT: Record<StepState, string> = {
  running: "bg-blue-400 animate-pulse",
  success: "bg-emerald-500",
  error: "bg-rose-500",
  none: "bg-slate-300",
};

function StepGroupBlock({ group }: { group: StepGroup }) {
  return (
    <div className="mb-2 overflow-hidden rounded-md border border-slate-200 bg-white">
      <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-100/60 px-2 py-1">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STEP_DOT[group.state]}`} />
        <span className="text-[11px] font-semibold text-slate-700">
          {STEP_LABELS[group.step] ?? group.step}
        </span>
        <span className="ml-auto text-[10px] tabular-nums text-slate-400">
          {group.logs.length}
        </span>
      </div>
      <div className="bg-slate-50 p-1">
        {group.logs.map((log, i) => (
          <LogLine key={i} log={log} hideStep />
        ))}
      </div>
    </div>
  );
}

// ─── Manual + source lists ────────────────────────────────────────────────────

function ManualList({ manuals }: { manuals: ManualEntry[] }) {
  if (manuals.length === 0) return null;
  return (
    <div className="space-y-2">
      {manuals.map((entry, i) => {
        const Icon = ICON_FOR_TYPE[entry.type] ?? FileText;
        return (
          <div key={i} className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-2.5">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                <Icon className="h-3 w-3" />
                {entry.type}
              </span>
              {entry.language && (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                  {entry.language}
                </span>
              )}
              {entry.label && (
                <span className="text-sm font-medium text-slate-800">{entry.label}</span>
              )}
            </div>
            {entry.url && (
              <a
                href={entry.url}
                target="_blank"
                rel="noreferrer"
                className="block break-all text-[13px] font-medium text-brand-700 underline-offset-2 hover:underline"
              >
                {entry.url}
              </a>
            )}
            {entry.content && (
              <pre className="mt-2 max-h-[18rem] overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-700">
                {entry.content}
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SourceList({ sources }: { sources: WsSource[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">
        <Link2 className="h-3 w-3" />
        Web sources ({sources.length})
      </div>
      <div className="space-y-0.5">
        {sources.map((s, i) => (
          <a
            key={i}
            href={s.uri}
            target="_blank"
            rel="noreferrer"
            className="block truncate font-mono text-[11px] text-slate-600 hover:text-blue-600 hover:underline"
            title={s.uri}
          >
            {s.domain || s.title || s.uri}
          </a>
        ))}
      </div>
    </div>
  );
}

// ─── Run section ──────────────────────────────────────────────────────────────

function RunSection({
  run,
  dispatch,
}: {
  run: ScRun;
  dispatch: React.Dispatch<Action>;
}) {
  const CollapseIcon = run.collapsed ? ChevronRight : ChevronDown;
  const dot =
    run.status === "running"
      ? "bg-blue-400 animate-pulse"
      : run.status === "error"
        ? "bg-red-500"
        : "bg-emerald-400";

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-md shadow-slate-200/50">
      {/* ── header ── */}
      <div
        className="flex cursor-pointer select-none items-center gap-2 border-b border-slate-200 bg-gradient-to-r from-slate-50 to-slate-100/50 px-4 py-3 transition-colors hover:from-slate-100 hover:to-slate-100"
        onClick={() => dispatch({ type: "TOGGLE", id: run.id })}
      >
        <CollapseIcon className="h-3.5 w-3.5 shrink-0 text-slate-600" />
        <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} />
        <span className="font-mono text-[11px] text-slate-600">{fmtDate(run.startedAt)}</span>
        <span className="text-xs text-slate-300">·</span>
        <span className="truncate text-[12px] font-medium text-slate-700">
          {run.input.product_name}{" "}
          <span className="font-mono text-slate-400">({run.input.product_code})</span>
        </span>
        <span
          className={`hidden shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium sm:inline-flex ${
            run.mode === "serpapi"
              ? "bg-amber-100 text-amber-700"
              : run.mode === "deep"
                ? "bg-indigo-100 text-indigo-700"
                : "bg-slate-100 text-slate-500"
          }`}
          title={
            run.mode === "serpapi"
              ? "LLM tạo query → SerpAPI → LLM chọn theo rule → crawl 3 hop ra manual"
              : run.mode === "deep"
                ? "Tìm trang hỗ trợ/chi tiết → trích manual 3 hop"
                : "Tìm trang chủ → crawl đầy đủ"
          }
        >
          {run.mode === "serpapi" ? (
            <Filter className="h-2.5 w-2.5" />
          ) : run.mode === "deep" ? (
            <FileSearch className="h-2.5 w-2.5" />
          ) : (
            <Compass className="h-2.5 w-2.5" />
          )}
          {run.mode === "serpapi" ? "serpapi" : run.mode === "deep" ? "support page" : "homepage"}
        </span>
        {run.site?.url && (
          <span
            className="hidden shrink-0 items-center gap-1 rounded-full bg-indigo-100 px-2 py-0.5 font-mono text-[10px] text-indigo-700 md:inline-flex"
            title={run.site.url}
          >
            <Compass className="h-2.5 w-2.5" />
            {run.site.domain || run.site.url}
          </span>
        )}

        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          {run.manuals.length > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-400/50 bg-emerald-400/20 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
              <FileDown className="h-2.5 w-2.5" />
              {run.manuals.length} manual{run.manuals.length !== 1 ? "s" : ""}
            </span>
          )}
          {run.status === "running" && (
            <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/25 bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-500">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              running
            </span>
          )}
          {run.status === "error" && (
            <span className="rounded-full border border-rose-400/50 bg-rose-400/20 px-2 py-0.5 text-[10px] font-medium text-rose-600">
              error
            </span>
          )}
          <button
            className="rounded p-1 text-slate-500 transition-colors hover:bg-red-100 hover:text-red-600"
            title="Remove this run"
            onClick={(e) => {
              e.stopPropagation();
              dispatch({ type: "REMOVE", id: run.id });
            }}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* ── body ── */}
      {!run.collapsed && (
        <div className="space-y-3 border-t border-slate-200 bg-slate-50 p-3">
          {run.error && (
            <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{run.error}</span>
            </div>
          )}

          {/* Discovered page (official homepage, or support/detail page) */}
          {run.site?.url ? (
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-2.5">
              <div className="mb-1 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-indigo-500">
                {run.mode === "deep" ? (
                  <FileSearch className="h-3 w-3" />
                ) : (
                  <Compass className="h-3 w-3" />
                )}
                {run.mode === "deep" ? "Support / detail page" : "Official site"}
                {run.site.brand ? ` · ${run.site.brand}` : ""}
              </div>
              <a
                href={run.site.url}
                target="_blank"
                rel="noreferrer"
                className="block break-all text-[13px] font-medium text-indigo-700 underline-offset-2 hover:underline"
              >
                {run.site.url}
              </a>
              {run.site.summary && (
                <p className="mt-1 text-[11px] italic text-slate-500">{run.site.summary}</p>
              )}
            </div>
          ) : (
            run.status !== "running" &&
            run.site &&
            run.site.found === false && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                {run.site.reason ||
                  (run.mode === "deep"
                    ? "No support/detail page found for this product."
                    : "No official site found for this product.")}
              </div>
            )
          )}

          {/* Manuals found by the crawl on the discovered site */}
          {run.manuals.length > 0
            ? <ManualList manuals={run.manuals} />
            : run.status !== "running" && run.site?.url && (
                <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  {run.mode === "deep"
                    ? "No manual found on the support/detail page."
                    : "No manual found on the official site."}
                </div>
              )}

          {run.queries.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-slate-400">
                <Search className="h-3 w-3" />
                queries
              </span>
              {run.queries.map((q, i) => (
                <span
                  key={i}
                  className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-600"
                >
                  {q}
                </span>
              ))}
            </div>
          )}

          <SourceList sources={run.sources} />

          {/* ── log timeline ── */}
          <details className="rounded-lg border border-slate-200 bg-white" open>
            <summary className="cursor-pointer select-none px-3 py-1.5 text-[11px] font-semibold text-slate-600">
              Log timeline ({run.logs.length})
            </summary>
            <div className="max-h-[360px] overflow-y-auto border-t border-slate-200 bg-slate-50 p-2 scroll-smooth">
              {run.logs.length === 0 ? (
                <div className="py-2 text-center text-[11px] text-slate-400">No events yet…</div>
              ) : (
                groupByStep(run.logs).map((group, i) => (
                  <StepGroupBlock key={i} group={group} />
                ))
              )}
              {run.status === "running" && (
                <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-600">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Đang chạy…
                </div>
              )}
            </div>
          </details>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function WebSearchCrawlFinder() {
  const [runs, dispatch] = useReducer(reducer, undefined, loadRuns);
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // Write the whole run history (what's in localStorage) to a JSON file in the
  // FE public/ folder via the backend, since only the browser can read its own
  // localStorage.
  const exportHistory = useCallback(async () => {
    if (runs.length === 0 || exporting) return;
    setExporting(true);
    try {
      const r = await exportSiteCrawlHistory(runs);
      alert(
        `Đã ghi ${r.count} run (${(r.bytes / 1024).toFixed(1)} KB) vào:\n${r.path}\n\n` +
          `Mở qua dev server: ${r.served_url}`
      );
    } catch (err) {
      alert(`Export lỗi: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setExporting(false);
    }
  }, [runs, exporting]);

  // ── Form fields ──
  const [productName, setProductName] = useState("");
  const [productCode, setProductCode] = useState("");
  const [searchPrompt, setSearchPrompt] = useState(DEFAULT_SEARCH_PROMPT);
  // SerpAPI mode prompts: the LLM is used twice — once to GENERATE the queries
  // and once to EVALUATE/SELECT the returned results against these rules.
  const [queryPrompt, setQueryPrompt] = useState(DEFAULT_SERP_QUERY_PROMPT);
  const [evalRule, setEvalRule] = useState(DEFAULT_SERP_EVAL_RULE);
  // Which pipeline to run:
  //   "site"    → web-search the homepage, then crawl it (default).
  //   "deep"    → web-search the support/detail page, then 3-hop extract.
  //   "serpapi" → LLM builds queries → SerpAPI → LLM evaluates/selects.
  const [mode, setMode] = useState<RunMode>("site");

  // Switching between the site/deep modes swaps the search prompt to the
  // matching default — but only while it is still an unedited default, so a
  // custom prompt survives. SerpAPI mode has its own (separate) prompt fields.
  const onSelectMode = (next: RunMode) => {
    setMode(next);
    if (next === "serpapi") return;
    setSearchPrompt((cur) => {
      const untouched =
        cur.trim() === "" ||
        cur === DEFAULT_SEARCH_PROMPT ||
        cur === DEFAULT_SUPPORT_PROMPT;
      if (!untouched) return cur;
      return next === "deep" ? DEFAULT_SUPPORT_PROMPT : DEFAULT_SEARCH_PROMPT;
    });
  };

  // ── Quick-fill presets (Japanese product dataset) ──
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<string>("");

  useEffect(() => {
    fetch("/sitecrawl-presets.json")
      .then((res) => (res.ok ? res.json() : []))
      .then((data: Preset[]) => setPresets(Array.isArray(data) ? data : []))
      .catch(() => setPresets([]));
  }, []);

  const onPresetChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const idx = e.target.value;
    setSelectedPreset(idx);
    if (idx === "") return;
    const preset = presets[Number(idx)];
    if (!preset) return;
    setProductName(preset.product_name);
    setProductCode(preset.product_code);
  };

  // ── Model selection ──
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);
  // Whether the backend has SERPAPI_API_KEY configured; SerpAPI mode needs it.
  const [serpApiAvailable, setSerpApiAvailable] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listWebSearchModels();
        if (cancelled) return;
        setModels(res.models);
        setSelectedModel(res.default || res.models[0]?.name || "");
        setModelsError(res.error);
        setSerpApiAvailable(res.serpapi_available);
        // If SerpAPI mode was pre-selected but the key is missing, fall back.
        if (!res.serpapi_available) setMode((m) => (m === "serpapi" ? "site" : m));
      } catch (err) {
        if (cancelled) return;
        setModelsError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setModelsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const modelOptions = useMemo(() => {
    if (!selectedModel || models.some((m) => m.name === selectedModel)) return models;
    return [
      { name: selectedModel, display_name: `${selectedModel} (current)`, description: "" },
      ...models,
    ];
  }, [models, selectedModel]);

  // Persist run history.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(runs));
    } catch {
      /* quota / serialization — non-fatal for a POC */
    }
  }, [runs]);

  // Close any open stream on unmount.
  useEffect(() => () => esRef.current?.close(), []);

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (running) return;

      const product_name = productName.trim();
      const product_code = productCode.trim();
      if (!product_name || !product_code) {
        alert("Vui lòng nhập đủ Product name và Product code (model).");
        return;
      }

      // Build the per-mode payload + record-input. SerpAPI mode carries two
      // prompts (query generation + result evaluation); site/deep carry one.
      let input: ScInput;
      let start: () => Promise<JobCreatedResponse>;
      if (mode === "serpapi") {
        const qp = queryPrompt.trim();
        const rule = evalRule.trim();
        if (!qp || !rule) {
          alert("Vui lòng nhập đủ prompt tạo query và bộ rule đánh giá.");
          return;
        }
        const serpInput: SerpCrawlInput = {
          product_name,
          product_code,
          query_prompt: qp,
          eval_rule: rule,
          model: selectedModel || undefined,
        };
        input = serpInput;
        start = () => startSerpCrawl(serpInput);
      } else {
        const sp = searchPrompt.trim();
        if (!sp) {
          alert("Vui lòng nhập prompt tìm kiếm.");
          return;
        }
        const siteInput: SiteCrawlInput = {
          product_name,
          product_code,
          search_prompt: sp,
          model: selectedModel || undefined,
        };
        input = siteInput;
        start = mode === "deep" ? () => startDeepCrawl(siteInput) : () => startSiteCrawl(siteInput);
      }

      esRef.current?.close();
      setRunning(true);

      const runId = generateId();
      dispatch({
        type: "ADD_RUN",
        run: {
          id: runId,
          startedAt: new Date().toISOString(),
          mode,
          input,
          logs: [],
          manuals: [],
          site: null,
          sources: [],
          queries: [],
          status: "running",
          collapsed: false,
        },
      });

      const fail = (msg: string) => {
        dispatch({ type: "PATCH", id: runId, patch: { status: "error", error: msg } });
        setRunning(false);
      };

      try {
        const { job_id, stream_url } = await start();
        dispatch({ type: "PATCH", id: runId, patch: { jobId: job_id } });

        const es = new EventSource(stream_url);
        esRef.current = es;

        es.addEventListener("progress", (ev) => {
          const evt: ProgressEvent = JSON.parse((ev as MessageEvent).data);
          dispatch({
            type: "APPEND_LOG",
            id: runId,
            log: {
              kind: "progress",
              step: evt.step,
              status: evt.status,
              message: evt.message,
              ts: evt.timestamp,
            },
          });
          const data = (evt.data ?? {}) as ScProgressData;
          const patch: Partial<ScRun> = {};
          if (data.site) patch.site = data.site;
          if (Array.isArray(data.manuals) && data.manuals.length > 0)
            patch.manuals = data.manuals;
          if (Array.isArray(data.sources)) patch.sources = data.sources;
          if (Array.isArray(data.queries)) patch.queries = data.queries;
          if (Object.keys(patch).length > 0) dispatch({ type: "PATCH", id: runId, patch });
        });

        es.addEventListener("log", (ev) => {
          const evt: LogEvent = JSON.parse((ev as MessageEvent).data);
          dispatch({
            type: "APPEND_LOG",
            id: runId,
            log: {
              kind: "log",
              step: evt.step ?? undefined,
              level: evt.level,
              message: evt.message,
              ts: evt.timestamp,
            },
          });
        });

        es.addEventListener("completion", async (ev) => {
          const evt: CompletionEvent = JSON.parse((ev as MessageEvent).data);
          es.close();
          setRunning(false);

          if (!evt.success) {
            dispatch({
              type: "PATCH",
              id: runId,
              patch: { status: "error", error: evt.error ?? "No manual found" },
            });
            return;
          }

          // Pull the canonical result for the full (inline) manual content.
          let manuals: ManualEntry[] | undefined;
          try {
            const final =
              mode === "serpapi"
                ? await getSerpCrawlResult(job_id)
                : mode === "deep"
                  ? await getDeepCrawlResult(job_id)
                  : await getSiteCrawlResult(job_id);
            manuals = manualsFromResult(final.manual);
          } catch {
            /* keep manuals captured from progress events */
          }
          dispatch({
            type: "PATCH",
            id: runId,
            patch: { status: "done", ...(manuals ? { manuals } : {}) },
          });
        });

        es.onerror = () => {
          if (es.readyState === EventSource.CLOSED) {
            es.close();
            fail("Connection to server lost");
          }
        };
      } catch (err) {
        fail(err instanceof Error ? err.message : String(err));
      }
    },
    [running, productName, productCode, searchPrompt, queryPrompt, evalRule, selectedModel, mode]
  );

  return (
    <div className="flex flex-col gap-5">
      {/* ── Model selector ── */}
      <div className="card">
        <div className="card-body flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600/10">
              <Cpu className="h-4 w-4 text-brand-600" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-slate-800">Model</h2>
              <p className="text-xs text-slate-400">
                Gemini model dùng cho web-search tìm trang chính chủ
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:ml-auto">
            {!modelsLoading && models.length > 0 && (
              <span className="hidden rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500 sm:inline">
                {models.length} models
              </span>
            )}
            {modelsLoading ? (
              <span className="flex items-center gap-2 text-xs text-slate-400">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Đang tải models…
              </span>
            ) : (
              <select
                className="input w-full sm:w-[320px]"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                disabled={running}
                aria-label="Gemini model"
              >
                {modelOptions.length === 0 && <option value="">(không có model)</option>}
                {modelOptions.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.display_name && m.display_name !== m.name
                      ? `${m.display_name} — ${m.name}`
                      : m.name}
                  </option>
                ))}
              </select>
            )}
          </div>
          {modelsError && (
            <p className="w-full text-xs text-amber-600">
              Không lấy được danh sách models: {modelsError}. Vẫn dùng model mặc định.
            </p>
          )}
        </div>
      </div>

      {/* ── Search form ── */}
      <form className="card" onSubmit={submit}>
        <div className="card-header flex items-center gap-2">
          <Compass className="h-4 w-4 text-brand-600" />
          <h2 className="text-base font-semibold text-slate-900">
            Web Search + Crawl — tìm trang chính chủ rồi cào manual
          </h2>
        </div>
        <div className="card-body grid grid-cols-1 gap-4 md:grid-cols-3">
          {presets.length > 0 && (
            <div className="md:col-span-3">
              <label className="label" htmlFor="sc_preset">
                Preset (sản phẩm tiếng Nhật)
              </label>
              <select
                id="sc_preset"
                className="input"
                value={selectedPreset}
                onChange={onPresetChange}
                disabled={running}
              >
                <option value="">— Chọn preset có sẵn —</option>
                {presets.map((p, i) => (
                  <option key={i} value={i}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="md:col-span-2">
            <label className="label" htmlFor="sc_product_name">
              Product name
            </label>
            <input
              id="sc_product_name"
              className="input"
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="例: ドラム式洗濯乾燥機"
              disabled={running}
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="sc_product_code">
              Product code / model
            </label>
            <input
              id="sc_product_code"
              className="input"
              value={productCode}
              onChange={(e) => setProductCode(e.target.value)}
              placeholder="例: NA-LX129CL"
              disabled={running}
              required
            />
          </div>
          {/* ── Pipeline mode selector (homepage / support page / SerpAPI) ── */}
          <div className="md:col-span-3">
            <span className="label">Chế độ tìm kiếm</span>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {MODE_OPTIONS.map((opt) => {
                const active = mode === opt.id;
                const Icon = opt.icon;
                const unavailable = opt.id === "serpapi" && !serpApiAvailable;
                const blocked = running || unavailable;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    disabled={blocked}
                    title={unavailable ? "Backend chưa cấu hình SERPAPI_API_KEY" : undefined}
                    onClick={() => onSelectMode(opt.id)}
                    className={`flex items-start gap-2.5 rounded-lg border p-3 text-left transition-colors ${
                      active ? opt.activeClass : "border-slate-200 bg-slate-50 hover:bg-slate-100"
                    } ${blocked ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
                  >
                    <Icon
                      className={`mt-0.5 h-4 w-4 shrink-0 ${
                        active ? opt.iconClass : "text-slate-400"
                      }`}
                    />
                    <span>
                      <span className="block text-sm font-medium text-slate-800">
                        {opt.title}
                      </span>
                      <span className="mt-0.5 block text-xs text-slate-400">
                        {unavailable ? "Cần cấu hình SERPAPI_API_KEY ở backend." : opt.desc}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Prompts: single search prompt (site/deep) OR query + rule (serpapi) ── */}
          {mode === "serpapi" ? (
            <>
              <div className="md:col-span-3">
                <div className="flex items-center justify-between">
                  <label className="label" htmlFor="sc_query_prompt">
                    Prompt tạo query (LLM #1 → SerpAPI)
                  </label>
                  <button
                    type="button"
                    className="text-xs text-slate-400 transition-colors hover:text-slate-600"
                    onClick={() => setQueryPrompt(DEFAULT_SERP_QUERY_PROMPT)}
                    disabled={running}
                  >
                    Reset về mặc định
                  </button>
                </div>
                <textarea
                  id="sc_query_prompt"
                  className="input min-h-[120px] font-mono text-[12px] leading-relaxed"
                  value={queryPrompt}
                  onChange={(e) => setQueryPrompt(e.target.value)}
                  disabled={running}
                  required
                />
                <p className="mt-1 text-xs text-slate-400">
                  LLM dùng prompt này để sinh các câu query (theo ngôn ngữ, tên + model) gửi sang
                  SerpAPI.
                </p>
              </div>
              <div className="md:col-span-3">
                <div className="flex items-center justify-between">
                  <label className="label" htmlFor="sc_eval_rule">
                    Bộ rule đánh giá / chọn kết quả (LLM #2)
                  </label>
                  <button
                    type="button"
                    className="text-xs text-slate-400 transition-colors hover:text-slate-600"
                    onClick={() => setEvalRule(DEFAULT_SERP_EVAL_RULE)}
                    disabled={running}
                  >
                    Reset về mặc định
                  </button>
                </div>
                <textarea
                  id="sc_eval_rule"
                  className="input min-h-[140px] font-mono text-[12px] leading-relaxed"
                  value={evalRule}
                  onChange={(e) => setEvalRule(e.target.value)}
                  disabled={running}
                  required
                />
                <p className="mt-1 text-xs text-slate-400">
                  LLM dùng bộ rule này để chọn các kết quả SerpAPI cần xét; mỗi kết quả sau đó
                  được crawl 3 hop để ra link manual cuối. Dùng{" "}
                  <code className="rounded bg-slate-100 px-1">{"{product_name}"}</code> và{" "}
                  <code className="rounded bg-slate-100 px-1">{"{product_code}"}</code> để chèn dữ
                  liệu sản phẩm.
                </p>
              </div>
            </>
          ) : (
            <div className="md:col-span-3">
              <div className="flex items-center justify-between">
                <label className="label" htmlFor="sc_prompt">
                  {mode === "deep"
                    ? "Search prompt (web search → trang hỗ trợ/chi tiết)"
                    : "Search prompt (web search → trang chính chủ)"}
                </label>
                <button
                  type="button"
                  className="text-xs text-slate-400 transition-colors hover:text-slate-600"
                  onClick={() =>
                    setSearchPrompt(mode === "deep" ? DEFAULT_SUPPORT_PROMPT : DEFAULT_SEARCH_PROMPT)
                  }
                  disabled={running}
                >
                  Reset về mặc định
                </button>
              </div>
              <textarea
                id="sc_prompt"
                className="input min-h-[120px] font-mono text-[12px] leading-relaxed"
                value={searchPrompt}
                onChange={(e) => setSearchPrompt(e.target.value)}
                disabled={running}
                required
              />
              <p className="mt-1 text-xs text-slate-400">
                Prompt này được gửi nguyên văn xuống backend. Dùng{" "}
                <code className="rounded bg-slate-100 px-1">{"{product_name}"}</code> và{" "}
                <code className="rounded bg-slate-100 px-1">{"{product_code}"}</code> để chèn dữ
                liệu sản phẩm.
              </p>
            </div>
          )}
          <div className="md:col-span-3 flex justify-end">
            <button type="submit" className="btn-primary" disabled={running}>
              <Search className="h-4 w-4" />
              {running
                ? "Running…"
                : mode === "serpapi"
                  ? "Start SerpAPI + 3-hop extract"
                  : mode === "deep"
                    ? "Start support-page + extract"
                    : "Start search + crawl"}
            </button>
          </div>
        </div>
      </form>

      {runs.length > 0 ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-700">Search History</h3>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              {runs.length}
            </span>
            <button
              className="ml-auto flex items-center gap-1 text-xs text-brand-600 transition-colors hover:text-brand-700 disabled:opacity-50"
              onClick={exportHistory}
              disabled={exporting}
              title="Ghi toàn bộ lịch sử ra frontend/public/sitecrawl-history.json"
            >
              <Download className="h-3.5 w-3.5" />
              {exporting ? "Exporting…" : "Export JSON"}
            </button>
            <button
              className="flex items-center gap-1 text-xs text-slate-400 transition-colors hover:text-slate-600"
              onClick={() => dispatch({ type: "CLEAR_ALL" })}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear all
            </button>
          </div>
          <div className="space-y-3">
            {runs.map((run) => (
              <RunSection key={run.id} run={run} dispatch={dispatch} />
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center">
          <Compass className="h-8 w-8 text-slate-300" />
          <div>
            <p className="text-sm font-medium text-slate-500">Chưa có lần tìm nào</p>
            <p className="mt-1 text-xs text-slate-400">
              Nhập tên sản phẩm + model, rồi nhấn "Start search + crawl": web search tìm trang
              chính chủ → cào trang đó để lấy manual.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function manualsFromResult(manual: ManualResult | undefined): ManualEntry[] {
  if (!manual || manual.type === "not_found") return [];
  if (manual.manuals && manual.manuals.length > 0) return manual.manuals;
  return [{ type: manual.type, url: manual.url, content: manual.content }];
}
