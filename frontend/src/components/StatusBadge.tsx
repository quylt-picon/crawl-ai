import { cn } from "@/lib/cn";
import { CheckCircle2, CircleDashed, Loader2, XCircle, MinusCircle } from "lucide-react";
import type { StepStatus } from "@/types/events";

const STYLES: Record<StepStatus, { icon: typeof CircleDashed; cls: string; label: string }> = {
  pending: { icon: CircleDashed, cls: "text-slate-400 bg-slate-100", label: "Pending" },
  running: { icon: Loader2, cls: "text-brand-700 bg-brand-50", label: "Running" },
  success: { icon: CheckCircle2, cls: "text-emerald-700 bg-emerald-50", label: "Success" },
  error: { icon: XCircle, cls: "text-rose-700 bg-rose-50", label: "Error" },
  skipped: { icon: MinusCircle, cls: "text-amber-700 bg-amber-50", label: "Skipped" },
};

export function StatusBadge({ status }: { status: StepStatus }) {
  const { icon: Icon, cls, label } = STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
        cls
      )}
    >
      <Icon className={cn("h-3.5 w-3.5", status === "running" && "animate-spin")} />
      {label}
    </span>
  );
}
