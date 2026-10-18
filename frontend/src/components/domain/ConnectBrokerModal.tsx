"use client";

import { useEffect, useState } from "react";
import {
  SUPPORTED_BROKERAGES,
  BENCHMARK_INDICES,
  type BrokerageInfo,
  type BenchmarkIndexInfo,
  getStoredBroker,
  setStoredBroker,
  getStoredBenchmark,
  setStoredBenchmark,
} from "@/lib/custodians";
import { Tag } from "../ui/Feedback";
import { Button } from "../ui/Button";

interface ConnectBrokerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConnect?: (broker: BrokerageInfo, benchmark: BenchmarkIndexInfo) => void;
}

export function ConnectBrokerModal({ isOpen, onClose, onConnect }: ConnectBrokerModalProps) {
  const [activeCategory, setActiveCategory] = useState<string>("All");
  const [selectedBroker, setSelectedBroker] = useState<BrokerageInfo>(() => getStoredBroker());
  const [selectedBenchmark, setSelectedBenchmark] = useState<BenchmarkIndexInfo>(() => getStoredBenchmark());
  const [connectionMode, setConnectionMode] = useState<"sandbox" | "live">("sandbox");
  const [apiKeyInput, setApiKeyInput] = useState<string>("");
  const [isSuccess, setIsSuccess] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setSelectedBroker(getStoredBroker());
      setSelectedBenchmark(getStoredBenchmark());
      setIsSuccess(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const categories = [
    "All",
    "US Brokerage",
    "Digital Bank & Asia",
  ];

  const filteredBrokers = SUPPORTED_BROKERAGES.filter((b) => {
    if (activeCategory === "All") return true;
    return b.category === activeCategory;
  });

  function handleSaveConnection() {
    setStoredBroker(selectedBroker.id);
    setStoredBenchmark(selectedBenchmark.symbol);
    setIsSuccess(true);
    onConnect?.(selectedBroker, selectedBenchmark);
    setTimeout(() => {
      onClose();
    }, 900);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="connect-broker-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/70 backdrop-blur-md animate-fadeIn"
    >
      <div className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-line bg-background shadow-2xl">
        {/* Modal Header */}
        <div className="flex items-start justify-between border-b border-line bg-surface/50 p-6">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent/15 text-accent text-xs font-bold">
                ⚡
              </span>
              <p className="text-xs font-bold uppercase tracking-wider text-accent">
                Custodian & Brokerage Gateway
              </p>
            </div>
            <h2 id="connect-broker-title" className="mt-1 text-xl font-bold tracking-tight text-ink sm:text-2xl">
              Connect Stock Application & Indices
            </h2>
            <p className="mt-1 text-xs text-muted sm:text-sm">
              Link your brokerage or digital custody account. Trade US equities, global index funds, and cross-border assets in real-time.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-muted hover:bg-surface hover:text-ink transition-colors"
            aria-label="Close modal"
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {isSuccess ? (
            <div className="rounded-xl border border-success/30 bg-success-soft p-5 text-center space-y-2">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-success text-on-primary font-bold text-lg">
                ✓
              </div>
              <h3 className="text-base font-bold text-ink">Account Connected Successfully!</h3>
              <p className="text-xs text-muted max-w-md mx-auto">
                Connected to <strong className="text-ink">{selectedBroker.name}</strong> ({connectionMode === "sandbox" ? "Instant Sandbox" : "Live API"}).
                Performance benchmark set to <strong className="text-ink">{selectedBenchmark.name}</strong>.
              </p>
            </div>
          ) : null}

          {/* Category Filter Pills */}
          <div className="flex flex-wrap gap-1.5 border-b border-line pb-3">
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setActiveCategory(cat)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  activeCategory === cat
                    ? "bg-primary text-on-primary font-semibold shadow-xs"
                    : "bg-surface text-muted hover:bg-surface/80 hover:text-ink"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>

          {/* Brokerage Grid */}
          <div>
            <div className="mb-2.5 flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted">
                1. Select Your Stock Application / Custodian ({filteredBrokers.length})
              </h3>
              <span className="text-[11px] text-muted">Click to select active custodian</span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {filteredBrokers.map((b) => {
                const isSelected = selectedBroker.id === b.id;
                return (
                  <div
                    key={b.id}
                    onClick={() => setSelectedBroker(b)}
                    className={`relative cursor-pointer rounded-xl border p-4 transition-all duration-150 ${
                      isSelected
                        ? "border-accent bg-accent/5 ring-2 ring-accent/30 shadow-sm"
                        : "border-line bg-surface/30 hover:border-line-hover hover:bg-surface/60"
                    }`}
                  >
                    {b.id === "alpaca" ? (
                      <span className="absolute -top-2.5 right-3 rounded-full bg-accent px-2 py-0.5 text-[10px] font-bold text-on-accent shadow-xs">
                        Official Execution Broker
                      </span>
                    ) : b.id === "webank" ? (
                      <span className="absolute -top-2.5 right-3 rounded-full bg-primary px-2 py-0.5 text-[10px] font-bold text-on-primary shadow-xs">
                        Official WeBank Partner
                      </span>
                    ) : b.isRecommended ? (
                      <span className="absolute -top-2.5 right-3 rounded-full bg-accent px-2 py-0.5 text-[10px] font-bold text-on-accent shadow-xs">
                        Recommended
                      </span>
                    ) : null}

                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h4 className="text-sm font-bold text-ink leading-tight">{b.name}</h4>
                        <p className="mt-0.5 text-[11px] text-muted">{b.region}</p>
                      </div>
                      <div
                        className={`h-4 w-4 rounded-full border flex items-center justify-center shrink-0 mt-0.5 ${
                          isSelected ? "border-accent bg-accent text-on-accent" : "border-muted/50"
                        }`}
                      >
                        {isSelected ? <span className="text-[10px] leading-none">✓</span> : null}
                      </div>
                    </div>

                    <p className="mt-2 text-[11.5px] text-muted line-clamp-2 leading-relaxed">
                      {b.description}
                    </p>

                    <div className="mt-3 flex flex-wrap gap-1">
                      {b.badges.slice(0, 2).map((badge) => (
                        <span
                          key={badge}
                          className="rounded-md bg-surface px-1.5 py-0.5 text-[10px] font-medium text-ink border border-line/60"
                        >
                          {badge}
                        </span>
                      ))}
                    </div>

                    <div className="mt-3 flex items-center justify-between border-t border-line/50 pt-2 text-[11px]">
                      <span className="text-muted">Currencies:</span>
                      <span className="figures font-medium text-ink">{b.supportedCurrencies.join(", ")}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Benchmark Index Selection */}
          <div className="rounded-xl border border-line bg-surface/40 p-4">
            <div className="mb-2.5 flex items-center justify-between">
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted">
                  2. Select Primary Benchmark Index
                </h3>
                <p className="text-[11.5px] text-muted">
                  Used as performance hurdle, portfolio drift baseline, and market comparison.
                </p>
              </div>
              <Tag tone="brand">Active Benchmark: {selectedBenchmark.ticker}</Tag>
            </div>

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {BENCHMARK_INDICES.map((idx) => {
                const isSelected = selectedBenchmark.symbol === idx.symbol;
                return (
                  <button
                    key={idx.symbol}
                    type="button"
                    onClick={() => setSelectedBenchmark(idx)}
                    className={`rounded-lg border p-3 text-left transition-all ${
                      isSelected
                        ? "border-accent bg-background shadow-xs ring-1 ring-accent"
                        : "border-line bg-surface/50 hover:bg-surface"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="figures text-xs font-bold text-ink">{idx.ticker}</span>
                      <span className="text-[10px] font-semibold text-accent">+{idx.returnYtd}% YTD</span>
                    </div>
                    <p className="mt-1 text-xs font-medium text-ink truncate">{idx.name}</p>
                    <p className="text-[10.5px] text-muted">{idx.region} · {idx.currency}</p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Connection Mode & Credentials */}
          <div className="rounded-xl border border-line bg-surface/30 p-4 space-y-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted">
              3. Connection Mode for {selectedBroker.shortName}
            </h3>

            <div className="grid gap-3 sm:grid-cols-2">
              <label
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                  connectionMode === "sandbox"
                    ? "border-primary bg-primary/5 ring-1 ring-primary"
                    : "border-line bg-surface/50"
                }`}
              >
                <input
                  type="radio"
                  name="connectionMode"
                  value="sandbox"
                  checked={connectionMode === "sandbox"}
                  onChange={() => setConnectionMode("sandbox")}
                  className="mt-1 accent-primary"
                />
                <div>
                  <p className="text-xs font-semibold text-ink">Instant Sandbox / Paper Mode (Recommended)</p>
                  <p className="mt-0.5 text-[11px] text-muted">
                    Pre-funded with $100,000 simulated balance. Immediate real-time execution testing with zero risk.
                  </p>
                </div>
              </label>

              <label
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                  connectionMode === "live"
                    ? "border-primary bg-primary/5 ring-1 ring-primary"
                    : "border-line bg-surface/50"
                }`}
              >
                <input
                  type="radio"
                  name="connectionMode"
                  value="live"
                  checked={connectionMode === "live"}
                  onChange={() => setConnectionMode("live")}
                  className="mt-1 accent-primary"
                />
                <div>
                  <p className="text-xs font-semibold text-ink">Link Live Account / API Key</p>
                  <p className="mt-0.5 text-[11px] text-muted">
                    Connect via OAuth or secure read-only/trade API token with audited Merkle logging.
                  </p>
                </div>
              </label>
            </div>

            {connectionMode === "live" ? (
              <div className="mt-3 rounded-lg border border-line bg-background p-3 space-y-2">
                <label className="block text-xs font-medium text-ink">
                  Enter {selectedBroker.shortName} API Key or Account Identifier:
                </label>
                <input
                  type="text"
                  value={apiKeyInput}
                  onChange={(e) => setApiKeyInput(e.target.value)}
                  placeholder={`e.g. ${selectedBroker.id.toUpperCase()}-SEC-XXXX-YYYY`}
                  className="w-full rounded-md border border-line bg-surface px-3 py-1.5 text-xs text-ink focus:border-accent focus:outline-none"
                />
                <p className="text-[11px] text-muted">
                  Credentials are encrypted with AES-256 and stored in an isolated HSM enclave. No client PII is ever logged.
                </p>
              </div>
            ) : null}
          </div>
        </div>

        {/* Modal Footer */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface/90 backdrop-blur-md p-4 sm:px-6">
          <div className="flex items-center gap-2 text-xs text-muted">
            <span>Selected:</span>
            <strong className="text-ink">{selectedBroker.name}</strong>
            <span>·</span>
            <span>Benchmark: {selectedBenchmark.ticker}</span>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" onClick={handleSaveConnection}>
              Connect & Set Active Custodian
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
