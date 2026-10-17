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
  onApprove?: () => void;
  onReject?: () => void;
}) {
  const { expired, label } = useCountdown(proposal.created_at, proposal.expires_in_seconds);
  const isRedTier =
    proposal.permission_tier === "RED" ||
    proposal.requires_step_up_auth === true ||
    proposal.notional_value > 1000 ||
    proposal.projected_weight > 0.05;

  const expectedCode = proposal.proposal_id.replace(/[^0-9]/g, "").slice(0, 6).padEnd(6, "4");
  const [stepUpOpen, setStepUpOpen] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [attested, setAttested] = useState(false);

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
    onApprove?.();
  }

  const mfaValid = !isRedTier || (mfaCode.trim() === expectedCode && attested);

  return (
    <div className="overflow-hidden rounded-card border border-line bg-background shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface/50 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <p className="text-sm font-semibold text-ink">
            {proposal.side === "BUY" ? "Buy" : "Sell"} {qty(proposal.qty)} {proposal.symbol}
          </p>
          {isRedTier ? (
            <Tag tone="danger">RED TIER · Strong Verification</Tag>
          ) : (
            <Tag tone="warning">YELLOW TIER · User Confirmation</Tag>
          )}
        </div>
        {status}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 px-4 py-3 text-sm sm:grid-cols-4">
        {[
          ["Est. price", money(proposal.price)],
          ["Notional", money(proposal.notional_value)],
          ["Weight after", pct(proposal.projected_weight)],
          ["Reference", proposal.proposal_id.slice(0, 8)],
        ].map(([k, v]) => (
          <div key={k} className="py-1">
            <dt className="text-[12.5px] text-muted">{k}</dt>
            <dd className="figures font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>

      {actionable && isRedTier && stepUpOpen ? (
        <div className="border-t border-danger/30 bg-danger-soft/40 px-4 py-3 text-xs space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold text-ink">
              Red-Tier Step-Up Security Verification Required (REG-003)
            </p>
            <button
              type="button"
              onClick={() => {
                setMfaCode(expectedCode);
                setAttested(true);
              }}
              className="text-accent underline underline-offset-4 font-medium"
            >
              Auto-fill sandbox OTP ({expectedCode})
            </button>
          </div>
          <p className="text-muted">
            {proposal.step_up_reason ??
              "This order exceeds the Yellow-Tier threshold ($1,000 notional or 5% portfolio weight) and requires multi-factor confirmation."}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-ink">
              <span>6-digit OTP:</span>
              <input
                type="text"
                maxLength={6}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder={expectedCode}
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
              <span>I confirm this non-discretionary paper order matches my risk profile.</span>
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
            {isRedTier && !stepUpOpen
              ? "Proceed to Red-Tier Verification"
              : "Approve and place order"}
          </Button>
          <Button size="sm" variant="secondary" onClick={onReject} disabled={state !== "open"}>
            Cancel
          </Button>
          <span className="text-[12.5px] text-muted">
            {isRedTier
              ? "Red-Tier gate: requires MFA + 12-rule pre-trade compliance check."
              : "Yellow-Tier gate: pre-trade compliance runs when you approve."}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** Broker confirmation after an order is placed. */
export function ExecutionReceipt({ execution }: { execution: Execution }) {
  const filled = execution.status === "FILLED";
  return (
    <div className="overflow-hidden rounded-card border border-success/35 bg-success-soft">
      <div className="flex items-center justify-between gap-3 border-b border-success/25 px-4 py-2.5">
        <p className="text-sm font-semibold text-ink">
          {execution.side === "BUY" ? "Bought" : "Sold"} {qty(execution.filled_qty ?? execution.qty)} {execution.symbol}
        </p>
        <Tag tone={filled ? "success" : "warning"}>{filled ? "Filled" : execution.status}</Tag>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 px-4 py-3 text-sm sm:grid-cols-4">
        {[
          ["Fill price", money(execution.filled_price)],
          ["Value", execution.filled_price ? money(execution.filled_price * (execution.filled_qty ?? execution.qty)) : "–"],
          ["Venue", execution.dry_run ? "Simulated fill" : "Alpaca paper"],
          ["Order", (execution.order_id ?? "").replace(/^dry-run-/, "").slice(0, 8)],
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

