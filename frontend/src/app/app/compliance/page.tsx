"use client";

import { ErrorNotice, Loading, Tag } from "@/components/ui/Feedback";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { ComplianceRule } from "@/lib/types";
import { useRequest } from "@/lib/useRequest";

const categoryOrder = ["SUITABILITY", "CONCENTRATION", "REGULATORY", "AML"];
const categoryNotes: Record<string, string> = {
  SUITABILITY: "Does the advice fit this client?",
  CONCENTRATION: "Is the portfolio spread widely enough?",
  REGULATORY: "Is the wording fair and is every order authorised?",
  AML: "Is the activity consistent with legitimate use?",
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
          <dl className="mt-2 grid max-w-[70ch] grid-cols-[minmax(10rem,auto)_1fr] gap-x-4 gap-y-0.5 text-[0.9375rem]">
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
  const rules = data?.rules ?? [];
  const cats = [...categoryOrder.filter((c) => rules.some((r) => r.category === c)), ...Array.from(new Set(rules.map((r) => r.category))).filter((c) => !categoryOrder.includes(c))];

  return (
    <>
      <PageHeader
        title="Compliance rules"
        lede="The active rule catalogue, read live from the backend. A rule that blocks stops the recommendation or order. A rule that warns lets it through with a note."
      />
      {loading && !data ? <Loading label="Loading rules" /> : null}
      <ErrorNotice error={error} onRetry={reload} />
      <div className="space-y-8">
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
