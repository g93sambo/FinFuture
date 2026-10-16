"use client";

import { useEffect, useRef, useState } from "react";
import { TranscriptRow } from "@/components/domain/AgentMessage";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Feedback";
import { Textarea } from "@/components/ui/Field";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { useAuth } from "@/lib/auth";
import { useAdvisor, type Connection } from "@/lib/useAdvisor";

const stages = [
  ["PROFILING", "Risk profiling"],
  ["ADVICE_GENERATION", "Advice"],
  ["PROPOSAL_REVIEW", "Reviewing a trade"],
  ["EXECUTION", "Placing the order"],
  ["HEALTH_MONITORING", "Health review"],
] as const;

const profilingTopics = [
  "Age, employment and dependents",
  "Income, savings, expenses and debts",
  "Time horizon and main goal",
  "Risk rating and reaction to a 20% fall",
  "Experience, source of funds, PEP status",
];

const prompts = [
  "Recommend a portfolio for me",
  "Compare SPY VTI QQQ",
  "What is the yield curve doing?",
  "How is my portfolio doing?",
  "Rebalance my portfolio",
  "Buy 5 shares of BND",
  "I am based in Nigeria, optimize my tax strategy for least legal tax",
  "Simulate $10M to $100M wealth plan over 10 years with $500k withdrawals",
];

const connectionText: Record<Connection, string> = {
  connecting: "Connecting",
  live: "Live connection",
  fallback: "Standard requests (live connection unavailable)",
  closed: "Connection closed. Messages will use standard requests.",
};

export default function AdvisorPage() {
  const { clientId } = useAuth();
  const { items, connection, waiting, stage, proposals, send, approve, reject, ready } = useAdvisor();
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [items.length, waiting]);

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (!draft.trim() || waiting) return;
    send(draft);
    setDraft("");
    inputRef.current?.focus();
  }

  const profiling = stage === "PROFILING" && !clientId;

  return (
    <>
      <PageHeader
        title="Advisor"
        lede={
          profiling
            ? "Answer in your own words. Several answers in one message is fine; the profiler picks out what it needs."
            : "Ask for an allocation, a fund comparison, a health review or a trade. Trades are drafted for you to approve."
        }
      />

      <div className="grid gap-8 xl:grid-cols-12">
        <section aria-label="Conversation" className="flex min-h-[60vh] flex-col border border-line xl:col-span-8">
          <div className="flex-1 overflow-y-auto px-5">
            {!ready ? (
              <Loading label="Opening your advisory session" />
            ) : (
              <ol className="divide-y divide-line" aria-live="polite">
                {items.map((it) => (
                  <TranscriptRow key={it.id} item={it} proposals={proposals} onApprove={approve} onReject={reject} />
                ))}
                {waiting ? (
                  <li className="grid gap-x-5 py-4 sm:grid-cols-[8.5rem_1fr]">
                    <span className="text-[13px] font-semibold text-ink">Advisor</span>
                    <span className="text-sm text-muted">Working on it…</span>
                  </li>
                ) : null}
              </ol>
            )}
            <div ref={endRef} />
          </div>

          <form onSubmit={submit} className="border-t border-ink bg-surface p-4">
            <label htmlFor="composer" className="sr-only">
              Message
            </label>
            <Textarea
              id="composer"
              ref={inputRef}
              rows={3}
              value={draft}
              placeholder={profiling ? "For example: I'm 34, employed full time, with one child." : "Type a request, or approve / cancel a pending trade."}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              disabled={!ready}
              maxLength={4000}
              className="resize-none"
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-[12.5px] text-muted">Enter to send, Shift and Enter for a new line.</p>
              <Button type="submit" disabled={!ready || !draft.trim() || waiting}>
                Send
              </Button>
            </div>
          </form>
        </section>

        <div className="space-y-8 xl:col-span-4">
          <Panel title="Session">
            <ol className="space-y-2 text-sm">
              {stages.map(([key, label]) => {
                const on = stage === key;
                return (
                  <li key={key} className={`flex items-center gap-3 ${on ? "font-semibold text-ink" : "text-muted"}`}>
                    <span aria-hidden className={`inline-block h-2.5 w-2.5 border ${on ? "border-primary bg-primary" : "border-line"}`} />
                    {label}
                    {on ? <span className="sr-only">(current)</span> : null}
                  </li>
                );
              })}
            </ol>
            <p className="mt-5 border-t border-line pt-3 text-[13px] text-muted">{connectionText[connection]}</p>
          </Panel>

          {profiling ? (
            <Panel title="What the profiler asks">
              <ol className="divide-y divide-line text-sm">
                {profilingTopics.map((t, i) => (
                  <li key={t} className="grid grid-cols-[1.5rem_1fr] py-2">
                    <span className="figures text-muted">{i + 1}</span>
                    <span className="text-ink">{t}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-4 text-[13px] text-muted">
                Useful phrasing: &ldquo;My risk tolerance is 6 out of 10&rdquo;, &ldquo;My horizon is 12 years&rdquo;, &ldquo;Income is 90k, savings
                40k&rdquo;.
              </p>
            </Panel>
          ) : (
            <Panel title="Try asking">
              <ul className="space-y-1">
                {prompts.map((p) => (
                  <li key={p}>
                    <button
                      type="button"
                      onClick={() => send(p)}
                      disabled={waiting || !ready}
                      className="w-full border border-transparent px-2 py-1.5 text-left text-sm text-primary hover:border-line hover:bg-surface disabled:opacity-50"
                    >
                      {p}
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </>
  );
}
