"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

export interface SecurityRecord {
  symbol: string;
  name: string;
  category: string;
  assetClass: "Equity" | "Fixed Income" | "Commodity" | "Crypto" | "Real Estate";
  currency?: string;
}

export const SECURITIES_DIRECTORY: SecurityRecord[] = [
  // Core Benchmark Indices & Market ETFs
  { symbol: "SPY", name: "SPDR S&P 500 ETF Trust", category: "US Large Cap Core", assetClass: "Equity" },
  { symbol: "QQQ", name: "Invesco QQQ Trust", category: "US Tech Large Cap", assetClass: "Equity" },
  { symbol: "DIA", name: "SPDR Dow Jones Industrial Average ETF", category: "US Blue-Chip Core", assetClass: "Equity" },
  { symbol: "IWM", name: "iShares Russell 2000 ETF", category: "US Small Cap Core", assetClass: "Equity" },
  { symbol: "VTI", name: "Vanguard Total Stock Market ETF", category: "US Total Market", assetClass: "Equity" },
  { symbol: "VOO", name: "Vanguard S&P 500 ETF", category: "US Large Cap Blend", assetClass: "Equity" },
  { symbol: "URTH", name: "iShares MSCI World ETF", category: "Global Developed Markets", assetClass: "Equity" },
  { symbol: "ACWI", name: "iShares MSCI ACWI ETF", category: "All-Country World Index", assetClass: "Equity" },
  { symbol: "VXUS", name: "Vanguard Total International Stock ETF", category: "Global Ex-US Equity", assetClass: "Equity" },
  { symbol: "EEM", name: "iShares MSCI Emerging Markets ETF", category: "Emerging Markets", assetClass: "Equity" },
  { symbol: "VNQ", name: "Vanguard Real Estate ETF", category: "US Real Estate REITs", assetClass: "Real Estate" },

  // Chinese & Hong Kong Stock Market Indices
  { symbol: "000300.SS", name: "CSI 300 Index (沪深300指数)", category: "China A-Shares Top 300", assetClass: "Equity", currency: "CNY" },
  { symbol: "ASHR", name: "Xtrackers Harvest CSI 300 China A-Shares ETF", category: "China A-Shares Core", assetClass: "Equity" },
  { symbol: "2800.HK", name: "Tracker Fund of Hong Kong (盈富基金 / 恒生指数)", category: "Hong Kong Hang Seng Index", assetClass: "Equity", currency: "HKD" },
  { symbol: "^HSI", name: "Hang Seng Index Benchmark (恒生指数)", category: "Hong Kong Blue-Chip Equities", assetClass: "Equity", currency: "HKD" },
  { symbol: "FXI", name: "iShares China Large-Cap ETF", category: "China Top 50 Equities", assetClass: "Equity" },
  { symbol: "MCHI", name: "iShares MSCI China ETF", category: "Broad China Equities", assetClass: "Equity" },

  // Global Index Benchmarks
  { symbol: "^GSPC", name: "S&P 500 Benchmark Index", category: "US Large-Cap Benchmark", assetClass: "Equity" },
  { symbol: "^NDX", name: "Nasdaq-100 Benchmark Index", category: "US Technology Benchmark", assetClass: "Equity" },
  { symbol: "^DJI", name: "Dow Jones Industrial Average Benchmark", category: "US Industrial Blue-Chip", assetClass: "Equity" },
  { symbol: "^RUT", name: "Russell 2000 Benchmark Index", category: "US Small-Cap Benchmark", assetClass: "Equity" },

  // Fixed Income & Bonds
  { symbol: "BND", name: "Vanguard Total Bond Market ETF", category: "US Aggregate Bond", assetClass: "Fixed Income" },
  { symbol: "AGG", name: "iShares Core U.S. Aggregate Bond ETF", category: "US Aggregate Bond", assetClass: "Fixed Income" },
  { symbol: "SHY", name: "iShares 1-3 Year Treasury Bond ETF", category: "Short-Term Treasury", assetClass: "Fixed Income" },
  { symbol: "IEF", name: "iShares 7-10 Year Treasury Bond ETF", category: "Intermediate Treasury", assetClass: "Fixed Income" },
  { symbol: "TLT", name: "iShares 20+ Year Treasury Bond ETF", category: "Long-Term Treasury", assetClass: "Fixed Income" },
  { symbol: "TIP", name: "iShares TIPS Bond ETF", category: "Inflation-Protected Treasury", assetClass: "Fixed Income" },
  { symbol: "LQD", name: "iShares iBoxx $ Investment Grade Corporate Bond", category: "Corporate Bonds", assetClass: "Fixed Income" },
  { symbol: "HYG", name: "iShares iBoxx $ High Yield Corporate Bond", category: "High Yield Bonds", assetClass: "Fixed Income" },

  // Commodities & Hard Assets
  { symbol: "GLD", name: "SPDR Gold Shares", category: "Physical Gold Bullion", assetClass: "Commodity" },
  { symbol: "SLV", name: "iShares Silver Trust", category: "Physical Silver Bullion", assetClass: "Commodity" },
  { symbol: "USO", name: "United States Oil Fund LP", category: "Crude Oil Commodity", assetClass: "Commodity" },

  // Mega-Cap US Equities
  { symbol: "AAPL", name: "Apple Inc.", category: "Consumer Technology", assetClass: "Equity" },
  { symbol: "MSFT", name: "Microsoft Corporation", category: "Enterprise Software & Cloud", assetClass: "Equity" },
  { symbol: "NVDA", name: "NVIDIA Corporation", category: "Semiconductors & AI Hardware", assetClass: "Equity" },
  { symbol: "AMZN", name: "Amazon.com Inc.", category: "E-Commerce & Cloud Infrastructure", assetClass: "Equity" },
  { symbol: "GOOGL", name: "Alphabet Inc. (Google)", category: "Internet Media & Artificial Intelligence", assetClass: "Equity" },
  { symbol: "META", name: "Meta Platforms Inc.", category: "Social Networks & Metaverse", assetClass: "Equity" },
  { symbol: "TSLA", name: "Tesla Inc.", category: "Automotive & Clean Energy", assetClass: "Equity" },
  { symbol: "BRK.B", name: "Berkshire Hathaway Inc.", category: "Multi-Sector Conglomerate", assetClass: "Equity" },
  { symbol: "JPM", name: "JPMorgan Chase & Co.", category: "Diversified Global Banking", assetClass: "Equity" },

  // Crypto & Regulated Spot Digital Asset ETFs
  { symbol: "BTC", name: "Bitcoin Reserve", category: "Decentralized Digital Asset", assetClass: "Crypto" },
  { symbol: "ETH", name: "Ethereum", category: "Smart Contract Platform", assetClass: "Crypto" },
  { symbol: "IBIT", name: "iShares Bitcoin Trust ETF", category: "Regulated Spot Bitcoin ETF", assetClass: "Crypto" },
  { symbol: "FBTC", name: "Fidelity Wise Origin Bitcoin Fund", category: "Regulated Spot Bitcoin ETF", assetClass: "Crypto" },
  { symbol: "ETHA", name: "iShares Ethereum Trust ETF", category: "Regulated Spot Ethereum ETF", assetClass: "Crypto" },

  // WeBank Smart Wealth (微众银行财富+) & GBA Cross-Border Wealth Connect (跨境理财通)
  { symbol: "WBKCASH", name: "WeBank Live+ Cash Management Fund (微众活期+ R1)", category: "WeBank Money Market · R1", assetClass: "Fixed Income" },
  { symbol: "WBK6M", name: "WeBank Steady+ 180D Short-Duration Bond Note (微众稳健+ R2)", category: "WeBank Short-Duration Bond · R2", assetClass: "Fixed Income" },
  { symbol: "GBAHK", name: "WeBank GBA Wealth Connect Multi-Asset Income ETF (跨境理财通南向通)", category: "GBA Cross-Border Multi-Asset · R2", assetClass: "Equity" },
  { symbol: "WBKGLD", name: "WeBank Digital Gold Accumulation Trust (微众黄金 Inflation Hedge)", category: "WeBank Digital Bullion · R3", assetClass: "Commodity" },

  // International / Frontier
  { symbol: "DANGCEM", name: "Dangote Cement Plc", category: "Industrial Materials", assetClass: "Equity", currency: "NGN" },
  { symbol: "MTNN", name: "MTN Nigeria Communications Plc", category: "Telecommunications", assetClass: "Equity", currency: "NGN" },
  { symbol: "GTCO", name: "Guaranty Trust Holding Company Plc", category: "Commercial Banking", assetClass: "Equity", currency: "NGN" },
  { symbol: "ZENITHBANK", name: "Zenith Bank Plc", category: "Commercial Banking", assetClass: "Equity", currency: "NGN" },
];

export interface TickerAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  onSelectSymbol?: (symbol: string) => void;
  placeholder?: string;
  className?: string;
  id?: string;
  name?: string;
  autoCapitalize?: string;
  spellCheck?: boolean;
  allowMultiple?: boolean;
  disabled?: boolean;
}

export function TickerAutocomplete({
  value,
  onChange,
  onSelectSymbol,
  placeholder = "e.g. SPY, Apple, Vanguard...",
  className = "",
  id: customId,
  name,
  allowMultiple = false,
  disabled = false,
}: TickerAutocompleteProps) {
  const generatedId = useId();
  const inputId = customId ?? generatedId;
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Extract the active query token if multiple tokens are allowed
  const currentQuery = useMemo(() => {
    if (!allowMultiple) return value.trim().toUpperCase();
    const parts = value.split(/[\s,;]+/);
    return (parts[parts.length - 1] ?? "").trim().toUpperCase();
  }, [allowMultiple, value]);

  // Compute matching security suggestions
  const suggestions = useMemo(() => {
    if (!currentQuery || currentQuery.length < 1) return [];

    const exactMatches: SecurityRecord[] = [];
    const prefixMatches: SecurityRecord[] = [];
    const nameMatches: SecurityRecord[] = [];

    for (const sec of SECURITIES_DIRECTORY) {
      const sym = sec.symbol.toUpperCase();
      const n = sec.name.toUpperCase();
      const cat = sec.category.toUpperCase();

      if (sym === currentQuery) {
        exactMatches.push(sec);
      } else if (sym.startsWith(currentQuery)) {
        prefixMatches.push(sec);
      } else if (n.includes(currentQuery) || cat.includes(currentQuery)) {
        nameMatches.push(sec);
      }
    }

    return [...exactMatches, ...prefixMatches, ...nameMatches].slice(0, 6);
  }, [currentQuery]);

  // Close suggestions when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Reset highlighted index when suggestions change
  useEffect(() => {
    setHighlightedIndex(0);
  }, [suggestions]);

  function handleSelect(item: SecurityRecord) {
    if (allowMultiple) {
      const parts = value.split(/([\s,;]+)/);
      // Replace the last non-separator token with the selected symbol
      let foundLast = false;
      for (let i = parts.length - 1; i >= 0; i--) {
        if (!/^[\s,;]+$/.test(parts[i]) && parts[i].trim().length > 0) {
          parts[i] = item.symbol;
          foundLast = true;
          break;
        }
      }
      if (!foundLast) parts.push(item.symbol);
      const nextVal = parts.join("") + " ";
      onChange(nextVal);
    } else {
      onChange(item.symbol);
    }

    setIsOpen(false);
    onSelectSymbol?.(item.symbol);
    inputRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!isOpen || suggestions.length === 0) {
      if (e.key === "ArrowDown" && suggestions.length > 0) {
        setIsOpen(true);
        e.preventDefault();
      }
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightedIndex((prev) => (prev + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightedIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === "Enter") {
      if (suggestions[highlightedIndex]) {
        e.preventDefault();
        handleSelect(suggestions[highlightedIndex]);
      }
    } else if (e.key === "Escape") {
      setIsOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <input
        ref={inputRef}
        id={inputId}
        name={name}
        type="text"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setIsOpen(true);
        }}
        onFocus={() => {
          if (suggestions.length > 0) setIsOpen(true);
        }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        autoCapitalize="characters"
        autoComplete="off"
        spellCheck={false}
        className={`figures h-10 w-full rounded-control border border-line bg-background px-3 text-sm text-ink transition-colors duration-140 placeholder:text-muted/70 focus:border-accent focus:bg-background focus:outline-none ${className}`}
      />

      {/* Floating Suggestions Dropdown */}
      {isOpen && suggestions.length > 0 && (
        <div className="absolute left-0 top-[calc(100%+4px)] z-50 w-full min-w-[280px] max-w-[420px] rounded-xl border border-line bg-background p-1.5 shadow-lg backdrop-blur-md animate-fadeIn">
          <div className="px-2 py-1 text-[11px] font-semibold text-muted uppercase tracking-wider">
            Suggested Securities
          </div>
          <ul role="listbox" className="space-y-0.5">
            {suggestions.map((item, index) => {
              const isSelected = index === highlightedIndex;
              return (
                <li
                  key={item.symbol}
                  role="option"
                  aria-selected={isSelected}
                  onMouseEnter={() => setHighlightedIndex(index)}
                  onClick={() => handleSelect(item)}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-xs transition-colors ${
                    isSelected ? "bg-accent-soft text-ink" : "hover:bg-surface text-ink"
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="figures inline-flex h-6 min-w-[44px] items-center justify-center rounded-md bg-primary px-1.5 font-bold text-on-primary text-[11px]">
                      {item.symbol}
                    </span>
                    <div className="min-w-0 truncate">
                      <p className="truncate font-semibold leading-tight text-ink">{item.name}</p>
                      <p className="truncate text-[11px] text-muted leading-tight">{item.category}</p>
                    </div>
                  </div>
                  <span className="shrink-0 rounded-full border border-line bg-surface px-2 py-0.5 text-[10px] font-medium text-muted">
                    {item.assetClass}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
