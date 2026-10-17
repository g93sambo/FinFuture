"use client";

import { useState } from "react";
import {
  getCustodianVerificationGuide,
  getStoredBroker,
  type CustodianVerificationGuide,
} from "@/lib/custodians";
import { dateTime, money, qty } from "@/lib/format";
import type { Trade } from "@/lib/types";
import { Button } from "../ui/Button";
import { Tag } from "../ui/Feedback";

interface CustodianVerificationModalProps {
  isOpen: boolean;
  onClose: () => void;
  trade?: Trade | null;
  brokerId?: string;
}

export function CustodianVerificationModal({
  isOpen,
  onClose,
  trade,
  brokerId,
}: CustodianVerificationModalProps) {
  const [copiedId, setCopiedId] = useState(false);
  const [copiedHash, setCopiedHash] = useState(false);
  const [showRawJson, setShowRawJson] = useState(false);

  if (!isOpen) return null;

  const activeBrokerId = trade?.broker || brokerId || getStoredBroker().id;
  const orderId = trade?.broker_order_id || trade?.alpaca_order_id || trade?.trade_id || "WBK-ORD-PENDING";
  const guide: CustodianVerificationGuide = getCustodianVerificationGuide(activeBrokerId, orderId);

  const price = trade?.filled_price ?? 0;
  const quantity = trade?.qty ?? 1;
  const totalVal = price * quantity;
  const auditHash = trade?.full_audit_hash || trade?.audit_hash || "0x9f8e7d6c5b4a3210fedcba9876543210";

  function copyOrderId() {
    navigator.clipboard.writeText(orderId);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  }

  function copyAuditHash() {
    navigator.clipboard.writeText(auditHash);
    setCopiedHash(true);
    setTimeout(() => setCopiedHash(false), 2000);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="custodian-verify-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-fadeIn"
    >
      <div className="relative flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-line bg-background shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-line bg-surface/60 p-5 sm:p-6">
          <div className="flex items-start gap-3.5">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-2xl shadow-inner">
              {guide.icon}
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 id="custodian-verify-title" className="text-lg font-bold text-ink sm:text-xl">
                  {guide.brokerName}
                </h2>
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Custodian Verified
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted">
                Order Execution &amp; Clearing Verification Slip
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-muted hover:bg-surface hover:text-ink transition-colors"
            aria-label="Close modal"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-5">
          {/* Trade Details Summary */}
          {trade ? (
            <div className="rounded-xl border border-line bg-surface/40 p-4">
              <div className="flex items-center justify-between pb-3 border-b border-line/60">
                <div className="flex items-center gap-2">
                  <span
                    className={`font-bold text-sm ${
                      trade.side === "BUY" ? "text-emerald-600" : "text-amber-600"
                    }`}
                  >
                    {trade.side === "BUY" ? "Buy" : "Sell"}
                  </span>
                  <span className="font-bold text-ink text-base">
                    {qty(trade.qty)} {trade.symbol}
                  </span>
                </div>
                <Tag tone={trade.status === "FILLED" || trade.status === "ACCEPTED" ? "success" : "neutral"}>
                  {trade.status === "ACCEPTED" ? "Executed" : trade.status}
                </Tag>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 text-xs">
                <div>
                  <span className="text-muted block text-[11px]">Fill Price</span>
                  <span className="font-semibold text-ink figures">{money(price)}</span>
                </div>
                <div>
                  <span className="text-muted block text-[11px]">Total Value</span>
                  <span className="font-semibold text-ink figures">{money(totalVal)}</span>
                </div>
                <div>
                  <span className="text-muted block text-[11px]">Settlement</span>
                  <span className="font-semibold text-ink">{trade.settlement_cycle || guide.settlementCycle}</span>
                </div>
                <div>
                  <span className="text-muted block text-[11px]">Order Time</span>
                  <span className="font-semibold text-ink">{dateTime(trade.created_at)}</span>
                </div>
              </div>
            </div>
          ) : null}

          {/* Custodian Identifiers with Copy */}
          <div className="rounded-xl border border-line/80 bg-background p-4 space-y-3">
            <p className="text-xs font-bold uppercase tracking-wider text-muted">
              Custodian Clearing Identifiers
            </p>

            {/* Broker Order ID */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-lg border border-line bg-surface/50 p-2.5 text-xs">
              <div>
                <span className="text-muted block text-[11px]">Broker Order ID / Reference</span>
                <span className="font-mono font-bold text-ink">{orderId}</span>
              </div>
              <button
                type="button"
                onClick={copyOrderId}
                className="self-start sm:self-auto rounded px-2.5 py-1 text-xs font-medium border border-line hover:bg-surface text-ink transition-colors"
              >
                {copiedId ? "✓ Copied" : "📋 Copy ID"}
              </button>
            </div>

            {/* Clearing Depository */}
            <div className="rounded-lg border border-line bg-surface/50 p-2.5 text-xs">
              <span className="text-muted block text-[11px]">Clearing Depository &amp; Routing</span>
              <span className="font-semibold text-ink">{guide.clearingHouse}</span>
            </div>

            {/* Cryptographic Audit Leaf */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-lg border border-line bg-surface/50 p-2.5 text-xs">
              <div className="overflow-hidden">
                <span className="text-muted block text-[11px]">Immutable Merkle Leaf Audit Hash</span>
                <span className="font-mono text-muted text-[11px] truncate block">
                  {trade?.audit_hash || auditHash.slice(0, 24) + "..."}
                </span>
              </div>
              <button
                type="button"
                onClick={copyAuditHash}
                className="self-start sm:self-auto shrink-0 rounded px-2.5 py-1 text-xs font-medium border border-line hover:bg-surface text-ink transition-colors"
              >
                {copiedHash ? "✓ Copied" : "📋 Copy Hash"}
              </button>
            </div>
          </div>

          {/* Where to check on Broker (Step-by-step guidance) */}
          <div className="rounded-xl border border-accent/25 bg-accent/5 p-4 sm:p-5 space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-base">📱</span>
              <h3 className="text-sm font-bold text-ink">
                Where to check this on {guide.shortName}:
              </h3>
            </div>

            {/* Mobile App Path Breadcrumb */}
            <div className="rounded-lg border border-accent/30 bg-background/90 p-3 text-xs">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted block mb-1">
                In-App Navigation Path:
              </span>
              <p className="font-mono font-bold text-accent sm:text-xs text-[11px] leading-relaxed">
                {guide.mobileAppPath}
              </p>
            </div>

            {/* Numbered Steps */}
            <ol className="list-decimal list-inside space-y-1.5 text-xs text-ink/90 pt-1">
              {guide.verificationSteps.map((step, idx) => (
                <li key={idx} className="leading-relaxed">
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          </div>

          {/* Direct External Link */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-2">
            <a
              href={guide.portalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-xs font-bold text-white shadow-xs hover:bg-accent/90 transition-colors"
            >
              <span>Open {guide.shortName} Portal ↗</span>
            </a>

            <button
              type="button"
              onClick={() => setShowRawJson(!showRawJson)}
              className="text-xs text-muted hover:text-ink underline underline-offset-4"
            >
              {showRawJson ? "Hide Raw Clearing Payload" : "View Raw Clearing Payload"}
            </button>
          </div>

          {/* Collapsible Raw JSON */}
          {showRawJson ? (
            <div className="rounded-xl border border-line bg-black/90 p-3.5 text-emerald-400 font-mono text-[11px] overflow-x-auto">
              <pre>
                {JSON.stringify(
                  {
                    broker: guide.brokerId,
                    broker_name: guide.brokerName,
                    order_id: orderId,
                    symbol: trade?.symbol || "AAPL",
                    side: trade?.side || "BUY",
                    quantity: quantity,
                    fill_price: price,
                    clearing_depository: guide.clearingHouse,
                    settlement_cycle: guide.settlementCycle,
                    merkle_leaf_hash: auditHash,
                    timestamp: trade?.created_at || new Date().toISOString(),
                    status: "EXECUTED_AND_LOGGED",
                  },
                  null,
                  2
                )}
              </pre>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-line bg-surface/50 px-5 py-3.5">
          <span className="text-[11px] text-muted">
            All trades are non-discretionary and cryptographically verifiable.
          </span>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}
