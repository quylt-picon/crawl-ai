import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Cpu,
  FileDown,
  FileText,
  Globe,
  Link2,
  Loader2,
  Network,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { SearchForm } from "@/components/SearchForm";
import {
  getWebSearchResult,
  listWebSearchModels,
  startWebSearch,
  type ModelInfo,
  type SearchInput,
} from "@/lib/api";
import type {
  CompletionEvent,
  LogEvent,
  ManualEntry,
  ManualEntryType,
  ManualResult,
  ProgressEvent,
} from "@/types/events";

// ─── Types ──────────────────────────────────────────────────────────────────

interface WsSource {
  title?: string;
  uri: string;
  domain?: string;
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

interface WsRun {
  id: string;
  jobId?: string;
  startedAt: string;
  input: SearchInput;
  logs: RunLog[];
  manuals: ManualEntry[];
  sources: WsSource[];
  queries: string[];
  summary?: string | null;
  reason?: string | null;
  status: RunStatus;
  error?: string | null;
  collapsed: boolean;
}

/** Shape of the `data` payload on the web_search / finalize progress events. */
interface WsProgressData {
  found?: boolean;
  summary?: string | null;
  reason?: string | null;
  manuals?: ManualEntry[];
  sources?: WsSource[];
  queries?: string[];
}

// ─── State management ─────────────────────────────────────────────────────────

type Action =
  | { type: "HYDRATE"; runs: WsRun[] }
  | { type: "ADD_RUN"; run: WsRun }
  | { type: "APPEND_LOG"; id: string; log: RunLog }
  | { type: "PATCH"; id: string; patch: Partial<WsRun> }
  | { type: "TOGGLE"; id: string }
  | { type: "REMOVE"; id: string }
  | { type: "CLEAR_ALL" };

function reducer(state: WsRun[], action: Action): WsRun[] {
  switch (action.type) {
    case "HYDRATE":
      return action.runs;
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

const STORAGE_KEY = "websearch-runs-v1";

function loadRuns(): WsRun[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const runs = JSON.parse(raw) as WsRun[];
    if (!Array.isArray(runs)) return [];
    // A run left "running" when the page was closed can never resume — flag it.
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
  // Progress lines are the step's own state transitions — render them a touch
  // bolder so the detail (log) lines beneath read as their children.
  const weight = isProgress ? "font-medium text-slate-800" : "text-slate-600";

  return (
    <div className="group flex items-start gap-0 rounded px-1 py-[1.5px] font-mono text-[11px] leading-5 hover:bg-slate-200/40">
      <span className="w-[64px] shrink-0 pr-2 text-right tabular-nums text-cyan-600/70">
        {new Date(log.ts).toLocaleTimeString("vi-VN", { hour12: false })}
      </span>
      <span className={`w-[60px] shrink-0 pr-2 font-bold uppercase ${accent}`}>
        {tag}
      </span>
      {!hideStep && log.step && (
        <span className="w-[110px] shrink-0 truncate pr-2 text-slate-500">
          {log.step}
        </span>
      )}
      <span className={`whitespace-pre-wrap break-words ${weight}`}>{log.message}</span>
    </div>
  );
}

// ─── Step grouping for the log timeline ───────────────────────────────────────

const STEP_LABELS: Record<string, string> = {
  web_search: "1 · Web search",
  review_results: "2 · Review documents",
  finalize: "3 · Finalize",
};

type StepState = "running" | "success" | "error" | "none";

interface StepGroup {
  step: string;
  state: StepState;
  logs: RunLog[];
}

/** Group consecutive log lines by their `step` so the timeline reads as a
 * sequence of phases, each showing exactly what was found within it. */
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
          <div
            key={i}
            className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-2.5"
          >
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
  run: WsRun;
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
        <span className="font-mono text-[11px] text-slate-600">
          {fmtDate(run.startedAt)}
        </span>
        <span className="text-xs text-slate-300">·</span>
        <span className="truncate text-[12px] font-medium text-slate-700">
          {run.input.product_name}{" "}
          <span className="font-mono text-slate-400">({run.input.product_code})</span>
        </span>
        {run.input.model && (
          <span className="hidden shrink-0 items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-500 md:inline-flex">
            <Cpu className="h-2.5 w-2.5" />
            {run.input.model}
          </span>
        )}
        {!run.input.website_url && (
          <span
            className="hidden shrink-0 items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700 sm:inline-flex"
            title="Tìm trên web không giới hạn site"
          >
            <Globe className="h-2.5 w-2.5" />
            open web
          </span>
        )}
        <span
          className={`hidden shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium sm:inline-flex ${
            run.input.use_serpapi
              ? "bg-indigo-100 text-indigo-700"
              : "bg-slate-100 text-slate-500"
          }`}
          title={run.input.use_serpapi ? "SerpAPI + LLM filter" : "Gemini grounded search"}
        >
          {run.input.use_serpapi ? (
            <Network className="h-2.5 w-2.5" />
          ) : (
            <Globe className="h-2.5 w-2.5" />
          )}
          {run.input.use_serpapi ? "SerpAPI" : "Grounded"}
        </span>

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

          {run.summary && (
            <p className="text-[12px] italic text-slate-600">{run.summary}</p>
          )}

          {run.manuals.length > 0 ? (
            <ManualList manuals={run.manuals} />
          ) : (
            run.status !== "running" && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                {run.reason || "No documentation found for this product."}
              </div>
            )
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
                <div className="py-2 text-center text-[11px] text-slate-400">
                  No events yet…
                </div>
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

export default function WebSearchFinder() {
  const [runs, dispatch] = useReducer(reducer, undefined, loadRuns);
  const [running, setRunning] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // ── Model selection + search backend ──
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [serpapiAvailable, setSerpapiAvailable] = useState(false);
  const [useSerpapi, setUseSerpapi] = useState(false);

  // Fetch the usable model list (live, via the server's API key) once on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listWebSearchModels();
        if (cancelled) return;
        setModels(res.models);
        setSelectedModel(res.default || res.models[0]?.name || "");
        setSerpapiAvailable(res.serpapi_available);
        setModelsError(res.error);
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

  // Ensure the currently-selected model is always present as an option, even
  // when it isn't in the fetched list (e.g. fetch failed, or a custom default).
  const modelOptions = useMemo(() => {
    if (!selectedModel || models.some((m) => m.name === selectedModel)) return models;
    return [
      { name: selectedModel, display_name: `${selectedModel} (current)`, description: "" },
      ...models,
    ];
  }, [models, selectedModel]);

  // Persist run history (drop the live EventSource side; runs are plain data).
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
    async (input: SearchInput) => {
      if (running) return;
      // website_url is optional here — when omitted the LLM/SerpAPI searches the
      // open web with just the product name + code.
      if (!input.product_name || !input.product_code) {
        alert("Vui lòng nhập đủ Product name và Product code.");
        return;
      }

      const fullInput: SearchInput = {
        ...input,
        model: selectedModel || undefined,
        use_serpapi: useSerpapi,
      };

      esRef.current?.close();
      setRunning(true);

      const runId = generateId();
      dispatch({
        type: "ADD_RUN",
        run: {
          id: runId,
          startedAt: new Date().toISOString(),
          input: fullInput,
          logs: [],
          manuals: [],
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
        const { job_id, stream_url } = await startWebSearch(fullInput);
        dispatch({ type: "PATCH", id: runId, patch: { jobId: job_id } });

        const es = new EventSource(stream_url);
        esRef.current = es;

        es.addEventListener("progress", (e) => {
          const ev: ProgressEvent = JSON.parse((e as MessageEvent).data);
          dispatch({
            type: "APPEND_LOG",
            id: runId,
            log: {
              kind: "progress",
              step: ev.step,
              status: ev.status,
              message: ev.message,
              ts: ev.timestamp,
            },
          });
          const data = (ev.data ?? {}) as WsProgressData;
          const patch: Partial<WsRun> = {};
          if (Array.isArray(data.manuals)) patch.manuals = data.manuals;
          if (Array.isArray(data.sources)) patch.sources = data.sources;
          if (Array.isArray(data.queries)) patch.queries = data.queries;
          if (data.summary != null) patch.summary = data.summary;
          if (data.reason != null) patch.reason = data.reason;
          if (Object.keys(patch).length > 0)
            dispatch({ type: "PATCH", id: runId, patch });
        });

        es.addEventListener("log", (e) => {
          const ev: LogEvent = JSON.parse((e as MessageEvent).data);
          dispatch({
            type: "APPEND_LOG",
            id: runId,
            log: {
              kind: "log",
              step: ev.step ?? undefined,
              level: ev.level,
              message: ev.message,
              ts: ev.timestamp,
            },
          });
        });

        es.addEventListener("completion", async (e) => {
          const ev: CompletionEvent = JSON.parse((e as MessageEvent).data);
          es.close();
          setRunning(false);

          if (!ev.success) {
            dispatch({
              type: "PATCH",
              id: runId,
              patch: { status: "error", error: ev.error ?? "No documentation found" },
            });
            return;
          }

          // Pull the canonical result for the full (inline) manual content.
          let manuals: ManualEntry[] | undefined;
          try {
            const final = await getWebSearchResult(job_id);
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
    [running, selectedModel, useSerpapi]
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
                Gemini model dùng cho web-search (lấy trực tiếp từ API)
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
        <div className="card-body flex flex-col gap-2 sm:flex-row sm:items-center">
          {/* ── Search backend: SerpAPI toggle ── */}
          <div className="w-full border-t border-slate-100 pt-3">
            <label
              className={`flex items-start gap-2.5 ${
                serpapiAvailable ? "cursor-pointer" : "cursor-not-allowed opacity-60"
              }`}
            >
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                checked={useSerpapi}
                disabled={running || !serpapiAvailable}
                onChange={(e) => setUseSerpapi(e.target.checked)}
              />
              <span className="text-sm">
                <span className="flex items-center gap-1.5 font-medium text-slate-800">
                  <Network className="h-3.5 w-3.5 text-brand-600" />
                  Dùng Web Search API (SerpAPI)
                </span>
                <span className="mt-0.5 block text-xs text-slate-400">
                  {serpapiAvailable
                    ? "Query bằng SerpAPI, sau đó LLM lọc kết quả liên quan và trích xuất đường dẫn. Bỏ chọn = Gemini grounded search."
                    : "Chưa cấu hình SERPAPI_API_KEY ở backend — không thể dùng chế độ này."}
                </span>
              </span>
            </label>
          </div>
        </div>
      </div>

      <SearchForm onSubmit={submit} disabled={running} allowNoSite />

      {runs.length > 0 ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-700">Search History</h3>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              {runs.length}
            </span>
            <button
              className="ml-auto flex items-center gap-1 text-xs text-slate-400 transition-colors hover:text-slate-600"
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
          <Globe className="h-8 w-8 text-slate-300" />
          <div>
            <p className="text-sm font-medium text-slate-500">Chưa có lần tìm nào</p>
            <p className="mt-1 text-xs text-slate-400">
              Nhập thông tin sản phẩm và nhấn "Start search" để LLM tìm tài liệu trên web.
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
