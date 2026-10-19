"""
backend/tools/definitions/price_projection.py
=============================================
PriceProjectionTool (project_price_range): a volatility-based price range for a stock, ETF,
commodity, currency pair or crypto asset over a short horizon, computed from real daily closes.

It is a statistical range, not a directional forecast: the centre is the latest price (no drift is
assumed over a few days), and the bands come from recent realised volatility, cross-checked against
the asset's own historical moves over the same horizon.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

try:
    from agents.market_data import MarketDataAgent
    from tools.base import BaseTool, ToolCategory, ToolResult
except ImportError:
    from backend.agents.market_data import MarketDataAgent
    from backend.tools.base import BaseTool, ToolCategory, ToolResult

# Common names for non-equity assets -> Yahoo Finance tickers with daily history
SYMBOL_ALIASES: Dict[str, tuple] = {
    "XAUUSD": ("GC=F", "Gold (COMEX gold futures, tracks spot XAU/USD)"),
    "XAU": ("GC=F", "Gold (COMEX gold futures, tracks spot XAU/USD)"),
    "GOLD": ("GC=F", "Gold (COMEX gold futures, tracks spot XAU/USD)"),
    "XAGUSD": ("SI=F", "Silver (COMEX silver futures, tracks spot XAG/USD)"),
    "SILVER": ("SI=F", "Silver (COMEX silver futures, tracks spot XAG/USD)"),
    "WTI": ("CL=F", "WTI crude oil futures"),
    "OIL": ("CL=F", "WTI crude oil futures"),
    "BRENT": ("BZ=F", "Brent crude oil futures"),
    "EURUSD": ("EURUSD=X", "EUR/USD"),
    "GBPUSD": ("GBPUSD=X", "GBP/USD"),
    "USDJPY": ("JPY=X", "USD/JPY"),
    "AUDUSD": ("AUDUSD=X", "AUD/USD"),
    "USDCAD": ("CAD=X", "USD/CAD"),
    "BTC": ("BTC-USD", "Bitcoin (USD)"),
    "BTCUSD": ("BTC-USD", "Bitcoin (USD)"),
    "ETH": ("ETH-USD", "Ether (USD)"),
    "ETHUSD": ("ETH-USD", "Ether (USD)"),
}
SEVEN_DAY_MARKETS = ("-USD",)  # crypto trades every day


def resolve_symbol(raw: str) -> tuple:
    key = raw.strip().upper().replace("/", "").replace(" ", "")
    if key in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[key]
    return key, key


def _pct(a: float, b: float) -> float:
    return round((a / b - 1.0) * 100.0, 2)


def compute_projection(closes: List[float], horizon_days: int) -> Dict[str, Any]:
    """Pure maths on a chronological list of daily closes (needs ~60+ points)."""
    if len(closes) < 30:
        raise ValueError("Not enough price history to estimate volatility (need at least 30 daily closes).")
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]

    def stdev(xs: List[float]) -> float:
        m = sum(xs) / len(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

    vol_20 = stdev(rets[-20:])
    vol_60 = stdev(rets[-60:]) if len(rets) >= 60 else vol_20
    sigma = 0.5 * vol_20 + 0.5 * vol_60  # blend: reacts to recent moves without overreacting
    last = closes[-1]
    h = max(1, horizon_days)
    band = sigma * math.sqrt(h)

    def bound(z: float) -> float:
        return round(last * math.exp(z * band), 4)

    # Cross-check with the asset's own historical moves over the same horizon
    moves = sorted(closes[i] / closes[i - h] - 1.0 for i in range(h, len(closes)))

    def q(p: float) -> float:
        idx = min(len(moves) - 1, max(0, int(round(p * (len(moves) - 1)))))
        return moves[idx]

    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else sma20
    trend = "uptrend" if last > sma20 > sma50 else "downtrend" if last < sma20 < sma50 else "sideways / mixed"

    return {
        "last_price": round(last, 4),
        "horizon_trading_days": h,
        "annualised_volatility_pct": round(sigma * math.sqrt(252) * 100, 2),
        "daily_volatility_20d_pct": round(vol_20 * 100, 3),
        "daily_volatility_60d_pct": round(vol_60 * 100, 3),
        "expected_move_1sd_pct": round((math.exp(band) - 1) * 100, 2),
        "range_68pct": {"low": bound(-1.0), "high": bound(1.0)},
        "range_95pct": {"low": bound(-1.96), "high": bound(1.96)},
        "historical_same_horizon_moves_pct": {
            "p5": round(q(0.05) * 100, 2),
            "median": round(q(0.5) * 100, 2),
            "p95": round(q(0.95) * 100, 2),
            "observations": len(moves),
        },
        "trend": {
            "label": trend,
            "sma20": round(sma20, 4),
            "sma50": round(sma50, 4),
            "change_5d_pct": _pct(last, closes[-6]) if len(closes) > 6 else None,
            "change_20d_pct": _pct(last, closes[-21]) if len(closes) > 21 else None,
        },
        "method": (
            "Centre = latest close (no drift assumed over the horizon). Bands = latest close x exp(+/- z x sigma x sqrt(days)), "
            "sigma = average of 20- and 60-day daily log-return volatility. Cross-checked against the 5th/50th/95th percentile "
            "of the asset's own moves over the same number of days in the past year. A statistical range, not a prediction."
        ),
    }


class PriceProjectionArgs(BaseModel):
    symbol: str = Field(
        ...,
        min_length=1,
        description="Ticker or asset name, e.g. 'XAUUSD' (gold), 'GLD', 'SPY', 'AAPL', 'EURUSD', 'BTC', 'WTI'",
    )
    horizon_days: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Horizon in trading days: 1 = tomorrow, 5 = one week (crypto: 7), 21 = one month",
    )

    @field_validator("symbol")
    @classmethod
    def strip_symbol(cls, v: str) -> str:
        return v.strip()


class PriceProjectionTool(BaseTool):
    name: str = "project_price_range"
    description: str = (
        "Project a statistical price range for any stock, ETF, commodity (gold XAUUSD, silver, oil), currency pair "
        "or crypto over the next N trading days, from real daily prices: last price, 68% and 95% ranges, expected move, "
        "volatility, recent trend and the asset's historical moves over the same horizon."
    )
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = PriceProjectionArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Macro & Market Analyst",
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]
    cache_ttl: int = 900

    def __init__(self, market_agent: Optional[MarketDataAgent] = None):
        self._market = market_agent or MarketDataAgent()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            if args and isinstance(args[0], PriceProjectionArgs):
                parsed = args[0]
            elif args and isinstance(args[0], dict):
                parsed = PriceProjectionArgs(**args[0])
            else:
                parsed = PriceProjectionArgs(**{k: v for k, v in kwargs.items() if k not in ("context", "self")})

            ticker, label = resolve_symbol(parsed.symbol)
            df = await self._market.get_history([ticker], period="1y")
            series = (df[ticker] if ticker in df.columns else df.iloc[:, 0]).dropna()
            closes = [float(v) for v in series.tolist()]
            data = compute_projection(closes, parsed.horizon_days)
            data.update({
                "requested_symbol": parsed.symbol.upper(),
                "data_symbol": ticker,
                "asset": label,
                "as_of": series.index[-1].strftime("%Y-%m-%d"),
                "source": "Yahoo Finance daily closes (1 year)",
                "trades_every_day": ticker.endswith(SEVEN_DAY_MARKETS),
            })
            return ToolResult(tool_name=self.name, success=True, data=data,
                              execution_time_ms=round((time.perf_counter() - start_time) * 1000.0, 2))
        except Exception as exc:
            return ToolResult(tool_name=self.name, success=False, error=f"Could not project a range for this symbol: {exc}",
                              execution_time_ms=round((time.perf_counter() - start_time) * 1000.0, 2))
