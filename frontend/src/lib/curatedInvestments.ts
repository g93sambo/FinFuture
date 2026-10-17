/**
 * Curated investment choices and thematic baskets for intuitive,
 * beginner-friendly investing without requiring financial jargon or ticker memorization.
 */

export interface CuratedAsset {
  symbol: string;
  name: string;
  category: "Tech & AI" | "Core Index" | "Cash & Yield" | "Asia Growth" | "Digital Asset" | "Bonds";
  icon: string;
  refPrice: number;
  oneLiner: string;
  risk: "Low" | "Moderate" | "Growth";
  highlight?: string;
}

export interface CuratedBasket {
  id: string;
  title: string;
  subtitle: string;
  icon: string;
  risk: "Low" | "Moderate" | "Growth";
  primarySymbol: string;
  symbols: string[];
  refPrice: number;
  badge: string;
  description: string;
  recommendedDollar: number;
}

export const POPULAR_CURATED_ASSETS: CuratedAsset[] = [
  {
    symbol: "AAPL",
    name: "Apple Inc.",
    category: "Tech & AI",
    icon: "🍎",
    refPrice: 343.46,
    oneLiner: "Consumer tech leader, iPhone & global Apple ecosystem",
    risk: "Growth",
    highlight: "Household Favorite",
  },
  {
    symbol: "NVDA",
    name: "NVIDIA Corp.",
    category: "Tech & AI",
    icon: "🧠",
    refPrice: 125.40,
    oneLiner: "Global AI chips and GPU computing architecture",
    risk: "Growth",
    highlight: "AI Frontier",
  },
  {
    symbol: "MSFT",
    name: "Microsoft Corp.",
    category: "Tech & AI",
    icon: "💻",
    refPrice: 428.15,
    oneLiner: "Enterprise cloud, Windows & enterprise AI platform",
    risk: "Growth",
  },
  {
    symbol: "TSLA",
    name: "Tesla Inc.",
    category: "Tech & AI",
    icon: "⚡",
    refPrice: 218.50,
    oneLiner: "Autonomous driving, electric vehicles & energy storage",
    risk: "Growth",
  },
  {
    symbol: "AMZN",
    name: "Amazon.com Inc.",
    category: "Tech & AI",
    icon: "📦",
    refPrice: 186.20,
    oneLiner: "World's largest e-commerce & AWS cloud infrastructure",
    risk: "Growth",
  },
  {
    symbol: "GOOGL",
    name: "Alphabet / Google",
    category: "Tech & AI",
    icon: "🔍",
    refPrice: 168.30,
    oneLiner: "Search engine, Android, YouTube & DeepMind AI models",
    risk: "Growth",
  },
  {
    symbol: "SPY",
    name: "S&P 500 Index Fund",
    category: "Core Index",
    icon: "📊",
    refPrice: 575.20,
    oneLiner: "Top 500 biggest and most profitable companies in the US",
    risk: "Moderate",
    highlight: "Best for Beginners",
  },
  {
    symbol: "WBKCASH",
    name: "WeBank Smart Cash Yield",
    category: "Cash & Yield",
    icon: "🏦",
    refPrice: 1.00,
    oneLiner: "3.8% APY liquid institutional cash yield with zero volatility",
    risk: "Low",
    highlight: "Capital Protected",
  },
  {
    symbol: "BND",
    name: "Vanguard Total Bond Market",
    category: "Bonds",
    icon: "🛡️",
    refPrice: 72.80,
    oneLiner: "Diversified US government and high-grade corporate bonds",
    risk: "Low",
  },
  {
    symbol: "ASHR",
    name: "Xtrackers Harvest CSI 300",
    category: "Asia Growth",
    icon: "🇨🇳",
    refPrice: 28.40,
    oneLiner: "Direct China A-Shares blue-chip equity market exposure",
    risk: "Growth",
    highlight: "Asia Expansion",
  },
  {
    symbol: "2800.HK",
    name: "Tracker Fund of Hong Kong",
    category: "Asia Growth",
    icon: "🇭🇰",
    refPrice: 19.20,
    oneLiner: "Hong Kong Hang Seng top 50 flagship blue-chip enterprises",
    risk: "Moderate",
  },
  {
    symbol: "IBIT",
    name: "iShares Bitcoin Trust",
    category: "Digital Asset",
    icon: "🪙",
    refPrice: 38.50,
    oneLiner: "BlackRock SEC-registered spot Bitcoin ETF with cold custody",
    risk: "Growth",
    highlight: "Regulated Crypto",
  },
];

export const CURATED_BASKETS: CuratedBasket[] = [
  {
    id: "tech-titans",
    title: "Tech Titans & AI Leaders",
    subtitle: "Apple, NVIDIA, Microsoft, Google",
    icon: "🚀",
    risk: "Growth",
    primarySymbol: "AAPL",
    symbols: ["AAPL", "NVDA", "MSFT", "GOOGL"],
    refPrice: 343.46,
    badge: "High Growth",
    description: "Invest directly in the frontier tech giants transforming artificial intelligence and global productivity.",
    recommendedDollar: 250,
  },
  {
    id: "all-weather",
    title: "All-Weather Safe Growth",
    subtitle: "S&P 500 Index + Bond Defense",
    icon: "🛡️",
    risk: "Moderate",
    primarySymbol: "SPY",
    symbols: ["SPY", "BND", "WBKCASH"],
    refPrice: 575.20,
    badge: "Low Stress",
    description: "Ray Dalio inspired portfolio foundation balancing equity upside with bond and cash risk dampening.",
    recommendedDollar: 100,
  },
  {
    id: "safe-yield",
    title: "100% Safe Daily Interest",
    subtitle: "WeBank Smart Cash + Short-Term Bills",
    icon: "🏦",
    risk: "Low",
    primarySymbol: "WBKCASH",
    symbols: ["WBKCASH", "BND"],
    refPrice: 1.00,
    badge: "3.8% APY",
    description: "Zero market drops. Institutional-grade yield with daily compounding and instant same-day liquidity.",
    recommendedDollar: 500,
  },
  {
    id: "asia-expansion",
    title: "Asia & China Growth Engine",
    subtitle: "CSI 300 + Hang Seng Blue Chips",
    icon: "🌏",
    risk: "Growth",
    primarySymbol: "ASHR",
    symbols: ["ASHR", "2800.HK"],
    refPrice: 28.40,
    badge: "Global Reach",
    description: "Capture the multi-decade compounding of Asian domestic consumption and high-tech manufacturing.",
    recommendedDollar: 100,
  },
];

export const PRESET_DOLLAR_AMOUNTS = [50, 100, 250, 500, 1000, 2500];

export function getAssetRefPrice(symbol: string): number {
  const found = POPULAR_CURATED_ASSETS.find((a) => a.symbol.toUpperCase() === symbol.toUpperCase());
  if (found) return found.refPrice;
  const defaults: Record<string, number> = {
    SPY: 575.20,
    AAPL: 343.46,
    MSFT: 428.15,
    NVDA: 125.40,
    GOOGL: 168.30,
    AMZN: 186.20,
    TSLA: 218.50,
    BND: 72.80,
    BTC: 64200.0,
    IBIT: 38.50,
    WBKCASH: 1.00,
    ASHR: 28.40,
    "2800.HK": 19.20,
  };
  return defaults[symbol.toUpperCase()] ?? 100.0;
}
