import { useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  STEP_LABELS,
  useWorkflow,
  type TimelineEntry,
} from "@/store/workflow";
import { DetailModal, type DetailModalPayload } from "@/components/DetailModal";

export function Timeline() {
  const timeline = useWorkflow((s) => s.timeline);
  const entries = useMemo(() => timeline.slice().reverse(), [timeline]);
  const [selected, setSelected] = useState<DetailModalPayload | null>(null);

  return (
    <>
      <div className="card">
        <div className="card-header flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Activity log</h2>
            <p className="mt-0.5 text-xs text-slate-500">Click a row to see what was analyzed and the result.</p>
          </div>
          <span className="text-xs text-slate-500">{timeline.length} entries</span>
        </div>
        <div className="card-body max-h-[28rem] overflow-y-auto">
          {entries.length === 0 ? (
            <p className="text-sm text-slate-500">No events yet. Start a search above.</p>
          ) : (
            <ul className="space-y-1">
              {entries.map((entry) => (
                <li key={entry.id}>
                  <TimelineRow entry={entry} onOpen={setSelected} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <DetailModal open={selected !== null} payload={selected} onClose={() => setSelected(null)} />
    </>
  );
}

function TimelineRow({
  entry,
  onOpen,
}: {
  entry: TimelineEntry;
  onOpen: (payload: DetailModalPayload) => void;
}) {
  const time = formatTime(entry.timestamp);
  const stepLabel = entry.step ? STEP_LABELS[entry.step] : null;

  return (
    <button
      type="button"
      onClick={() =>
        onOpen({
          step: entry.step,
          status: entry.status,
          level: entry.level,
          message: entry.message,
          timestamp: entry.timestamp,
          data: entry.data ?? null,
        })
      }
      className={cn(
        "group flex w-full items-start gap-3 rounded-lg border border-transparent px-2 py-1.5 text-left transition hover:border-slate-200 hover:bg-slate-50",
        entry.kind === "log" && entry.level === "error" && "bg-rose-50/40"
      )}
    >
      <span className="mt-0.5 font-mono text-[11px] text-slate-400">{time}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          {stepLabel && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-600">
              {stepLabel}
            </span>
          )}
          {entry.status && (
            <span
              className={cn(
                "rounded px-1.5 py-0.5 font-medium",
                entry.status === "success" && "bg-emerald-100 text-emerald-700",
                entry.status === "error" && "bg-rose-100 text-rose-700",
                entry.status === "running" && "bg-brand-100 text-brand-700",
                entry.status === "pending" && "bg-slate-100 text-slate-600"
              )}
            >
              {entry.status}
            </span>
          )}
          {entry.level && entry.kind === "log" && (
            <span
              className={cn(
                "rounded px-1.5 py-0.5 font-medium",
                entry.level === "info" && "bg-slate-100 text-slate-600",
                entry.level === "warning" && "bg-amber-100 text-amber-700",
                entry.level === "error" && "bg-rose-100 text-rose-700",
                entry.level === "debug" && "bg-slate-100 text-slate-500"
              )}
            >
              {entry.level}
            </span>
          )}
          {entry.data && Object.keys(entry.data).length > 0 && (
            <span className="rounded bg-brand-50 px-1.5 py-0.5 font-medium text-brand-700">
              details
            </span>
          )}
        </div>
        <p className="mt-0.5 break-words text-sm text-slate-800">{entry.message}</p>
      </div>
      <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-300 transition group-hover:text-slate-500" />
    </button>
  );
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return ts;
  }
}
