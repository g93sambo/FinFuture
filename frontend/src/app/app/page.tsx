"use client";

import Link from "next/link";
import { BulletBars } from "@/components/charts/BulletBars";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { ButtonLink } from "@/components/ui/Button";
import { Empty, ErrorNotice, Skeleton, TableSkeleton, Tag } from "@/components/ui/Feedback";
import { Ledger, PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime, fixed, humanize, money, pct, qty } from "@/lib/format";
import { useRequest } from "@/lib/useRequest";

function OverviewSkeleton() {
  return (
    <div className="space-y-8 animate-fadeIn" aria-busy="true" aria-label="Loading portfolio">
      <div className="mb-10 grid grid-cols-2 border-y border-ink md:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className={`px-0 py-4 md:px-5 ${i > 1 ? "md:border-l md:border-line" : ""}`}>
            <Skeleton height="14px" width="80px" />
            <div className="mt-2">
              <Skeleton height="26px" width="120px" />
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-8 xl:grid-cols-12">
        <div className="space-y-8 xl:col-span-8">
          <Panel title="Holdings" flush>
            <TableSkeleton rows={4} columns={5} />
          </Panel>
        </div>
        <div className="space-y-8 xl:col-span-4">
          <Panel title="Your profile">
            <div className="space-y-4 py-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex justify-between items-center">
                  <Skeleton height="14px" width="100px" />
                  <Skeleton height="14px" width="80px" />
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Recent orders" flush>
            <div className="p-4 space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex justify-between items-center py-1">
                  <Skeleton height="14px" width="110px" />
                  <Skeleton height="14px" width="60px" />
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Overview({ clientId }: { clientId: string }) {
  const { data, error, loading, reload } = useRequest(`overview:${clientId}`, () =>
    Promise.all([api.portfolio(clientId), api.profile(clientId), api.trades(clientId, 6)]),
  );

  if (loading && !data) return <OverviewSkeleton />;
  if (error) return <ErrorNotice error={error} onRetry={reload} />;
  if (!data) return null;
  const [pf, profile, { trades }] = data;
  const positions = [...pf.positions].sort((a, b) => b.market_value - a.market_value);
  const cashWeight = pf.total_value > 0 ? pf.cash / pf.total_value : 1;

  return (
    <>
      <dl className="mb-10 grid grid-cols-2 border-y border-ink md:grid-cols-4">
        {[
          ["Account value", money(pf.total_value)],
          ["Invested", money(pf.invested_value)],
          ["Cash", money(pf.cash)],
          ["Holdings", String(pf.positions.length)],
        ].map(([k, v], i) => (
          <div key={k} className={`px-0 py-4 md:px-5 ${i % 2 ? "pl-5" : ""} ${i > 0 ? "md:border-l md:border-line" : "md:pl-0"} ${i >= 2 ? "border-t border-line md:border-t-0" : ""}`}>
            <dt className="text-sm text-muted">{k}</dt>
            <dd className="figures mt-1 text-[22px] text-ink">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="grid gap-8 xl:grid-cols-12">
        <div className="space-y-8 xl:col-span-8">
          <Panel
            title="Holdings"
            aside={<span>{pf.source === "alpaca_paper" ? "Alpaca paper account" : "Ledger of filled orders"}</span>}
            flush
          >
            {positions.length === 0 ? (
              <div className="p-5">
                <Empty
                  title="Nothing invested yet"
                  action={
                    <div className="flex flex-wrap gap-3">
                      <ButtonLink href="/app/allocation">See a recommended allocation</ButtonLink>
                      <ButtonLink href="/app/trade" variant="secondary">
                        Place a trade
                      </ButtonLink>
                    </div>
                  }
                >
                  Your {money(pf.cash)} is held as cash. Start with an allocation built from your profile, or draft an order
                  yourself.
                </Empty>
              </div>
            ) : (
              <Table caption="Holdings">
                <thead>
                  <tr>
                    <Th>Symbol</Th>
                    <Th numeric>Quantity</Th>
                    <Th numeric>Price</Th>
                    <Th numeric>Value</Th>
                    <Th numeric>Weight</Th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <Tr key={p.symbol}>
                      <Td className="font-semibold">{p.symbol}</Td>
                      <Td numeric>{qty(p.qty)}</Td>
                      <Td numeric>{money(p.price)}</Td>
                      <Td numeric>{money(p.market_value)}</Td>
                      <Td numeric>{pct(p.weight)}</Td>
                    </Tr>
                  ))}
                  <Tr>
                    <Td className="text-muted">Cash</Td>
                    <Td numeric />
                    <Td numeric />
                    <Td numeric>{money(pf.cash)}</Td>
                    <Td numeric>{pct(cashWeight)}</Td>
                  </Tr>
                </tbody>
              </Table>
            )}
          </Panel>

          {positions.length > 0 ? (
            <Panel title="Where the money sits" aside={<Link href="/app/health" className="text-primary underline underline-offset-4">Check drift</Link>}>
              <BulletBars
                title="Portfolio weight by holding, including cash"
                max={1}
                rows={[
                  ...positions.map((p) => ({ label: p.symbol, value: p.weight })),
                  { label: "Cash", value: cashWeight },
                ]}
              />
            </Panel>
          ) : null}
        </div>

        <div className="space-y-8 xl:col-span-4">
          <Panel title="Your profile" aside={<Link href="/app/profile" className="text-primary underline underline-offset-4">Details</Link>}>
            <Ledger
              rows={[
                { label: "Suitability tier", value: profile.suitability_category ?? "–" },
                { label: "Risk tolerance", value: `${fixed(profile.risk_tolerance_score, 1)} / 10` },
                { label: "Horizon", value: profile.investment_horizon_years ? `${profile.investment_horizon_years} years` : "–" },
                { label: "Goal", value: humanize(profile.primary_goal) },
                {
                  label: "KYC",
                  value: profile.kyc_verified ? <Tag tone="success">Verified</Tag> : <Tag tone="danger">Not verified</Tag>,
                },
              ]}
            />
          </Panel>

          <Panel title="Recent orders" aside={<Link href="/app/trade" className="text-primary underline underline-offset-4">All orders</Link>} flush>
            {trades.length === 0 ? (
              <p className="p-5 text-sm text-muted">No orders yet.</p>
            ) : (
              <ul className="divide-y divide-line">
                {trades.map((t) => (
                  <li key={t.trade_id} className="flex items-baseline justify-between gap-4 px-5 py-3 text-sm">
                    <span>
                      <span className="font-medium text-ink">
                        {t.side === "BUY" ? "Buy" : "Sell"} {qty(t.qty)} {t.symbol}
                      </span>
                      <span className="block text-[13px] text-muted">{dateTime(t.created_at)}</span>
                    </span>
                    <span className="figures text-right text-ink">
                      {money(t.filled_price)}
                      <span className="block text-[13px] text-muted">{humanize(t.status)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Next steps">
            <ul className="space-y-3 text-sm">
              {[
                ["/app/health", "Run a health review", "Drift, concentration and a 60/40 comparison."],
                ["/app/allocation", "Get an allocation", "Optimised for your profile, with reasons."],
                ["/app/compare", "Compare funds", "Six-factor scores for any tickers you choose."],
                ["/app/audit", "Verify your audit trail", "Recompute every hash and signature."],
              ].map(([href, label, note]) => (
                <li key={href}>
                  <Link href={href} className="font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary">
                    {label}
                  </Link>
                  <p className="text-[13px] text-muted">{note}</p>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}

export default function OverviewPage() {
  const { user } = useAuth();
  return (
    <>
      <PageHeader title="Overview" lede={user ? `Paper account for ${user.email}.` : undefined} />
      <RequireProfile>{(id) => <Overview clientId={id} />}</RequireProfile>
    </>
  );
}
