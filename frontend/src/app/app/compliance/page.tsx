"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { ErrorNotice, Loading, Notice, Tag, type Tone } from "@/components/ui/Feedback";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { dateTime, humanize } from "@/lib/format";
import type { CircuitBreakerStatus, ComplianceRule } from "@/lib/types";
import { useAction, useRequest } from "@/lib/useRequest";

const categoryOrder = ["SUITABILITY", "CONCENTRATION", "REGULATORY", "AML"];
const categoryNotes: Record<string, string> = {
  SUITABILITY: "Does the advice fit this client?",
  CONCENTRATION: "Is the portfolio spread widely enough?",
  REGULATORY: "Is the wording fair and is every order authorised?",
  AML: "Is the activity consistent with legitimate use?",
};

const tierTone: Record<string, Tone> = {
  GREEN: "success",
  YELLOW: "warning",
  RED: "danger",
  DISABLED: "neutral",
};

function formatParam(v: unknown): string {
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-US") : String(v);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

function RuleRow({ r }: { r: ComplianceRule }) {
  const params = Object.entries(r.parameters ?? {});
  return (
    <li className="grid gap-x-6 gap-y-2 py-4 md:grid-cols-[6.5rem_1fr_6rem]">
      <span className="figures text-sm text-primary">{r.id}</span>
      <div>
        <p className="font-medium text-ink">{r.name}</p>
        {r.description ? <p className="mt-0.5 max-w-[70ch] text-sm text-ink">{r.description}</p> : null}
        {params.length ? (
          <dl className="mt-2 grid max-w-[70ch] grid-cols-[minmax(10rem,auto)_1fr] gap-x-4 gap-y-0.5 text-[13px]">
            {params.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted">{humanize(k)}</dt>
                <dd className="figures text-ink">{formatParam(v)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
      <span className="md:text-right">
        {r.severity === "BLOCK" ? <Tag tone="danger">Blocks</Tag> : <Tag tone="warning">Warns</Tag>}
      </span>
    </li>
  );
}

export default function CompliancePage() {
  const { data, error, loading, reload } = useRequest("rules", () => api.rules());
  const tiersReq = useRequest("permission-tiers", () => api.permissionTiers());
  const [cbOverride, setCbOverride] = useState<CircuitBreakerStatus | null>(null);

  const simulateCb = useAction(async () => {
    const res = await api.simulateCircuitBreaker();
    setCbOverride(res.circuit_breaker);
  });

  const resetCb = useAction(async () => {
    const res = await api.resetCircuitBreaker();
    setCbOverride(res.circuit_breaker);
  });

  const rules = data?.rules ?? [];
  const cats = [
    ...categoryOrder.filter((c) => rules.some((r) => r.category === c)),
    ...Array.from(new Set(rules.map((r) => r.category))).filter((c) => !categoryOrder.includes(c)),
  ];

  const tiers = tiersReq.data?.permission_tiers ?? [];
  const knownRisks = tiersReq.data?.known_risks ?? [];
  const pillars = tiersReq.data?.security_pillars ?? [];
  const cb = cbOverride ?? tiersReq.data?.circuit_breaker;

  return (
    <>
      <PageHeader
        title="Compliance & security self-assessment"
        lede="Runtime 5-tier permission architecture (Read-Only · Advise · Propose · Execute with Approval under Limits · Autonomous Hard-Disabled), anomaly circuit breaker, 5-pillar defense architecture, known-risk mitigations, and the active 12-rule regulatory catalogue."
      />
      {loading && !data ? <Loading label="Loading compliance architecture" /> : null}
      <ErrorNotice error={error} onRetry={reload} />

      <div className="space-y-8">
        {tiers.length > 0 ? (
          <Panel
            title="Five-tier permission model (code-enforced execution boundaries)"
            aside={<span>Non-discretionary · $100k single cap · $250k daily cap · 86-symbol whitelist · Autonomous disabled</span>}
          >
            <div className="grid gap-6 lg:grid-cols-3">
              {tiers.map((t) => (
                <div key={t.tier_id ?? t.label} className="rounded-xl border border-line bg-surface/70 p-4 flex flex-col justify-between space-y-4">
                  <div className="space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <Tag tone={tierTone[t.tier] ?? "neutral"}>{t.tier}</Tag>
                      <span className="text-xs font-medium text-muted">{t.label}</span>
                    </div>
                    <p className="text-xs text-ink font-medium">{t.execution_policy}</p>
                    <div>
                      <p className="text-[11.5px] uppercase tracking-wider text-muted mb-1">Permitted operations</p>
                      <ul className="list-disc list-inside space-y-1 text-xs text-ink marker:text-muted">
                        {t.operations.map((op) => (
                          <li key={op}>{op}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  <div className="border-t border-line pt-2.5">
                    <p className="text-[11.5px] uppercase tracking-wider text-muted mb-1">Code-enforced safeguards</p>
                    <ul className="list-disc list-inside space-y-0.5 text-[12px] text-muted">
                      {t.safeguards.map((sg) => (
                        <li key={sg}>{sg}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        ) : null}

        <div className="grid gap-8 xl:grid-cols-12">
          <Panel
            title="Anomaly circuit breaker (live stress-test)"
            className="xl:col-span-6"
            aside={
              cb ? (
                <Tag tone={cb.is_locked ? "danger" : cb.recent_incidents_60s > 0 ? "warning" : "success"}>
                  {cb.state.replace(/_/g, " ")}
                </Tag>
              ) : null
            }
          >
            <p className="text-sm text-muted">
              Automatically trips into a 15-minute security lock if a session triggers 3 or more consecutive compliance blocks or
              adversarial override attempts within 60 seconds.
            </p>
            {cb ? (
              <div className="mt-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface/70 px-4 py-3 text-sm">
                  <span>
                    Blocked anomalies (last 60s):{" "}
                    <strong className="figures text-ink">
                      {cb.recent_incidents_60s} / {cb.trip_threshold}
                    </strong>
                  </span>
                  {cb.is_locked && cb.locked_until ? (
                    <span className="text-xs text-danger font-medium">Locked until {dateTime(cb.locked_until)}</span>
                  ) : (
                    <span className="text-xs text-muted">Execution channel open</span>
                  )}
                </div>
                {cb.is_locked ? (
                  <Notice tone="danger" title="Circuit breaker tripped (OPEN_LOCKED)">
                    High-risk trade execution is temporarily frozen due to repeated blocked compliance/injection attempts. Click Reset below to
                    clear the lock.
                  </Notice>
                ) : null}
                <div className="flex flex-wrap gap-3 pt-1">
                  <Button size="sm" variant="secondary" onClick={() => simulateCb.run()} pending={simulateCb.pending}>
                    Simulate blocked anomaly (+1)
                  </Button>
                  <Button size="sm" variant="quiet" onClick={() => resetCb.run()} pending={resetCb.pending}>
                    Reset circuit breaker
                  </Button>
                </div>
              </div>
            ) : null}
          </Panel>

          <Panel title="Five mandatory security pillars" className="xl:col-span-6">
            <ul className="divide-y divide-line -my-2">
              {pillars.map((p) => (
                <li key={p.id} className="py-2.5 flex items-start justify-between gap-4 text-sm">
                  <div>
                    <p className="font-medium text-ink">{p.name}</p>
                    <p className="text-xs text-muted mt-0.5">{p.detail}</p>
                  </div>
                  <Tag tone={p.status === "LOCKED" ? "danger" : "success"}>{p.status}</Tag>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        {knownRisks.length > 0 ? (
          <Panel title="Security self-assessment: known-risk register & mitigations" flush>
            <Table caption="Known risks and technical mitigations">
              <thead>
                <tr>
                  <Th>ID</Th>
                  <Th>Risk category</Th>
                  <Th>Known risk description</Th>
                  <Th>Architectural mitigation</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {knownRisks.map((kr) => (
                  <Tr key={kr.risk_id}>
                    <Td className="figures text-primary font-medium whitespace-nowrap">{kr.risk_id}</Td>
                    <Td className="font-medium whitespace-nowrap">{kr.category}</Td>
                    <Td className="text-sm text-muted max-w-[34ch]">{kr.description}</Td>
                    <Td className="text-sm text-ink max-w-[46ch]">{kr.mitigation}</Td>
                    <Td>
                      <Tag tone="success">{kr.status}</Tag>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </Panel>
        ) : null}

        {cats.map((c) => (
          <Panel key={c} title={humanize(c)} aside={<span>{categoryNotes[c] ?? ""}</span>}>
            <ul className="-my-4 divide-y divide-line">
              {rules
                .filter((r) => r.category === c)
                .map((r) => (
                  <RuleRow key={r.id} r={r} />
                ))}
            </ul>
          </Panel>
        ))}
      </div>
    </>
  );
}

