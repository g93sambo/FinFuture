"use client";

import { Fragment, useMemo, useState } from "react";
import { RequireProfile } from "@/components/shell/RequireProfile";
import { Button } from "@/components/ui/Button";
import { ErrorNotice, Loading, Notice, Tag, type Tone } from "@/components/ui/Feedback";
import { Select } from "@/components/ui/Field";
import { Ledger, PageHeader, Panel } from "@/components/ui/Layout";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { dateTime, humanize, shortHash } from "@/lib/format";
import type { AnchorResult, MerkleProofResponse } from "@/lib/types";
import { useAction, useRequest } from "@/lib/useRequest";

const statusTone: Record<string, Tone> = { PASS: "success", WARN: "warning", FAIL: "danger", BLOCK: "danger" };

const UUID = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;

/** A user ID as the actor is the signed-in client; agents and forms get readable names. */
function actorLabel(a: string) {
  const name = a.replace(/^(AGENT|SYSTEM|USER):/, "");
  if (UUID.test(name)) return "You";
  return humanize(name.split(":")[0]);
}

function EtherscanLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="break-all text-primary underline underline-offset-4">
      {children}
    </a>
  );
}

function Audit({ clientId }: { clientId: string }) {
  const { data, error, loading, reload } = useRequest(`audit:${clientId}`, () => api.audit(clientId, 1000));
  const network = useRequest("sepolia:health", () => api.sepoliaNetwork());
  const [filter, setFilter] = useState("ALL");
  const [open, setOpen] = useState<string | null>(null);
  const [verify, setVerify] = useState<{ valid: boolean; first_invalid_entry: string | null; at: string } | null>(null);
  const [anchor, setAnchor] = useState<AnchorResult | null>(null);
  const [proofs, setProofs] = useState<Record<string, MerkleProofResponse>>({});
  const verifyAction = useAction(async () => {
    const r = await api.verifyAudit(clientId);
    setVerify({ ...r, at: new Date().toISOString() });
  });
  const anchorAction = useAction(async () => {
    const res = await api.anchorAudit(clientId);
    setAnchor(res);
    if (res.tx_hash) reload();
  });
  const proofAction = useAction(async (entryId: string) => {
    const res = await api.merkleProof(clientId, entryId);
    setProofs((prev) => ({ ...prev, [entryId]: res }));
  });

  const entries = useMemo(() => data?.entries ?? [], [data]);
  const types = useMemo(() => Array.from(new Set(entries.map((e) => e.event_type))).sort(), [entries]);
  const shown = filter === "ALL" ? entries : entries.filter((e) => e.event_type === filter);
  const pastAnchors = useMemo(() => entries.filter((e) => e.event_type === "AUDIT_ANCHORED"), [entries]);
  const net = network.data;
  const anchoringEnabled = Boolean(net?.anchoring_enabled);

  return (
    <div className="space-y-8">
      <div className="grid gap-8 xl:grid-cols-2">
        <Panel title="Verify the chain" aside={<Tag tone="neutral">SHA-256 + HMAC-SHA256</Tag>}>
          <p className="text-sm text-muted">
            Recomputes every entry&rsquo;s SHA-256 hash from its contents and the previous entry&rsquo;s hash, then checks its HMAC signature. Any edit,
            deletion or reordering breaks the chain at that entry.
          </p>
          <div className="mt-4">
            <Button variant="secondary" onClick={() => verifyAction.run()} pending={verifyAction.pending}>
              Verify {entries.length} {entries.length === 1 ? "entry" : "entries"}
            </Button>
          </div>
          <div className="mt-4 space-y-3">
            <ErrorNotice error={verifyAction.error} />
            {verify ? (
              verify.valid ? (
                <Notice tone="success" title="Chain intact">
                  Every hash and signature matched. Checked {dateTime(verify.at)}.
                </Notice>
              ) : (
                <Notice tone="danger" title="Chain broken">
                  The first entry that fails is <span className="figures">{verify.first_invalid_entry}</span>. Entries from that point cannot be
                  trusted.
                </Notice>
              )
            ) : null}
          </div>
        </Panel>

        <Panel
          title="Anchor on Ethereum Sepolia"
          aside={
            network.loading && !net ? (
              <Tag tone="neutral">Checking…</Tag>
            ) : anchoringEnabled ? (
              <Tag tone="success">Enabled</Tag>
            ) : (
              <Tag tone="warning">Not configured</Tag>
            )
          }
        >
          <p className="text-sm text-muted">
            Combines every entry hash into one SHA-256 Merkle root and writes it into a Sepolia testnet transaction. Anyone can then open the
            transaction on Etherscan and check that its input data equals the root, which proves the trail existed in this form at that time.
          </p>
          {net?.connected ? (
            <p className="figures mt-2 text-[13px] text-muted">
              Sepolia block #{net.block_number?.toLocaleString()} · gas {net.gas_price_gwei} gwei
              {net.wallet_address && net.wallet_url ? (
                <>
                  {" · wallet "}
                  <EtherscanLink href={net.wallet_url}>{shortHash(net.wallet_address)}</EtherscanLink>
                  {` (${net.wallet_balance_eth ?? 0} ETH)`}
                </>
              ) : null}
            </p>
          ) : null}
          <div className="mt-4">
            <Button variant="secondary" onClick={() => anchorAction.run()} pending={anchorAction.pending} disabled={!anchoringEnabled}>
              Anchor {entries.length} {entries.length === 1 ? "entry" : "entries"}
            </Button>
          </div>
          <div className="mt-4 space-y-4">
            {!anchoringEnabled && net ? (
              <Notice tone="neutral" title="On-chain anchoring is off on this server">
                It needs <code>SEPOLIA_RPC_URL</code>, <code>SEPOLIA_PRIVATE_KEY</code> (a testnet-only wallet) and a little free Sepolia ETH in
                that wallet. Chain verification and Merkle proofs on this page work without it.
              </Notice>
            ) : null}
            <ErrorNotice error={anchorAction.error} />
            {anchor && !anchor.tx_hash ? (
              <Notice tone="warning" title="Nothing was anchored">
                {anchor.status === "failed"
                  ? `The transaction could not be sent (${anchor.error ?? "unknown error"}). Check that the wallet has Sepolia ETH.`
                  : "No wallet is configured on the server, so no transaction was sent."}
              </Notice>
            ) : null}
            {anchor?.tx_hash && anchor.explorer_url ? (
              <Ledger
                rows={[
                  {
                    label: "Status",
                    value: <Tag tone={anchor.status === "confirmed" ? "success" : "warning"}>{humanize(anchor.status)}</Tag>,
                  },
                  { label: "Entries anchored", value: anchor.entries_count },
                  { label: "Merkle root", value: <span className="text-[13px] break-all">0x{anchor.merkle_root}</span> },
                  { label: "Transaction", value: <EtherscanLink href={anchor.explorer_url}>{anchor.tx_hash}</EtherscanLink> },
                  { label: "Block", value: anchor.block_number ?? "Pending" },
                ]}
              />
            ) : null}
            {pastAnchors.length > 0 ? (
              <div>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">Previous anchors</p>
                <ul className="space-y-1 text-[13px]">
                  {pastAnchors.map((e) => (
                    <li key={e.entry_id} className="flex flex-wrap gap-x-2">
                      <span className="text-muted">{dateTime(e.timestamp)}</span>
                      <span>{String(e.details.entries_count ?? "")} entries</span>
                      {typeof e.details.explorer_url === "string" ? (
                        <EtherscanLink href={e.details.explorer_url}>{shortHash(String(e.details.tx_hash ?? ""))}</EtherscanLink>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </Panel>
      </div>

      <Panel
        title="Entries"
        flush
        aside={
          types.length ? (
            <div className="w-56">
              <label htmlFor="audit-filter" className="sr-only">
                Filter by event
              </label>
              <Select id="audit-filter" value={filter} onChange={(e) => setFilter(e.target.value)} className="h-8 text-sm">
                <option value="ALL">All events ({entries.length})</option>
                {types.map((t) => (
                  <option key={t} value={t}>
                    {humanize(t)}
                  </option>
                ))}
              </Select>
            </div>
          ) : null
        }
      >
        {loading && !data ? (
          <div className="px-5">
            <Loading label="Loading audit entries" />
          </div>
        ) : error ? (
          <div className="p-5">
            <ErrorNotice error={error} onRetry={reload} />
          </div>
        ) : shown.length === 0 ? (
          <p className="p-5 text-sm text-muted">No entries.</p>
        ) : (
          <Table caption="Audit entries, newest first">
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Event</Th>
                <Th>Recorded by</Th>
                <Th>Result</Th>
                <Th>Hash</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {shown.map((e) => {
                const proof = proofs[e.entry_id];
                return (
                  <Fragment key={e.entry_id}>
                    <Tr className={verify && !verify.valid && verify.first_invalid_entry === e.entry_id ? "bg-danger-soft" : ""}>
                      <Td className="whitespace-nowrap text-muted">{dateTime(e.timestamp)}</Td>
                      <Td className="font-medium">{humanize(e.event_type)}</Td>
                      <Td>{actorLabel(e.actor)}</Td>
                      <Td>{e.status ? <Tag tone={statusTone[e.status] ?? "neutral"}>{humanize(e.status)}</Tag> : "–"}</Td>
                      <Td className="figures text-[13px] text-muted">{shortHash(e.entry_hash)}</Td>
                      <Td className="text-right">
                        <button
                          onClick={() => setOpen(open === e.entry_id ? null : e.entry_id)}
                          aria-expanded={open === e.entry_id}
                          className="text-sm text-primary underline decoration-primary/30 underline-offset-4"
                        >
                          {open === e.entry_id ? "Hide" : "Inspect"}
                        </button>
                      </Td>
                    </Tr>
                    {open === e.entry_id ? (
                      <tr>
                        <td colSpan={6} className="border-b border-line bg-surface px-5 py-4">
                          <div className="flex flex-wrap items-start justify-between gap-4">
                            <dl className="figures grid gap-x-6 gap-y-1 text-[12.5px] md:grid-cols-[8rem_1fr]">
                              <dt className="font-sans text-muted">Previous hash</dt>
                              <dd className="break-all">{e.prev_hash}</dd>
                              <dt className="font-sans text-muted">Entry hash</dt>
                              <dd className="break-all">{e.entry_hash}</dd>
                              <dt className="font-sans text-muted">Signature</dt>
                              <dd className="break-all">{e.signature}</dd>
                            </dl>
                            <Button
                              size="sm"
                              variant="secondary"
                              pending={proofAction.pending}
                              onClick={() => void proofAction.run(e.entry_id)}
                            >
                              {proof ? "Recompute Merkle proof" : "Verify Merkle inclusion proof"}
                            </Button>
                          </div>

                          {proof ? (
                            <div className="mt-4 rounded-xl border border-line bg-background p-4">
                              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2.5">
                                <p className="text-xs font-semibold tracking-wider text-ink uppercase">
                                  Merkle inclusion proof
                                </p>
                                <Tag tone={proof.verified ? "success" : "danger"}>
                                  {proof.verified ? `VERIFIED · Leaf #${proof.leaf_index} of ${proof.total_leaves}` : "PROOF MISMATCH"}
                                </Tag>
                              </div>
                              <dl className="figures mt-3 grid gap-x-6 gap-y-1 text-[12px] md:grid-cols-[9.5rem_1fr]">
                                <dt className="font-sans text-muted">Algorithm</dt>
                                <dd>Binary Merkle tree, SHA-256 (odd nodes duplicated)</dd>
                                <dt className="font-sans text-muted">Leaf hash</dt>
                                <dd className="break-all">{proof.leaf_hash}</dd>
                                <dt className="font-sans text-muted">Root</dt>
                                <dd className="break-all font-semibold text-accent">{proof.merkle_root}</dd>
                              </dl>
                              {proof.proof.length > 0 ? (
                                <div className="mt-3">
                                  <p className="text-xs font-medium text-muted">
                                    Sibling path ({proof.proof.length} steps from leaf to root):
                                  </p>
                                  <ol className="figures mt-1.5 space-y-1 text-[11.5px] text-ink">
                                    {proof.proof.map((s, idx) => (
                                      <li key={`${s.hash}-${idx}`} className="flex flex-wrap items-center gap-2">
                                        <span className="text-muted">Step {idx + 1} ({s.position}):</span>
                                        <span className="break-all">{s.hash}</span>
                                      </li>
                                    ))}
                                  </ol>
                                </div>
                              ) : (
                                <p className="mt-2 text-xs text-muted">Single-leaf tree: the leaf hash is the root.</p>
                              )}
                            </div>
                          ) : null}

                          {e.details && Object.keys(e.details).length > 0 ? (
                            <div className="mt-3 rounded-xl border border-line bg-background p-3.5">
                              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Event Summary</p>
                              <dl className="grid gap-x-6 gap-y-1.5 text-[12.5px] sm:grid-cols-[11rem_1fr]">
                                {Object.entries(e.details)
                                  .filter(([k]) => !k.endsWith("_id") && k !== "client_id")
                                  .map(([k, v]) => (
                                    <Fragment key={k}>
                                      <dt className="text-muted">{humanize(k)}</dt>
                                      <dd className="figures break-words text-ink">
                                        {typeof v === "object" && v !== null
                                          ? Array.isArray(v)
                                            ? v.length > 0
                                              ? `${v.length} item(s)`
                                              : "None"
                                            : Object.entries(v)
                                                .map(([sk, sv]) => `${humanize(sk)}: ${String(sv)}`)
                                                .join(" · ")
                                          : String(v)}
                                      </dd>
                                    </Fragment>
                                  ))}
                              </dl>
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </Table>
        )}
      </Panel>
    </div>
  );
}

export default function AuditPage() {
  return (
    <>
      <PageHeader title="Audit trail" lede="Every profile change, recommendation, compliance check and order, in a signed, append-only chain." />
      <RequireProfile>{(id) => <Audit clientId={id} />}</RequireProfile>
    </>
  );
}
