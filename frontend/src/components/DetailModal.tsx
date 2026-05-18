import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Code2, ExternalLink, X } from "lucide-react";
import type { StepId, StepStatus } from "@/types/events";
import { STEP_LABELS } from "@/store/workflow";
import { StatusBadge } from "@/components/StatusBadge";
import { StepDetail } from "@/components/StepDetail";
import { cn } from "@/lib/cn";

export interface DetailModalPayload {
  step?: StepId;
  status?: StepStatus;
  level?: "info" | "warning" | "error" | "debug";
  message: string;
  timestamp: string;
  data?: Record<string, unknown> | null;
}

interface Props {
  open: boolean;
  payload: DetailModalPayload | null;
  onClose: () => void;
}

export function DetailModal({ open, payload, onClose }: Props) {
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    if (!open) return;
    setShowRaw(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open || !payload) return null;

  const heading = payload.step ? STEP_LABELS[payload.step] : "Log entry";
  const renderedTime = formatTime(payload.timestamp);
  const hasData = !!payload.data && Object.keys(payload.data).length > 0;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4 py-8 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start gap-3 border-b border-slate-100 px-6 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-slate-900">{heading}</h2>
              {payload.status && <StatusBadge status={payload.status} />}
              {payload.level && !payload.status && (
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[11px] font-medium",
                    payload.level === "info" && "bg-slate-100 text-slate-600",
                    payload.level === "warning" && "bg-amber-100 text-amber-700",
                    payload.level === "error" && "bg-rose-100 text-rose-700",
                    payload.level === "debug" && "bg-slate-100 text-slate-500"
                  )}
                >
                  {payload.level}
                </span>
              )}
              <span className="ml-auto font-mono text-[11px] text-slate-400">{renderedTime}</span>
            </div>
            <p className="mt-1 break-words text-sm text-slate-700">{payload.message}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <StepIntro step={payload.step} />

          {hasData ? (
            <StepDetail step={payload.step} data={payload.data!} />
          ) : (
            <p className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm italic text-slate-500">
              No structured detail captured for this entry.
            </p>
          )}

          {hasData && (
            <div className="mt-4 border-t border-slate-100 pt-3">
              <button
                type="button"
                onClick={() => setShowRaw((v) => !v)}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-700"
              >
                <Code2 className="h-3.5 w-3.5" />
                {showRaw ? "Hide raw data" : "Show raw data (advanced)"}
              </button>
              {showRaw && (
                <pre className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-600">
                  {JSON.stringify(payload.data, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

function StepIntro({ step }: { step?: StepId }) {
  if (!step) return null;
  const desc = STEP_DESCRIPTIONS[step];
  if (!desc) return null;
  return (
    <div className="mb-4 rounded-xl border border-brand-100 bg-brand-50/60 px-4 py-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-brand-700">What this step does</h3>
      <p className="mt-1 text-sm text-slate-700">{desc}</p>
    </div>
  );
}

const STEP_DESCRIPTIONS: Record<StepId, string> = {
  crawl_homepage:
    "Opens the homepage with popups auto-dismissed and the page fully scrolled, then captures the final rendered HTML.",
  analyze_ui:
    "Hands the homepage HTML to the AI: does this page have a product search box? If yes, return the search input + button CSS selectors. If no, pick a link to a dedicated search page.",
  search_product:
    "Types the product code into the search input and submits. If the homepage had no search, opens the dedicated search page from step 2 and tries again there. Header/footer/nav are stripped from the results so only the product body is kept.",
  filter_results:
    "Sends the full results markdown plus every link on the page to the AI and asks it to pick the single most relevant product detail URL.",
  find_manual:
    "Opens the product page with header/footer stripped and runs an LLM extraction strategy on it. If the manual lives on a separate support/downloads page, follows that link and extracts again (up to a few hops). Returns every manual found, across languages and variants.",
  finalize:
    "Wraps up the manual list: a download URL is returned directly; an HTML manual is fetched into clean text; inline content is kept as-is. All manuals collected from extraction are preserved.",
};

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return ts;
  }
}

export function LinkOut({ href, label }: { href: string; label?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex max-w-full items-center gap-1 break-all text-brand-700 underline-offset-2 hover:underline"
    >
      <span className="truncate">{label ?? href}</span>
      <ExternalLink className="h-3 w-3 shrink-0" />
    </a>
  );
}
