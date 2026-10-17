/**
 * frontend/src/lib/custodians.ts
 * ==============================
 * Comprehensive Directory of Connected Stock Brokerages, Custodians & Benchmark Indices.
 * Supports WeBank Smart Wealth, Alpaca, IBKR, Charles Schwab, Fidelity, Robinhood,
 * Tiger Brokers, Futu/Moomoo, Bamboo, Coinbase, and Vanguard.
 */

export interface BrokerageInfo {
  id: string;
  name: string;
  shortName: string;
  region: string;
  category: "Digital Bank & Asia" | "US Brokerage" | "Global Prime" | "Crypto & Digital" | "Frontier & Africa";
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
    id: "webank",
    name: "WeBank Smart Wealth (微众银行财富+)",
    shortName: "WeBank",
    region: "China / Hong Kong GBA",
    category: "Digital Bank & Asia",
    description: "China's leading digital bank. Supports Greater Bay Area (GBA) Cross-Border Wealth Connect (跨境理财通), FISCO BCOS blockchain audit logging, and RMB/HKD dual-currency mutual funds.",
    supportedCurrencies: ["CNY", "HKD", "USD"],
    badges: ["WeBank Official", "FISCO BCOS Anchored", "GBA Wealth Connect", "Institutional"],
    popularAssets: ["WBKCASH", "WBK6M", "GBAHK", "WBKGLD"],
    isRecommended: true,
    isWeBank: true,
    accountModes: ["sandbox", "oauth"],
    defaultBuyingPower: 100000,
    status: "available",
  },
  {
    id: "alpaca",
    name: "Alpaca Securities",
    shortName: "Alpaca",
    region: "United States / Global",
    category: "US Brokerage",
    description: "Commission-free US equities and fractional ETF trading. SEC-registered broker-dealer and FINRA/SIPC member with real-time paper sandbox and institutional live API.",
    supportedCurrencies: ["USD"],
    badges: ["SEC / FINRA Member", "SIPC Insured", "Fractional Shares", "Instant Sandbox"],
    popularAssets: ["SPY", "QQQ", "VTI", "AAPL", "NVDA", "BND"],
    accountModes: ["sandbox", "api_key"],
    defaultBuyingPower: 100000,
    status: "available",
  },
  {
    id: "ibkr",
    name: "Interactive Brokers (IBKR)",
    shortName: "IBKR",
    region: "Global (150+ Markets)",
    category: "Global Prime",
    description: "Institutional prime brokerage across 150+ electronic exchanges in 33 countries. Multi-currency margin, deep order routing, and professional asset management connectivity.",
    supportedCurrencies: ["USD", "EUR", "GBP", "HKD", "CNH", "SGD", "JPY"],
    badges: ["150+ Global Markets", "Institutional Prime", "Multi-Currency Cash", "Lowest Margin"],
    popularAssets: ["SPY", "URTH", "000300.SS", "2800.HK", "AGG"],
    accountModes: ["sandbox", "oauth", "api_key"],
    defaultBuyingPower: 150000,
    status: "available",
  },
  {
    id: "schwab",
    name: "Charles Schwab & Co.",
    shortName: "Schwab",
    region: "United States",
    category: "US Brokerage",
    description: "Full-service US wealth custodian and brokerage. Supports Schwab Intelligent Portfolios, ThinkorSwim equity research, and comprehensive retirement custody.",
    supportedCurrencies: ["USD"],
    badges: ["RIA Custodian", "ThinkorSwim", "$0 Commission", "FDIC Cash Sweep"],
    popularAssets: ["SCHD", "SWPPX", "SPY", "VTI", "MSFT", "GOOGL"],
    accountModes: ["sandbox", "oauth"],
    defaultBuyingPower: 100000,
    status: "available",
  },
  {
    id: "fidelity",
    name: "Fidelity Investments",
    shortName: "Fidelity",
    region: "United States",
    category: "US Brokerage",
    description: "Pioneer in zero-expense ratio index mutual funds (FZROX, FNILX), fractional equity execution, and integrated workplace retirement accounts.",
    supportedCurrencies: ["USD"],
    badges: ["Zero-Expense Funds", "Retirement / 401(k)", "Fractional Shares", "Fidelity Crypto"],
    popularAssets: ["FZROX", "SPY", "QQQ", "AMZN", "META", "BND"],
    accountModes: ["sandbox", "oauth"],
    defaultBuyingPower: 100000,
    status: "available",
  },
  {
    id: "robinhood",
    name: "Robinhood Financial",
    shortName: "Robinhood",
    region: "United States / UK / EU",
    category: "US Brokerage",
    description: "Mobile-first retail trading app with 24-hour market trading, fractional shares, recurring investment schedules, and high-yield uninvested cash sweep.",
    supportedCurrencies: ["USD", "GBP", "EUR"],
    badges: ["24-Hour Market", "Mobile-First", "High-Yield Sweep", "Recurring Deposits"],
    popularAssets: ["AAPL", "TSLA", "NVDA", "SPY", "BTC", "ETH"],
    accountModes: ["sandbox", "oauth"],
    defaultBuyingPower: 50000,
    status: "available",
  },
  {
    id: "tiger",
    name: "Tiger Brokers (UP Fintech)",
    shortName: "Tiger",
    region: "Singapore / HK / US / Australia",
    category: "Digital Bank & Asia",
    description: "NASDAQ-listed global fintech brokerage (TIGR). Instant cross-border execution covering US Equities, Hong Kong Stock Connect, and Shanghai-Shenzhen A-shares.",
    supportedCurrencies: ["USD", "HKD", "CNH", "SGD", "AUD"],
    badges: ["Hong Kong Connect", "China A-Shares", "Pre/Post Market", "Multi-Market"],
    popularAssets: ["2800.HK", "ASHR", "BABA", "TCEHY", "SPY", "NVDA"],
    accountModes: ["sandbox", "oauth", "api_key"],
    defaultBuyingPower: 100000,
    status: "available",
  },
  {
    id: "futu",
    name: "Futu / Moomoo (富途牛牛)",
    shortName: "Moomoo",
    region: "Hong Kong / US / Singapore / Japan",
    category: "Digital Bank & Asia",
    description: "Global fintech and wealth management platform (NASDAQ: FUTU). Features free Level 2 real-time depth feeds, Hong Kong IPO subscriptions, and US/HK/China stock baskets.",
    supportedCurrencies: ["HKD", "USD", "CNH", "SGD", "JPY"],
    badges: ["Level 2 Real-Time", "Hong Kong IPO", "Options & Margin", "SIPC Insured"],
    popularAssets: ["0700.HK", "9988.HK", "SPY", "QQQ", "FXI", "ASHR"],
    accountModes: ["sandbox", "oauth"],
    defaultBuyingPower: 100000,
    status: "available",
  },
  {
    id: "bamboo",
    name: "Bamboo Investment",
    shortName: "Bamboo",
    region: "Nigeria & African Diaspora",
    category: "Frontier & Africa",
    description: "Leading digital investment platform providing seamless access to the Nigerian Exchange (NGX) and US capital markets with dual NGN and USD wallets.",
    supportedCurrencies: ["NGN", "USD"],
    badges: ["Nigerian Exchange (NGX)", "Dual NGN / USD", "SEC Registered Partner", "Instant Paystack"],
    popularAssets: ["DANGCEM", "MTNN", "GTCO", "SEPLAT", "SPY", "AAPL"],
    accountModes: ["sandbox", "api_key"],
    defaultBuyingPower: 100000,
    status: "available",
  },
  {
    id: "coinbase",
    name: "Coinbase Prime & Institutional",
    shortName: "Coinbase",
    region: "Global / United States",
    category: "Crypto & Digital",
    description: "Qualified digital asset custodian and execution venue. Supports institutional cold storage, regulated spot crypto trading, and crypto ETF balance aggregation.",
    supportedCurrencies: ["USD", "EUR", "USDC", "BTC", "ETH"],
    badges: ["Qualified Custodian", "Cold Storage", "Spot BTC & ETH", "Institutional SOC 2"],
    popularAssets: ["BTC", "ETH", "IBIT", "FBTC", "ETHA", "SOL"],
    accountModes: ["sandbox", "oauth", "api_key"],
    defaultBuyingPower: 100000,
    status: "available",
  },
  {
    id: "vanguard",
    name: "The Vanguard Group",
    shortName: "Vanguard",
    region: "United States / Global",
    category: "US Brokerage",
    description: "Investor-owned asset manager and pioneer of low-cost passive index investing. The gold standard for long-term Boglehead asset allocation and retirement stability.",
    supportedCurrencies: ["USD"],
    badges: ["Index Pioneer", "Ultra-Low Expense", "Client-Owned", "Long-Term Core"],
    popularAssets: ["VTI", "VOO", "VXUS", "BND", "VNQ", "VIG"],
    accountModes: ["sandbox", "oauth"],
    defaultBuyingPower: 100000,
    status: "available",
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
    symbol: "^DJI",
    ticker: "DIA",
    name: "Dow Jones Industrial Average",
    region: "United States",
    category: "US Large Cap",
    currency: "USD",
    returnYtd: 9.8,
    description: "Price-weighted benchmark of 30 prominent blue-chip US industrial, consumer, and financial giants.",
  },
  {
    symbol: "URTH",
    ticker: "URTH",
    name: "MSCI World Developed Equities",
    region: "Global Developed",
    category: "Global Equities",
    currency: "USD",
    returnYtd: 13.2,
    description: "Tracks large and mid-cap stocks across 23 developed countries worldwide.",
  },
  {
    symbol: "^RUT",
    ticker: "IWM",
    name: "Russell 2000 Small-Cap Index",
    region: "United States",
    category: "US Large Cap",
    currency: "USD",
    returnYtd: 7.4,
    description: "Comprehensive benchmark of 2,000 small-capitalization US companies.",
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
    if (!raw) return SUPPORTED_BROKERAGES[0]; // WeBank Smart Wealth default
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
