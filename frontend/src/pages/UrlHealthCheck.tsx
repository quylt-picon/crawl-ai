import { useCallback, useReducer, useRef, useState } from "react";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  FileText,
  FileUp,
  Loader2,
  Play,
  Trash2,
  X,
} from "lucide-react";

// ─── Utilities ────────────────────────────────────────────────────────────

function generateId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // Fallback for browsers that don't support crypto.randomUUID
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

// ─── Types ────────────────────────────────────────────────────────────────────

type UrlStatus = "valid" | "dead" | "blocked" | "error";

interface HcEvent {
  type: string;
  job_id?: string;
  url: string | null;
  uid: string;
  step: string;
  message: string;
  dt_ms: number | null;
  phase?: string;
  timestamp?: string;
  // result fields
  status?: UrlStatus;
  status_code?: number | null;
  response_time_ms?: number;
  via?: string;
  // legend fields
  uid_to_url?: Record<string, string>;
  // summary fields
  total_ms?: number;
  counts?: { valid: number; dead: number; blocked: number; error: number; total: number };
}

type RunView = "timeline" | "byurl";

interface Run {
  id: string;
  startedAt: string;
  urls: string[];
  events: HcEvent[];
  status: "running" | "done" | "error";
  collapsed: boolean;
  view: RunView;
}

// ─── State management ─────────────────────────────────────────────────────────

type Action =
  | { type: "ADD_RUN"; run: Run }
  | { type: "APPEND_EVENT"; id: string; event: HcEvent }
  | { type: "SET_STATUS"; id: string; status: Run["status"] }
  | { type: "TOGGLE"; id: string }
  | { type: "SET_VIEW"; id: string; view: RunView }
  | { type: "REMOVE"; id: string }
  | { type: "CLEAR_ALL" };

function reducer(state: Run[], action: Action): Run[] {
  switch (action.type) {
    case "ADD_RUN":
      return [action.run, ...state];
    case "APPEND_EVENT":
      return state.map((r) =>
        r.id === action.id ? { ...r, events: [...r.events, action.event] } : r
      );
    case "SET_STATUS":
      return state.map((r) =>
        r.id === action.id ? { ...r, status: action.status } : r
      );
    case "TOGGLE":
      return state.map((r) =>
        r.id === action.id ? { ...r, collapsed: !r.collapsed } : r
      );
    case "SET_VIEW":
      return state.map((r) =>
        r.id === action.id ? { ...r, view: action.view } : r
      );
    case "REMOVE":
      return state.filter((r) => r.id !== action.id);
    case "CLEAR_ALL":
      return [];
    default:
      return state;
  }
}

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<UrlStatus, string> = {
  valid: "bg-emerald-400/20 text-emerald-600 border-emerald-400/50",
  dead: "bg-red-400/20 text-red-600 border-red-400/50",
  blocked: "bg-amber-400/20 text-amber-600 border-amber-400/50",
  error: "bg-rose-400/20 text-rose-600 border-rose-400/50",
};

const STATUS_DOT: Record<UrlStatus, string> = {
  valid: "bg-emerald-500",
  dead: "bg-red-500",
  blocked: "bg-amber-500",
  error: "bg-rose-500",
};

const STATUS_LABEL: Record<UrlStatus, string> = {
  valid: "VALID",
  dead: "DEAD",
  blocked: "BLOCKED",
  error: "ERROR",
};

// Warna per uid index (u1=0, u2=1, ...)
const UID_COLORS = [
  "text-amber-400",
  "text-sky-400",
  "text-violet-400",
  "text-pink-400",
  "text-emerald-400",
  "text-orange-400",
  "text-cyan-400",
  "text-rose-400",
];

function uidColor(uid: string): string {
  const n = parseInt(uid.replace("u", ""), 10);
  return isNaN(n) ? "text-slate-400" : UID_COLORS[(n - 1) % UID_COLORS.length];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function parseUrls(input: string): string[] {
  return [
    ...new Set(
      input
        .split(/[\n,]+/)
        .map((u) => u.trim())
        .filter((u) => u.startsWith("http"))
    ),
  ];
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

function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms.toFixed(0)}ms`;
}

// ─── Log line sub-components ──────────────────────────────────────────────────

function SectionDivider({ event }: { event: HcEvent }) {
  return (
    <div className="my-3 select-none">
      <div className="flex items-center gap-2">
        <div className="h-px flex-1 bg-indigo-400/40" />
        <span className="text-indigo-600 text-[10px] font-bold uppercase tracking-widest px-2">
          {event.message}
        </span>
        <div className="h-px flex-1 bg-indigo-400/40" />
      </div>
    </div>
  );
}

function LegendBlock({ event }: { event: HcEvent }) {
  const map = event.uid_to_url ?? {};
  const entries = Object.entries(map);
  return (
    <div className="my-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2">
      <div className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-amber-700">
        URL Registry
      </div>
      <div className="space-y-0.5">
        {entries.map(([uid, url]) => (
          <div key={uid} className="flex items-center gap-2 font-mono">
            <span
              className={`w-7 shrink-0 text-[11px] font-bold ${uidColor(uid)}`}
            >
              [{uid}]
            </span>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-600 text-[11px] truncate hover:text-blue-600 hover:underline"
              title={url}
            >
              {url}
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResultBlock({ event }: { event: HcEvent }) {
  const st = (event.status ?? "error") as UrlStatus;
  return (
    <div
      className={`my-0.5 flex items-center gap-2 rounded border px-2.5 py-1.5 font-mono text-[11px] ${STATUS_BADGE[st]}`}
    >
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[st]}`}
      />
      <span className="w-14 shrink-0 font-bold">{STATUS_LABEL[st]}</span>
      <span className="w-8 shrink-0 text-right opacity-70">
        {event.status_code ?? "—"}
      </span>
      <span className="w-14 shrink-0 text-right opacity-70">
        {event.response_time_ms != null ? fmtMs(event.response_time_ms) : "—"}
      </span>
      <span className="shrink-0 text-slate-400 text-[10px]">
        ({event.via ?? "—"})
      </span>
      <a
        href={event.url || "#"}
        target="_blank"
        rel="noopener noreferrer"
        className="truncate text-slate-700 ml-1 hover:text-blue-600 hover:underline"
        title={event.url || ""}
      >
        {event.url}
      </a>
    </div>
  );
}

function SummaryBlock({ event }: { event: HcEvent }) {
  const c = event.counts;
  return (
    <div className="mt-3 rounded-lg border border-slate-300 bg-gradient-to-r from-slate-100 to-slate-50 px-3 py-2">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[11px] text-slate-700 font-semibold">
          Run complete
        </span>
        {event.total_ms != null && (
          <span className="text-[11px] text-slate-600">
            {fmtMs(event.total_ms)}
          </span>
        )}
        {c && (
          <div className="flex gap-1.5 flex-wrap">
            {c.valid > 0 && (
              <span
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_BADGE.valid}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT.valid}`} />
                {c.valid} valid
              </span>
            )}
            {c.dead > 0 && (
              <span
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_BADGE.dead}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT.dead}`} />
                {c.dead} dead
              </span>
            )}
            {c.blocked > 0 && (
              <span
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_BADGE.blocked}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT.blocked}`} />
                {c.blocked} blocked
              </span>
            )}
            {c.error > 0 && (
              <span
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_BADGE.error}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT.error}`} />
                {c.error} error
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ErrorBlock({ event }: { event: HcEvent }) {
  return (
    <div className="mt-1 rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 font-mono text-[11px]">
      <span className="text-rose-600 font-bold">[{event.step}]</span>{" "}
      <span className="text-rose-600">{event.message}</span>
    </div>
  );
}

function LogLine({ event }: { event: HcEvent }) {
  if (event.type === "section") return <SectionDivider event={event} />;
  if (event.type === "legend") return <LegendBlock event={event} />;
  if (event.type === "result") return <ResultBlock event={event} />;
  if (event.type === "summary") return <SummaryBlock event={event} />;
  if (event.type === "error") return <ErrorBlock event={event} />;

  const col = uidColor(event.uid);

  return (
    <div className="group flex items-start gap-0 py-[1.5px] leading-5 font-mono text-[11px] rounded px-1 hover:bg-slate-200/40">
      <span className={`${col} w-[38px] shrink-0 font-bold`}>
        [{event.uid}]
      </span>
      {event.dt_ms != null ? (
        <span className="text-cyan-600/80 w-[72px] shrink-0 text-right pr-2 tabular-nums">
          [{event.dt_ms.toFixed(0)}ms]
        </span>
      ) : (
        <span className="w-[72px] shrink-0" />
      )}
      <span className="text-slate-700 w-[148px] shrink-0 pr-2 truncate">
        {event.step}
      </span>
      <span className="text-slate-600 break-all">{event.message}</span>
    </div>
  );
}

// ─── By-URL grouped view ──────────────────────────────────────────────────────

function ByUrlView({ run }: { run: Run }) {
  const legend = run.events.find((e) => e.type === "legend");
  const uidToUrl = legend?.uid_to_url ?? {};

  // Collect ordered uids, preserving first-seen order
  const seenUids: string[] = [];
  const byUid: Record<string, HcEvent[]> = {};
  for (const ev of run.events) {
    if (ev.uid === "----" || !ev.uid) continue;
    if (!seenUids.includes(ev.uid)) seenUids.push(ev.uid);
    (byUid[ev.uid] ??= []).push(ev);
  }

  if (seenUids.length === 0) {
    return (
      <div className="text-slate-600 text-[12px] py-4 text-center">
        No per-URL events yet…
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {seenUids.map((uid) => {
        const url = uidToUrl[uid] ?? run.urls.find(Boolean) ?? uid;
        const events = byUid[uid] ?? [];
        const result = events.find((e) => e.type === "result");
        const col = uidColor(uid);
        return (
          <div
            key={uid}
            className="rounded-lg border border-slate-300 overflow-hidden bg-white"
          >
            {/* URL header */}
            <div className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-slate-100 to-slate-50 border-b border-slate-200">
              <span
                className={`font-mono text-[11px] font-bold shrink-0 ${col}`}
              >
                [{uid}]
              </span>
              {result && (
                <span
                  className={`shrink-0 inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-bold ${STATUS_BADGE[result.status as UrlStatus]}`}
                >
                  {STATUS_LABEL[result.status as UrlStatus]}
                  {result.status_code != null && (
                    <span className="opacity-70">{result.status_code}</span>
                  )}
                </span>
              )}
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-600 text-[11px] font-mono truncate hover:text-blue-600 hover:underline"
                title={url}
              >
                {url}
              </a>
              {result?.response_time_ms != null && (
                <span className="ml-auto shrink-0 text-slate-700 text-[10px] tabular-nums font-semibold">
                  {fmtMs(result.response_time_ms)}
                </span>
              )}
            </div>
            {/* Events */}
            <div className="px-2 py-1.5 bg-slate-50">
              {events.map((ev, i) => (
                <LogLine key={i} event={ev} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Run section ──────────────────────────────────────────────────────────────

function RunSection({
  run,
  dispatch,
}: {
  run: Run;
  dispatch: React.Dispatch<Action>;
}) {
  const logEndRef = useRef<HTMLDivElement>(null);
  const results = run.events.filter((e) => e.type === "result");
  const counts: Partial<Record<UrlStatus, number>> = {};
  for (const r of results) {
    const s = r.status as UrlStatus;
    if (s) counts[s] = (counts[s] ?? 0) + 1;
  }
  const summary = run.events.find((e) => e.type === "summary");
  const CollapseIcon = run.collapsed ? ChevronRight : ChevronDown;

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 shadow-md shadow-slate-200/50 bg-white">
      {/* ── Run header ── */}
      <div
        className="flex cursor-pointer select-none items-center gap-2 bg-gradient-to-r from-slate-50 to-slate-100/50 px-4 py-3 hover:from-slate-100 hover:to-slate-100 transition-colors border-b border-slate-200"
        onClick={() => dispatch({ type: "TOGGLE", id: run.id })}
      >
        <CollapseIcon className="h-3.5 w-3.5 shrink-0 text-slate-600" />

        {/* Status indicator */}
        {run.status === "running" ? (
          <span className="h-2 w-2 shrink-0 rounded-full bg-blue-400 animate-pulse" />
        ) : run.status === "error" ? (
          <span className="h-2 w-2 shrink-0 rounded-full bg-red-500" />
        ) : (
          <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-400" />
        )}

        <span className="font-mono text-[11px] text-slate-600">
          {fmtDate(run.startedAt)}
        </span>

        <span className="text-slate-300 text-xs">·</span>
        <span className="text-[11px] text-slate-600">
          {run.urls.length} URL{run.urls.length !== 1 ? "s" : ""}
        </span>

        {summary?.total_ms != null && (
          <>
            <span className="text-slate-300 text-xs">·</span>
            <span className="text-[11px] text-slate-600">
              {fmtMs(summary.total_ms)}
            </span>
          </>
        )}

        {/* Status badges */}
        <div className="flex gap-1 flex-wrap">
          {(["valid", "dead", "blocked", "error"] as UrlStatus[]).map((s) =>
            counts[s] ? (
              <span
                key={s}
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_BADGE[s]}`}
              >
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[s]}`}
                />
                {counts[s]} {s}
              </span>
            ) : null
          )}
          {run.status === "running" && results.length === 0 && (
            <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/25 bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-400">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              running
            </span>
          )}
        </div>

        {/* Right controls */}
        <div
          className="ml-auto flex items-center gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          {!run.collapsed && (
            <div className="mr-1 flex overflow-hidden rounded-md border border-slate-300 text-[10px]">
              <button
                className={`px-2.5 py-1 transition-colors ${
                  run.view === "timeline"
                    ? "bg-blue-500 text-white"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-200"
                }`}
                onClick={() =>
                  dispatch({ type: "SET_VIEW", id: run.id, view: "timeline" })
                }
              >
                Timeline
              </button>
              <button
                className={`px-2.5 py-1 transition-colors border-l border-slate-300 ${
                  run.view === "byurl"
                    ? "bg-blue-500 text-white"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-200"
                }`}
                onClick={() =>
                  dispatch({ type: "SET_VIEW", id: run.id, view: "byurl" })
                }
              >
                By URL
              </button>
            </div>
          )}
          <button
            className="rounded p-1 text-slate-600 transition-colors hover:bg-red-100 hover:text-red-600"
            title="Remove this run"
            onClick={() => dispatch({ type: "REMOVE", id: run.id })}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* ── Log body ── */}
      {!run.collapsed && (
        <div className="max-h-[560px] overflow-y-auto bg-slate-50 p-3 scroll-smooth border-t border-slate-200">
          {run.view === "timeline" ? (
            run.events.map((ev, i) => <LogLine key={i} event={ev} />)
          ) : (
            <ByUrlView run={run} />
          )}

          {run.status === "running" && (
            <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-700">
              <Loader2 className="h-3 w-3 animate-spin" />
              Đang chạy…
            </div>
          )}

          <div ref={logEndRef} />
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function UrlHealthCheck() {
  const [urlInput, setUrlInput] = useState("");
  const [runs, dispatch] = useReducer(reducer, []);
  const [running, setRunning] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const esRef = useRef<EventSource | null>(null);

  const parsedUrls = parseUrls(urlInput);

  const loadPresets = async () => {
    try {
      const res = await fetch("/api/hc/presets");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { urls } = (await res.json()) as { urls: string[] };
      setUrlInput(urls.join("\n"));
    } catch (err) {
      alert(`Cannot load presets: ${err}`);
    }
  };

  const importFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setUrlInput((ev.target?.result as string) ?? "");
    reader.readAsText(file);
    e.target.value = "";
  };

  const runCheck = useCallback(async () => {
    const urls = parseUrls(urlInput);
    console.log("[runCheck] Starting with URLs:", urls);
    if (urls.length === 0 || running) {
      console.log("[runCheck] Returning early - urls empty or running", { urls: urls.length, running });
      return;
    }

    esRef.current?.close();
    setRunning(true);

    const runId = generateId();
    const startedAt = new Date().toISOString();

    dispatch({
      type: "ADD_RUN",
      run: {
        id: runId,
        startedAt,
        urls,
        events: [],
        status: "running",
        collapsed: false,
        view: "timeline",
      },
    });

    try {
      console.log("[runCheck] Making API call to /api/hc/start with", urls.length, "URLs");
      const res = await fetch("/api/hc/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls }),
      });
      console.log("[runCheck] Got response, status:", res.status);
      if (!res.ok) {
        const text = await res.text();
        console.error("[runCheck] Request failed:", text);
        throw new Error(`Server ${res.status}: ${text}`);
      }
      const { stream_url } = (await res.json()) as { stream_url: string };
      console.log("[runCheck] Got stream_url:", stream_url);

      const es = new EventSource(stream_url);
      esRef.current = es;

      es.onmessage = (e) => {
        const event: HcEvent = JSON.parse(e.data as string);
        if (event.type === "done") {
          es.close();
          dispatch({ type: "SET_STATUS", id: runId, status: "done" });
          setRunning(false);
          return;
        }
        dispatch({ type: "APPEND_EVENT", id: runId, event });
        if (event.type === "error") {
          es.close();
          dispatch({ type: "SET_STATUS", id: runId, status: "error" });
          setRunning(false);
        }
      };

      es.onerror = () => {
        es.close();
        dispatch({ type: "SET_STATUS", id: runId, status: "error" });
        dispatch({
          type: "APPEND_EVENT",
          id: runId,
          event: {
            type: "error",
            url: null,
            uid: "----",
            step: "SSE-ERROR",
            message: "Connection to server lost",
            dt_ms: null,
          },
        });
        setRunning(false);
      };
    } catch (err) {
      console.error("[runCheck] Error:", err);
      dispatch({
        type: "APPEND_EVENT",
        id: runId,
        event: {
          type: "error",
          url: null,
          uid: "----",
          step: "CONNECT",
          message: String(err),
          dt_ms: null,
        },
      });
      dispatch({ type: "SET_STATUS", id: runId, status: "error" });
      setRunning(false);
    }
  }, [urlInput, running, dispatch]);

  return (
    <div className="flex flex-col gap-5">
      {/* ── Input card ── */}
      <div className="card">
        <div className="card-header flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600/10">
            <Activity className="h-4 w-4 text-brand-600" />
          </div>
          <div>
            <h2 className="font-semibold text-slate-800">URL Health Check</h2>
            <p className="text-xs text-slate-400">
              Kiểm tra HTTP status, WAF detection và response headers cho nhiều URL cùng lúc.
            </p>
          </div>
        </div>

        <div className="card-body space-y-3">
          {/* Textarea */}
          <div>
            <label className="label">
              URLs{" "}
              <span className="font-normal text-slate-400">
                (mỗi dòng hoặc cách nhau bằng dấu phẩy)
              </span>
            </label>
            <textarea
              className="input min-h-[160px] resize-y font-mono text-[13px] leading-relaxed"
              placeholder={"https://example.com\nhttps://another.com, https://third.com"}
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              spellCheck={false}
            />
          </div>

          {/* Actions row */}
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-ghost text-xs" onClick={loadPresets}>
              <FileText className="h-3.5 w-3.5" />
              Import presets
            </button>

            <button
              className="btn-ghost text-xs"
              onClick={() => fileInputRef.current?.click()}
            >
              <FileUp className="h-3.5 w-3.5" />
              Import file (.txt)
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.csv"
              className="hidden"
              onChange={importFile}
            />

            <div className="ml-auto flex items-center gap-3">
              {parsedUrls.length > 0 && (
                <span className="text-xs text-slate-400">
                  {parsedUrls.length} URL{parsedUrls.length !== 1 ? "s" : ""}
                </span>
              )}
              <button
                className="btn-primary"
                onClick={runCheck}
                disabled={running || parsedUrls.length === 0}
              >
                {running ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Đang chạy…
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" />
                    Run Health Check
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── Run history ── */}
      {runs.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-700">
              Run History
            </h3>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              {runs.length}
            </span>
            <button
              className="ml-auto flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition-colors"
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
      )}

      {runs.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-200 py-16 text-center">
          <Activity className="h-8 w-8 text-slate-300" />
          <div>
            <p className="text-sm font-medium text-slate-500">
              Chưa có lần chạy nào
            </p>
            <p className="text-xs text-slate-400 mt-1">
              Nhập URLs và nhấn "Run Health Check" để bắt đầu.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
