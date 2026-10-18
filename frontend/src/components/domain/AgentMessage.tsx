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

const DISCLOSURE = /\s*(Important Regulatory Disclosure: )?(All investments|Investing) involves? risk, including possible loss of principal\.\s*Past performance (is no guarantee|does not guarantee) (of )?future results\.?\s*/i;

/** Splits the standard risk disclosure off the end so it is shown once, small, under the message. */
function splitDisclosure(text: string): [string, boolean] {
  const m = text.match(DISCLOSURE);
  if (!m) return [text, false];
  return [text.replace(DISCLOSURE, "\n").trim(), true];
}

function renderInlineBold(line: string) {
  const parts = line.split(/(\*\*.*?\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
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
    const line = lines[i].trim();

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
          <div key={`tbl-${i}`} className="my-3 overflow-x-auto border border-line bg-surface">
            <table className="w-full border-collapse text-left text-[0.9375rem]">
              <thead>
                <tr className="border-b border-line bg-surface-muted">
                  {headers.map((h, hi) => (
                    <th key={hi} className="px-3 py-2 font-semibold text-ink">
                      {renderInlineBold(h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {dataRows.map((row, ri) => (
                  <tr key={ri} className="hover:bg-surface-muted/50">
                    {row.map((cell, ci) => (
                      <td key={ci} className="figures px-3 py-2 text-ink">
                        {renderInlineBold(cell)}
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
        <h4 key={i} className="mt-4 mb-1 text-[1rem] font-semibold text-ink">
          {renderInlineBold(line.slice(4))}
        </h4>
      );
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push(
        <h3 key={i} className="mt-5 mb-1.5 text-[1.0625rem] font-semibold text-ink">
          {renderInlineBold(line.slice(3))}
        </h3>
      );
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      blocks.push(
        <h2 key={i} className="mt-5 mb-2 text-[1.125rem] font-semibold text-ink">
          {renderInlineBold(line.slice(2))}
        </h2>
      );
      i++;
      continue;
    }

    // Empty line
    if (!line) {
      i++;
      continue;
    }

    // Standard paragraph / list line
    blocks.push(
      <p key={i} className="max-w-[82ch] whitespace-pre-line text-[1.0625rem] leading-relaxed text-ink">
        {renderInlineBold(lines[i])}
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
  onApprove: (id: string) => void;
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
              onApprove={() => onApprove(ev.proposal!.proposal_id)}
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
      // agent_response, including allocation and comparison results
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

export function TranscriptRow({
  item,
  proposals,
  onApprove,
  onReject,
}: {
  item: TranscriptItem;
  proposals: Record<string, ProposalState>;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const you = item.from === "you";
  const who = you ? "You" : agentNames[item.event?.agent ?? ""] ?? item.event?.agent ?? "Advisor";
  return (
    <li className={`grid gap-x-5 gap-y-1 py-4 sm:grid-cols-[8.5rem_1fr]`}>
      <div className="flex items-baseline gap-2 sm:block">
        <p className={`text-[0.9375rem] font-semibold ${you ? "text-primary" : "text-ink"}`}>{who}</p>
        <p className="figures text-[0.875rem] text-muted">{timeOnly(item.at)}</p>
      </div>
      <div className={`min-w-0 ${you ? "border-l-2 border-primary pl-4" : ""}`}>
        {you ? (
          <p className="max-w-[72ch] whitespace-pre-line text-[1rem] text-ink">{item.text}</p>
        ) : item.event ? (
          <EventBody ev={item.event} proposals={proposals} onApprove={onApprove} onReject={onReject} />
        ) : (
          <Body text={item.text} />
        )}
      </div>
    </li>
  );
}
