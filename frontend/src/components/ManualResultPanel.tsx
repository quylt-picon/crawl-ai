import { FileDown, FileText, AlertTriangle, Globe } from "lucide-react";
import { useWorkflow } from "@/store/workflow";

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

  return (
    <div className="card border-emerald-200">
      <div className="card-header flex items-center gap-2">
        {manual.type === "link" && <FileDown className="h-4 w-4 text-emerald-600" />}
        {manual.type === "html_url" && <Globe className="h-4 w-4 text-emerald-600" />}
        {manual.type === "inline" && <FileText className="h-4 w-4 text-emerald-600" />}
        <h2 className="text-base font-semibold text-slate-900">Manual found</h2>
        <span className="ml-auto rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
          {manual.type}
        </span>
      </div>
      <div className="card-body space-y-3">
        {manual.url && (
          <a
            href={manual.url}
            target="_blank"
            rel="noreferrer"
            className="block break-all text-sm font-medium text-brand-700 underline-offset-2 hover:underline"
          >
            {manual.url}
          </a>
        )}
        {manual.content && (
          <div className="rounded-lg border border-slate-200 bg-slate-50">
            <pre className="max-h-[28rem] overflow-y-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-relaxed text-slate-700">
              {manual.content}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
