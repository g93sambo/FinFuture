"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState, useEffect } from "react";
import { ComplianceSummary, Violations } from "@/components/domain/Compliance";
import { ConnectBrokerModal } from "@/components/domain/ConnectBrokerModal";
import { TickerAutocomplete } from "@/components/domain/TickerAutocomplete";
import { ExecutionReceipt, ProposalTicket } from "@/components/domain/TradeTicket";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button } from "@/components/ui/Button";
import { ErrorNotice, Loading, Notice, TableSkeleton, Tag } from "@/components/ui/Feedback";
import { Field, Input, Segmented } from "@/components/ui/Field";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, api } from "@/lib/api";
import {
  getStoredBroker,
  getStoredBenchmark,
  type BrokerageInfo,
  type BenchmarkIndexInfo,
} from "@/lib/custodians";
import {
  POPULAR_CURATED_ASSETS,
  CURATED_BASKETS,
  PRESET_DOLLAR_AMOUNTS,
  getAssetRefPrice,
  type CuratedAsset,
  type CuratedBasket,
} from "@/lib/curatedInvestments";
import { dateTime, humanize, money, qty } from "@/lib/format";
import type { AgentEvent, Execution, Proposal, Trade, TradeBlockedDetail } from "@/lib/types";
import { CustodianVerificationModal } from "@/components/domain/CustodianVerificationModal";
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
  const [symbol, setSymbol] = useState((params.get("symbol") ?? "AAPL").toUpperCase());
  const [side, setSide] = useState<Side>(params.get("side") === "SELL" ? "SELL" : "BUY");
  const [quantity, setQuantity] = useState(params.get("qty") ?? "1");
  const [selectedDollar, setSelectedDollar] = useState<number | null>(null);
  const [investMode, setInvestMode] = useState<"quick" | "custom">("quick");

  // Broker & Custody Gateway state
  const [isBrokerModalOpen, setIsBrokerModalOpen] = useState(false);
  const [isVerifyModalOpen, setIsVerifyModalOpen] = useState(false);
  const [verificationTrade, setVerificationTrade] = useState<Trade | null>(null);
  const [activeBroker, setActiveBroker] = useState<BrokerageInfo>(() => getStoredBroker());
  const [activeBenchmark, setActiveBenchmark] = useState<BenchmarkIndexInfo>(() => getStoredBenchmark());

  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [ticketState, setTicketState] = useState<"open" | "approving" | "done" | "cancelled" | "blocked">("open");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const history = useRequest(`trades:${clientId}`, () => api.trades(clientId, 100));
  const portfolio = useRequest(`pf:${clientId}`, () => api.portfolio(clientId));

  useEffect(() => {
    setActiveBroker(getStoredBroker());
    setActiveBenchmark(getStoredBenchmark());
  }, []);

  const q = Number(quantity);
  const symbolOk = /^[A-Z0-9.]{1,10}$/.test(symbol);
  const qtyOk = Number.isFinite(q) && q > 0;
  const held = portfolio.data?.positions.find((p) => p.symbol === symbol)?.qty ?? 0;
  const buyingPower = portfolio.data?.cash ?? 83420.0;
  const currentRefPrice = getAssetRefPrice(symbol);
  const estimatedTotal = qtyOk ? q * currentRefPrice : 0;

  function handleSelectAsset(asset: CuratedAsset, dollarAmount?: number) {
    setSymbol(asset.symbol);
    const amt = dollarAmount ?? selectedDollar ?? 100;
    setSelectedDollar(amt);
    const calculatedQty = Math.max(0.0001, Number((amt / asset.refPrice).toFixed(4)));
    setQuantity(String(calculatedQty));
    setDraftError(null);
  }

  function handleSelectBasket(basket: CuratedBasket) {
    setSymbol(basket.primarySymbol);
    setSelectedDollar(basket.recommendedDollar);
    const calculatedQty = Math.max(0.0001, Number((basket.recommendedDollar / basket.refPrice).toFixed(4)));
    setQuantity(String(calculatedQty));
    setDraftError(null);
  }

  function handleSelectDollar(dollarAmt: number) {
    setSelectedDollar(dollarAmt);
    const price = currentRefPrice > 0 ? currentRefPrice : 100.0;
    const calculatedQty = Math.max(0.0001, Number((dollarAmt / price).toFixed(4)));
    setQuantity(String(calculatedQty));
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

  async function approve(opts?: { mfaCode?: string; fiduciaryAttested?: boolean }) {
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
      {/* 1. Connected Custodian & Account Banner */}
      <div className="rounded-2xl border border-line bg-surface/70 p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-2xl shadow-inner">
              {activeBroker.isWeBank ? "🏦" : activeBroker.category === "Crypto & Digital" ? "🪙" : "📈"}
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-base font-bold text-ink sm:text-lg">{activeBroker.name}</span>
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Connected & Audited
                </span>
                <Tag tone="neutral">{activeBroker.region}</Tag>
              </div>
              <p className="mt-1 text-xs text-muted sm:text-sm">
                Category: <strong className="text-ink">{activeBroker.category}</strong> • Merkle Hash Audit Trail Active
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-xl border border-line/80 bg-background/80 px-4 py-2 text-right">
              <span className="block text-[11px] font-medium uppercase tracking-wider text-muted">Available Buying Power</span>
              <span className="figures text-base font-bold text-ink sm:text-lg">{money(buyingPower)}</span>
            </div>
            <div className="rounded-xl border border-line/80 bg-background/80 px-4 py-2 text-right">
              <span className="block text-[11px] font-medium uppercase tracking-wider text-muted">Benchmark Index</span>
              <span className="text-sm font-semibold text-ink">{activeBenchmark.name} ({activeBenchmark.symbol})</span>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setVerificationTrade(null);
                setIsVerifyModalOpen(true);
              }}
              className="font-medium shrink-0"
            >
              🔍 Verify Custody Ledger
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setIsBrokerModalOpen(true)}
              className="font-medium shrink-0"
            >
              🔄 Switch Broker
            </Button>
          </div>
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
                  className={`rounded px-2.5 py-1 font-medium transition-colors ${
                    investMode === "quick" ? "bg-accent text-white" : "text-muted hover:text-ink"
                  }`}
                >
                  🌟 Quick Invest
                </button>
                <button
                  type="button"
                  onClick={() => setInvestMode("custom")}
                  className={`rounded px-2.5 py-1 font-medium transition-colors ${
                    investMode === "custom" ? "bg-accent text-white" : "text-muted hover:text-ink"
                  }`}
                >
                  🔍 Custom Ticker
                </button>
              </div>
            }
          >
            {investMode === "quick" ? (
              <div className="space-y-6">
                {/* Thematic Baskets */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-bold uppercase tracking-wider text-muted">
                      Curated Thematic Baskets (1-Click)
                    </p>
                    <span className="text-[11px] text-muted">Pre-diversified packs</span>
                  </div>
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    {CURATED_BASKETS.map((b) => {
                      const isSelected = symbol === b.primarySymbol;
                      return (
                        <button
                          key={b.id}
                          type="button"
                          onClick={() => handleSelectBasket(b)}
                          className={`flex flex-col justify-between rounded-xl border p-3 text-left transition-all ${
                            isSelected
                              ? "border-accent bg-accent/5 ring-1 ring-accent"
                              : "border-line bg-surface/50 hover:border-line-strong hover:bg-surface"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-xl">{b.icon}</span>
                            <span className="rounded-full bg-surface px-2 py-0.5 text-[10px] font-semibold text-muted">
                              {b.badge}
                            </span>
                          </div>
                          <div className="mt-2">
                            <p className="text-xs font-bold text-ink">{b.title}</p>
                            <p className="mt-0.5 text-[11px] text-muted line-clamp-1">{b.subtitle}</p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Popular Household Stocks */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-bold uppercase tracking-wider text-muted">
                      Popular Household Investments
                    </p>
                    <span className="text-[11px] text-muted">Fractional shares available</span>
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
                          <span className="figures text-[10px] text-muted">{money(a.refPrice)}</span>
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
                    <span className="text-[11px] text-muted">Instant fractional share auto-calc</span>
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
                              ? "border-accent bg-accent text-white shadow-xs"
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
                      <span className="text-[11px] uppercase font-semibold text-muted">Reference Price</span>
                      <p className="figures text-sm font-bold text-ink">{money(currentRefPrice)}</p>
                    </div>
                  </div>
                </div>
              )}

              <Field
                label="Quantity (Shares)"
                hint={
                  qtyOk
                    ? `Estimated value: ${money(estimatedTotal)} (${qty(q)} shares @ ${money(currentRefPrice)})`
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

              <div className="flex items-center gap-4 pt-1">
                <Button type="submit" pending={drafting} disabled={!symbolOk || !qtyOk || ticketState === "approving"}>
                  Draft Investment Proposal
                </Button>
                <span className="text-[13px] text-muted">Review compliance before placing.</span>
              </div>
            </form>
          </Panel>

          <Notice tone="neutral" title="Investor Protection & Safeguards">
            <ul className="mt-1 list-inside list-disc space-y-1 text-xs text-muted marker:text-muted">
              <li><strong>Zero Discretionary Risk:</strong> The platform will never trade on your behalf without your explicit approval.</li>
              <li><strong>Fractional Investing:</strong> You own real underlying shares regardless of dollar amount.</li>
              <li><strong>Regulatory Compliance:</strong> Every order is checked against FINRA Rule 2111 and SEC Reg BI limits in real-time.</li>
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
                Pick a popular stock or curated basket above, or enter your own ticker. Click &quot;Draft Investment Proposal&quot; to review the pricing and compliance checks.
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
                    <Th>Custodian Verification</Th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.trades.map((t) => {
                    const price = t.filled_price ?? getAssetRefPrice(t.symbol);
                    const totalVal = price * t.qty;
                    const isAcceptedOrFilled = t.status === "FILLED" || t.status === "ACCEPTED";
                    const orderRef = t.broker_order_id || t.alpaca_order_id || `WBK-ORD-${t.trade_id.slice(0, 8).toUpperCase()}`;
                    const brokerKey = t.broker || "webank";
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
                        <Td numeric className="figures">{money(price)}</Td>
                        <Td numeric className="figures font-medium">{money(totalVal)}</Td>
                        <Td>
                          <Tag tone={isAcceptedOrFilled ? "success" : "neutral"}>
                            {t.status === "ACCEPTED" ? "Executed" : humanize(t.status)}
                          </Tag>
                        </Td>
                        <Td>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-[11px] text-muted">{orderRef}</span>
                            <button
                              type="button"
                              onClick={() => {
                                setVerificationTrade(t);
                                setIsVerifyModalOpen(true);
                              }}
                              className="inline-flex items-center gap-1 rounded bg-accent/10 hover:bg-accent/20 px-2.5 py-1 text-[11px] font-semibold text-accent transition-colors"
                            >
                              <span>🔍 Check on {brokerKey.toUpperCase()} ↗</span>
                            </button>
                          </div>
                        </Td>
                      </Tr>
                    );
                  })}
                </tbody>
              </Table>
            )}
          </Panel>
        </div>
      </div>

      {/* Broker & Custodian Connection Modal */}
      <ConnectBrokerModal
        isOpen={isBrokerModalOpen}
        onClose={() => setIsBrokerModalOpen(false)}
        onConnect={(broker, benchmark) => {
          setActiveBroker(broker);
          setActiveBenchmark(benchmark);
        }}
      />

      {/* Custodian Verification & Execution Slip Modal */}
      <CustodianVerificationModal
        isOpen={isVerifyModalOpen}
        onClose={() => setIsVerifyModalOpen(false)}
        trade={verificationTrade}
        brokerId={verificationTrade?.broker || activeBroker.id}
      />
    </div>
  );
}

export default function TradePage() {
  return (
    <>
      <PageHeader
        title="Trade & Investments"
        lede="Invest in curated baskets, popular stocks, or custom securities with institutional custody and non-discretionary protection."
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
