"use client";

import { Fragment, useState } from "react";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button } from "@/components/ui/Button";
import { ErrorNotice, Tag } from "@/components/ui/Feedback";
import { Field, Input, Segmented } from "@/components/ui/Field";
import { PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { fixed, pct } from "@/lib/format";
import type { ComparedProduct, CompareResponse } from "@/lib/types";
import { useAction } from "@/lib/useRequest";

type Kind = "etfs" | "bonds";

const presets: Record<Kind, string[][]> = {
  etfs: [
    ["SPY", "VTI", "QQQ"],
    ["VTI", "VXUS", "SPY"],
    ["SPY", "VTI", "GLD", "VNQ"],
  ],
  bonds: [
    ["BND", "AGG", "SHY"],
    ["IEF", "TLT", "TIP"],
    ["LQD", "VCIT", "HYG"],
  ],
};

const factors: [keyof ComparedProduct["factor_breakdown"], string, string][] = [
  ["expense_ratio_score", "Cost", "30%"],
  ["tracking_error_score", "Tracking", "15%"],
  ["liquidity_score", "Liquidity", "20%"],
  ["aum_scale_score", "Size", "10%"],
  ["historical_return_score", "Return", "15%"],
  ["reputation_score", "Manager", "10%"],
];

const parseSymbols = (s: string) =>
  Array.from(new Set(s.toUpperCase().split(/[\s,;]+/).map((x) => x.trim()).filter((x) => /^[A-Z.]{1,10}$/.test(x))));

function ProductDetail({ p }: { p: ComparedProduct }) {
  const r = p.factor_breakdown.raw_metrics ?? {};
  return (
    <div className="grid gap-6 bg-surface px-5 py-4 text-sm md:grid-cols-3">
      <div>
        <p className="mb-1.5 font-medium text-ink">Strengths</p>
        {p.key_advantages.length ? (
          <ul className="list-inside list-disc space-y-1 text-ink marker:text-muted">
            {p.key_advantages.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">None stood out.</p>
        )}
      </div>
      <div>
        <p className="mb-1.5 font-medium text-ink">Risks</p>
        {p.key_risks.length ? (
          <ul className="list-inside list-disc space-y-1 text-ink marker:text-muted">
            {p.key_risks.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">None flagged.</p>
        )}
      </div>
      <dl className="figures grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
        <dt className="font-sans text-muted">Expense ratio</dt>
        <dd className="text-right">{pct(r.expense_ratio, 2)}</dd>
        <dt className="font-sans text-muted">Tracking error</dt>
        <dd className="text-right">{pct(r.tracking_error, 2)}</dd>
        <dt className="font-sans text-muted">Bid-ask spread</dt>
        <dd className="text-right">{pct(r.spread_pct, 3)}</dd>
        <dt className="font-sans text-muted">Assets</dt>
        <dd className="text-right">${fixed(r.aum_billions, 1)}bn</dd>
        <dt className="font-sans text-muted">1-year return</dt>
        <dd className="text-right">{pct(r.return_1y)}</dd>
        <dt className="font-sans text-muted">30-day yield</dt>
        <dd className="text-right">{pct(r.yield_30d, 2)}</dd>
      </dl>
    </div>
  );
}

function Results({ res }: { res: CompareResponse }) {
  const [open, setOpen] = useState<string | null>(res.ranked_products[0]?.symbol ?? null);
  const winner = res.ranked_products[0];
  return (
    <div className="space-y-8">
      {winner ? (
        <div className="border-l-2 border-primary pl-5">
          <p className="text-sm text-muted">Best fit for your profile</p>
          <p className="mt-1 text-[22px] font-semibold text-ink">
            {winner.symbol} <span className="font-normal text-muted">· {winner.name}</span>
          </p>
          <p className="figures mt-1 text-sm text-ink">Composite score {fixed(winner.composite_score)} out of 10</p>
        </div>
      ) : null}

      <Panel title="Ranking" aside={<span>Factor scores out of 10, weights in brackets</span>} flush>
        {res.ranked_products.length === 0 ? (
          <p className="p-5 text-sm text-muted">None of these funds is within your risk tier.</p>
        ) : (
          <Table caption="Ranked products">
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Fund</Th>
                <Th numeric>Risk</Th>
                <Th numeric>Score</Th>
                {factors.map(([k, label, w]) => (
                  <Th key={k} numeric>
                    {label} <span className="font-normal">({w})</span>
                  </Th>
                ))}
                <Th />
              </tr>
            </thead>
            <tbody>
              {res.ranked_products.map((p) => (
                <Fragment key={p.symbol}>
                  <Tr>
                    <Td numeric className="text-muted">
                      {p.rank}
                    </Td>
                    <Td>
                      <span className="font-semibold">{p.symbol}</span>
                      <span className="block max-w-[26ch] truncate text-[13px] text-muted" title={p.name}>
                        {p.name}
                      </span>
                    </Td>
                    <Td numeric>{p.risk_level}/5</Td>
                    <Td numeric className="font-semibold">
                      {fixed(p.composite_score)}
                    </Td>
                    {factors.map(([k]) => (
                      <Td key={k} numeric>
                        {fixed(p.factor_breakdown[k] as number, 1)}
                      </Td>
                    ))}
                    <Td className="text-right">
                      <button
                        onClick={() => setOpen(open === p.symbol ? null : p.symbol)}
                        aria-expanded={open === p.symbol}
                        className="text-sm whitespace-nowrap text-primary underline decoration-primary/30 underline-offset-4"
                      >
                        {open === p.symbol ? "Hide" : "Details"}
                      </button>
                    </Td>
                  </Tr>
                  {open === p.symbol ? (
                    <tr>
                      <td colSpan={5 + factors.length} className="border-b border-line p-0">
                        <ProductDetail p={p} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>

      {res.unsuitable_products.length ? (
        <Panel title="Set aside for your profile">
          <ul className="divide-y divide-line">
            {res.unsuitable_products.map((p) => (
              <li key={p.symbol} className="grid gap-1 py-2.5 text-sm sm:grid-cols-[7rem_1fr_auto] sm:gap-4">
                <span className="font-semibold text-ink">{p.symbol}</span>
                <span className="text-ink">{p.suitability_reason}</span>
                <Tag tone="warning">Outside tier</Tag>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <Panel title="Summary">
        <p className="max-w-[72ch] whitespace-pre-line text-[15px] text-ink">{res.rationale}</p>
        <p className="mt-4 text-[13px] text-muted">
          Method: {res.report?.methodology}. Your risk tier for products is {res.report?.client_risk_tier} of 5.
        </p>
      </Panel>
    </div>
  );
}

function Compare({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<Kind>("etfs");
  const [input, setInput] = useState("SPY VTI QQQ");
  const [res, setRes] = useState<CompareResponse | null>(null);
  const symbols = parseSymbols(input);
  const tooFew = symbols.length < 2;
  const tooMany = symbols.length > 15;
  const { run, pending, error } = useAction(async (k: Kind, syms: string[]) => {
    setRes(await api.compare(k, clientId, syms));
  });

  return (
    <div className="space-y-8">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!tooFew && !tooMany) void run(kind, symbols);
        }}
        className="grid gap-5 border border-line bg-surface p-5 lg:grid-cols-[auto_1fr_auto] lg:items-end"
      >
        <div>
          <p className="mb-1.5 text-sm font-medium text-ink">Fund type</p>
          <Segmented
            label="Fund type"
            value={kind}
            onChange={(k) => {
              setKind(k);
              setInput(presets[k][0].join(" "));
              setRes(null);
            }}
            options={[
              { value: "etfs", label: "Equity ETFs" },
              { value: "bonds", label: "Bond funds" },
            ]}
          />
        </div>
        <Field
          label="Tickers"
          hint={
            <span className="flex flex-wrap gap-x-3">
              <span>Two to fifteen, separated by spaces. Try:</span>
              {presets[kind].map((p) => (
                <button key={p.join()} type="button" className="text-primary underline underline-offset-4" onClick={() => setInput(p.join(" "))}>
                  {p.join(" ")}
                </button>
              ))}
            </span>
          }
          error={input && tooFew ? "Enter at least two tickers." : tooMany ? "Fifteen tickers at most." : null}
        >
          {(p) => <Input {...p} value={input} onChange={(e) => setInput(e.target.value)} autoCapitalize="characters" spellCheck={false} />}
        </Field>
        <Button type="submit" pending={pending} disabled={tooFew || tooMany} className="lg:mb-[26px]">
          Compare
        </Button>
      </form>

      <ErrorNotice error={error} />
      {res ? <Results res={res} /> : null}
      {!res && !pending ? (
        <p className="max-w-[70ch] text-sm text-muted">
          Each fund is scored on six factors and combined with fixed weights. Funds above your risk tier are listed separately with the reason;
          they are never ranked.{kind === "bonds" ? " Bond funds are also checked for duration against your horizon." : ""}
        </p>
      ) : null}
    </div>
  );
}

export default function ComparePage() {
  return (
    <>
      <PageHeader title="Compare funds" lede="Score funds against each other and against your profile." />
      <RequireProfile>{(id) => <Compare clientId={id} />}</RequireProfile>
    </>
  );
}
