import { useEffect } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, X } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
}

const VIEWER_PATH = "/manual-search-flow-viewer.html";

export function WorkflowDiagramModal({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
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

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4 py-8 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-full w-full max-w-7xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start gap-3 border-b border-slate-100 px-6 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-slate-900">Manual search workflow</h2>
            <p className="mt-1 text-xs text-slate-500">
              Diagram rendered from manual-search-flow.drawio
            </p>
          </div>
          <div className="flex items-center gap-2">
            <a
              href={VIEWER_PATH}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-800"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open in new tab
            </a>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>
        <div className="min-h-0 flex-1 bg-slate-50">
          <iframe
            title="Manual search workflow"
            src={VIEWER_PATH}
            className="h-[70vh] w-full border-0"
            loading="lazy"
          />
        </div>
      </div>
    </div>,
    document.body
  );
}
