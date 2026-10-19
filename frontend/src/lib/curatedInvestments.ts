/**
 * Popular, whitelisted securities offered as one-tap picks on the trade desk.
 * Prices are never hard-coded here; the trade desk fetches a live quote for the selection.
 */

export interface CuratedAsset {
  symbol: string;
  name: string;
  icon: string;
}

export const POPULAR_CURATED_ASSETS: CuratedAsset[] = [
  { symbol: "SPY", name: "SPDR S&P 500 ETF", icon: "📈" },
  { symbol: "VTI", name: "Vanguard Total Stock Market ETF", icon: "🌐" },
  { symbol: "BND", name: "Vanguard Total Bond Market ETF", icon: "🛡️" },
  { symbol: "GLD", name: "SPDR Gold Shares", icon: "🥇" },
  { symbol: "AAPL", name: "Apple Inc.", icon: "🍎" },
  { symbol: "MSFT", name: "Microsoft Corp.", icon: "💻" },
  { symbol: "NVDA", name: "NVIDIA Corp.", icon: "🟩" },
  { symbol: "IBIT", name: "iShares Bitcoin Trust ETF", icon: "₿" },
];

export const PRESET_DOLLAR_AMOUNTS = [50, 100, 250, 500, 1000, 2500];
