"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { dateTime, money, pct, qty } from "@/lib/format";
import { api, type ApproveOptions } from "@/lib/api";
import type { Execution, Proposal, StepUpChallenge } from "@/lib/types";
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

/** Resolves to an inline error message when the client can correct the input and retry. */
export type ApproveHandler = (opts?: ApproveOptions) => Promise<string | void> | void;

/** Counts down once per second from `seconds`, restarting whenever `key` changes. */
function useSecondsLeft(seconds: number, key: unknown) {
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    setLeft(seconds);
    if (seconds <= 0) return;
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [seconds, key]);
  return left;
}

/** A drafted order awaiting the client's decision. Nothing reaches the broker until Approve. */
export function ProposalTicket({
  proposal,
  state = "open",
  onApprove,
  onReject,
}: {
  proposal: Proposal;
  state?: TicketState;
  onApprove?: ApproveHandler;
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

  const [stepUpOpen, setStepUpOpen] = useState(false);
  const [challenge, setChallenge] = useState<StepUpChallenge | null>(null);
  const [sending, setSending] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [attested, setAttested] = useState(false);
  const [stepUpError, setStepUpError] = useState<string | null>(null);
  const [sentAt, setSentAt] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const resendIn = useSecondsLeft(challenge?.resend_after_seconds ?? 0, sentAt);
  const codeExpiresIn = useSecondsLeft(challenge?.expires_in_seconds ?? 0, sentAt);

  // A different order loaded into this ticket starts from a clean slate (no code, attestation or errors)
  useEffect(() => {
    setStepUpOpen(false);
    setChallenge(null);
    setMfaCode("");
    setAttested(false);
    setStepUpError(null);
    setSentAt(0);
    setConfirming(false);
  }, [proposal.proposal_id]);

  useEffect(() => {
    if (!confirming) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setConfirming(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirming]);

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
      <span className="figures text-[0.9375rem] text-muted">Expires in {label}</span>
    );

  async function sendCode() {
    setSending(true);
    setStepUpError(null);
    try {
      const res = await api.requestStepUpCode(proposal.proposal_id);
      setChallenge(res);
      setSentAt(Date.now());
      setMfaCode("");
    } catch (err) {
      setStepUpError((err as Error).message);
    } finally {
      setSending(false);
    }
  }

  async function handlePrimaryApprove() {
    if (isRedTier && !stepUpOpen) {
      setStepUpOpen(true);
      void sendCode();
      return;
    }
    // Large orders get a final "are you sure?" summary before anything is sent
    if (isRedTier && !confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    setStepUpError(null);
    const retry = await onApprove?.(
      isRedTier ? { mfaCode: mfaCode.trim(), fiduciaryAttested: attested } : { fiduciaryAttested: true },
    );
    if (retry) {
      setStepUpError(retry);
      setMfaCode("");
    }
  }

  const codeReady = /^\d{6}$/.test(mfaCode.trim()) && attested && challenge !== null && codeExpiresIn > 0;
  const expiryLabel = `${Math.floor(codeExpiresIn / 60)}:${String(codeExpiresIn % 60).padStart(2, "0")}`;

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
            <dt className="text-[0.9375rem] text-muted">{k}</dt>
            <dd className="figures font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>

      {/* Concentration Ceiling Warning & Client-Directed Override Notice */}
      {actionable && exceedsConcentration ? (
        <div className="border-t border-warning/30 bg-warning-soft/40 px-4 py-3 text-xs">
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
        </div>
      ) : null}

      {actionable && isRedTier && stepUpOpen ? (
        <div className="border-t border-line bg-surface/60 px-4 py-3 text-xs space-y-2.5">
          <p className="font-semibold text-ink">Two-Step Order Confirmation</p>
          <p className="text-muted">
            {challenge
              ? codeExpiresIn > 0
                ? `We emailed a 6-digit code to ${challenge.destination}. It approves this order only and expires in ${expiryLabel}.`
                : "Your code has expired. Request a new one."
              : sending
              ? "Sending your verification code…"
              : "Orders above $1,000 or 5% of your portfolio need a one-time code sent to your registered email."}
          </p>
          {challenge?.dev_code ? (
            <p className="rounded-md border border-warning/40 bg-warning-soft/40 px-2.5 py-1.5 text-ink">
              Local development server: email delivery is not configured, so the code is shown here:{" "}
              <span className="figures font-semibold">{challenge.dev_code}</span>
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-ink">
              <span>Verification code:</span>
              <input
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ""))}
                placeholder="6-digit code"
                disabled={!challenge}
                className="figures w-24 rounded-md border border-line bg-background px-2.5 py-1 text-xs text-ink focus:border-accent focus:outline-none disabled:opacity-50"
              />
            </label>
            <button
              type="button"
              onClick={() => void sendCode()}
              disabled={sending || resendIn > 0}
              className="text-accent underline underline-offset-4 font-medium disabled:text-muted disabled:no-underline"
            >
              {sending ? "Sending…" : !challenge ? "Send code" : resendIn > 0 ? `Resend code in ${resendIn}s` : "Resend code"}
            </button>
          </div>
          <label className="flex items-start gap-2 text-ink cursor-pointer">
            <input
              type="checkbox"
              checked={attested}
              onChange={(e) => setAttested(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded accent-primary"
            />
            <span>
              {exceedsConcentration
                ? `I acknowledge that holding ${pct(proposal.projected_weight)} in ${proposal.symbol} exceeds the 15.0% concentration ceiling, and I instruct the platform to execute this as an unsolicited, client-directed order under my informed consent.`
                : "I confirm this order matches my investment goals and risk profile."}
            </span>
          </label>
          {stepUpError ? <p className="font-medium text-danger">{stepUpError}</p> : null}
        </div>
      ) : null}

      {actionable ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-line bg-surface px-4 py-3">
          <Button
            size="sm"
            onClick={() => void handlePrimaryApprove()}
            pending={state === "approving"}
            disabled={state !== "open" || (isRedTier && stepUpOpen && !codeReady)}
          >
            {isRedTier && !stepUpOpen
              ? "Continue to verification"
              : exceedsConcentration
              ? "Approve & Execute (Client-Directed Override)"
              : "Approve and place order"}
          </Button>
          <Button size="sm" variant="secondary" onClick={onReject} disabled={state !== "open"}>
            Cancel
          </Button>
          <span className="text-[0.9375rem] text-muted">
            {exceedsConcentration
              ? "The client-directed waiver is recorded in the signed audit trail."
              : "Suitability and portfolio limits are checked automatically before execution."}
          </span>
        </div>
      ) : null}

      {confirming && actionable && typeof document !== "undefined"
        ? createPortal(
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4"
          onClick={() => setConfirming(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`confirm-${proposal.proposal_id}`}
            className="w-full max-w-md rounded-card border border-line bg-background p-5 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id={`confirm-${proposal.proposal_id}`} className="text-base font-semibold text-ink">
              Confirm this order
            </h2>
            <p className="mt-2 text-sm text-ink">
              {proposal.side === "BUY" ? "Buy" : "Sell"} <strong>{qty(proposal.qty)} {proposal.symbol}</strong> for about{" "}
              <strong className="figures">{money(proposal.notional_value)}</strong> at market. It will be{" "}
              <strong className="figures">{pct(proposal.projected_weight)}</strong> of your portfolio afterwards.
            </p>
            <p className="mt-2 text-xs text-muted">
              Once sent to the broker the order cannot be cancelled from FinFuture. Prices can move before it fills.
            </p>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button size="sm" variant="secondary" onClick={() => setConfirming(false)}>
                Go back
              </Button>
              <Button size="sm" autoFocus onClick={() => void handlePrimaryApprove()} pending={state === "approving"}>
                Yes, place order
              </Button>
            </div>
          </div>
        </div>,
          document.body,
        )
        : null}
    </div>
  );
}

/** Broker confirmation after an order is placed. */
export function ExecutionReceipt({ execution }: { execution: Execution }) {
  const [copied, setCopied] = useState(false);

  const displayQty = execution.filled_qty && execution.filled_qty > 0 ? execution.filled_qty : execution.qty;
  const displayPrice = execution.filled_price ?? (execution.total_price && displayQty ? execution.total_price / displayQty : null);
  const orderRef = execution.order_id ?? execution.trade_id ?? "";
  const filled = execution.status === "FILLED";

  function copyId() {
    void navigator.clipboard.writeText(orderRef);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-success/35 bg-success-soft shadow-xs">
      <div className="flex items-center justify-between gap-3 border-b border-success/25 bg-surface/40 px-4 py-3">
        <p className="text-sm font-bold text-ink">
          {execution.side === "BUY" ? "Bought" : "Sold"} {qty(displayQty)} {execution.symbol}
        </p>
        <div className="flex items-center gap-2">
          {execution.dry_run ? <Tag tone="warning">Simulated fill</Tag> : <Tag tone="neutral">Alpaca paper</Tag>}
          <Tag tone={filled ? "success" : "warning"}>{filled ? "Filled" : humanizeStatus(execution.status)}</Tag>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 bg-background/50 px-4 py-3 text-sm sm:grid-cols-3">
        {[
          [filled ? "Fill price" : "Est. price", displayPrice ? money(displayPrice) : "Pending"],
          ["Total value", displayPrice ? money(displayPrice * displayQty) : "–"],
          ["Placed", dateTime(execution.executed_at)],
        ].map(([k, v]) => (
          <div key={k} className="py-1">
            <dt className="text-[12px] text-muted">{k}</dt>
            <dd className="figures font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="space-y-2 border-t border-success/25 bg-background/90 px-4 py-3 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-ink">
            Order ID: <span className="font-mono font-semibold">{orderRef}</span>
          </p>
          <button
            type="button"
            onClick={copyId}
            className="rounded-md border border-line bg-surface px-2.5 py-1 font-semibold text-ink transition-colors hover:bg-surface/80"
          >
            {copied ? "Copied" : "Copy order ID"}
          </button>
        </div>
        <p className="text-muted">
          {execution.dry_run
            ? "No broker credentials are configured on this server, so the order was filled at a reference price and never sent to a broker. It is recorded in your portfolio and the audit trail."
            : "Sent to Alpaca's paper-trading API. The account owner can find this order ID under Orders in the Alpaca paper dashboard (app.alpaca.markets). Orders placed while the market is closed fill at the next open."}
        </p>
      </div>
    </div>
  );
}

function humanizeStatus(status: string) {
  return status.charAt(0) + status.slice(1).toLowerCase().replace(/_/g, " ");
}
