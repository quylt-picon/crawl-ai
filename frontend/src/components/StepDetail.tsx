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
import type { StepId } from "@/types/events";
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
    case "open_product_page":
      return <OpenProductPageView data={data as any} />;
    case "expand_sections":
      return <ExpandSectionsView data={data as any} />;
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

function SourcePill({ source }: { source?: string }) {
  if (!source) return null;
  const tone =
    source === "header" ? "brand" : source === "nav" ? "slate" : "amber";
  return (
    <Pill tone={tone as any}>
      <span className="font-mono text-[10px]">{source}</span>
    </Pill>
  );
}

/* --------------------------------------------------------------- renderers */

interface Counts {
  inputs?: number;
  buttons?: number;
  forms?: number;
  nav_links?: number;
}

interface InputDescriptor {
  selector?: string;
  type?: string;
  placeholder?: string | null;
  aria_label?: string | null;
  visible?: boolean;
  parent_hint?: string | null;
  name?: string | null;
}

interface ButtonDescriptor {
  selector?: string;
  text?: string;
  aria_label?: string | null;
  aria_haspopup?: string | null;
  aria_controls?: string | null;
  has_icon?: boolean;
  visible?: boolean;
}

interface NavLinkDescriptor {
  href: string;
  text: string;
  source?: "header" | "nav" | "footer" | string;
}

function CrawlHomepageView({
  data,
}: {
  data: {
    page_title?: string;
    page_url?: string;
    counts?: Counts;
    inputs?: InputDescriptor[];
    buttons?: ButtonDescriptor[];
    forms?: Array<Record<string, any>>;
    nav_links?: NavLinkDescriptor[];
  };
}) {
  const c = data.counts ?? {};
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

      <Section title="What we extracted">
        <StatGrid
          items={[
            { label: "Inputs", value: c.inputs ?? 0 },
            { label: "Buttons", value: c.buttons ?? 0 },
            { label: "Forms", value: c.forms ?? 0 },
            { label: "Nav links", value: c.nav_links ?? 0 },
          ]}
        />
        <p className="mt-2 text-xs text-slate-500">
          Cookie banners are dismissed, search/menu triggers clicked, and the
          page is scrolled before snapshotting — so hidden search inputs and
          mega-menu links should appear below.
        </p>
      </Section>

      {data.inputs?.length ? (
        <Section title="Inputs found">
          <Collapsible title="All inputs" count={data.inputs.length}>
            <ul className="space-y-1.5">
              {data.inputs.map((inp, i) => (
                <li key={i} className="text-sm">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px] text-slate-800">
                    {inp.selector || "(no selector)"}
                  </code>{" "}
                  <span className="text-slate-500">
                    type={inp.type}
                    {inp.placeholder ? ` · placeholder="${inp.placeholder}"` : ""}
                    {inp.aria_label ? ` · aria="${inp.aria_label}"` : ""}
                    {inp.parent_hint ? ` · in "${inp.parent_hint}"` : ""}
                    {inp.visible === false ? " · hidden" : ""}
                  </span>
                </li>
              ))}
            </ul>
          </Collapsible>
        </Section>
      ) : null}

      {data.buttons?.length ? (
        <Section title="Buttons found">
          <Collapsible title="All buttons" count={data.buttons.length}>
            <ul className="space-y-1.5">
              {data.buttons.map((b, i) => (
                <li key={i} className="text-sm">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px] text-slate-800">
                    {b.selector || "(no selector)"}
                  </code>{" "}
                  <span className="text-slate-700">
                    "{b.text || b.aria_label || ""}"
                  </span>
                  {b.has_icon && (
                    <span className="ml-1 text-[11px] text-slate-500">· icon</span>
                  )}
                  {b.aria_haspopup && (
                    <span className="ml-1 text-[11px] text-slate-500">
                      · haspopup={b.aria_haspopup}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </Collapsible>
        </Section>
      ) : null}

      {data.nav_links?.length ? (
        <Section title="Navigation links (header / nav / footer)">
          <Collapsible title="All nav links" count={data.nav_links.length}>
            <ul className="space-y-1">
              {data.nav_links.map((l, i) => (
                <li key={i} className="flex flex-wrap items-center gap-1.5 text-sm">
                  <SourcePill source={l.source} />
                  <span className="text-slate-700">{l.text}</span>
                  <span className="text-slate-400">·</span>
                  <Link href={l.href} />
                </li>
              ))}
            </ul>
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
      support_url?: string | null;
    };
    input_sent_summary?: {
      page_title?: string;
      inputs?: number;
      buttons?: number;
      nav_links?: number;
    };
  };
}) {
  const a = data.analysis ?? {};
  return (
    <>
      <Section title="What the AI analyzed">
        <p className="text-sm text-slate-700">
          We sent the homepage's UI skeleton ({data.input_sent_summary?.inputs ?? 0}{" "}
          inputs, {data.input_sent_summary?.buttons ?? 0} buttons,{" "}
          {data.input_sent_summary?.nav_links ?? 0} nav links) and asked the AI to
          identify the product search box — or, failing that, a likely support page.
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
          {a.support_url ? (
            <KV k="Fallback support URL">
              <Link href={a.support_url} />
            </KV>
          ) : (
            <KV k="Fallback support URL">
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

function OpenProductPageView({
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
      <Section title="Product page loaded">
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

function ExpandSectionsView({
  data,
}: {
  data: {
    chars_before?: number;
    chars_after?: number;
    delta_chars?: number;
    markdown?: string;
    link_counts?: { internal?: number; external?: number };
    links?: LinkRow[];
  };
}) {
  const delta = data.delta_chars ?? 0;
  const tone = delta > 0 ? "emerald" : delta < 0 ? "amber" : "slate";
  const sign = delta > 0 ? "+" : "";
  return (
    <>
      <Section title="What changed">
        <StatGrid
          items={[
            { label: "Before", value: (data.chars_before ?? 0).toLocaleString() },
            { label: "After", value: (data.chars_after ?? 0).toLocaleString() },
            {
              label: "Delta",
              value: (
                <Pill tone={tone}>
                  {sign}
                  {delta.toLocaleString()}
                </Pill>
              ),
            },
            {
              label: "Total links",
              value:
                (data.link_counts?.internal ?? 0) + (data.link_counts?.external ?? 0),
            },
          ]}
        />
        <p className="mt-2 text-xs text-slate-500">
          {delta > 0
            ? "Expanding tabs and accordions revealed additional content — manuals are usually inside those panels."
            : delta < 0
            ? "Page content was slightly smaller after expansion — likely because tabs replaced their summary text."
            : "No new content was revealed. The page may not have collapsible sections, or the manual is already visible."}
        </p>
      </Section>
      {data.markdown ? (
        <Section title="Expanded content (full markdown)">
          <MarkdownPanel markdown={data.markdown} />
        </Section>
      ) : null}
      {data.links?.length ? (
        <Section title="Links after expansion">
          <Collapsible title="All links" count={data.links.length}>
            <LinksList links={data.links} />
          </Collapsible>
        </Section>
      ) : null}
    </>
  );
}

function FindManualView({
  data,
}: {
  data: {
    locator?: {
      type?: "link" | "html_url" | "inline" | "not_found";
      url?: string | null;
      content?: string | null;
    };
    links_seen?: number;
    markdown_chars?: number;
    product_markdown?: string;
    product_links?: LinkRow[];
  };
}) {
  const t = data.locator?.type ?? "not_found";
  const TONES = {
    link: { tone: "emerald" as const, icon: FileDown, label: "Downloadable file" },
    html_url: { tone: "emerald" as const, icon: Globe, label: "Online HTML manual" },
    inline: { tone: "emerald" as const, icon: FileText, label: "Inline content on page" },
    not_found: { tone: "rose" as const, icon: Search, label: "No manual found" },
  };
  const m = TONES[t];
  return (
    <>
      <Section title="What the AI found">
        <div className="mb-2 flex items-center gap-2">
          <Pill tone={m.tone}>
            <m.icon className="mr-1 h-3.5 w-3.5" />
            {m.label}
          </Pill>
        </div>
        <div className="space-y-1">
          {data.locator?.url && (
            <KV k="Manual URL">
              <Link href={data.locator.url} />
            </KV>
          )}
          {data.locator?.content && (
            <KV k="Inline content">
              <span className="text-slate-700">
                {data.locator.content.length.toLocaleString()} characters of text
              </span>
            </KV>
          )}
        </div>
      </Section>
      {data.locator?.content ? (
        <Section title="Inline manual content">
          <MarkdownPanel markdown={data.locator.content} />
        </Section>
      ) : null}
      <Section title="What the AI looked at">
        <p className="text-xs text-slate-500">
          Reviewed {data.links_seen ?? 0} links and{" "}
          {(data.markdown_chars ?? 0).toLocaleString()} characters of page content.
        </p>
      </Section>
      {data.product_markdown ? (
        <Section title="Product page content (full markdown)">
          <MarkdownPanel markdown={data.product_markdown} />
        </Section>
      ) : null}
      {data.product_links?.length ? (
        <Section title="Product page links">
          <Collapsible title="All links" count={data.product_links.length}>
            <LinksList links={data.product_links} />
          </Collapsible>
        </Section>
      ) : null}
    </>
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
  };
}) {
  const t = data.type ?? "not_found";
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
          {data.url && (
            <KV k="Manual URL">
              <Link href={data.url} />
            </KV>
          )}
          {(data.content || data.content_chars) && (
            <KV k="Content length">
              {(data.content_chars ?? data.content?.length ?? 0).toLocaleString()} characters
            </KV>
          )}
        </div>
      </Section>
      {data.content ? (
        <Section title="Manual content (full markdown)">
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
