/**
 * frontend/src/lib/custodians.ts
 * ==============================
 * Connected Stock Brokerages, Custodians & Benchmark Indices.
 * Focused strictly on real, verifiable execution:
 * 1. Alpaca Securities LLC — Real-time live paper trading sandbox with REST/WebSocket API and app.alpaca.markets dashboard.
 * 2. WeBank Smart Wealth — Institutional sponsor banking & FISCO BCOS blockchain cryptographic audit custody.
 */

export interface BrokerageInfo {
  id: string;
  name: string;
  shortName: string;
  region: string;
  category: "US Brokerage" | "Digital Bank & Asia";
  description: string;
  supportedCurrencies: string[];
  badges: string[];
  popularAssets: string[];
  isRecommended?: boolean;
  isWeBank?: boolean;
  accountModes: ("sandbox" | "oauth" | "api_key")[];
  defaultBuyingPower: number;
  status: "available" | "connected" | "maintenance";
}

export interface BenchmarkIndexInfo {
  symbol: string;
  ticker: string;
  name: string;
  region: string;
  category: "US Large Cap" | "Tech & Growth" | "China & Hong Kong" | "Global Equities" | "Fixed Income";
  currency: string;
  returnYtd: number;
  description: string;
}

export const SUPPORTED_BROKERAGES: BrokerageInfo[] = [
  {
    id: "alpaca",
    name: "Alpaca Securities LLC (Live Paper Sandbox)",
    shortName: "Alpaca",
    region: "United States / Global",
    category: "US Brokerage",
    description: "Official execution broker for Equify. Real-time paper trading sandbox with live matching engine, SIPC protection, and instant web dashboard verification at app.alpaca.markets.",
    supportedCurrencies: ["USD"],
    badges: ["Live Sandbox API", "Instant Matching", "app.alpaca.markets", "DTC #3848", "SIPC Insured"],
    popularAssets: ["AAPL", "NVDA", "MSFT", "TSLA", "SPY", "BND", "IBIT"],
    isRecommended: true,
    accountModes: ["sandbox", "api_key"],
    defaultBuyingPower: 376906.49,
    status: "connected",
  },
  {
    id: "webank",
    name: "WeBank Smart Wealth (微众银行财富+)",
    shortName: "WeBank",
    region: "China / Hong Kong GBA",
    category: "Digital Bank & Asia",
    description: "Consortium banking & FISCO BCOS blockchain audit partner. Anchors all trade execution hashes and client suitability records into immutable cryptographic Merkle trees.",
    supportedCurrencies: ["CNY", "HKD", "USD"],
    badges: ["FISCO BCOS Blockchain", "WeBank Official", "GBA Wealth Connect", "Institutional Custody"],
    popularAssets: ["WBKCASH", "WBK6M", "GBAHK", "WBKGLD"],
    isWeBank: true,
    accountModes: ["sandbox", "oauth"],
    defaultBuyingPower: 100000,
    status: "connected",
  },
];

export const BENCHMARK_INDICES: BenchmarkIndexInfo[] = [
  {
    symbol: "^GSPC",
    ticker: "SPY",
    name: "S&P 500 Index (Standard & Poor's 500)",
    region: "United States",
    category: "US Large Cap",
    currency: "USD",
    returnYtd: 14.8,
    description: "The premier benchmark of 500 leading US public companies, representing ~80% of available market capitalization.",
  },
  {
    symbol: "^NDX",
    ticker: "QQQ",
    name: "Nasdaq-100 Index",
    region: "United States",
    category: "Tech & Growth",
    currency: "USD",
    returnYtd: 19.4,
    description: "Top 100 largest non-financial innovative companies listed on the Nasdaq exchange, heavy in software, cloud, and semiconductors.",
  },
  {
    symbol: "000300.SS",
    ticker: "ASHR",
    name: "CSI 300 Index (沪深300指数)",
    region: "China Mainland",
    category: "China & Hong Kong",
    currency: "CNY",
    returnYtd: 11.2,
    description: "The core benchmark tracking 300 largest and most liquid A-shares listed on Shanghai and Shenzhen stock exchanges.",
  },
  {
    symbol: "^HSI",
    ticker: "2800.HK",
    name: "Hang Seng Index (恒生指数)",
    region: "Hong Kong SAR",
    category: "China & Hong Kong",
    currency: "HKD",
    returnYtd: 8.6,
    description: "The bellwether index of the Hong Kong stock market, tracking top financial, tech, and enterprise leaders.",
  },
  {
    symbol: "AGG",
    ticker: "BND",
    name: "Bloomberg US Aggregate Bond Index",
    region: "United States",
    category: "Fixed Income",
    currency: "USD",
    returnYtd: 3.5,
    description: "The definitive total US bond market benchmark covering investment-grade Treasuries, corporate debt, and mortgage-backed securities.",
  },
];

export const STORAGE_KEYS = {
  ACTIVE_BROKER: "equify_connected_broker",
  ACTIVE_BENCHMARK: "equify_benchmark_index",
  BROKER_ACCOUNTS: "equify_broker_accounts",
} as const;

export function getStoredBroker(): BrokerageInfo {
  if (typeof window === "undefined") return SUPPORTED_BROKERAGES[0];
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.ACTIVE_BROKER);
    if (!raw) return SUPPORTED_BROKERAGES[0]; // Alpaca default
    const found = SUPPORTED_BROKERAGES.find((b) => b.id === raw);
    return found || SUPPORTED_BROKERAGES[0];
  } catch {
    return SUPPORTED_BROKERAGES[0];
  }
}

export function setStoredBroker(brokerId: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEYS.ACTIVE_BROKER, brokerId);
    window.dispatchEvent(new CustomEvent("equify:broker_changed", { detail: { brokerId } }));
  } catch (err) {
    console.error("Failed to persist connected broker:", err);
  }
}

export function getStoredBenchmark(): BenchmarkIndexInfo {
  if (typeof window === "undefined") return BENCHMARK_INDICES[0];
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.ACTIVE_BENCHMARK);
    if (!raw) return BENCHMARK_INDICES[0]; // S&P 500 default
    const found = BENCHMARK_INDICES.find((idx) => idx.symbol === raw || idx.ticker === raw);
    return found || BENCHMARK_INDICES[0];
  } catch {
    return BENCHMARK_INDICES[0];
  }
}

export function setStoredBenchmark(symbolOrTicker: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEYS.ACTIVE_BENCHMARK, symbolOrTicker);
    window.dispatchEvent(new CustomEvent("equify:benchmark_changed", { detail: { benchmark: symbolOrTicker } }));
  } catch (err) {
    console.error("Failed to persist benchmark:", err);
  }
}

export interface CustodianVerificationGuide {
  brokerId: string;
  brokerName: string;
  shortName: string;
  icon: string;
  portalName: string;
  portalUrl: string;
  mobileAppPath: string;
  clearingHouse: string;
  settlementCycle: string;
  auditLedgerType: string;
  verificationSteps: string[];
}

export function getCustodianVerificationGuide(brokerId: string, orderId?: string): CustodianVerificationGuide {
  const normalized = (brokerId || "alpaca").toLowerCase().replace(/[^a-z0-9]/g, "");

  if (normalized.includes("webank") || normalized.includes("wbk")) {
    return {
      brokerId: "webank",
      brokerName: "WeBank Smart Wealth (微众银行财富+)",
      shortName: "WeBank",
      icon: "🏦",
      portalName: "WeBank Wealth Mobile & WeChat Mini-Program (微众银行App/财富小程序)",
      portalUrl: "https://www.webank.com",
      mobileAppPath: "WeBank App → 财富 (Wealth) → 我的持仓 (Holdings) → 交易明细 (Transaction Records)",
      clearingHouse: "WeBank Interbank Clearing & FISCO BCOS Consortium Chain",
      settlementCycle: "Instant Core Banking Ledger (Sandbox / Live T+1)",
      auditLedgerType: "FISCO BCOS Consortium Merkle Tree Leaf (Block Inscribed)",
      verificationSteps: [
        "Open your official WeBank App (微众银行) or WeChat Wealth Mini-Program.",
        "Tap the '财富' (Wealth) tab in the bottom navigation.",
        "Select '持仓' (Holdings) to see your updated security positions and cash balance.",
        "Tap '交易明细' (Transaction Records) to verify the order, fill price, and cryptographic timestamp.",
        "For Cross-Border Wealth Connect (跨境理财通), check your dedicated GBA investment account sub-ledger.",
      ],
    };
  }

  // Alpaca is the default, live paper sandbox execution broker
  return {
    brokerId: "alpaca",
    brokerName: "Alpaca Securities LLC",
    shortName: "Alpaca",
    icon: "🦙",
    portalName: "Alpaca Trading Dashboard (Live Paper Sandbox)",
    portalUrl: "https://app.alpaca.markets/paper/dashboard/orders",
    mobileAppPath: "app.alpaca.markets → Paper Trading → Orders Tab",
    clearingHouse: "Alpaca Securities LLC / DTC Participant #3848",
    settlementCycle: "T+1 Delivery-versus-Payment (SEC Rule 15c6-1 / Sandbox Instant)",
    auditLedgerType: "Live REST/FIX Order Execution Slip",
    verificationSteps: [
      "Open your live Alpaca Dashboard at https://app.alpaca.markets.",
      "Ensure the top-left switcher is set to 'Paper Trading'.",
      "Click 'Orders' in the left menu to view your live executed orders in real time.",
      `Locate order ID ${orderId ? `"${orderId}"` : "matching your trade timestamp"} under the 'Filled' or 'Accepted' tab.`,
      "Inspect the execution average price, filled quantity, and exchange routing.",
    ],
  };
}
