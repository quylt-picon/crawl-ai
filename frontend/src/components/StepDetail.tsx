/**
 * StepDetail — friendly, non-JSON rendering of each workflow step's `data`.
 *
 * Each step picks a dedicated renderer that knows the shape of its payload
 * and lays it out as labeled sections, clickable links, summary stats, and
 * collapsible samples. Raw JSON is available via "Show raw data" in the
 * parent modal for power users.
 */
import { useState, type ReactNode } from "react";
import {
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  FileDown,
  FileText,
  Globe,
  Search,
  XCircle,
} from "lucide-react";
import type { ManualEntry, StepId } from "@/types/events";
import { cn } from "@/lib/cn";
import { MarkdownPanel } from "@/components/MarkdownView";

export function StepDetail({
  step,
  data,
}: {
  step?: StepId;
  data: Record<string, unknown>;
}) {
  switch (step) {
    case "crawl_homepage":
      return <CrawlHomepageView data={data as any} />;
    case "analyze_ui":
      return <AnalyzeUIView data={data as any} />;
    case "search_product":
      return <SearchProductView data={data as any} />;
    case "filter_results":
      return <FilterResultsView data={data as any} />;
    case "find_manual":
      return <FindManualView data={data as any} />;
    case "finalize":
      return <FinalizeView data={data as any} />;
    default:
      return <GenericKVView data={data} />;
  }
}

/* ------------------------------------------------------------------ shared */

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-4 last:mb-0">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
        {title}
      </h3>
      <div>{children}</div>
    </section>
  );
}

function StatGrid({ items }: { items: Array<{ label: string; value: ReactNode }> }) {
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {items.map((it) => (
        <div
          key={it.label}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2"
        >
          <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {it.label}
          </dt>
          <dd className="mt-0.5 text-sm font-semibold text-slate-900">{it.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function KV({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5">
      <span className="w-44 shrink-0 text-xs font-medium text-slate-500">{k}</span>
      <span className="min-w-0 flex-1 text-sm text-slate-800">{children}</span>
    </div>
  );
}

function Link({ href, label }: { href: string; label?: string }) {
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

function Pill({
  tone = "slate",
  children,
}: {
  tone?: "slate" | "emerald" | "rose" | "amber" | "brand";
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        tone === "slate" && "bg-slate-100 text-slate-700",
        tone === "emerald" && "bg-emerald-100 text-emerald-700",
        tone === "rose" && "bg-rose-100 text-rose-700",
        tone === "amber" && "bg-amber-100 text-amber-700",
        tone === "brand" && "bg-brand-100 text-brand-700"
      )}
    >
      {children}
    </span>
  );
}

function Collapsible({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium text-slate-800 hover:bg-slate-50"
      >
        <span>
          {title}
          {typeof count === "number" && (
            <span className="ml-1.5 text-xs text-slate-500">({count})</span>
          )}
        </span>
        <span className="text-xs text-slate-400">{open ? "Hide" : "Show"}</span>
      </button>
      {open && <div className="border-t border-slate-100 p-3">{children}</div>}
    </div>
  );
}

function YesNo({ value }: { value: boolean }) {
  return value ? (
    <Pill tone="emerald">
      <CheckCircle2 className="mr-1 h-3 w-3" /> Yes
    </Pill>
  ) : (
    <Pill tone="rose">
      <XCircle className="mr-1 h-3 w-3" /> No
    </Pill>
  );
}

/* --------------------------------------------------------------- renderers */

function CrawlHomepageView({
  data,
}: {
  data: {
    page_title?: string;
    page_url?: string;
    html_chars?: number;
    link_count?: number;
    links?: LinkRow[];
  };
}) {
  return (
    <>
      <Section title="Page">
        <div className="space-y-1">
          {data.page_title && <KV k="Title">{data.page_title}</KV>}
          {data.page_url && (
            <KV k="URL">
              <Link href={data.page_url} />
            </KV>
          )}
        </div>
      </Section>

      <Section title="What we captured">
        <StatGrid
          items={[
            {
              label: "HTML chars",
              value: (data.html_chars ?? 0).toLocaleString(),
            },
            {
              label: "Links",
              value: data.link_count ?? data.links?.length ?? 0,
            },
          ]}
        />
        <p className="mt-2 text-xs text-slate-500">
          Cookie / consent overlays are auto-dismissed and the page is fully
          scrolled before snapshotting. The cleaned HTML is then handed to the
          AI, which picks the search selectors directly from it — no probing
          JS is run on the page.
        </p>
      </Section>

      {data.links?.length ? (
        <Section title="Links on the homepage">
          <Collapsible title="All links" count={data.links.length}>
            <LinksList links={data.links} />
          </Collapsible>
        </Section>
      ) : null}
    </>
  );
}

function AnalyzeUIView({
  data,
}: {
  data: {
    analysis?: {
      has_search_box?: boolean;
      search_input_selector?: string | null;
      search_button_selector?: string | null;
      search_page_url?: string | null;
    };
    input_sent_summary?: {
      page_title?: string;
      page_url?: string;
      html_chars?: number;
      link_count?: number;
    };
  };
}) {
  const a = data.analysis ?? {};
  const s = data.input_sent_summary ?? {};
  return (
    <>
      <Section title="What the AI analyzed">
        <p className="text-sm text-slate-700">
          We sent the homepage's cleaned HTML (
          {(s.html_chars ?? 0).toLocaleString()} characters,{" "}
          {s.link_count ?? 0} links) and asked the AI to read it and pick the
          search input + button selectors — or, failing that, a link to a
          dedicated search page.
        </p>
      </Section>

      <Section title="AI verdict">
        <div className="space-y-2">
          <KV k="Has a search box?">
            <YesNo value={!!a.has_search_box} />
          </KV>
          {a.search_input_selector && (
            <KV k="Search input selector">
              <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px]">
                {a.search_input_selector}
              </code>
            </KV>
          )}
          {a.search_button_selector && (
            <KV k="Search button selector">
              <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px]">
                {a.search_button_selector}
              </code>
            </KV>
          )}
          {a.search_page_url ? (
            <KV k="Fallback search page URL">
              <Link href={a.search_page_url} />
            </KV>
          ) : (
            <KV k="Fallback search page URL">
              <span className="italic text-slate-500">none</span>
            </KV>
          )}
        </div>
      </Section>
    </>
  );
}

interface LinkRow {
  href: string;
  text?: string;
}

function LinksList({ links }: { links: LinkRow[] }) {
  return (
    <ul className="space-y-1">
      {links.map((l, i) => (
        <li key={i} className="text-sm">
          {l.text && <span className="text-slate-700">{l.text}</span>}{" "}
          {l.text && <span className="text-slate-400">·</span>}{" "}
          <Link href={l.href} />
        </li>
      ))}
    </ul>
  );
}

function SearchProductView({
  data,
}: {
  data: {
    final_url?: string;
    status?: number;
    markdown_chars?: number;
    markdown?: string;
    link_counts?: { internal?: number; external?: number };
    links?: LinkRow[];
  };
}) {
  return (
    <>
      <Section title="Results page">
        <div className="space-y-1">
          {data.final_url && (
            <KV k="URL">
              <Link href={data.final_url} />
            </KV>
          )}
          <KV k="HTTP status">
            <Pill tone={data.status && data.status >= 400 ? "rose" : "emerald"}>
              {data.status ?? "—"}
            </Pill>
          </KV>
        </div>
      </Section>

      <Section title="Content">
        <StatGrid
          items={[
            { label: "Markdown chars", value: (data.markdown_chars ?? 0).toLocaleString() },
            { label: "Internal links", value: data.link_counts?.internal ?? 0 },
            { label: "External links", value: data.link_counts?.external ?? 0 },
          ]}
        />
      </Section>

      {data.markdown ? (
        <Section title="Page content (full markdown)">
          <MarkdownPanel markdown={data.markdown} />
        </Section>
      ) : null}

      {data.links?.length ? (
        <Section title="Links on this page">
          <Collapsible title="All links" count={data.links.length}>
            <LinksList links={data.links} />
          </Collapsible>
        </Section>
      ) : null}
    </>
  );
}

function FilterResultsView({
  data,
}: {
  data: {
    match?: { found?: boolean; product_url?: string | null; confidence?: number | null };
    candidates?: Array<{ url: string; title?: string }>;
    total_links_seen?: number;
  };
}) {
  const m = data.match ?? {};
  return (
    <>
      <Section title="Process">
        <p className="text-sm text-slate-700">
          We scanned <strong>{data.total_links_seen ?? 0}</strong> links on the
          results page, kept the <strong>{data.candidates?.length ?? 0}</strong>{" "}
          that looked product-related, and asked the AI to pick the exact match.
        </p>
      </Section>

      <Section title="AI decision">
        <div className="space-y-2">
          <KV k="Matched a product?">
            <YesNo value={!!m.found} />
          </KV>
          {m.product_url && (
            <KV k="Picked URL">
              <Link href={m.product_url} />
            </KV>
          )}
          {typeof m.confidence === "number" && (
            <KV k="Confidence">
              <Pill tone={m.confidence >= 0.7 ? "emerald" : m.confidence >= 0.4 ? "amber" : "rose"}>
                {(m.confidence * 100).toFixed(0)}%
              </Pill>
            </KV>
          )}
        </div>
      </Section>

      {data.candidates?.length ? (
        <Section title="Candidate links">
          <Collapsible
            title="Candidates shown to the AI"
            count={data.candidates.length}
            defaultOpen={!m.found}
          >
            <ol className="space-y-1.5">
              {data.candidates.map((c, i) => {
                const isPick = m.product_url && c.url === m.product_url;
                return (
                  <li
                    key={i}
                    className={cn(
                      "rounded-lg border px-2 py-1.5 text-sm",
                      isPick
                        ? "border-emerald-200 bg-emerald-50"
                        : "border-slate-100 bg-white"
                    )}
                  >
                    <div className="flex items-start gap-2">
                      {isPick && <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />}
                      <div className="min-w-0">
                        {c.title && <div className="text-slate-800">{c.title}</div>}
                        <Link href={c.url} />
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </Collapsible>
        </Section>
      ) : null}
    </>
  );
}

interface HopRow {
  hop: number;
  url: string;
  final_url?: string;
  markdown_chars?: number;
  link_count?: number;
  extraction?: {
    final?: boolean;
    follow_url?: string | null;
    reason?: string | null;
    manuals?: ManualEntry[];
  };
  extracted_raw?: string;
}

function FindManualView({
  data,
}: {
  data: {
    manuals?: ManualEntry[];
    manual_count?: number;
    hops?: HopRow[];
    hops_used?: number;
    last_markdown?: string;
    last_links?: LinkRow[];
  };
}) {
  const manuals = data.manuals ?? [];
  const hops = data.hops ?? [];
  const found = manuals.length > 0;
  return (
    <>
      <Section title="What the AI found">
        <div className="mb-2 flex items-center gap-2">
          {found ? (
            <Pill tone="emerald">
              <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
              {manuals.length} manual{manuals.length > 1 ? "s" : ""} found
            </Pill>
          ) : (
            <Pill tone="rose">
              <Search className="mr-1 h-3.5 w-3.5" />
              No manual found
            </Pill>
          )}
          <span className="text-xs text-slate-500">
            after {data.hops_used ?? hops.length} hop
            {(data.hops_used ?? hops.length) === 1 ? "" : "s"}
          </span>
        </div>
        {found && (
          <ul className="space-y-2">
            {manuals.map((m, i) => (
              <li key={i}>
                <ManualEntryRow entry={m} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      {hops.length > 0 && (
        <Section title="Extraction hops">
          <ol className="space-y-2">
            {hops.map((h) => (
              <li key={h.hop}>
                <HopRowView hop={h} />
              </li>
            ))}
          </ol>
        </Section>
      )}

      {data.last_markdown ? (
        <Section title="Last page content (full markdown)">
          <MarkdownPanel markdown={data.last_markdown} />
        </Section>
      ) : null}

      {data.last_links?.length ? (
        <Section title="Last page links">
          <Collapsible title="All links" count={data.last_links.length}>
            <LinksList links={data.last_links} />
          </Collapsible>
        </Section>
      ) : null}
    </>
  );
}

function ManualEntryRow({ entry }: { entry: ManualEntry }) {
  const TYPE_META = {
    link: { tone: "emerald" as const, icon: FileDown, label: "Downloadable file" },
    html_url: { tone: "emerald" as const, icon: Globe, label: "Online HTML manual" },
    inline: { tone: "emerald" as const, icon: FileText, label: "Inline content" },
  };
  const meta = TYPE_META[entry.type];
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 px-3 py-2">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Pill tone={meta.tone}>
          <meta.icon className="mr-1 h-3.5 w-3.5" />
          {meta.label}
        </Pill>
        {entry.language && <Pill tone="slate">{entry.language}</Pill>}
        {entry.label && (
          <span className="text-sm font-medium text-slate-800">{entry.label}</span>
        )}
      </div>
      {entry.url && (
        <div className="text-sm">
          <Link href={entry.url} />
        </div>
      )}
      {entry.content && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
            Show inline content ({entry.content.length.toLocaleString()} chars)
          </summary>
          <div className="mt-2">
            <MarkdownPanel markdown={entry.content} />
          </div>
        </details>
      )}
    </div>
  );
}

function HopRowView({ hop }: { hop: HopRow }) {
  const ex = hop.extraction ?? {};
  const isFinal = ex.final !== false;
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone="brand">Hop {hop.hop}</Pill>
        <Pill tone={isFinal ? "emerald" : "amber"}>
          {isFinal ? "final" : "follow-up"}
        </Pill>
        <span className="text-xs text-slate-500">
          {(hop.markdown_chars ?? 0).toLocaleString()} chars · {hop.link_count ?? 0} links
        </span>
      </div>
      <div className="mt-1 text-sm">
        <Link href={hop.url} />
      </div>
      {ex.reason && (
        <p className="mt-1 text-xs italic text-slate-500">Reason: {ex.reason}</p>
      )}
      {ex.follow_url && !isFinal && (
        <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-600">
          <ArrowRight className="h-3 w-3" />
          <Link href={ex.follow_url} label="follow next" />
        </div>
      )}
      {ex.manuals && ex.manuals.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {ex.manuals.map((m, i) => (
            <ManualEntryRow entry={m} key={i} />
          ))}
        </div>
      )}
    </div>
  );
}

function FinalizeView({
  data,
}: {
  data: {
    type?: "link" | "html_url" | "inline" | "not_found";
    url?: string | null;
    content?: string | null;
    content_chars?: number;
    manuals?: ManualEntry[];
  };
}) {
  const t = data.type ?? "not_found";
  const manuals = data.manuals ?? [];
  return (
    <>
      <Section title="Final result">
        <div className="space-y-2">
          <KV k="Result type">
            <Pill tone={t === "not_found" ? "rose" : "emerald"}>
              {t === "link"
                ? "Downloadable file"
                : t === "html_url"
                ? "Online HTML manual"
                : t === "inline"
                ? "Inline content"
                : "No manual found"}
            </Pill>
          </KV>
          <KV k="Manuals collected">{manuals.length}</KV>
          {data.url && (
            <KV k="Primary URL">
              <Link href={data.url} />
            </KV>
          )}
          {(data.content || data.content_chars) && (
            <KV k="Primary content length">
              {(data.content_chars ?? data.content?.length ?? 0).toLocaleString()} characters
            </KV>
          )}
        </div>
      </Section>
      {manuals.length > 0 && (
        <Section title={`All manuals (${manuals.length})`}>
          <ul className="space-y-2">
            {manuals.map((m, i) => (
              <li key={i}>
                <ManualEntryRow entry={m} />
              </li>
            ))}
          </ul>
        </Section>
      )}
      {data.content ? (
        <Section title="Primary manual content (full markdown)">
          <MarkdownPanel markdown={data.content} />
        </Section>
      ) : null}
    </>
  );
}

function GenericKVView({ data }: { data: Record<string, unknown> }) {
  return (
    <Section title="Details">
      <div className="space-y-1">
        {Object.entries(data).map(([k, v]) => (
          <KV k={k} key={k}>
            <span className="break-words text-slate-700">
              {typeof v === "string" ? v : JSON.stringify(v)}
            </span>
          </KV>
        ))}
      </div>
    </Section>
  );
}
