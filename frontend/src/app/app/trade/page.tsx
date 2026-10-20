"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ComplianceSummary, Violations } from "@/components/domain/Compliance";
import { TickerAutocomplete } from "@/components/domain/TickerAutocomplete";
import { ExecutionReceipt, ProposalTicket } from "@/components/domain/TradeTicket";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button } from "@/components/ui/Button";
import { ErrorNotice, Loading, Notice, TableSkeleton, Tag } from "@/components/ui/Feedback";
import { Field, Input, Segmented } from "@/components/ui/Field";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, api, retryableStepUpReason, type ApproveOptions } from "@/lib/api";
import { POPULAR_CURATED_ASSETS, PRESET_DOLLAR_AMOUNTS, type CuratedAsset } from "@/lib/curatedInvestments";
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
  KYCUnverifiedError: "Trading is paused for your account",
  UnapprovedTradeError: "The order was not approved",
};

function TradeDesk({ clientId }: { clientId: string }) {
  const params = useSearchParams();
  const [symbol, setSymbol] = useState((params.get("symbol") ?? "AAPL").toUpperCase());
  const [side, setSide] = useState<Side>(params.get("side") === "SELL" ? "SELL" : "BUY");
  const [quantity, setQuantity] = useState(params.get("qty") ?? "1");
  const [selectedDollar, setSelectedDollar] = useState<number | null>(null);
  const [investMode, setInvestMode] = useState<"quick" | "custom">("quick");

  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [ticketState, setTicketState] = useState<"open" | "approving" | "done" | "cancelled" | "blocked">("open");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const history = useRequest(`trades:${clientId}`, () => api.trades(clientId, 100));
  const portfolio = useRequest(`pf:${clientId}`, () => api.portfolio(clientId));

  const q = Number(quantity);
  const symbolOk = /^[A-Z0-9.]{1,10}$/.test(symbol);
  const qtyOk = Number.isFinite(q) && q > 0;
  const held = portfolio.data?.positions.find((p) => p.symbol === symbol)?.qty ?? 0;
  const buyingPower = portfolio.data?.cash ?? null;
  const quote = useRequest(symbolOk ? `quote:${symbol}` : null, () => api.quote(symbol));
  const livePrice = quote.data?.symbol === symbol && quote.data.price > 0 ? quote.data.price : null;
  const estimatedTotal = qtyOk && livePrice ? q * livePrice : null;

  // Dollar presets become a share quantity once the live price is known
  const sharesFor = (dollars: number, price: number) => String(Math.max(0.0001, Number((dollars / price).toFixed(4))));
  if (selectedDollar && livePrice && quantity !== sharesFor(selectedDollar, livePrice)) {
    setQuantity(sharesFor(selectedDollar, livePrice));
  }

  function handleSelectAsset(asset: CuratedAsset) {
    setSymbol(asset.symbol);
    setSelectedDollar((d) => d ?? 100);
    setDraftError(null);
  }

  function handleSelectDollar(dollarAmt: number) {
    setSelectedDollar(dollarAmt);
    setDraftError(null);
  }

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

  async function approve(opts?: ApproveOptions): Promise<string | void> {
    if (!proposal) return;
    setTicketState("approving");
    try {
      const res = await api.executeProposal(clientId, proposal.proposal_id, true, opts);
      if (res.execution) {
        setOutcome({ kind: "filled", execution: res.execution, events: res.events });
        setTicketState("done");
      }
      history.reload();
      portfolio.reload();
    } catch (err) {
      const retry = retryableStepUpReason(err);
      if (retry) {
        setTicketState("open");
        return retry;
      }
      const e = err as ApiError;
      const detail = (e.detail ?? e.message) as TradeBlockedDetail | string;
      const code = typeof detail === "object" && detail ? detail.error : "";
      setOutcome({
        kind: "blocked",
        title: blockedTitles[code] ?? (e.status === 404 ? "This proposal has expired" : "The order was not placed"),
        detail,
      });
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
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface/70 px-5 py-4 shadow-xs">
        <div>
          <p className="text-sm font-bold text-ink">Alpaca paper-trading account</p>
          <p className="text-xs text-muted">Simulated money. Every order needs your approval and is recorded in the audit trail.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="rounded-xl border border-line/80 bg-background/80 px-4 py-2 text-right">
            <span className="block text-[11px] font-medium uppercase tracking-wider text-muted">Cash available</span>
            <span className="figures text-base font-bold text-ink">{buyingPower === null ? "–" : money(buyingPower)}</span>
          </div>
          <a href="/app/audit" className="text-xs font-semibold text-primary underline underline-offset-4">
            View audit trail
          </a>
        </div>
      </div>

      <div className="grid gap-8 xl:grid-cols-12">
        {/* Left Column: Easy Investing / Order Form */}
        <div className="space-y-6 xl:col-span-5">
          <Panel
            title="Invest & Trade"
            aside={
              <div className="flex rounded-lg border border-line p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => setInvestMode("quick")}
                  className={`rounded-md px-3 py-1 font-semibold transition-colors ${
                    investMode === "quick" ? "bg-accent text-on-accent shadow-xs" : "text-muted hover:text-ink"
                  }`}
                >
                  🌟 Quick Invest
                </button>
                <button
                  type="button"
                  onClick={() => setInvestMode("custom")}
                  className={`rounded-md px-3 py-1 font-semibold transition-colors ${
                    investMode === "custom" ? "bg-accent text-on-accent shadow-xs" : "text-muted hover:text-ink"
                  }`}
                >
                  🔍 Custom Ticker
                </button>
              </div>
            }
          >
            {investMode === "quick" ? (
              <div className="space-y-6">
                {/* Popular Household Stocks */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-bold uppercase tracking-wider text-muted">
                      Popular picks
                    </p>
                    <span className="text-[11px] text-muted">Fractional shares accepted</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                    {POPULAR_CURATED_ASSETS.map((a) => {
                      const isSelected = symbol === a.symbol;
                      return (
                        <button
                          key={a.symbol}
                          type="button"
                          onClick={() => handleSelectAsset(a)}
                          className={`flex flex-col items-center justify-center rounded-xl border p-2.5 text-center transition-all ${
                            isSelected
                              ? "border-accent bg-accent/10 font-bold text-accent shadow-xs"
                              : "border-line bg-surface/40 hover:bg-surface hover:border-line-strong"
                          }`}
                        >
                          <span className="text-lg">{a.icon}</span>
                          <span className="mt-1 text-xs font-bold text-ink">{a.symbol}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Quick Dollar Presets */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-bold uppercase tracking-wider text-muted">
                      Select Investment Amount
                    </p>
                    <span className="text-[11px] text-muted">Converted to shares at the live price</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                    {PRESET_DOLLAR_AMOUNTS.map((amt) => {
                      const isSelected = selectedDollar === amt;
                      return (
                        <button
                          key={amt}
                          type="button"
                          onClick={() => handleSelectDollar(amt)}
                          className={`rounded-lg border py-2 text-center text-xs font-semibold transition-all ${
                            isSelected
                              ? "border-accent bg-accent text-on-accent shadow-xs"
                              : "border-line bg-surface/50 text-ink hover:bg-surface hover:border-line-strong"
                          }`}
                        >
                          ${amt}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : null}

            {/* Order Form Execution */}
            <form onSubmit={draft} className="mt-6 space-y-5 border-t border-line/80 pt-5" noValidate>
              <div>
                <p className="mb-1.5 text-sm font-medium text-ink">Action</p>
                <Segmented
                  label="Side"
                  value={side}
                  onChange={setSide}
                  options={[
                    { value: "BUY", label: "Buy / Invest" },
                    { value: "SELL", label: "Sell / Cash Out" },
                  ]}
                />
              </div>

              {investMode === "custom" ? (
                <Field
                  label="Ticker / Security Symbol"
                  hint={symbol && symbolOk && side === "SELL" ? `You hold ${qty(held)} ${symbol}.` : "Search by company name or ticker (e.g. SPY, AAPL, BND)."}
                  error={symbol && !symbolOk ? "Letters only, up to ten." : null}
                >
                  {() => (
                    <TickerAutocomplete
                      value={symbol}
                      onChange={(val) => {
                        setSymbol(val.toUpperCase().trim());
                        setSelectedDollar(null);
                      }}
                      onSelectSymbol={(sym) => {
                        setSymbol(sym);
                        setSelectedDollar(null);
                      }}
                      placeholder="Type symbol or name (e.g. SPY, Apple, BND)..."
                    />
                  )}
                </Field>
              ) : (
                <div className="rounded-xl border border-line bg-surface/60 p-3.5">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-[11px] uppercase font-semibold text-muted">Selected Asset</span>
                      <p className="text-base font-bold text-ink">{symbol} • {POPULAR_CURATED_ASSETS.find((a) => a.symbol === symbol)?.name ?? symbol}</p>
                    </div>
                    <div className="text-right">
                      <span className="text-[11px] uppercase font-semibold text-muted">Last price</span>
                      <p className="figures text-sm font-bold text-ink">{livePrice ? money(livePrice) : quote.loading ? "…" : "–"}</p>
                    </div>
                  </div>
                </div>
              )}

              <Field
                label="Quantity (Shares)"
                hint={
                  qtyOk && estimatedTotal !== null && livePrice
                    ? `Estimated value: ${money(estimatedTotal)} (${qty(q)} shares @ ${money(livePrice)})`
                    : "Fractional shares are accepted."
                }
                error={quantity && !qtyOk ? "Enter a quantity above zero." : null}
              >
                {(p) => (
                  <Input
                    {...p}
                    inputMode="decimal"
                    value={quantity}
                    onChange={(e) => {
                      setQuantity(e.target.value);
                      setSelectedDollar(null);
                    }}
                    className="figures"
                    placeholder="e.g. 1.5 or 0.25"
                  />
                )}
              </Field>

              <ErrorNotice error={draftError} />

              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1">
                <Button type="submit" pending={drafting} disabled={!symbolOk || !qtyOk || ticketState === "approving"}>
                  Draft Investment Proposal
                </Button>
                <span className="text-[13px] text-muted">Review compliance before placing.</span>
              </div>
            </form>
          </Panel>

          <Notice tone="neutral" title="Safeguards">
            <ul className="mt-1 list-inside list-disc space-y-1 text-xs text-muted marker:text-muted">
              <li><strong>Non-discretionary:</strong> nothing is traded without your explicit approval.</li>
              <li><strong>Paper trading:</strong> orders use simulated money, never real funds.</li>
              <li><strong>Pre-trade checks:</strong> suitability, concentration, AML and daily limits run before every order; orders over $1,000 also need an emailed code.</li>
            </ul>
          </Notice>
        </div>

        {/* Right Column: Proposal, Execution & Order History */}
        <div className="space-y-6 xl:col-span-7">
          {proposal ? (
            <Panel
              title="Order Proposal & Fiduciary Review"
              aside={
                ticketState !== "approving" && outcome ? (
                  <button onClick={reset} className="text-primary underline underline-offset-4 text-xs font-semibold">
                    Draft Another Order
                  </button>
                ) : null
              }
            >
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
                {outcome?.kind === "cancelled" ? (
                  <p className="text-sm text-muted">Cancelled. Nothing was sent to the broker.</p>
                ) : null}
              </div>
            </Panel>
          ) : (
            <div className="rounded-card border border-dashed border-line bg-surface/40 p-8 text-center text-sm text-muted">
              <span className="text-3xl block mb-2">📋</span>
              <p className="font-medium text-ink">Ready to invest?</p>
              <p className="mt-1 text-xs text-muted">
                Pick a popular security above or enter your own ticker, then click &quot;Draft Investment Proposal&quot; to review pricing and compliance checks.
              </p>
            </div>
          )}

          {/* Order History */}
          <Panel
            title="Order History & Execution Log"
            flush
            aside={history.data ? <span>{history.data.trades.length} orders</span> : null}
          >
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
                    <Th numeric>Fill Price</Th>
                    <Th numeric>Total Value</Th>
                    <Th>Status</Th>
                    <Th>Order ID</Th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.trades.map((t) => {
                    const price = t.filled_price;
                    const isFilled = t.status === "FILLED";
                    return (
                      <Tr key={t.trade_id}>
                        <Td className="whitespace-nowrap text-muted text-xs">{dateTime(t.created_at)}</Td>
                        <Td className="font-medium whitespace-nowrap">
                          <div className="flex items-center gap-1.5">
                            <span className={t.side === "BUY" ? "text-emerald-600 font-bold" : "text-amber-600 font-bold"}>
                              {t.side === "BUY" ? "Buy" : "Sell"}
                            </span>
                            <span>{qty(t.qty)} {t.symbol}</span>
                          </div>
                        </Td>
                        <Td numeric className="figures">{price === null ? "–" : money(price)}</Td>
                        <Td numeric className="figures font-medium">{price === null ? "–" : money(price * t.qty)}</Td>
                        <Td>
                          <div className="flex flex-wrap gap-1">
                            <Tag tone={isFilled ? "success" : "neutral"}>{humanize(t.status)}</Tag>
                            {t.simulated ? <Tag tone="warning">Simulated</Tag> : null}
                          </div>
                        </Td>
                        <Td className="font-mono text-[11px] text-muted">{t.broker_order_id}</Td>
                      </Tr>
                    );
                  })}
                </tbody>
              </Table>
            )}
          </Panel>
        </div>
      </div>

    </div>
  );
}

export default function TradePage() {
  return (
    <>
      <PageHeader
        title="Trade & Investments"
        lede="Draft an order, review the pre-trade compliance checks, and approve it into the Alpaca paper-trading account."
      />
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
