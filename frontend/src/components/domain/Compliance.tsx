import type { ComplianceDetails, Violation } from "@/lib/types";
import { Tag } from "../ui/Feedback";

/** List of rule outcomes. Each row: rule id, name, outcome in words, detail. */
export function RuleResults({ details }: { details: ComplianceDetails }) {
  const rows = details.rule_results ?? [];
  if (rows.length === 0) return <p className="text-sm text-muted">No rules were evaluated.</p>;
  return (
    <ul className="divide-y divide-line border-y border-line">
      {rows.map((r) => (
        <li key={r.rule_id} className="grid grid-cols-[5.5rem_1fr_auto] gap-x-3 gap-y-0.5 py-2.5 text-sm">
          <span className="figures text-muted">{r.rule_id}</span>
          <span className="font-medium text-ink">{r.rule_name}</span>
          <span>
            {r.passed ? (
              <Tag tone="success">Pass</Tag>
            ) : r.severity === "BLOCK" ? (
              <Tag tone="danger">Blocked</Tag>
            ) : (
              <Tag tone="warning">Warning</Tag>
            )}
          </span>
          <span className="col-start-2 col-end-4 text-[13px] text-muted">{r.details}</span>
        </li>
      ))}
    </ul>
  );
}

export function Violations({ violations }: { violations: Violation[] }) {
  if (!violations?.length) return null;
  return (
    <ul className="divide-y divide-danger/20 border-y border-danger/25">
      {violations.map((v, i) => (
        <li key={`${v.rule_id}-${i}`} className="grid grid-cols-[5.5rem_1fr] gap-x-3 py-2.5 text-sm">
          <span className="figures text-danger">{v.rule_id}</span>
          <span>
            <span className="font-medium text-ink">{v.rule_name}</span>
            <span className="mt-0.5 block text-ink">{v.description}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** One-line verdict followed by the rule list (collapsible). */
export function ComplianceSummary({ passed, details, violations }: { passed?: boolean; details?: ComplianceDetails; violations?: Violation[] }) {
  const warn = details?.warnings ?? [];
  const failing = violations ?? details?.violations?.filter((v) => v.severity === "BLOCK") ?? [];
  return (
    <div className="space-y-3">
      <p className="flex flex-wrap items-center gap-3 text-sm">
        {passed ? <Tag tone="success">Cleared</Tag> : <Tag tone="danger">Blocked</Tag>}
        <span className="text-ink">
          {passed
            ? `${details?.rule_results?.length ?? 0} rules checked${warn.length ? `, ${warn.length} warning${warn.length > 1 ? "s" : ""}` : ", none failed"}.`
            : `${failing.length} rule${failing.length === 1 ? "" : "s"} stopped this.`}
        </span>
      </p>
      {!passed ? <Violations violations={failing} /> : null}
      {warn.length ? (
        <ul className="space-y-1 text-[13px] text-warning">
          {warn.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      {details?.rule_results?.length ? (
        <details className="group">
          <summary className="cursor-pointer text-[13px] text-primary underline decoration-primary/30 underline-offset-4 select-none">
            Show every rule
          </summary>
          <div className="mt-3">
            <RuleResults details={details} />
          </div>
        </details>
      ) : null}
    </div>
  );
}
