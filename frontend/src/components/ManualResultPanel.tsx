import { FileDown, FileText, AlertTriangle, Globe } from "lucide-react";
import { useWorkflow } from "@/store/workflow";
import type { ManualEntry, ManualEntryType } from "@/types/events";

const ICON_FOR_TYPE: Record<ManualEntryType, typeof FileDown> = {
  link: FileDown,
  html_url: Globe,
  inline: FileText,
};

export function ManualResultPanel() {
  const manual = useWorkflow((s) => s.manual);
  const running = useWorkflow((s) => s.running);
  const error = useWorkflow((s) => s.error);

  if (running) return null;
  if (!manual && !error) return null;

  if (error) {
    return (
      <div className="card border-rose-200">
        <div className="card-body flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 text-rose-500" />
          <div>
            <p className="text-sm font-medium text-rose-700">Job failed</p>
            <p className="mt-1 text-sm text-slate-600">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!manual || manual.type === "not_found") {
    return (
      <div className="card border-amber-200">
        <div className="card-body flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-500" />
          <div>
            <p className="text-sm font-medium text-amber-700">No manual found</p>
            <p className="mt-1 text-sm text-slate-600">
              The workflow finished but could not locate a manual for this product.
              Try a different product code or website.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // The full multi-manual list comes through /result; fall back to the
  // single-manual fields (populated even when the multi list is absent).
  const entries: ManualEntry[] =
    manual.manuals && manual.manuals.length > 0
      ? manual.manuals
      : [
          {
            type: manual.type as ManualEntryType,
            url: manual.url,
            content: manual.content,
          },
        ];

  return (
    <div className="card border-emerald-200">
      <div className="card-header flex items-center gap-2">
        <FileDown className="h-4 w-4 text-emerald-600" />
        <h2 className="text-base font-semibold text-slate-900">
          Manual{entries.length > 1 ? "s" : ""} found
        </h2>
        <span className="ml-auto rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
          {entries.length}
        </span>
      </div>
      <div className="card-body space-y-3">
        {entries.map((entry, i) => (
          <ManualRow entry={entry} key={i} />
        ))}
      </div>
    </div>
  );
}

function ManualRow({ entry }: { entry: ManualEntry }) {
  const Icon = ICON_FOR_TYPE[entry.type];
  return (
    <div className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-3">
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
          className="block break-all text-sm font-medium text-brand-700 underline-offset-2 hover:underline"
        >
          {entry.url}
        </a>
      )}
      {entry.content && (
        <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50">
          <pre className="max-h-[20rem] overflow-y-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-relaxed text-slate-700">
            {entry.content}
          </pre>
        </div>
      )}
    </div>
  );
}
