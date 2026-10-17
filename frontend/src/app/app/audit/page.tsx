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

function actorLabel(a: string) {
  return humanize(a.replace(/^(AGENT|SYSTEM):/, ""));
}

function Audit({ clientId }: { clientId: string }) {
  const { data, error, loading, reload } = useRequest(`audit:${clientId}`, () => api.audit(clientId, 1000));
  const [filter, setFilter] = useState("ALL");
  const [open, setOpen] = useState<string | null>(null);
  const [verify, setVerify] = useState<{ valid: boolean; first_invalid_entry: string | null; at: string } | null>(null);
  const [anchor, setAnchor] = useState<AnchorResult | null>(null);
  const [proofs, setProofs] = useState<Record<string, MerkleProofResponse>>({});
  const verifyAction = useAction(async () => {
    const r = await api.verifyAudit(clientId);
    setVerify({ ...r, at: new Date().toISOString() });
  });
  const anchorAction = useAction(async () => setAnchor(await api.anchorAudit(clientId)));
  const proofAction = useAction(async (entryId: string) => {
    const res = await api.merkleProof(clientId, entryId);
    setProofs((prev) => ({ ...prev, [entryId]: res }));
  });

  const entries = useMemo(() => data?.entries ?? [], [data]);
  const types = useMemo(() => Array.from(new Set(entries.map((e) => e.event_type))).sort(), [entries]);
  const shown = filter === "ALL" ? entries : entries.filter((e) => e.event_type === filter);

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
              Verify {entries.length} entries
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

        <Panel title="Anchor to a public ledger" aside={<Tag tone="success">On-Chain Challenge Bonus</Tag>}>
          <p className="text-sm text-muted">
            Combines all entry hashes into an RFC 6962 binary Merkle tree root and writes it to the Ethereum Sepolia network (`chain_id=11155111`) with domain separation (`WEALTHTECH_AUDIT_ANCHOR_V1:`).
          </p>
          <div className="mt-4">
            <Button variant="secondary" onClick={() => anchorAction.run()} pending={anchorAction.pending}>
              Anchor Merkle root to Sepolia
            </Button>
          </div>
          <div className="mt-4">
            <ErrorNotice error={anchorAction.error} />
            {anchor ? (
              <Ledger
                rows={[
                  {
                    label: "Status",
                    value: <Tag tone={anchor.status === "confirmed" ? "success" : anchor.status === "dry_run" ? "warning" : "neutral"}>{anchor.status === "dry_run" ? "Simulated (Deterministic)" : humanize(anchor.status)}</Tag>,
                  },
                  { label: "Entries anchored", value: anchor.entries_count },
                  { label: "RFC 6962 Merkle root", value: <span className="text-[13px] break-all">{anchor.merkle_root}</span> },
                  {
                    label: "Sepolia Transaction",
                    value: (
                      <a
                        href={`https://sepolia.etherscan.io/tx/${anchor.tx_hash}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[13px] break-all text-primary underline underline-offset-4"
                      >
                        {anchor.tx_hash}
                      </a>
                    ),
                  },
                  { label: "Block", value: anchor.block_number ?? "Pending" },
                  { label: "Chain ID", value: `${anchor.chain_id} (Ethereum Sepolia)` },
                ]}
              />
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
                              <dt className="font-sans text-muted">Entry</dt>
                              <dd className="break-all">{e.entry_id}</dd>
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
                              {proof ? "Recompute Merkle Proof" : "Verify RFC 6962 Merkle Inclusion Proof"}
                            </Button>
                          </div>

                          {proof ? (
                            <div className="mt-4 rounded-xl border border-line bg-background p-4">
                              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2.5">
                                <p className="text-xs font-semibold tracking-wider text-ink uppercase">
                                  RFC 6962 Cryptographic Merkle Inclusion Proof
                                </p>
                                <Tag tone={proof.verified ? "success" : "danger"}>
                                  {proof.verified ? `VERIFIED · Leaf #${proof.leaf_index} of ${proof.total_leaves}` : "PROOF MISMATCH"}
                                </Tag>
                              </div>
                              <dl className="figures mt-3 grid gap-x-6 gap-y-1 text-[12px] md:grid-cols-[9.5rem_1fr]">
                                <dt className="font-sans text-muted">Algorithm</dt>
                                <dd>RFC 6962 Binary Merkle Tree (SHA-256)</dd>
                                <dt className="font-sans text-muted">Network</dt>
                                <dd>{proof.network ?? "Ethereum Sepolia Testnet"} (Chain ID {proof.chain_id ?? 11155111})</dd>
                                <dt className="font-sans text-muted">Leaf Hash (0x00)</dt>
                                <dd className="break-all">{proof.leaf_hash}</dd>
                                <dt className="font-sans text-muted">Computed Root</dt>
                                <dd className="break-all font-semibold text-accent">{proof.merkle_root}</dd>
                              </dl>
                              {proof.proof.length > 0 ? (
                                <div className="mt-3">
                                  <p className="text-xs font-medium text-muted">
                                    Sibling Audit Path ({proof.proof.length} internal node hops, 0x01 prefix):
                                  </p>
                                  <ol className="figures mt-1.5 space-y-1 text-[11.5px] text-ink">
                                    {proof.proof.map((s, idx) => (
                                      <li key={`${s.hash}-${idx}`} className="flex flex-wrap items-center gap-2">
                                        <span className="text-muted">Hop {idx + 1} ({s.position}):</span>
                                        <span className="break-all">{s.hash}</span>
                                      </li>
                                    ))}
                                  </ol>
                                </div>
                              ) : (
                                <p className="mt-2 text-xs text-muted">Single-leaf tree (leaf hash is direct root).</p>
                              )}
                            </div>
                          ) : null}

                          <pre className="figures mt-3 max-h-80 overflow-auto rounded-xl border border-line bg-background p-3.5 text-[12px] leading-relaxed text-ink">
                            {JSON.stringify(e.details, null, 2)}
                          </pre>
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
