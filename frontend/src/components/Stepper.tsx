import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { DetailModal, type DetailModalPayload } from "@/components/DetailModal";
import { cn } from "@/lib/cn";
import {
  STEP_LABELS,
  STEP_ORDER,
  useWorkflow,
} from "@/store/workflow";

export function Stepper() {
  const steps = useWorkflow((s) => s.steps);
  const [selected, setSelected] = useState<DetailModalPayload | null>(null);

  return (
    <>
      <ol className="card">
        <div className="card-header">
          <h2 className="text-base font-semibold text-slate-900">Workflow</h2>
          <p className="mt-1 text-xs text-slate-500">
            Click a step to see what was analyzed and the result.
          </p>
        </div>
        <div className="card-body space-y-3">
          {STEP_ORDER.map((id, index) => {
            const state = steps[id];
            const running = state.status === "running";
            const clickable = state.status !== "pending";
            return (
              <li key={id}>
                <button
                  type="button"
                  disabled={!clickable}
                  onClick={() =>
                    clickable &&
                    setSelected({
                      step: id,
                      status: state.status,
                      message: state.message ?? STEP_LABELS[id],
                      timestamp: state.timestamp ?? new Date().toISOString(),
                      data: state.data ?? null,
                    })
                  }
                  className={cn(
                    "group flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition",
                    running ? "border-brand-200 bg-brand-50/60" : "border-slate-100 bg-white",
                    clickable ? "hover:border-slate-300 hover:bg-slate-50" : "cursor-default"
                  )}
                >
                  <div
                    className={cn(
                      "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                      state.status === "success" && "bg-emerald-100 text-emerald-700",
                      state.status === "error" && "bg-rose-100 text-rose-700",
                      state.status === "running" && "bg-brand-100 text-brand-700",
                      state.status === "pending" && "bg-slate-100 text-slate-500",
                      state.status === "skipped" && "bg-amber-100 text-amber-700"
                    )}
                  >
                    {index + 1}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium text-slate-900">
                        {STEP_LABELS[id]}
                      </span>
                      <StatusBadge status={state.status} />
                    </div>
                    {state.message && (
                      <p className="mt-1 break-words text-xs text-slate-600">{state.message}</p>
                    )}
                  </div>
                  {clickable && (
                    <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-300 transition group-hover:text-slate-500" />
                  )}
                </button>
              </li>
            );
          })}
        </div>
      </ol>

      <DetailModal open={selected !== null} payload={selected} onClose={() => setSelected(null)} />
    </>
  );
}
