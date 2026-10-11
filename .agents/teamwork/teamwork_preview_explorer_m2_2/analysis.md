# Analysis Report: Milestone 2 Data Layer Providers & Offline Fixtures

**Author**: Explorer 2 (Milestone 2 - Data Layer)  
**Date**: 2026-10-10  
**Target Modules**: `backend/services/providers/` (`equities.py`, `treasury.py`, `macro.py`, `etf_holdings.py`, `screener.py`)  
**Target Fixtures**: `backend/tests/fixtures/` (`market_quotes.json`, `historical_prices.json`, `yield_curve.json`, `macro_indicators.json`, `etf_holdings.json`)

---

## 1. Executive Summary

Milestone 2 establishes the financial data backbone for the Wealth Advisory Agent. The system requires accurate, low-latency market data for:
1. Real-time quotes and historical price trajectories for portfolio optimization (`skfolio` CVaR MeanRisk).
2. Treasury yield curves for fixed-income duration matching and term-structure analysis.
3. Macroeconomic indicators (CPI, unemployment rate, federal funds rate) for macroeconomic context and regime awareness.
4. ETF top holdings and sector weights for product comparison and concentration risk analysis (`CONC-001..003`).
5. Asset universe screening to filter suitable investment candidates for client risk profiles.

To satisfy the zero-external-dependency requirement (`python main.py starts with no Docker, Redis or Postgres`) and ensure 100% deterministic, offline test execution, all providers implement a **two-tier architecture**:
- **Live Tier**: Asynchronous external queries (via `yfinance` in thread workers, US Treasury FiscalData REST API, and FRED/CalcFi HTTP APIs).
- **Recorded Fixture Tier**: Seamless, automatic fallback to recorded JSON fixtures located in `backend/tests/fixtures/` when upstream APIs fail, rate-limit (HTTP 429), circuit breaker trips, or `offline_mode=True`.

---

## 2. Architecture & Provider Specifications

```
                     ┌────────────────────────────────────────┐
                     │          MarketDataAgent (M2_3)        │
                     │  (Cache Layer: Redis / InMemoryCache)  │
                     └───────────────────┬────────────────────┘
                                         │ calls
                     ┌───────────────────┴────────────────────┐
                     │          Data Providers (M2_2)         │
                     └─┬─────────┬──────────┬──────────┬────┬─┘
                       │         │          │          │    │
       ┌───────────────┘         │          │          │    └──────────────┐
       ▼                         ▼          ▼          ▼                   ▼
┌───────────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────────┐ ┌────────────────┐
│   equities    │ │   treasury   │ │  macro   │ │ etf_holdings │ │    screener    │
└───────┬───────┘ └──────┬───────┘ └────┬─────┘ └──────┬───────┘ └───────┬────────┘
        │                │              │              │                 │
 ┌──────┴──────┐  ┌──────┴──────┐ ┌─────┴────┐  ┌──────┴──────┐   ┌──────┴──────┐
 │ yfinance /  │  │ FiscalData  │ │  FRED /  │  │  yfinance   │   │ Predefined  │
 │ thread exec │  │  REST API   │ │  CalcFi  │  │ funds_data  │   │  Universe   │
 └──────┬──────┘  └──────┬──────┘ └─────┬────┘  └──────┬──────┘   └──────┬──────┘
        │                │              │              │                 │
        ▼ (fallback)     ▼ (fallback)   ▼ (fallback)   ▼ (fallback)      ▼ (fallback)
┌───────────────────────────────────────────────────────────────────────────────┐
│                       Recorded Fixtures (backend/tests/fixtures/)             │
│   market_quotes.json | historical_prices.json | yield_curve.json             │
│              macro_indicators.json | etf_holdings.json                        │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

### 2.1. Equities Provider (`backend/services/providers/equities.py`)

#### Design Rationale & Mechanics
- **`yfinance` Thread Safety**: `yfinance` is inherently synchronous and relies on blocking network I/O (`urllib3`/`requests`). Calling it directly inside async FastAPI routes blocks the event loop. Therefore, all `yfinance` calls must be offloaded via `asyncio.to_thread` (Python 3.9+) or `loop.run_in_executor(None, ...)`.
- **Fast Quote Extraction**: `yf.Ticker(symbol).fast_info` provides low-overhead quote data (`last_price`, `previous_close`, `open`, `day_high`, `day_low`, `last_volume`). If any field is missing or None, fallback to `ticker.history(period="2d")` and inspect the last row.
- **Historical Prices Structure**: Must return a `pandas.DataFrame` where:
  - `df.index` is a UTC `DatetimeIndex` named `"Date"`.
  - Columns are uppercase asset tickers (`["SPY", "BND", "AGG", "VTI", "VXUS", "GLD"]`).
  - Values are daily adjusted closing prices (`float64`).
  - No missing values (`dropna()` or forward fill) to ensure immediate compatibility with `skfolio.preprocessing.prices_to_returns()`.

#### Class Specification
```python
class EquitiesProvider:
    """
    Asynchronous equities and ETF market data provider.
    Integrates yfinance with thread pool execution and local fixture fallback.
    """
    def __init__(self, offline_mode: bool = False, fixtures_dir: Optional[Path] = None):
        self.offline_mode = offline_mode
        self.fixtures_dir = fixtures_dir or (Path(__file__).parents[2] / "tests" / "fixtures")
        self._quotes_fixture: Optional[Dict[str, Any]] = None
        self._history_fixture: Optional[Dict[str, Any]] = None

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch live or fixture quote for a single symbol.
        Returns unified dictionary compatible with MarketDataPoint.
        """
        sym = symbol.upper().strip()
        if not self.offline_mode:
            try:
                return await asyncio.to_thread(self._fetch_yfinance_quote, sym)
            except Exception as exc:
                logger.warning(f"Live quote fetch failed for {sym}: {exc}. Falling back to fixture.")
        
        return self._get_quote_from_fixture(sym)

    async def get_historical_prices(
        self,
        symbols: List[str],
        period: str = "1y",
        interval: str = "1d"
    ) -> pd.DataFrame:
        """
        Fetch historical daily closing prices as a pandas DataFrame.
        Columns: symbols, Index: DatetimeIndex (Date).
        """
        normalized_symbols = [s.upper().strip() for s in symbols]
        if not self.offline_mode:
            try:
                df = await asyncio.to_thread(
                    self._fetch_yfinance_history, normalized_symbols, period, interval
                )
                if df is not None and not df.empty and len(df) >= 30:
                    return df
            except Exception as exc:
                logger.warning(f"Live history fetch failed for {symbols}: {exc}. Falling back to fixture.")

        return self._get_history_from_fixture(normalized_symbols)
```

---

### 2.2. Treasury Provider (`backend/services/providers/treasury.py`)

#### Design Rationale & Mechanics
- **US Treasury FiscalData API**:
  - Endpoint: `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates?sort=-record_date&page[size]=100`
  - Open API, no authentication token required.
  - Returns rates across bills, notes, and bonds.
- **Canonical Maturities**:
  - Standard Treasury curve terms: `["1M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]`.
- **Inversion Metrics**:
  - `spread_10y_2y = yield_10y - yield_2y`: Key indicator for yield curve inversion and recessionary regimes.
  - `spread_10y_3m = yield_10y - yield_3m`: Fed's preferred recession probability metric.
- **Fallback**:
  - If network request times out, fails, or returns status code != 200, load `backend/tests/fixtures/yield_curve.json`.

#### Class Specification
```python
class TreasuryProvider:
    """
    US Treasury yield curve provider querying FiscalData REST API with offline fixture fallback.
    """
    FISCAL_DATA_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates"

    def __init__(self, offline_mode: bool = False, fixtures_dir: Optional[Path] = None, http_client: Optional[httpx.AsyncClient] = None):
        self.offline_mode = offline_mode
        self.fixtures_dir = fixtures_dir or (Path(__file__).parents[2] / "tests" / "fixtures")
        self._client = http_client

    async def get_yield_curve(self) -> Dict[str, float]:
        """
        Returns dictionary mapping maturity strings to percentage yields:
        {"1M": 5.48, "2M": 5.45, "3M": 5.42, "6M": 5.35, "1Y": 5.15, "2Y": 4.90, "3Y": 4.70, "5Y": 4.52, "7Y": 4.50, "10Y": 4.50, "20Y": 4.72, "30Y": 4.60}
        """
        details = await self.get_yield_curve_details()
        return details.get("rates", {})

    async def get_yield_curve_details(self) -> Dict[str, Any]:
        """
        Returns full yield curve structure including record_date, rates, and inversion metrics.
        """
        if not self.offline_mode:
            try:
                return await self._fetch_live_yield_curve()
            except Exception as exc:
                logger.warning(f"Live Treasury yield curve query failed: {exc}. Falling back to fixture.")
        
        return self._get_yield_curve_from_fixture()
```

---

### 2.3. Macro Provider (`backend/services/providers/macro.py`)

#### Design Rationale & Mechanics
- **Multi-Source Strategy**:
  1. **FRED API (St. Louis Fed)**: If `settings.fred_api_key` (or env `FRED_API_KEY`) is set, queries series:
     - `CPIAUCSL`: Consumer Price Index for All Urban Consumers.
     - `UNRATE`: Civilian Unemployment Rate.
     - `FEDFUNDS`: Federal Funds Effective Rate.
  2. **CalcFi Open Data / CSV**: If FRED is unconfigured, queries open CalcFi public macroeconomic summary.
  3. **Offline Fixture**: If unconfigured or offline, immediately loads `backend/tests/fixtures/macro_indicators.json`.
- **Target Indicators**:
  - `cpi`: 3.48 (YoY inflation rate)
  - `unemployment_rate`: 3.9 (percentage)
  - `fed_funds_rate`: 5.33 (percentage)
  - Optional: `gdp_growth_rate`, `treasury_10y_yield`, `yield_spread_10y_2y`.

#### Class Specification
```python
class MacroProvider:
    """
    Macroeconomic indicators provider querying FRED API, CalcFi open data, or local fixture.
    """
    FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, fred_api_key: Optional[str] = None, offline_mode: bool = False, fixtures_dir: Optional[Path] = None):
        self.fred_api_key = fred_api_key or os.getenv("FRED_API_KEY")
        self.offline_mode = offline_mode
        self.fixtures_dir = fixtures_dir or (Path(__file__).parents[2] / "tests" / "fixtures")

    async def get_macro_indicators(self) -> Dict[str, float]:
        """
        Returns core macroeconomic indicators:
        {"cpi": 3.48, "unemployment_rate": 3.9, "fed_funds_rate": 5.33}
        """
        details = await self.get_macro_context()
        return details.get("indicators", {})

    async def get_macro_context(self) -> Dict[str, Any]:
        """
        Returns full macroeconomic context, including indicators, metadata, and regime summary.
        """
        if not self.offline_mode and self.fred_api_key:
            try:
                return await self._fetch_fred_indicators()
            except Exception as exc:
                logger.warning(f"FRED API query failed: {exc}. Falling back to fixture.")

        return self._get_macro_from_fixture()
```

---

### 2.4. ETF Holdings Provider (`backend/services/providers/etf_holdings.py`)

#### Design Rationale & Mechanics
- **Product Comparison & Concentration Guard**: The system must evaluate ETF holdings and sector allocations to prevent portfolio over-concentration (`CONC-001` single asset > 30%, `CONC-002` single sector > 40%).
- **Live Query**: Calls `yf.Ticker(symbol).funds_data` in thread worker to extract top holdings, sector weightings, and asset class.
- **Bond Specifics**: For bond ETFs (e.g. `BND`, `AGG`), extracts credit quality distribution (AAA, AA, A, BBB) and effective duration.
- **Offline Fallback**: Loads `backend/tests/fixtures/etf_holdings.json` containing detailed holding profiles for core ETFs (`SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`).

#### Class Specification
```python
class ETFHoldingsProvider:
    """
    Provider for ETF fund holdings, sector weightings, and fixed income profiles.
    """
    def __init__(self, offline_mode: bool = False, fixtures_dir: Optional[Path] = None):
        self.offline_mode = offline_mode
        self.fixtures_dir = fixtures_dir or (Path(__file__).parents[2] / "tests" / "fixtures")

    async def get_holdings(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch top holdings and sector weights for an ETF.
        Returns:
        {
            "symbol": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "asset_class": "Equity",
            "expense_ratio": 0.0009,
            "top_holdings": [{"symbol": "MSFT", "weight": 0.071}, ...],
            "sector_weights": {"Technology": 0.298, ...},
            "source": "yfinance" | "fixture"
        }
        """
        sym = symbol.upper().strip()
        if not self.offline_mode:
            try:
                data = await asyncio.to_thread(self._fetch_yfinance_holdings, sym)
                if data:
                    return data
            except Exception as exc:
                logger.warning(f"yfinance holdings query failed for {sym}: {exc}. Falling back to fixture.")

        return self._get_holdings_from_fixture(sym)
```

---

### 2.5. Asset Screener Provider (`backend/services/providers/screener.py`)

#### Design Rationale & Mechanics
- **Asset Universe**: Predefined, vetted universe of liquid ETFs and fixed-income assets spanning equities, aggregate bonds, corporate credit, short/intermediate/long Treasuries, inflation-protected securities, and commodities.
- **Product Comparison Agent (`agents/product_comparison.py`) Support**: Enables filtering and scoring across 6 factors:
  $w = [0.30 \text{ Sharpe/Returns}, 0.15 \text{ Expense Ratio}, 0.20 \text{ Max Drawdown}, 0.10 \text{ Liquidity/AUM}, 0.15 \text{ Duration Match}, 0.10 \text{ ESG/Rating}]$.
- **Suitability Matching**: Pre-filters candidates by client investment horizon and risk tolerance score (1-10).

#### Model & Class Specification
```python
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class AssetMetadata(BaseModel):
    symbol: str
    name: str
    asset_class: str                  # "equity", "fixed_income", "commodity", "real_estate"
    sub_category: str                 # "large_cap_blend", "total_bond", "emerging_market", etc.
    expense_ratio: float              # e.g. 0.0003 for 3 bps
    aum_billions: float               # e.g. 350.5
    yield_30d: float                  # e.g. 0.048 for 4.8%
    risk_level: int                   # 1 (Conservative) to 5 (Aggressive)
    duration: Optional[float] = None  # in years (for bonds)
    credit_rating: Optional[str] = None # e.g. "AAA", "A"
    suitable_horizons: List[str]      # ["SHORT", "MEDIUM", "LONG"]

class AssetScreenerProvider:
    """
    Asset universe querying and screening provider.
    """
    def __init__(self, universe: Optional[List[AssetMetadata]] = None):
        self._universe: Dict[str, AssetMetadata] = {
            item.symbol: item for item in (universe or self._load_default_universe())
        }

    def screen(
        self,
        asset_class: Optional[str] = None,
        max_expense_ratio: Optional[float] = None,
        min_yield: Optional[float] = None,
        min_aum: Optional[float] = None,
        max_risk_level: Optional[int] = None,
        horizon: Optional[str] = None
    ) -> List[AssetMetadata]:
        results = list(self._universe.values())
        if asset_class:
            results = [a for a in results if a.asset_class.lower() == asset_class.lower()]
        if max_expense_ratio is not None:
            results = [a for a in results if a.expense_ratio <= max_expense_ratio]
        if min_yield is not None:
            results = [a for a in results if a.yield_30d >= min_yield]
        if min_aum is not None:
            results = [a for a in results if a.aum_billions >= min_aum]
        if max_risk_level is not None:
            results = [a for a in results if a.risk_level <= max_risk_level]
        if horizon:
            results = [a for a in results if horizon.upper() in a.suitable_horizons]
        return results

    def get_by_symbol(self, symbol: str) -> Optional[AssetMetadata]:
        return self._universe.get(symbol.upper().strip())
```

---

## 3. Offline Recorded Fixtures Specification (`backend/tests/fixtures/`)

To guarantee reproducible test execution and offline startup, exactly five JSON fixture files must be placed in `backend/tests/fixtures/`.

### 3.1. `market_quotes.json`
- **Location**: `backend/tests/fixtures/market_quotes.json`
- **Schema & Core Symbols**:
```json
{
  "SPY": {
    "symbol": "SPY",
    "name": "SPDR S&P 500 ETF Trust",
    "price": 510.50,
    "change": 2.45,
    "change_percent": 0.48,
    "open": 508.80,
    "high": 511.20,
    "low": 507.95,
    "previous_close": 508.05,
    "volume": 68500000,
    "currency": "USD",
    "timestamp": "2024-04-12T20:00:00Z",
    "source": "offline_fixture"
  },
  "BND": {
    "symbol": "BND",
    "name": "Vanguard Total Bond Market ETF",
    "price": 72.30,
    "change": -0.15,
    "change_percent": -0.21,
    "open": 72.45,
    "high": 72.55,
    "low": 72.22,
    "previous_close": 72.45,
    "volume": 5200000,
    "currency": "USD",
    "timestamp": "2024-04-12T20:00:00Z",
    "source": "offline_fixture"
  },
  "AGG": {
    "symbol": "AGG",
    "name": "iShares Core U.S. Aggregate Bond ETF",
    "price": 98.15,
    "change": -0.20,
    "change_percent": -0.20,
    "open": 98.30,
    "high": 98.40,
    "low": 98.05,
    "previous_close": 98.35,
    "volume": 7100000,
    "currency": "USD",
    "timestamp": "2024-04-12T20:00:00Z",
    "source": "offline_fixture"
  },
  "VTI": {
    "symbol": "VTI",
    "name": "Vanguard Total Stock Market ETF",
    "price": 255.40,
    "change": 1.20,
    "change_percent": 0.47,
    "open": 254.50,
    "high": 255.90,
    "low": 254.10,
    "previous_close": 254.20,
    "volume": 3200000,
    "currency": "USD",
    "timestamp": "2024-04-12T20:00:00Z",
    "source": "offline_fixture"
  },
  "VXUS": {
    "symbol": "VXUS",
    "name": "Vanguard Total International Stock ETF",
    "price": 58.75,
    "change": 0.35,
    "change_percent": 0.60,
    "open": 58.50,
    "high": 58.90,
    "low": 58.35,
    "previous_close": 58.40,
    "volume": 2800000,
    "currency": "USD",
    "timestamp": "2024-04-12T20:00:00Z",
    "source": "offline_fixture"
  },
  "GLD": {
    "symbol": "GLD",
    "name": "SPDR Gold Shares",
    "price": 215.80,
    "change": 3.10,
    "change_percent": 1.46,
    "open": 213.50,
    "high": 216.40,
    "low": 213.10,
    "previous_close": 212.70,
    "volume": 8900000,
    "currency": "USD",
    "timestamp": "2024-04-12T20:00:00Z",
    "source": "offline_fixture"
  },
  "QQQ": {
    "symbol": "QQQ",
    "name": "Invesco QQQ Trust",
    "price": 438.20,
    "change": 2.80,
    "change_percent": 0.64,
    "open": 436.00,
    "high": 439.10,
    "low": 435.50,
    "previous_close": 435.40,
    "volume": 41200000,
    "currency": "USD",
    "timestamp": "2024-04-12T20:00:00Z",
    "source": "offline_fixture"
  }
}
```

---

### 3.2. `historical_prices.json`
- **Location**: `backend/tests/fixtures/historical_prices.json`
- **Format Requirements**:
  1. Contains exactly **252 business days** (full 1-year trading window from 2023-04-12 to 2024-03-28).
  2. Covers symbols: `["SPY", "BND", "AGG", "VTI", "VXUS", "GLD"]`.
  3. Mathematical conditioning: The price returns must be positive-definite and non-singular so `skfolio` MeanRisk convex solver (`CLARABEL`) converges without solver errors.
- **Structure**:
```json
{
  "metadata": {
    "period": "1y",
    "frequency": "1d",
    "start_date": "2023-04-12",
    "end_date": "2024-03-28",
    "total_records": 252,
    "symbols": ["SPY", "BND", "AGG", "VTI", "VXUS", "GLD"]
  },
  "records": [
    {
      "date": "2023-04-12",
      "SPY": 408.05,
      "BND": 73.12,
      "AGG": 99.45,
      "VTI": 204.10,
      "VXUS": 54.30,
      "GLD": 186.20
    },
    {
      "date": "2023-04-13",
      "SPY": 409.15,
      "BND": 73.08,
      "AGG": 99.40,
      "VTI": 204.65,
      "VXUS": 54.42,
      "GLD": 186.95
    }
    // ... 250 additional well-conditioned daily price points
  ]
}
```
- **Loading Snippet**:
```python
def load_historical_prices_dataframe(filepath: Path) -> pd.DataFrame:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data["records"]).set_index("date")
    df.index = pd.to_datetime(df.index)
    df = df.astype(float)
    return df
```

---

### 3.3. `yield_curve.json`
- **Location**: `backend/tests/fixtures/yield_curve.json`
- **Structure**:
```json
{
  "record_date": "2024-04-12",
  "source": "US_TREASURY_FISCAL_DATA",
  "rates": {
    "1M": 5.48,
    "2M": 5.45,
    "3M": 5.42,
    "4M": 5.38,
    "6M": 5.35,
    "1Y": 5.15,
    "2Y": 4.90,
    "3Y": 4.70,
    "5Y": 4.52,
    "7Y": 4.50,
    "10Y": 4.50,
    "20Y": 4.72,
    "30Y": 4.60
  },
  "metrics": {
    "spread_10y_2y": -0.40,
    "spread_10y_3m": -0.92,
    "inversion_detected": true,
    "curve_regime": "INVERTED"
  }
}
```

---

### 3.4. `macro_indicators.json`
- **Location**: `backend/tests/fixtures/macro_indicators.json`
- **Structure**:
```json
{
  "record_date": "2024-04-12",
  "source": "FRED_CALCFI_FIXTURE",
  "indicators": {
    "cpi": 3.48,
    "cpi_index": 312.332,
    "unemployment_rate": 3.9,
    "fed_funds_rate": 5.33,
    "gdp_growth_rate": 2.1,
    "treasury_10y_yield": 4.50,
    "treasury_2y_yield": 4.90,
    "yield_spread_10y_2y": -0.40
  },
  "trailing_history": [
    {"date": "2024-03", "cpi": 3.48, "unemployment_rate": 3.8, "fed_funds_rate": 5.33},
    {"date": "2024-02", "cpi": 3.15, "unemployment_rate": 3.9, "fed_funds_rate": 5.33},
    {"date": "2024-01", "cpi": 3.09, "unemployment_rate": 3.7, "fed_funds_rate": 5.33}
  ]
}
```

---

### 3.5. `etf_holdings.json`
- **Location**: `backend/tests/fixtures/etf_holdings.json`
- **Structure**:
```json
{
  "SPY": {
    "symbol": "SPY",
    "name": "SPDR S&P 500 ETF Trust",
    "asset_class": "Equity",
    "expense_ratio": 0.0009,
    "aum_billions": 505.2,
    "dividend_yield": 0.0135,
    "top_holdings": [
      {"symbol": "MSFT", "name": "Microsoft Corporation", "weight": 0.071},
      {"symbol": "AAPL", "name": "Apple Inc.", "weight": 0.058},
      {"symbol": "NVDA", "name": "NVIDIA Corporation", "weight": 0.051},
      {"symbol": "AMZN", "name": "Amazon.com Inc.", "weight": 0.038},
      {"symbol": "META", "name": "Meta Platforms Inc.", "weight": 0.024},
      {"symbol": "GOOGL", "name": "Alphabet Inc. Class A", "weight": 0.021},
      {"symbol": "BRK.B", "name": "Berkshire Hathaway Inc.", "weight": 0.017},
      {"symbol": "GOOG", "name": "Alphabet Inc. Class C", "weight": 0.017},
      {"symbol": "LLY", "name": "Eli Lilly and Company", "weight": 0.015},
      {"symbol": "AVGO", "name": "Broadcom Inc.", "weight": 0.014}
    ],
    "sector_weights": {
      "Technology": 0.298,
      "Financial Services": 0.131,
      "Healthcare": 0.122,
      "Consumer Cyclical": 0.104,
      "Communication Services": 0.089,
      "Industrials": 0.085,
      "Consumer Defensive": 0.061,
      "Energy": 0.039,
      "Real Estate": 0.022,
      "Basic Materials": 0.021,
      "Utilities": 0.028
    }
  },
  "BND": {
    "symbol": "BND",
    "name": "Vanguard Total Bond Market ETF",
    "asset_class": "Fixed Income",
    "expense_ratio": 0.0003,
    "aum_billions": 315.4,
    "dividend_yield": 0.0435,
    "top_holdings": [
      {"symbol": "T_91", "name": "United States Treasury Note/Bond 4.25%", "weight": 0.012},
      {"symbol": "T_84", "name": "United States Treasury Note/Bond 3.875%", "weight": 0.011},
      {"symbol": "FNMA", "name": "Federal National Mortgage Association 3.0%", "weight": 0.008}
    ],
    "fixed_income_profile": {
      "avg_duration_years": 6.1,
      "avg_maturity_years": 8.4,
      "credit_quality": {
        "AAA": 0.68,
        "AA": 0.05,
        "A": 0.13,
        "BBB": 0.14
      }
    },
    "sector_weights": {
      "Government": 0.68,
      "Corporate": 0.19,
      "Securitized": 0.13
    }
  },
  "AGG": {
    "symbol": "AGG",
    "name": "iShares Core U.S. Aggregate Bond ETF",
    "asset_class": "Fixed Income",
    "expense_ratio": 0.0003,
    "aum_billions": 105.8,
    "dividend_yield": 0.0430,
    "fixed_income_profile": {
      "avg_duration_years": 6.2,
      "avg_maturity_years": 8.5,
      "credit_quality": {
        "AAA": 0.71,
        "AA": 0.04,
        "A": 0.12,
        "BBB": 0.13
      }
    },
    "sector_weights": {
      "Treasury": 0.45,
      "Mortgage-Backed": 0.28,
      "Corporate": 0.25,
      "Agency": 0.02
    }
  },
  "VTI": {
    "symbol": "VTI",
    "name": "Vanguard Total Stock Market ETF",
    "asset_class": "Equity",
    "expense_ratio": 0.0003,
    "aum_billions": 380.0,
    "dividend_yield": 0.0142,
    "top_holdings": [
      {"symbol": "MSFT", "name": "Microsoft Corporation", "weight": 0.063},
      {"symbol": "AAPL", "name": "Apple Inc.", "weight": 0.052},
      {"symbol": "NVDA", "name": "NVIDIA Corporation", "weight": 0.046},
      {"symbol": "AMZN", "name": "Amazon.com Inc.", "weight": 0.034}
    ],
    "sector_weights": {
      "Technology": 0.291,
      "Financial Services": 0.133,
      "Healthcare": 0.120,
      "Consumer Cyclical": 0.102,
      "Industrials": 0.092
    }
  },
  "VXUS": {
    "symbol": "VXUS",
    "name": "Vanguard Total International Stock ETF",
    "asset_class": "Equity",
    "expense_ratio": 0.0007,
    "aum_billions": 65.4,
    "dividend_yield": 0.0315,
    "top_holdings": [
      {"symbol": "TSMC", "name": "Taiwan Semiconductor Manufacturing Co", "weight": 0.021},
      {"symbol": "NESN", "name": "Nestle SA", "weight": 0.013},
      {"symbol": "ASML", "name": "ASML Holding NV", "weight": 0.012},
      {"symbol": "NOVO", "name": "Novo Nordisk A/S", "weight": 0.011}
    ],
    "sector_weights": {
      "Financial Services": 0.210,
      "Industrials": 0.155,
      "Technology": 0.132,
      "Healthcare": 0.118,
      "Consumer Cyclical": 0.108
    }
  },
  "GLD": {
    "symbol": "GLD",
    "name": "SPDR Gold Shares",
    "asset_class": "Commodity",
    "expense_ratio": 0.0040,
    "aum_billions": 62.0,
    "dividend_yield": 0.0,
    "top_holdings": [
      {"symbol": "GOLD_BAR", "name": "100% Physical Gold Bullion (Allocated)", "weight": 1.00}
    ],
    "sector_weights": {
      "Precious Metals": 1.00
    }
  }
}
```

---

## 4. Downstream Integration & Inter-Agent Coordination

1. **`MarketDataAgent` (`backend/agents/market_data.py`)**:
   - Manages caching with `CacheService`:
     - Quotes: `key_quote(symbol)` (30s TTL)
     - Price History: `key_ohlcv("yfinance", symbol, period)` (24h TTL)
     - Treasury Yield Curve: `key_treasury()` (12h TTL)
     - Macro Indicators: `key_macro("indicators")` (24h TTL)
     - ETF Holdings: `key_holdings(symbol)` (6h TTL)
   - On cache miss, delegates directly to `EquitiesProvider`, `TreasuryProvider`, `MacroProvider`, or `ETFHoldingsProvider`.
2. **`AllocationEngine` (`backend/agents/allocation_engine.py`)**:
   - Calls `MarketDataAgent.get_history(["SPY", "BND", "AGG", "VTI", "VXUS", "GLD"], period="1y")`.
   - Uses `prices_to_returns(df)` to compute returns.
   - Solves CVaR MeanRisk optimization:
     ```python
     model = MeanRisk(
         risk_measure=RiskMeasure.CVAR,
         objective_function=ObjectiveFunction.MAXIMIZE_RATIO,
         max_weights=0.30,
         min_weights=0.02,
         transaction_costs=0.001
     )
     model.fit(returns)
     ```
   - *Key finding addressed*: Parameter names are `max_weights` and `min_weights` (plural), and `objective_function` must be `ObjectiveFunction.MAXIMIZE_RATIO`.
3. **`ProductComparisonAgent` (`backend/agents/product_comparison.py`)**:
   - Queries `AssetScreenerProvider.screen()` for ETF or bond candidates.
   - Enriches candidates with `ETFHoldingsProvider.get_holdings(sym)` to check expense ratio and duration.
   - Calculates 6-factor composite scores and returns ranked rationale.
4. **`ComplianceGuard` (`backend/agents/compliance_guard.py`)**:
   - Uses `ETFHoldingsProvider` to evaluate concentration rules:
     - `CONC-001`: Single asset concentration <= 30%.
     - `CONC-002`: Single sector concentration <= 40%.

---

## 5. Verification & Testing Strategy

A dedicated test suite should be created to verify all providers and fixtures:
- `tests/unit/test_providers.py`:
  1. `test_equities_provider_offline_quote()`: Verifies quote parsing from fixture for all core symbols.
  2. `test_equities_provider_offline_history()`: Verifies 252-day price history returns a valid DataFrame without NaNs.
  3. `test_treasury_provider_offline_curve()`: Verifies par yield curve dictionary and inversion metrics.
  4. `test_macro_provider_offline_indicators()`: Verifies CPI, unemployment rate, and fed funds rate.
  5. `test_etf_holdings_provider_offline()`: Verifies holdings and sector weights for SPY, BND, AGG, VTI, VXUS, GLD.
  6. `test_screener_provider()`: Verifies asset screening by expense ratio, asset class, and risk level.
  7. `test_historical_prices_skfolio_compatibility()`: Verifies that fitting `MeanRisk` on `historical_prices.json` completes successfully and produces optimal portfolio weights.
