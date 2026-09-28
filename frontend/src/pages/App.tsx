import { useState } from "react";
import { Activity, Compass, FileText, Globe, Sparkles } from "lucide-react";
import { SearchForm } from "@/components/SearchForm";
import { Stepper } from "@/components/Stepper";
import { Timeline } from "@/components/Timeline";
import { ManualResultPanel } from "@/components/ManualResultPanel";
import { WorkflowDiagramModal } from "@/components/WorkflowDiagramModal";
import { useCrawlJob } from "@/hooks/useCrawlJob";
import { useWorkflow } from "@/store/workflow";
import UrlHealthCheck from "@/pages/UrlHealthCheck";
import WebSearchFinder from "@/pages/WebSearchFinder";
import WebSearchCrawlFinder from "@/pages/WebSearchCrawlFinder";

type Tab = "finder" | "websearch" | "sitecrawl" | "health";

export default function App() {
  const { submit } = useCrawlJob();
  const running = useWorkflow((s) => s.running);
  const jobId = useWorkflow((s) => s.jobId);
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("finder");

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-8 md:px-8">
      {/* ── Header ── */}
      <header className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            Crawl AI Toolkit
          </h1>
          <p className="text-sm text-slate-500">
            Product Manual Finder · Web Search Finder · Web Search + Crawl · URL Health Check
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {tab === "finder" && (
            <button
              type="button"
              onClick={() => setWorkflowOpen(true)}
              className="btn-ghost"
            >
              <FileText className="h-4 w-4" />
              View workflow
            </button>
          )}
          {jobId && tab === "finder" && (
            <span className="rounded-full bg-slate-100 px-3 py-1 font-mono text-[11px] text-slate-600">
              job: {jobId.slice(0, 12)}…
            </span>
          )}
        </div>
      </header>

      {/* ── Tab bar ── */}
      <div className="flex gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
        <button
          className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all ${
            tab === "finder"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
          onClick={() => setTab("finder")}
        >
          <Sparkles className="h-4 w-4" />
          Product Manual Finder
        </button>
        <button
          className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all ${
            tab === "websearch"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
          onClick={() => setTab("websearch")}
        >
          <Globe className="h-4 w-4" />
          Web Search Finder
        </button>
        <button
          className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all ${
            tab === "sitecrawl"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
          onClick={() => setTab("sitecrawl")}
        >
          <Compass className="h-4 w-4" />
          Web Search + Crawl
        </button>
        <button
          className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all ${
            tab === "health"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
          onClick={() => setTab("health")}
        >
          <Activity className="h-4 w-4" />
          URL Health Check
        </button>
      </div>

      {/* ── Content ── */}
      {tab === "finder" ? (
        <>
          <SearchForm onSubmit={submit} disabled={running} />
          <ManualResultPanel />
          <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Stepper />
            <Timeline />
          </section>
        </>
      ) : tab === "websearch" ? (
        <WebSearchFinder />
      ) : tab === "sitecrawl" ? (
        <WebSearchCrawlFinder />
      ) : (
        <UrlHealthCheck />
      )}

      <footer className="mt-auto pt-4 text-center text-xs text-slate-400">
        Backend: FastAPI + Crawl4AI + Gemini · Frontend: React + Vite + Tailwind
      </footer>

      <WorkflowDiagramModal
        open={workflowOpen}
        onClose={() => setWorkflowOpen(false)}
      />
    </div>
  );
}
