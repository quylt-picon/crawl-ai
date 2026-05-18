/**
 * MarkdownView — minimal, dependency-free markdown renderer for debugging
 * crawled pages.
 *
 * Supports headings, paragraphs, ordered/unordered lists, code fences, inline
 * code, links, images (as link badges), bold, italic, blockquotes, and
 * horizontal rules. Raw HTML in the source is treated as literal text (no
 * `dangerouslySetInnerHTML`), so this is safe for untrusted crawled content.
 *
 * The companion `MarkdownPanel` adds a Formatted / Raw toggle and a copy
 * button — useful when the formatted view loses fidelity and you need to
 * inspect the source.
 */
import { useState, type JSX, type ReactNode } from "react";
import { Check, ClipboardCopy, ImageIcon } from "lucide-react";
import { cn } from "@/lib/cn";

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "code"; lang?: string; text: string }
  | { kind: "hr" }
  | { kind: "blockquote"; text: string };

export interface MarkdownViewProps {
  markdown: string;
  className?: string;
  maxHeight?: string;
}

export function MarkdownView({ markdown, className, maxHeight = "28rem" }: MarkdownViewProps) {
  const blocks = parseBlocks(markdown);
  return (
    <div
      className={cn(
        "overflow-y-auto rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm",
        className
      )}
      style={{ maxHeight }}
    >
      {blocks.length === 0 ? (
        <p className="italic text-slate-500">(empty)</p>
      ) : (
        blocks.map((b, i) => renderBlock(b, i))
      )}
    </div>
  );
}

export interface MarkdownPanelProps {
  markdown: string;
  maxHeight?: string;
  /** Show the size badge in chars (default true). */
  showSize?: boolean;
}

export function MarkdownPanel({ markdown, maxHeight, showSize = true }: MarkdownPanelProps) {
  const [mode, setMode] = useState<"formatted" | "raw">("formatted");
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable in some browsers — ignore.
    }
  };

  return (
    <div>
      <div className="mb-2 flex items-center gap-1">
        <div className="inline-flex overflow-hidden rounded-lg border border-slate-200 bg-white text-xs">
          <button
            type="button"
            onClick={() => setMode("formatted")}
            className={cn(
              "px-2.5 py-1 font-medium transition-colors",
              mode === "formatted"
                ? "bg-brand-600 text-white"
                : "text-slate-600 hover:bg-slate-50"
            )}
          >
            Formatted
          </button>
          <button
            type="button"
            onClick={() => setMode("raw")}
            className={cn(
              "border-l border-slate-200 px-2.5 py-1 font-medium transition-colors",
              mode === "raw"
                ? "bg-brand-600 text-white"
                : "text-slate-600 hover:bg-slate-50"
            )}
          >
            Raw
          </button>
        </div>
        {showSize && (
          <span className="text-xs text-slate-400">
            {markdown.length.toLocaleString()} chars
          </span>
        )}
        <button
          type="button"
          onClick={copy}
          className="ml-auto inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
          aria-label="Copy markdown to clipboard"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-emerald-600" />
              Copied
            </>
          ) : (
            <>
              <ClipboardCopy className="h-3 w-3" />
              Copy
            </>
          )}
        </button>
      </div>
      {mode === "formatted" ? (
        <MarkdownView markdown={markdown} maxHeight={maxHeight} />
      ) : (
        <pre
          className="overflow-auto whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-700"
          style={{ maxHeight: maxHeight ?? "28rem" }}
        >
          {markdown}
        </pre>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- parsing */

function parseBlocks(md: string): Block[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block ```lang ... ```
    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, "").trim();
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1; // skip closing fence (or run off the end)
      blocks.push({ kind: "code", lang: lang || undefined, text: buf.join("\n") });
      continue;
    }

    // ATX heading
    const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
      i += 1;
      continue;
    }

    // Horizontal rule
    if (/^\s*(-{3,}|_{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push({ kind: "hr" });
      i += 1;
      continue;
    }

    // Unordered list — group consecutive items
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i += 1;
      }
      blocks.push({ kind: "ul", items });
      continue;
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push({ kind: "ol", items });
      continue;
    }

    // Blockquote
    if (/^\s*>/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      blocks.push({ kind: "blockquote", text: buf.join(" ") });
      continue;
    }

    // Blank line — separator only
    if (line.trim() === "") {
      i += 1;
      continue;
    }

    // Paragraph: collect lines until blank or another block starter
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^```/.test(lines[i]) &&
      !/^\s*>/.test(lines[i]) &&
      !/^\s*(-{3,}|_{3,}|\*{3,})\s*$/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i += 1;
    }
    if (buf.length) {
      blocks.push({ kind: "paragraph", text: buf.join(" ") });
    }
  }
  return blocks;
}

/* --------------------------------------------------------------- rendering */

function renderBlock(b: Block, key: number): ReactNode {
  switch (b.kind) {
    case "heading": {
      const headingClasses: Record<number, string> = {
        1: "mb-3 mt-4 text-2xl font-bold text-slate-900 first:mt-0",
        2: "mb-2 mt-4 text-xl font-bold text-slate-900 first:mt-0",
        3: "mb-2 mt-3 text-lg font-semibold text-slate-900",
        4: "mb-1 mt-2 text-base font-semibold text-slate-800",
        5: "mb-1 mt-2 text-sm font-semibold text-slate-800",
        6: "mb-1 mt-2 text-xs font-semibold uppercase tracking-wider text-slate-700",
      };
      const Tag = `h${b.level}` as keyof JSX.IntrinsicElements;
      return (
        <Tag key={key} className={headingClasses[b.level] ?? headingClasses[6]}>
          {renderInline(b.text)}
        </Tag>
      );
    }
    case "paragraph":
      return (
        <p key={key} className="my-2 leading-relaxed text-slate-700 first:mt-0 last:mb-0">
          {renderInline(b.text)}
        </p>
      );
    case "ul":
      return (
        <ul key={key} className="my-2 ml-5 list-disc space-y-1 text-slate-700">
          {b.items.map((it, i) => (
            <li key={i}>{renderInline(it)}</li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol key={key} className="my-2 ml-5 list-decimal space-y-1 text-slate-700">
          {b.items.map((it, i) => (
            <li key={i}>{renderInline(it)}</li>
          ))}
        </ol>
      );
    case "code":
      return (
        <pre
          key={key}
          className="my-2 overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-[12px] leading-relaxed text-slate-700"
        >
          <code>{b.text}</code>
        </pre>
      );
    case "hr":
      return <hr key={key} className="my-3 border-slate-200" />;
    case "blockquote":
      return (
        <blockquote
          key={key}
          className="my-2 border-l-4 border-slate-300 bg-slate-50 py-1 pl-3 italic text-slate-600"
        >
          {renderInline(b.text)}
        </blockquote>
      );
  }
}

/* --------------------------------------------------------------- inline */

function renderInline(text: string): ReactNode[] {
  // We walk the string once, peeling off recognized inline tokens. Anything
  // not matched is appended to a plain-text buffer that gets flushed when
  // the next token boundary appears.
  const nodes: ReactNode[] = [];
  let buf = "";
  let i = 0;
  let key = 0;
  const flush = () => {
    if (buf) {
      nodes.push(buf);
      buf = "";
    }
  };

  while (i < text.length) {
    const rest = text.slice(i);

    // Image ![alt](url)
    const img = rest.match(/^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/);
    if (img) {
      flush();
      nodes.push(
        <a
          key={`img-${key++}`}
          href={img[2]}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[12px] text-slate-700 hover:bg-slate-200"
        >
          <ImageIcon className="h-3 w-3" />
          {img[1] || "image"}
        </a>
      );
      i += img[0].length;
      continue;
    }

    // Link [text](url)
    if (rest.startsWith("[")) {
      const link = rest.match(/^\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/);
      if (link) {
        flush();
        nodes.push(
          <a
            key={`link-${key++}`}
            href={link[2]}
            target="_blank"
            rel="noreferrer"
            className="break-all text-brand-700 underline-offset-2 hover:underline"
          >
            {link[1] || link[2]}
          </a>
        );
        i += link[0].length;
        continue;
      }
    }

    // Bold **text**
    if (rest.startsWith("**")) {
      const close = rest.indexOf("**", 2);
      if (close > 2) {
        flush();
        nodes.push(<strong key={`b-${key++}`}>{rest.slice(2, close)}</strong>);
        i += close + 2;
        continue;
      }
    }

    // Italic *text* or _text_  (single char, must not be a list marker context)
    if ((rest.startsWith("*") || rest.startsWith("_")) && rest[1] !== rest[0]) {
      const ch = rest[0];
      const close = rest.indexOf(ch, 1);
      if (close > 1 && rest[close - 1] !== " " && rest[1] !== " ") {
        flush();
        nodes.push(<em key={`i-${key++}`}>{rest.slice(1, close)}</em>);
        i += close + 1;
        continue;
      }
    }

    // Inline code `code`
    if (rest.startsWith("`")) {
      const close = rest.indexOf("`", 1);
      if (close > 1) {
        flush();
        nodes.push(
          <code
            key={`c-${key++}`}
            className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[12px] text-slate-800"
          >
            {rest.slice(1, close)}
          </code>
        );
        i += close + 1;
        continue;
      }
    }

    // Bare URL http(s)://... → autolink
    const url = rest.match(/^https?:\/\/[^\s<>()\]]+/);
    if (url) {
      flush();
      nodes.push(
        <a
          key={`url-${key++}`}
          href={url[0]}
          target="_blank"
          rel="noreferrer"
          className="break-all text-brand-700 underline-offset-2 hover:underline"
        >
          {url[0]}
        </a>
      );
      i += url[0].length;
      continue;
    }

    buf += text[i];
    i += 1;
  }
  flush();
  return nodes;
}
