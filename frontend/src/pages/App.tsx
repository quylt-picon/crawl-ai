import { Sparkles } from "lucide-react";
import { SearchForm } from "@/components/SearchForm";
import { Stepper } from "@/components/Stepper";
import { Timeline } from "@/components/Timeline";
import { ManualResultPanel } from "@/components/ManualResultPanel";
import { useCrawlJob } from "@/hooks/useCrawlJob";
import { useWorkflow } from "@/store/workflow";

export default function App() {
  const { submit } = useCrawlJob();
  const running = useWorkflow((s) => s.running);
  const jobId = useWorkflow((s) => s.jobId);

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-8 md:px-8">
      <header className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            Product Manual Finder
          </h1>
          <p className="text-sm text-slate-500">
            AI agent that crawls a website, searches a product, and extracts its user manual.
          </p>
        </div>
        {jobId && (
          <span className="ml-auto rounded-full bg-slate-100 px-3 py-1 font-mono text-[11px] text-slate-600">
            job: {jobId.slice(0, 12)}…
          </span>
        )}
      </header>

      <SearchForm onSubmit={submit} disabled={running} />

      <ManualResultPanel />

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Stepper />
        <Timeline />
      </section>

      <footer className="mt-auto pt-4 text-center text-xs text-slate-400">
        Backend: FastAPI + Crawl4AI + Gemini · Frontend: React + Vite + Tailwind
      </footer>
    </div>
  );
}
