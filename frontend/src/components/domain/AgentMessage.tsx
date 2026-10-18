"use client";

import Link from "next/link";
import { BulletBars } from "../charts/BulletBars";
import { Notice, Tag } from "../ui/Feedback";
import { BiasAlert } from "./BiasAlert";
import { ComplianceSummary, Violations } from "./Compliance";
import { ExecutionReceipt, ProposalTicket } from "./TradeTicket";
import { fixed, money, pct, timeOnly } from "@/lib/format";
import type { AgentEvent } from "@/lib/types";
import type { ProposalState, TranscriptItem } from "@/lib/useAdvisor";

const agentNames: Record<string, string> = {
  Orchestrator: "Advisor",
  RiskProfiler: "Risk profiler",
  BehavioralBias: "Behaviour check",
  ComplianceGuard: "Compliance",
  AllocationEngine: "Allocation",
  ProductComparison: "Fund comparison",
  HealthReport: "Health review",
  MarketData: "Market data",
  ExecutionModule: "Execution",
  PortfolioService: "Portfolio",
  FinancialAnalyst: "Financial analyst",
  TaxStrategy: "Tax architect",
  User: "You",
};

const DISCLOSURE =
  /\s*(Important Regulatory Disclosure: )?(All investments|Investing) involves? risk, including possible loss of principal\.\s*Past performance (is no guarantee|does not guarantee) (of )?future results\.?\s*/i;

/** Splits the standard risk disclosure off the end so it is shown once, small, under the message. */
function splitDisclosure(text: string): [string, boolean] {
  const m = text.match(DISCLOSURE);
  if (!m) return [text, false];
  return [text.replace(DISCLOSURE, "\n").trim(), true];
}

/** Renders bold and footnote citation tokens [1], [2], etc. */
function renderInlineFormatting(line: string) {
  const parts = line.split(/(\*\*.*?\*\*|\[\d+\])/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (/^\[\d+\]$/.test(part)) {
      return (
        <span
          key={i}
          className="ml-1 inline-flex items-center justify-center rounded-sm bg-accent-soft px-1.5 py-0.2 text-[10px] font-semibold text-accent align-baseline"
          title={`Citation ${part}`}
        >
          {part.slice(1, -1)}
        </span>
      );
    }
    return part;
  });
}

function Body({ text }: { text?: string }) {
  if (!text) return null;
  const [main, hadDisclosure] = splitDisclosure(text);
  if (!main) return null;

  const lines = main.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const rawLine = lines[i];
    const line = rawLine.trim();

    // Markdown table block detection
    if (line.startsWith("|") && line.endsWith("|") && i + 1 < lines.length && lines[i + 1].trim().startsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        tableLines.push(lines[i].trim());
        i++;
      }
      if (tableLines.length >= 2) {
        const parseRow = (r: string) =>
          r
            .slice(1, -1)
            .split("|")
            .map((c) => c.trim());
        const headers = parseRow(tableLines[0]);
        const dataRows = tableLines.slice(2).map(parseRow);
        blocks.push(
          <div key={`tbl-${i}`} className="my-3 overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full border-collapse text-left text-[0.9375rem]">
              <thead>
                <tr className="border-b border-line bg-surface-muted">
                  {headers.map((h, hi) => (
                    <th key={hi} className="px-3 py-2 font-semibold text-ink">
                      {renderInlineFormatting(h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {dataRows.map((row, ri) => (
                  <tr key={ri} className="hover:bg-surface-muted/50">
                    {row.map((cell, ci) => (
                      <td key={ci} className="figures px-3 py-2 text-ink">
                        {renderInlineFormatting(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
        continue;
      }
    }

    // Headings
    if (line.startsWith("### ")) {
      blocks.push(
        <h4 key={i} className="mt-4 mb-1.5 text-[1rem] font-semibold text-ink">
          {renderInlineFormatting(line.slice(4))}
        </h4>
      );
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push(
        <h3 key={i} className="mt-5 mb-1.5 text-[1.0625rem] font-semibold text-ink">
          {renderInlineFormatting(line.slice(3))}
        </h3>
      );
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      blocks.push(
        <h2 key={i} className="mt-5 mb-2 text-[1.125rem] font-semibold text-ink">
          {renderInlineFormatting(line.slice(2))}
        </h2>
      );
      i++;
      continue;
    }

    // Bullet list items (- , * , • )
    if (line.startsWith("- ") || line.startsWith("* ") || line.startsWith("• ")) {
      blocks.push(
        <div key={i} className="my-1 flex items-start gap-2.5 text-[14px] leading-relaxed text-ink/90">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
          <span className="flex-1">{renderInlineFormatting(line.replace(/^[-*•]\s+/, ""))}</span>
        </div>
      );
      i++;
      continue;
    }

    // Numbered list items (1. , 2. )
    const numMatch = line.match(/^(\d+)\.\s+(.*)$/);
    if (numMatch) {
      blocks.push(
        <div key={i} className="my-1.5 flex items-start gap-2.5 text-[14px] leading-relaxed text-ink/90">
          <span className="figures mt-0.5 text-[12px] font-bold text-muted shrink-0">{numMatch[1]}.</span>
          <span className="flex-1">{renderInlineFormatting(numMatch[2])}</span>
        </div>
      );
      i++;
      continue;
    }

    // Empty line
    if (!line) {
      i++;
      continue;
    }

    // Standard paragraph line
    blocks.push(
      <p key={i} className="max-w-[82ch] whitespace-pre-line text-[1.0625rem] leading-relaxed text-ink/90">
        {renderInlineFormatting(lines[i])}
      </p>
    );
    i++;
  }

  return (
    <div className="space-y-2">
      {blocks}
      {hadDisclosure ? (
        <p className="mt-2 max-w-[72ch] text-[0.875rem] text-muted">
          Investing involves risk, including possible loss of principal. Past performance is no guarantee of future results.
        </p>
      ) : null}
    </div>
  );
}

function EventBody({
  ev,
  proposals,
  onApprove,
  onReject,
}: {
  ev: AgentEvent;
  proposals: Record<string, ProposalState>;
  onApprove: (id: string, opts?: { mfaCode?: string; fiduciaryAttested?: boolean }) => void;
  onReject: (id: string) => void;
}) {
  switch (ev.event) {
    case "bias_alert":
      return <BiasAlert biasType={ev.bias_type} severity={ev.severity} confidence={ev.confidence} text={ev.text} coolOff={ev.cool_off_recommended} />;

    case "compliance_check":
      return <ComplianceSummary passed={ev.passed} details={ev.details} violations={ev.violations} />;

    case "trade_proposal":
      return (
        <div className="space-y-3">
          <Body text={ev.text} />
          {ev.proposal ? (
            <ProposalTicket
              proposal={ev.proposal}
              state={proposals[ev.proposal.proposal_id] ?? "open"}
              onApprove={(opts) => onApprove(ev.proposal!.proposal_id, opts)}
              onReject={() => onReject(ev.proposal!.proposal_id)}
            />
          ) : null}
        </div>
      );

    case "trade_approved":
      return <p className="text-sm text-ink">{ev.text}. Running pre-trade checks.</p>;

    case "trade_filled":
      return (
        <div className="space-y-3">
          {ev.execution ? <ExecutionReceipt execution={ev.execution} /> : null}
          <Body text={ev.text} />
        </div>
      );

    case "portfolio_update":
      if (ev.report) {
        const r = ev.report;
        return (
          <div className="space-y-3">
            <p className="flex flex-wrap items-baseline gap-3 text-sm">
              <span className="figures text-[1.5rem] text-ink">{fixed(r.health_score, 0)}</span>
              <span className="text-muted">out of 100</span>
              <Tag tone={r.health_score >= 70 ? "success" : r.health_score >= 50 ? "warning" : "danger"}>{r.health_grade.toLowerCase()}</Tag>
            </p>
            <Body text={ev.text} />
            <Link href="/app/health" className="text-sm text-primary underline underline-offset-4">
              Open the full health review
            </Link>
          </div>
        );
      }
      if (ev.portfolio) {
        const p = ev.portfolio;
        return (
          <p className="figures text-sm text-ink">
            Portfolio now {money(p.total_value)}: {money(p.invested_value)} invested, {money(p.cash)} cash, {p.positions.length} holding
            {p.positions.length === 1 ? "" : "s"}.
          </p>
        );
      }
      return <Body text={ev.text} />;

    case "error":
      return (
        <Notice tone="danger" title={ev.error ? ev.error.replace(/Error$/, "").replace(/([a-z])([A-Z])/g, "$1 $2") : "Stopped"}>
          <p>{ev.text}</p>
          {ev.violations?.length ? (
            <div className="mt-2">
              <Violations violations={ev.violations} />
            </div>
          ) : null}
        </Notice>
      );

    default:
      return (
        <div className="space-y-4">
          {ev.weights ? (
            <>
              <Body text={ev.text?.split("\n\n")[0]} />
              <BulletBars
                title="Recommended weights"
                max={1}
                rows={Object.entries(ev.weights)
                  .filter(([, w]) => w > 0.001)
                  .sort((a, b) => b[1] - a[1])
                  .map(([s, w]) => ({ label: s, value: w }))}
              />
              {ev.metrics ? (
                <p className="figures text-[0.9375rem] text-muted">
                  Annualised volatility {pct(ev.metrics.annualized_volatility)} · Sharpe {fixed(ev.metrics.sharpe_ratio)} · CVaR (95%){" "}
                  {pct(ev.metrics.cvar_95, 2)}
                </p>
              ) : null}
              <Body text={ev.text?.split("\n\n").slice(1).join("\n\n")} />
              <Link href="/app/allocation" className="text-sm text-primary underline underline-offset-4">
                Open the allocation in detail
              </Link>
            </>
          ) : (
            <Body text={ev.text} />
          )}
          {ev.profile_complete ? (
            <div className="flex flex-wrap gap-4 text-sm">
              <Link href="/app/profile" className="text-primary underline underline-offset-4">
                Review your profile
              </Link>
              <Link href="/app/allocation" className="text-primary underline underline-offset-4">
                See a recommended allocation
              </Link>
            </div>
          ) : null}
        </div>
      );
  }
}

/** Derives a topical pill label for the user query (e.g. "Mortgage & Macro", "Onboarding Demo") */
function deriveQueryTopic(text?: string): string {
  if (!text) return "Advisory Inquiry";
  const lower = text.toLowerCase();
  if (lower.includes("mortgage") || lower.includes("yield") || lower.includes("rate") || lower.includes("treasury")) {
    return "Mortgage & Macro";
  }
  if (lower.includes("dangote") || lower.includes("refinery") || lower.includes("stock") || lower.includes("equity")) {
    return "Equity Intelligence";
  }
  if (lower.includes("tax") || lower.includes("irs") || lower.includes("deduction")) {
    return "Tax Optimization";
  }
  if (lower.includes("allocation") || lower.includes("portfolio") || lower.includes("wealth") || lower.includes("spy")) {
    return "Portfolio Strategy";
  }
  if (lower.includes("demo") || lower.includes("workflow") || lower.includes("onboarding")) {
    return "Onboarding Demo";
  }
  return "Institutional Advisory";
}

export function TranscriptRow({
  item,
  proposals,
  onApprove,
  onReject,
  onSelectOption,
}: {
  item: TranscriptItem;
  proposals: Record<string, ProposalState>;
  onApprove: (id: string, opts?: { mfaCode?: string; fiduciaryAttested?: boolean }) => void;
  onReject: (id: string) => void;
  onSelectOption?: (option: string) => void;
}) {
  const you = item.from === "you";
  const who = you ? "You" : agentNames[item.event?.agent ?? ""] ?? item.event?.agent ?? "Advisor";

  if (you) {
    const topic = deriveQueryTopic(item.text);
    return (
      <li className="flex flex-col items-end my-5 animate-fade-in">
        {/* Topic pill tag above user bubble */}
        <div className="mb-1.5 flex items-center gap-1.5 pr-9">
          <span className="inline-flex items-center rounded-md bg-accent-soft px-2.5 py-0.5 text-[11px] font-semibold text-accent">
            {topic}
          </span>
        </div>

        {/* User Bubble Row */}
        <div className="flex items-end justify-end gap-2.5 max-w-[85%] sm:max-w-[75%]">
          <div className="flex flex-col items-end gap-1.5">
            {/* Attached media thumbnails */}
            {item.attachments && item.attachments.length > 0 ? (
              <div className="flex flex-wrap justify-end gap-2">
                {item.attachments.map((att, idx) => (
                  <div
                    key={idx}
                    className="overflow-hidden rounded-xl border border-line bg-surface p-1 shadow-xs"
                  >
                    {att.type === "image" || att.data?.startsWith("data:image/") || att.url?.match(/\.(jpeg|jpg|gif|png|webp)/i) ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={att.data || att.url}
                        alt={att.name || "Upload"}
                        className="max-h-40 max-w-[200px] rounded-lg object-cover"
                      />
                    ) : (
                      <div className="flex items-center gap-1.5 px-2 py-1 text-xs text-ink">
                        <span className="text-accent">📎</span>
                        <span className="max-w-[130px] truncate font-medium">{att.name || "Document"}</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : null}

            {/* Bubble Pill Container */}
            <div
              className="rounded-2xl rounded-tr-xs bg-primary px-4 py-2.5 text-[14px] leading-relaxed text-on-primary shadow-xs"
              style={{ color: "#ffffff" }}
            >
              <p className="whitespace-pre-line select-text text-on-primary" style={{ color: "#ffffff" }}>
                {item.text}
              </p>
            </div>

            <span className="figures pr-1 text-[11px] text-muted">{timeOnly(item.at)}</span>
          </div>

          {/* User Avatar */}
          <div className="grid h-7 w-7 place-items-center rounded-full bg-primary/15 text-[11px] font-bold text-primary ring-1 ring-primary/25 shrink-0 shadow-2xs">
            U
          </div>
        </div>
      </li>
    );
  }

  // Advisor / AI Turn
  return (
    <li className="flex flex-col items-start my-5 w-full animate-fade-in">
      {/* Top Meta Bar: Advisor label + Time */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-0.5 text-xs font-semibold text-ink shadow-2xs">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          <span>{who}</span>
        </span>
        <span className="figures text-[11px] text-muted">• {timeOnly(item.at)}</span>
      </div>

      {/* Main Message Body & Content */}
      <div className="w-full max-w-3xl space-y-3 pl-0.5">
        {item.attachments && item.attachments.length > 0 ? (
          <div className="mb-2 flex flex-wrap gap-2">
            {item.attachments.map((att, idx) => (
              <div key={idx} className="overflow-hidden rounded-xl border border-line bg-surface p-1 shadow-xs">
                {att.type === "image" || att.data?.startsWith("data:image/") || att.url?.match(/\.(jpeg|jpg|gif|png|webp)/i) ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={att.data || att.url}
                    alt={att.name || "Upload"}
                    className="max-h-48 max-w-xs rounded-lg object-cover"
                  />
                ) : (
                  <div className="flex items-center gap-2 px-2.5 py-1 text-xs text-ink">
                    <span className="text-accent">📎</span>
                    <span className="max-w-[150px] truncate font-medium">{att.name || "Document"}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : null}

        {item.event ? (
          <EventBody ev={item.event} proposals={proposals} onApprove={onApprove} onReject={onReject} />
        ) : (
          <Body text={item.text} />
        )}

        {/* Tap-to-Answer Quick Replies for Onboarding & Clarifications */}
        {item.event?.options && item.event.options.length > 0 ? (
          <div className="mt-2.5 flex flex-wrap gap-2 animate-fade-in">
            {item.event.options.map((opt, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectOption?.(opt)}
                className="rounded-full border border-accent/40 bg-accent-soft px-3.5 py-1 text-xs font-semibold text-accent hover:bg-accent hover:text-on-accent transition-all shadow-2xs cursor-pointer active:scale-95"
              >
                {opt}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </li>
  );
}
