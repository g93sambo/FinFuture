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
  const normalized = (brokerId || "webank").toLowerCase().replace(/[^a-z0-9]/g, "");

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

  if (normalized.includes("alpaca")) {
    const alpacaUrl = orderId
      ? `https://app.alpaca.markets/paper/dashboard/orders`
      : `https://app.alpaca.markets/paper/dashboard/orders`;
    return {
      brokerId: "alpaca",
      brokerName: "Alpaca Securities LLC",
      shortName: "Alpaca",
      icon: "🦙",
      portalName: "Alpaca Trading Dashboard (Paper & Live Gateway)",
      portalUrl: alpacaUrl,
      mobileAppPath: "Alpaca Web Dashboard → Paper Trading → Orders Tab",
      clearingHouse: "Alpaca Securities LLC / DTC Participant #3848",
      settlementCycle: "T+1 Delivery-versus-Payment (SEC Rule 15c6-1)",
      auditLedgerType: "Direct FIX/REST API Order Acknowledgment Record",
      verificationSteps: [
        "Log in to your Alpaca account at app.alpaca.markets.",
        "Toggle to 'Paper Trading' (or 'Live Trading' depending on mode) in the top-left switcher.",
        "Click 'Orders' in the left sidebar navigation.",
        `Locate order ID ${orderId ? `"${orderId}"` : "matching your trade timestamp"} under the 'Filled' or 'Accepted' tab.`,
        "Inspect the execution average price, filled quantity, and exchange routing.",
      ],
    };
  }

  if (normalized.includes("ibkr") || normalized.includes("interactive")) {
    return {
      brokerId: "ibkr",
      brokerName: "Interactive Brokers (IBKR)",
      shortName: "IBKR",
      icon: "🌐",
      portalName: "IBKR Client Portal & Trader Workstation (TWS)",
      portalUrl: "https://www.interactivebrokers.com/portal/",
      mobileAppPath: "IBKR Mobile App → Trade → Orders & Trades → Executed Trades",
      clearingHouse: "Interactive Brokers LLC (DTC #0534, NYSE/NASDAQ Member)",
      settlementCycle: "T+1 Continuous Net Settlement (CNS)",
      auditLedgerType: "IBKR Flex Query & FIX Gateway Execution Slip",
      verificationSteps: [
        "Log in to IBKR Client Portal or launch IBKR Mobile.",
        "Click or tap 'Trade' at the top, then select 'Orders & Trades'.",
        "Switch to the 'Trades' tab to view all filled market transactions.",
        "Check your Activity Statement under 'Reports' for end-of-day trade confirmation slips.",
      ],
    };
  }

  if (normalized.includes("schwab")) {
    return {
      brokerId: "schwab",
      brokerName: "Charles Schwab & Co.",
      shortName: "Schwab",
      icon: "🏛️",
      portalName: "Schwab.com & ThinkorSwim Web Platform",
      portalUrl: "https://client.schwab.com/app/trade/tom/#/tradehistory",
      mobileAppPath: "Schwab Mobile → Accounts → History → Order Status",
      clearingHouse: "Charles Schwab & Co., Inc. (DTC #0164, SIPC Insured)",
      settlementCycle: "T+1 Standard US Equity Settlement",
      auditLedgerType: "Schwab Institutional Custody Ledger",
      verificationSteps: [
        "Log in to your Charles Schwab account at schwab.com.",
        "Go to 'Accounts' → 'History' in the top menu.",
        "Filter by 'Orders' or 'Trades' to view the execution timestamp and fill price.",
        "View official Schwab Trade Confirmation PDF under 'Statements'.",
      ],
    };
  }

  if (normalized.includes("robinhood")) {
    return {
      brokerId: "robinhood",
      brokerName: "Robinhood Financial LLC",
      shortName: "Robinhood",
      icon: "🏹",
      portalName: "Robinhood Web & Mobile Application",
      portalUrl: "https://robinhood.com/account/history",
      mobileAppPath: "Robinhood App → Profile Icon → History → Orders",
      clearingHouse: "Robinhood Securities, LLC (DTC #3856)",
      settlementCycle: "T+1 Standard Settlement",
      auditLedgerType: "Robinhood Clearing House Execution Log",
      verificationSteps: [
        "Open the Robinhood App or visit robinhood.com/account/history.",
        "Navigate to your Account Profile and select 'History'.",
        "Tap the stock order to view the full Order Detail receipt (limit/market price, shares, date).",
      ],
    };
  }

  if (normalized.includes("fidelity")) {
    return {
      brokerId: "fidelity",
      brokerName: "Fidelity Investments",
      shortName: "Fidelity",
      icon: "🌲",
      portalName: "Fidelity.com Account Portal",
      portalUrl: "https://www.fidelity.com",
      mobileAppPath: "Fidelity App → Activity & Orders → History",
      clearingHouse: "National Financial Services LLC (NFS, DTC #0226)",
      settlementCycle: "T+1 Standard Settlement",
      auditLedgerType: "Fidelity NFS Institutional Clearing Slip",
      verificationSteps: [
        "Log in to fidelity.com or open the Fidelity mobile app.",
        "Click 'Activity & Orders' from the top navigation bar.",
        "Review your recent orders under the 'History' tab.",
      ],
    };
  }

  if (normalized.includes("bamboo")) {
    return {
      brokerId: "bamboo",
      brokerName: "Bamboo Global Wealth",
      shortName: "Bamboo",
      icon: "🎋",
      portalName: "Bamboo Mobile Investment App",
      portalUrl: "https://investbamboo.com",
      mobileAppPath: "Bamboo App → Portfolio → Transaction History",
      clearingHouse: "DriveWealth LLC (DTC #3854) via Bamboo API",
      settlementCycle: "T+1 US Settlement / Instant In-App FX",
      auditLedgerType: "Bamboo Apex/DriveWealth Omnibus Custody Log",
      verificationSteps: [
        "Open your Bamboo app on iOS or Android.",
        "Navigate to your Portfolio and tap 'Transactions History'.",
        "Select the order to view the DriveWealth partner confirmation slip.",
      ],
    };
  }

  // Generic fallback for other custodians (Futu, Tiger, Coinbase, Vanguard)
  return {
    brokerId: brokerId,
    brokerName: "Connected Brokerage Custodian",
    shortName: brokerId.toUpperCase(),
    icon: "📈",
    portalName: "Custodian Online Web Portal & Trading App",
    portalUrl: "https://www.google.com/search?q=" + encodeURIComponent(`${brokerId} login order history`),
    mobileAppPath: "Brokerage App → Account / Portfolio → Trade History & Order Records",
    clearingHouse: "Licensed Custodian Clearing Depository (DTC / CSD)",
    settlementCycle: "Standard Equity Settlement (T+1)",
    auditLedgerType: "Cryptographically Verified Broker API Acknowledgment",
    verificationSteps: [
      `Open your ${brokerId} mobile application or web portal.`,
      "Navigate to your Account, Portfolio, or Trade History section.",
      "Look for recent orders matching this trade timestamp and symbol.",
      "Verify the executed quantity, price, and settlement confirmation slip.",
    ],
  };
}
