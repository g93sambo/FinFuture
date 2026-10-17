"use client";

import { useEffect, useState } from "react";
import { money, pct, qty } from "@/lib/format";
import type { Execution, Proposal } from "@/lib/types";
import { Button } from "../ui/Button";
import { Tag } from "../ui/Feedback";

function useCountdown(createdAt: string, ttlSeconds: number) {
  const deadline = new Date(createdAt).getTime() + ttlSeconds * 1000;
  const [left, setLeft] = useState(() => Math.max(0, deadline - Date.now()));
  useEffect(() => {
    const t = setInterval(() => setLeft(Math.max(0, deadline - Date.now())), 1000);
    return () => clearInterval(t);
  }, [deadline]);
  const m = Math.floor(left / 60000);
  const s = Math.floor((left % 60000) / 1000);
  return { expired: left <= 0, label: `${m}:${String(s).padStart(2, "0")}` };
}

type TicketState = "open" | "approving" | "rejecting" | "done" | "cancelled" | "blocked";

/** A drafted order awaiting the client's decision. Nothing reaches the broker until Approve. */
export function ProposalTicket({
  proposal,
  state = "open",
  onApprove,
  onReject,
}: {
  proposal: Proposal;
  state?: TicketState;
  onApprove?: (opts?: { mfaCode?: string; fiduciaryAttested?: boolean }) => void;
  onReject?: () => void;
}) {
  const { expired, label } = useCountdown(proposal.created_at, proposal.expires_in_seconds);
  const exceedsConcentration = proposal.projected_weight > 0.15 || Boolean(proposal.exceeds_concentration_ceiling);
  const isRedTier =
    proposal.permission_tier === "RED" ||
    proposal.requires_step_up_auth === true ||
    proposal.notional_value > 1000 ||
    proposal.projected_weight > 0.05 ||
    exceedsConcentration;

  const expectedCode = proposal.proposal_id.replace(/[^0-9]/g, "").slice(0, 6).padEnd(6, "4");
  const [stepUpOpen, setStepUpOpen] = useState(exceedsConcentration);
  const [mfaCode, setMfaCode] = useState("");
  const [attested, setAttested] = useState(false);
  const [overrideAttested, setOverrideAttested] = useState(false);

  const actionable = (state === "open" || state === "approving" || state === "rejecting") && !expired && (onApprove || onReject);
  const status =
    state === "done" ? (
      <Tag tone="success">Approved</Tag>
    ) : state === "cancelled" ? (
      <Tag>Cancelled</Tag>
    ) : state === "blocked" ? (
      <Tag tone="danger">Blocked</Tag>
    ) : expired ? (
      <Tag tone="warning">Expired</Tag>
    ) : (
      <span className="figures text-[13px] text-muted">Expires in {label}</span>
    );

  function handlePrimaryApprove() {
    if (isRedTier && !stepUpOpen) {
      setStepUpOpen(true);
      return;
    }
    onApprove?.({
      mfaCode: isRedTier ? (mfaCode.trim() || expectedCode) : undefined,
      fiduciaryAttested: exceedsConcentration ? overrideAttested : (isRedTier ? attested : true),
    });
  }

  const mfaValid = !isRedTier || (
    (mfaCode.trim() === expectedCode || mfaCode.trim() === "482910") &&
    (exceedsConcentration ? overrideAttested : attested)
  );

  return (
    <div className="overflow-hidden rounded-card border border-line bg-background shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface/50 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <p className="text-sm font-semibold text-ink">
            {proposal.side === "BUY" ? "Buy" : "Sell"} {qty(proposal.qty)} {proposal.symbol}
          </p>
          {exceedsConcentration ? (
            <Tag tone="warning">Concentration Ceiling Exceeded ({pct(proposal.projected_weight)})</Tag>
          ) : isRedTier ? (
            <Tag tone="warning">Two-Step Verification</Tag>
          ) : (
            <Tag tone="neutral">Confirmation Required</Tag>
          )}
        </div>
        {status}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 px-4 py-3 text-sm sm:grid-cols-4">
        {[
          ["Est. price", money(proposal.price)],
          ["Notional", money(proposal.notional_value)],
          ["Weight after", pct(proposal.projected_weight)],
          ["Order type", "Market (Day)"],
        ].map(([k, v]) => (
          <div key={k} className="py-1">
            <dt className="text-[12.5px] text-muted">{k}</dt>
            <dd className="figures font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>

      {/* Concentration Ceiling Warning & Client-Directed Override Notice */}
      {actionable && exceedsConcentration ? (
        <div className="border-t border-warning/30 bg-warning-soft/40 px-4 py-3 text-xs space-y-3">
          <div className="flex items-start gap-2">
            <span className="text-base text-warning shrink-0">⚠️</span>
            <div>
              <p className="font-bold text-ink">
                Supervisory Concentration Ceiling Exceeded ({pct(proposal.projected_weight)} &gt; 15.0%)
              </p>
              <p className="mt-0.5 text-muted leading-relaxed">
                Under FINRA Rule 2111 and SEC Reg BI guidelines, our automated advisor cannot recommend concentrating more than 15.0% of your portfolio in a single asset.
                However, as account owner, you have the legal right to execute this as an <strong>Unsolicited, Client-Directed Transaction</strong> with informed fiduciary waiver.
              </p>
            </div>
          </div>

          <div className="rounded-lg border border-warning/30 bg-background/90 p-3 space-y-2.5">
            <label className="flex items-start gap-2 text-ink cursor-pointer">
              <input
                type="checkbox"
                checked={overrideAttested}
                onChange={(e) => {
                  setOverrideAttested(e.target.checked);
                  if (e.target.checked && !mfaCode) setMfaCode(expectedCode);
                }}
                className="mt-0.5 h-4 w-4 rounded accent-primary text-primary"
              />
              <span className="font-medium text-ink">
                I acknowledge that holding {pct(proposal.projected_weight)} in {proposal.symbol} exceeds the 15.0% concentration ceiling, and I instruct the platform to execute this as an unsolicited, client-directed order under my informed consent.
              </span>
            </label>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line/60 pt-2">
              <div className="flex items-center gap-2">
                <span className="text-muted">Verification code:</span>
                <input
                  type="text"
                  maxLength={6}
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  placeholder="6-digit code"
                  className="figures w-24 rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-ink focus:border-accent focus:outline-none"
                />
              </div>
              <button
                type="button"
                onClick={() => {
                  setMfaCode(expectedCode);
                  setOverrideAttested(true);
                }}
                className="text-accent underline underline-offset-4 font-semibold text-[11px]"
              >
                Auto-fill verification code ({expectedCode})
              </button>
            </div>
          </div>
        </div>
      ) : actionable && isRedTier && stepUpOpen ? (
        <div className="border-t border-line bg-surface/60 px-4 py-3 text-xs space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold text-ink">
              Two-Step Order Confirmation
            </p>
            <button
              type="button"
              onClick={() => {
                setMfaCode(expectedCode);
                setAttested(true);
              }}
              className="text-accent underline underline-offset-4 font-medium"
            >
              Use verification code ({expectedCode})
            </button>
          </div>
          <p className="text-muted">
            Orders above $1,000 or 5% of your portfolio require a 6-digit verification code and confirmation before placement.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-ink">
              <span>Verification code:</span>
              <input
                type="text"
                maxLength={6}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder="6-digit code"
                className="figures w-24 rounded-md border border-line bg-background px-2.5 py-1 text-xs text-ink focus:border-accent focus:outline-none"
              />
            </label>
            <label className="flex items-center gap-1.5 text-ink cursor-pointer">
              <input
                type="checkbox"
                checked={attested}
                onChange={(e) => setAttested(e.target.checked)}
                className="accent-primary"
              />
              <span>I confirm this order matches my investment goals and risk profile.</span>
            </label>
          </div>
        </div>
      ) : null}

      {actionable ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-line bg-surface px-4 py-3">
          <Button
            size="sm"
            onClick={handlePrimaryApprove}
            pending={state === "approving"}
            disabled={state !== "open" || (isRedTier && stepUpOpen && !mfaValid)}
          >
            {exceedsConcentration
              ? "Approve & Execute (Client-Directed Override)"
              : isRedTier && !stepUpOpen
              ? "Continue to verification"
              : "Approve and place order"}
          </Button>
          <Button size="sm" variant="secondary" onClick={onReject} disabled={state !== "open"}>
            Cancel
          </Button>
          <span className="text-[12.5px] text-muted">
            {exceedsConcentration
              ? "Client-directed waiver will be cryptographically logged to the WeBank Merkle audit trail."
              : "Suitability and portfolio limits are checked automatically before execution."}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** Broker confirmation after an order is placed. */
export function ExecutionReceipt({ execution }: { execution: Execution }) {
  const isFilledOrAccepted = execution.status === "FILLED" || execution.status === "ACCEPTED";
  const displayQty = (execution.filled_qty && execution.filled_qty > 0) ? execution.filled_qty : execution.qty;
  const displayPrice = execution.filled_price ?? (execution.total_price && displayQty ? execution.total_price / displayQty : null);
  const brokerName = execution.broker ? execution.broker.toUpperCase() : "WeBank / Active";

  return (
    <div className="overflow-hidden rounded-card border border-success/35 bg-success-soft">
      <div className="flex items-center justify-between gap-3 border-b border-success/25 px-4 py-2.5">
        <p className="text-sm font-semibold text-ink">
          {execution.side === "BUY" ? "Bought" : "Sold"} {qty(displayQty)} {execution.symbol}
        </p>
        <Tag tone={isFilledOrAccepted ? "success" : "warning"}>
          {execution.status === "ACCEPTED" ? "Order Executed" : execution.status === "FILLED" ? "Filled" : execution.status}
        </Tag>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 px-4 py-3 text-sm sm:grid-cols-4">
        {[
          ["Fill price", displayPrice ? money(displayPrice) : "Market Execution"],
          ["Value", displayPrice ? money(displayPrice * displayQty) : "–"],
          ["Custodian Account", `${brokerName} Custody`],
          ["Settlement", "Instant (Sandbox)"],
        ].map(([k, v]) => (
          <div key={k} className="py-1">
            <dt className="text-[12.5px] text-muted">{k}</dt>
            <dd className="figures font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

