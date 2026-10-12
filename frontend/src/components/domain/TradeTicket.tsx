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

  return (
    <div className="border border-ink bg-background">
      <div className="flex items-center justify-between gap-3 border-b border-ink px-4 py-2.5">
        <p className="text-sm font-semibold text-ink">
          {proposal.side === "BUY" ? "Buy" : "Sell"} {qty(proposal.qty)} {proposal.symbol}
        </p>
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
            <dt className="text-[13px] text-muted">{k}</dt>
            <dd className="figures text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      {actionable ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-line bg-surface px-4 py-3">
          <Button size="sm" onClick={onApprove} pending={state === "approving"} disabled={state !== "open"}>
            Approve and place order
          </Button>
          <Button size="sm" variant="secondary" onClick={onReject} disabled={state !== "open"}>
            Cancel
          </Button>
          <span className="text-[13px] text-muted">Pre-trade compliance runs when you approve.</span>
        </div>
      ) : null}
    </div>
  );
}

/** Broker confirmation after an order is placed. */
export function ExecutionReceipt({ execution }: { execution: Execution }) {
  const filled = execution.status === "FILLED";
  return (
    <div className="border border-success/40 bg-success-soft">
      <div className="flex items-center justify-between gap-3 border-b border-success/30 px-4 py-2.5">
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
            <dt className="text-[13px] text-muted">{k}</dt>
            <dd className="figures text-ink">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
