"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ComplianceSummary, Violations } from "@/components/domain/Compliance";
import { ExecutionReceipt, ProposalTicket } from "@/components/domain/TradeTicket";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button } from "@/components/ui/Button";
import { ErrorNotice, Loading, Notice, TableSkeleton, Tag } from "@/components/ui/Feedback";
import { Field, Input, Segmented } from "@/components/ui/Field";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, api } from "@/lib/api";
import { dateTime, humanize, money, qty } from "@/lib/format";
import type { AgentEvent, Execution, Proposal, TradeBlockedDetail } from "@/lib/types";
import { useRequest } from "@/lib/useRequest";

type Side = "BUY" | "SELL";
type Outcome =
  | { kind: "filled"; execution: Execution; events: AgentEvent[] }
  | { kind: "blocked"; title: string; detail: TradeBlockedDetail | string }
  | { kind: "cancelled" };

const blockedTitles: Record<string, string> = {
  ComplianceViolationError: "Compliance rules stopped this order",
  DuplicateTradeError: "Another order was placed less than 30 seconds ago",
  ExpiredApprovalError: "The approval window has passed",
  KYCUnverifiedError: "Your identity checks are not complete",
  UnapprovedTradeError: "The order was not approved",
};

function TradeDesk({ clientId }: { clientId: string }) {
  const params = useSearchParams();
  const [symbol, setSymbol] = useState((params.get("symbol") ?? "").toUpperCase());
  const [side, setSide] = useState<Side>(params.get("side") === "SELL" ? "SELL" : "BUY");
  const [quantity, setQuantity] = useState(params.get("qty") ?? "");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [ticketState, setTicketState] = useState<"open" | "approving" | "done" | "cancelled" | "blocked">("open");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const history = useRequest(`trades:${clientId}`, () => api.trades(clientId, 100));
  const portfolio = useRequest(`pf:${clientId}`, () => api.portfolio(clientId));

  const q = Number(quantity);
  const symbolOk = /^[A-Z.]{1,10}$/.test(symbol);
  const qtyOk = Number.isFinite(q) && q > 0;
  const held = portfolio.data?.positions.find((p) => p.symbol === symbol)?.qty ?? 0;

  async function draft(e: React.FormEvent) {
    e.preventDefault();
    if (!symbolOk || !qtyOk) return;
    setDrafting(true);
    setDraftError(null);
    setOutcome(null);
    try {
      const res = await api.proposeTrade(clientId, symbol, side, q);
      setProposal(res.proposal);
      setTicketState("open");
    } catch (err) {
      setDraftError((err as Error).message);
    } finally {
      setDrafting(false);
    }
  }

  async function approve() {
    if (!proposal) return;
    setTicketState("approving");
    try {
      const res = await api.executeProposal(clientId, proposal.proposal_id, true);
      if (res.execution) {
        setOutcome({ kind: "filled", execution: res.execution, events: res.events });
        setTicketState("done");
      }
      history.reload();
      portfolio.reload();
    } catch (err) {
      const e = err as ApiError;
      const detail = (e.detail ?? e.message) as TradeBlockedDetail | string;
      const code = typeof detail === "object" && detail ? detail.error : "";
      setOutcome({ kind: "blocked", title: blockedTitles[code] ?? (e.status === 404 ? "This proposal has expired" : "The order was not placed"), detail });
      setTicketState("blocked");
    }
  }

  function reset() {
    setProposal(null);
    setOutcome(null);
    setTicketState("open");
  }

  const check = outcome?.kind === "filled" ? outcome.events.find((ev) => ev.event === "compliance_check") : undefined;

  return (
    <div className="grid gap-8 xl:grid-cols-12">
      <div className="space-y-6 xl:col-span-5">
        <Panel title="Draft an order">
          <form onSubmit={draft} className="space-y-5" noValidate>
            <div>
              <p className="mb-1.5 text-sm font-medium text-ink">Side</p>
              <Segmented
                label="Side"
                value={side}
                onChange={setSide}
                options={[
                  { value: "BUY", label: "Buy" },
                  { value: "SELL", label: "Sell" },
                ]}
              />
            </div>
            <Field
              label="Ticker"
              hint={symbol && symbolOk && side === "SELL" ? `You hold ${qty(held)} ${symbol}.` : "For example BND, VTI or SPY."}
              error={symbol && !symbolOk ? "Letters only, up to ten." : null}
            >
              {(p) => (
                <Input
                  {...p}
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase().trim())}
                  autoCapitalize="characters"
                  spellCheck={false}
                  className="figures uppercase"
                />
              )}
            </Field>
            <Field label="Quantity" hint="Fractional shares are accepted." error={quantity && !qtyOk ? "Enter a number above zero." : null}>
              {(p) => <Input {...p} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className="figures" />}
            </Field>
            <ErrorNotice error={draftError} />
            <div className="flex items-center gap-4">
              <Button type="submit" pending={drafting} disabled={!symbolOk || !qtyOk || ticketState === "approving"}>
                Draft proposal
              </Button>
              <span className="text-[13px] text-muted">Drafting does not place anything.</span>
            </div>
          </form>
        </Panel>

        <Notice tone="neutral" title="Before an order is placed">
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-muted marker:text-muted">
            <li>You approve it within 15 minutes of drafting.</li>
            <li>It passes concentration, size and frequency rules.</li>
            <li>Your KYC is verified and no other order was placed in the last 30 seconds.</li>
          </ul>
        </Notice>
      </div>

      <div className="space-y-6 xl:col-span-7">
        {proposal ? (
          <Panel title="Proposal" aside={ticketState !== "approving" && outcome ? <button onClick={reset} className="text-primary underline underline-offset-4">Start another</button> : null}>
            <div className="space-y-5">
              <ProposalTicket
                proposal={proposal}
                state={ticketState}
                onApprove={approve}
                onReject={() => {
                  setTicketState("cancelled");
                  setOutcome({ kind: "cancelled" });
                }}
              />
              {outcome?.kind === "filled" ? (
                <>
                  <ExecutionReceipt execution={outcome.execution} />
                  {check ? <ComplianceSummary passed={check.passed} details={check.details} /> : null}
                </>
              ) : null}
              {outcome?.kind === "blocked" ? (
                <Notice tone="danger" title={outcome.title}>
                  {typeof outcome.detail === "string" ? (
                    <p>{outcome.detail}</p>
                  ) : (
                    <>
                      {outcome.detail.violations?.length ? (
                        <div className="mt-2">
                          <Violations violations={outcome.detail.violations} />
                        </div>
                      ) : (
                        <p>{outcome.detail.reason}</p>
                      )}
                    </>
                  )}
                </Notice>
              ) : null}
              {outcome?.kind === "cancelled" ? <p className="text-sm text-muted">Cancelled. Nothing was sent to the broker.</p> : null}
            </div>
          </Panel>
        ) : (
          <div className="border border-dashed border-line px-6 py-10 text-sm text-muted">
            Your drafted order will appear here with its estimated cost and the weight it would take in your portfolio.
          </div>
        )}

        <Panel title="Order history" flush aside={history.data ? <span>{history.data.trades.length} orders</span> : null}>
          {history.loading && !history.data ? (
            <TableSkeleton rows={4} columns={5} />
          ) : history.error ? (
            <div className="p-5">
              <ErrorNotice error={history.error} onRetry={history.reload} />
            </div>
          ) : !history.data?.trades.length ? (
            <p className="p-5 text-sm text-muted">No orders yet.</p>
          ) : (
            <Table caption="Order history">
              <thead>
                <tr>
                  <Th>Date</Th>
                  <Th>Order</Th>
                  <Th numeric>Fill price</Th>
                  <Th numeric>Value</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {history.data.trades.map((t) => (
                  <Tr key={t.trade_id}>
                    <Td className="whitespace-nowrap text-muted">{dateTime(t.created_at)}</Td>
                    <Td className="font-medium whitespace-nowrap">
                      {t.side === "BUY" ? "Buy" : "Sell"} {qty(t.qty)} {t.symbol}
                    </Td>
                    <Td numeric>{money(t.filled_price)}</Td>
                    <Td numeric>{t.filled_price ? money(t.filled_price * t.qty) : "–"}</Td>
                    <Td>
                      <Tag tone={t.status === "FILLED" ? "success" : "neutral"}>{humanize(t.status)}</Tag>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
        </Panel>
      </div>
    </div>
  );
}

export default function TradePage() {
  return (
    <>
      <PageHeader title="Trade" lede="Draft an order, review it, then approve it. Orders go to a paper-trading account." />
      <RequireProfile>
        {(id) => (
          <Suspense fallback={<Loading />}>
            <TradeDesk clientId={id} />
          </Suspense>
        )}
      </RequireProfile>
    </>
  );
}
