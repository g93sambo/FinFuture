import type { ComponentProps } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

/**
 * Advisor text is model-written Markdown. Render it with a real parser (GFM tables,
 * nested lists, quotes, code, links) so nothing shows up as raw `####` or `>`.
 */

const CITE = /^cite:(\d+)$/;

/** GitHub alert markers ("> [!NOTE]") and footnote-style citations ("[1]") have no plain-Markdown form. */
function prepare(text: string): string {
  return text
    .replace(/^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$\n?/gim, "")
    .replace(/\[(\d{1,2})\](?![(:[])/g, "`cite:$1`");
}

const components: Components = {
  p: (props) => <p className="my-2 leading-relaxed text-ink/90" {...strip(props)} />,
  h1: (props) => <h2 className="font-display mt-5 mb-2 text-[1.3125rem] font-semibold text-ink" {...strip(props)} />,
  h2: (props) => <h3 className="font-display mt-5 mb-2 text-[1.1875rem] font-semibold text-ink" {...strip(props)} />,
  h3: (props) => <h4 className="font-display mt-4 mb-1.5 text-[1.125rem] font-semibold text-ink" {...strip(props)} />,
  h4: (props) => <h5 className="mt-4 mb-1 text-[1.0625rem] font-semibold text-ink" {...strip(props)} />,
  h5: (props) => <h6 className="mt-3 mb-1 text-[1rem] font-semibold text-ink" {...strip(props)} />,
  h6: (props) => <h6 className="mt-3 mb-1 text-[0.9375rem] font-semibold text-muted" {...strip(props)} />,
  ul: (props) => <ul className="my-2 list-disc space-y-1 pl-5 marker:text-accent [&_ol]:my-1 [&_ul]:my-1" {...strip(props)} />,
  ol: (props) => <ol className="my-2 list-decimal space-y-1 pl-5 marker:font-semibold marker:text-muted [&_ol]:my-1 [&_ul]:my-1" {...strip(props)} />,
  li: (props) => <li className="pl-1 leading-relaxed text-ink/90 [&>p]:my-0" {...strip(props)} />,
  strong: (props) => <strong className="font-semibold text-ink" {...strip(props)} />,
  em: (props) => <em className="italic" {...strip(props)} />,
  hr: () => <hr className="my-4 border-line" />,
  blockquote: (props) => (
    <blockquote className="my-3 rounded-r-lg border-l-4 border-accent bg-accent-soft/50 px-4 py-2 text-ink/90 [&>p]:my-1" {...strip(props)} />
  ),
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline decoration-primary/40 underline-offset-4 hover:decoration-primary">
      {children}
    </a>
  ),
  code: ({ className, children }) => {
    const raw = String(children ?? "");
    const cite = raw.match(CITE);
    if (cite) {
      return (
        <span
          className="ml-0.5 inline-flex items-center justify-center rounded-sm bg-accent-soft px-1.5 text-[10px] font-semibold text-accent align-baseline"
          title={`Citation ${cite[1]}`}
        >
          {cite[1]}
        </span>
      );
    }
    if (className?.startsWith("language-") || raw.includes("\n")) {
      return <code className="figures block whitespace-pre text-[0.875rem]">{children}</code>;
    }
    return <code className="figures rounded bg-surface-muted px-1.5 py-0.5 text-[0.875em] text-ink">{children}</code>;
  },
  pre: (props) => <pre className="my-3 overflow-x-auto rounded-xl border border-line bg-surface p-3" {...strip(props)} />,
  table: (props) => (
    <div className="relative my-3 overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full border-collapse text-left text-[0.9375rem]" {...strip(props)} />
    </div>
  ),
  thead: (props) => <thead className="border-b border-line bg-surface-muted" {...strip(props)} />,
  tbody: (props) => <tbody className="divide-y divide-line" {...strip(props)} />,
  th: (props) => <th className="px-3 py-2 font-semibold whitespace-nowrap text-ink" {...strip(props)} />,
  td: (props) => <td className="figures px-3 py-2 text-ink" {...strip(props)} />,
};

/** Drops react-markdown's `node` prop so it is not forwarded to the DOM. */
function strip<T extends { node?: unknown }>(props: T): Omit<T, "node"> {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { node, ...rest } = props;
  return rest;
}

export function Markdown({ text, className = "" }: { text: string } & Pick<ComponentProps<"div">, "className">) {
  return (
    <div className={`max-w-[82ch] [&>:first-child]:mt-0 [&>:last-child]:mb-0 ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} components={components}>
        {prepare(text)}
      </ReactMarkdown>
    </div>
  );
}
