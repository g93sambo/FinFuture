"""
backend/services/providers/sec_edgar.py
=======================================
Asynchronous SEC EDGAR Client providing dual-track quantitative XBRL facts
and qualitative narrative section extraction (Items 1A, 7, 8) with strict
User-Agent compliance, 8 req/s token bucket rate limiting, circuit breaking,
and offline fixture fallback.
"""

from __future__ import annotations

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

try:
    from services.data_pipeline import (
        AsyncRateLimiter,
        CircuitBreaker,
        execute_with_retry,
    )
except ImportError:
    from backend.services.data_pipeline import (
        AsyncRateLimiter,
        CircuitBreaker,
        execute_with_retry,
    )

logger = logging.getLogger("wealth_advisor.services.providers.sec_edgar")


# ============================================================================
# 1. Canonical Pydantic v2 Models
# ============================================================================

class SECCompanyInfo(BaseModel):
    """Normalized metadata for a public company registered with the SEC."""
    ticker: str = Field(..., description="Normalized uppercase ticker symbol (e.g. AAPL)")
    cik: str = Field(..., description="10-digit zero-padded Central Index Key (e.g. 0000320193)")
    cik_int: int = Field(..., description="Integer representation of CIK")
    title: str = Field(..., description="Official registered corporate name")
    sic: Optional[str] = Field(default=None, description="Standard Industrial Classification code")


class SECFilingMetadata(BaseModel):
    """Metadata record for an individual SEC filing."""
    symbol: str = Field(..., description="Ticker symbol")
    cik: str = Field(..., description="10-digit zero-padded CIK")
    accession_number: str = Field(..., description="SEC accession number (e.g. 0000320193-23-000106)")
    form: str = Field(..., description="Filing form type (10-K, 10-Q, 8-K, S-1, 424B4)")
    filing_date: str = Field(..., description="Filing acceptance date (YYYY-MM-DD)")
    report_date: Optional[str] = Field(default=None, description="Balance sheet / reporting period date")
    primary_document: str = Field(..., description="Primary filing document filename")
    primary_doc_url: str = Field(..., description="Canonical HTTPS URL to primary filing document")
    is_xbrl: bool = Field(default=True, description="Whether filing contains interactive XBRL data")
    description: Optional[str] = Field(default=None, description="Document description")


class SECGaapMetricPoint(BaseModel):
    """Individual GAAP observation from SEC company facts XBRL data."""
    concept: str = Field(..., description="US-GAAP XBRL taxonomy tag (e.g. Revenues)")
    label: Optional[str] = Field(default=None, description="Human-readable concept label")
    val: float = Field(..., description="Numerical monetary or share value")
    unit: str = Field(default="USD", description="Currency or unit denomination")
    end_date: str = Field(..., description="Period end date (YYYY-MM-DD)")
    fiscal_year: Optional[int] = Field(default=None, description="Fiscal year (e.g. 2024)")
    fiscal_period: Optional[str] = Field(default=None, description="Fiscal period (FY, Q1, Q2, Q3, Q4)")
    form: str = Field(default="10-K", description="Source filing form")
    filed_date: Optional[str] = Field(default=None, description="SEC filing date")


class SECGaapFinancialSummary(BaseModel):
    """Annual or quarterly GAAP financial statement summary and calculated ratios."""
    symbol: str = Field(..., description="Ticker symbol")
    cik: str = Field(..., description="10-digit CIK")
    fiscal_year: int = Field(..., description="Fiscal year")
    period: str = Field(default="FY", description="Fiscal period (FY or Q1-Q4)")
    form: str = Field(default="10-K", description="Filing type")
    revenue: Optional[float] = Field(default=None, description="Total net revenues / sales")
    net_income: Optional[float] = Field(default=None, description="Net income / loss")
    operating_income: Optional[float] = Field(default=None, description="Operating income / loss")
    gross_profit: Optional[float] = Field(default=None, description="Gross profit")
    operating_cash_flow: Optional[float] = Field(default=None, description="Net cash provided by operating activities")
    capex: Optional[float] = Field(default=None, description="Capital expenditures")
    free_cash_flow: Optional[float] = Field(default=None, description="Operating Cash Flow - CapEx")
    total_assets: Optional[float] = Field(default=None, description="Total balance sheet assets")
    total_liabilities: Optional[float] = Field(default=None, description="Total liabilities")
    stockholders_equity: Optional[float] = Field(default=None, description="Total stockholders equity")
    cash_and_equivalents: Optional[float] = Field(default=None, description="Cash and cash equivalents")
    long_term_debt: Optional[float] = Field(default=None, description="Long-term debt noncurrent")
    gross_margin: Optional[float] = Field(default=None, description="Gross margin ratio (Gross Profit / Revenue)")
    operating_margin: Optional[float] = Field(default=None, description="Operating margin ratio")
    net_margin: Optional[float] = Field(default=None, description="Net profit margin ratio")
    debt_to_equity: Optional[float] = Field(default=None, description="Long-term debt / Stockholders equity")
    source: str = Field(default="live", description="Data origin (live or fixture)")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SECNarrativeSection(BaseModel):
    """Extracted textual narrative section from 10-K, 10-Q, or 8-K."""
    symbol: str = Field(..., description="Ticker symbol")
    cik: str = Field(..., description="10-digit CIK")
    form: str = Field(..., description="Form type (10-K, 10-Q, 8-K)")
    accession_number: Optional[str] = Field(default=None, description="Accession number")
    section_key: str = Field(..., description="Section key (e.g. item_1a, item_7, item_8)")
    title: str = Field(..., description="Human-readable title (e.g. Item 1A. Risk Factors)")
    content: str = Field(..., description="Sanitized plain text narrative")
    char_count: int = Field(..., description="Total character count")
    source_url: str = Field(..., description="Canonical HTTPS filing document URL")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# 2. Asynchronous SEC EDGAR Client Implementation
# ============================================================================

class SecEdgarProvider:
    """
    Asynchronous SEC EDGAR Client providing dual-track quantitative XBRL facts
    and qualitative narrative section extraction with resilient rate limiting
    and offline fixture fallback.
    """
    SEC_WWW_URL = "https://www.sec.gov"
    SEC_DATA_URL = "https://data.sec.gov"
    DEFAULT_USER_AGENT = "WealthAdvisorResearch/2.0 (compliance@wealthadvisor.local)"

    SEED_TICKERS = {
        "AAPL": {"cik": "0000320193", "cik_int": 320193, "title": "Apple Inc."},
        "MSFT": {"cik": "0000789019", "cik_int": 789019, "title": "Microsoft Corporation"},
        "NVDA": {"cik": "0001045810", "cik_int": 1045810, "title": "NVIDIA Corporation"},
        "AMZN": {"cik": "0001018724", "cik_int": 1018724, "title": "Amazon.com, Inc."},
        "GOOGL": {"cik": "0001652044", "cik_int": 1652044, "title": "Alphabet Inc."},
        "TSLA": {"cik": "0001318605", "cik_int": 1318605, "title": "Tesla, Inc."},
        "SPY": {"cik": "0000884394", "cik_int": 884394, "title": "SPDR S&P 500 ETF Trust"},
    }

    def __init__(
        self,
        user_agent: Optional[str] = None,
        rate_limit_per_sec: float = 8.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        offline_mode: bool = False,
        fixtures_dir: Optional[Path] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.user_agent = user_agent or os.getenv("SEC_EDGAR_USER_AGENT") or self.DEFAULT_USER_AGENT
        self.offline_mode = offline_mode
        self.rate_limiter = rate_limiter or AsyncRateLimiter(
            rate_limit_per_sec=rate_limit_per_sec,
            burst_capacity=rate_limit_per_sec
        )
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            name="sec_edgar",
            failure_threshold=5,
            cooldown_seconds=60.0
        )
        self.fixtures_dir = self._resolve_fixtures_dir(fixtures_dir)
        self._client = http_client
        self._own_client = False
        self._ticker_map: Dict[str, SECCompanyInfo] = {}
        self._load_seed_tickers()

    def _resolve_fixtures_dir(self, custom_path: Optional[Path]) -> Path:
        if custom_path and Path(custom_path).exists():
            return Path(custom_path)
        base = Path(__file__).resolve()
        candidates = [
            base.parents[3] / "tests" / "fixtures" / "sec",
            base.parents[2] / "tests" / "fixtures" / "sec",
            Path.cwd() / "tests" / "fixtures" / "sec",
            Path.cwd() / "backend" / "tests" / "fixtures" / "sec",
            base.parents[3] / "backend" / "tests" / "fixtures" / "sec",
            base.parents[2] / "tests" / "fixtures",
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    def _load_seed_tickers(self) -> None:
        for sym, d in self.SEED_TICKERS.items():
            self._ticker_map[sym] = SECCompanyInfo(
                ticker=sym,
                cik=d["cik"],
                cik_int=d["cik_int"],
                title=d["title"],
            )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, text/html, */*",
            }
            self._client = httpx.AsyncClient(headers=headers, timeout=12.0, follow_redirects=True)
            self._own_client = True
        return self._client

    async def close(self) -> None:
        if self._own_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # --- CIK & Directory Mapping ---

    async def get_cik(self, symbol: str) -> str:
        """Resolves ticker symbol to 10-digit zero-padded CIK string."""
        info = await self.get_company_info(symbol)
        return info.cik

    async def get_company_info(self, symbol: str) -> SECCompanyInfo:
        """Returns SECCompanyInfo containing title, cik, and ticker."""
        sym = symbol.strip().upper()
        if sym in self._ticker_map:
            return self._ticker_map[sym]
        await self._refresh_ticker_directory()
        if sym in self._ticker_map:
            return self._ticker_map[sym]
        raise ValueError(f"Unknown ticker symbol '{sym}' in SEC EDGAR directory.")

    async def _refresh_ticker_directory(self) -> None:
        if self.offline_mode:
            self._load_ticker_fixture()
            return
        try:
            client = await self._get_client()
            url = f"{self.SEC_WWW_URL}/files/company_tickers.json"

            async def _fetch():
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()

            data = await execute_with_retry(_fetch, self.rate_limiter, self.circuit_breaker)
            self._populate_tickers_from_json(data)
        except Exception as e:
            logger.warning("Failed to fetch live company_tickers.json (%s). Falling back to fixture.", e)
            self._load_ticker_fixture()

    def _populate_tickers_from_json(self, data: Dict[str, Any]) -> None:
        for entry in data.values():
            if isinstance(entry, dict) and "ticker" in entry and "cik_str" in entry:
                t = str(entry["ticker"]).strip().upper()
                c_int = int(entry["cik_str"])
                self._ticker_map[t] = SECCompanyInfo(
                    ticker=t,
                    cik=f"{c_int:010d}",
                    cik_int=c_int,
                    title=str(entry.get("title", t)),
                )

    def _load_ticker_fixture(self) -> None:
        path = self.fixtures_dir / "sec_company_tickers.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self._populate_tickers_from_json(json.load(f))

    # --- Submissions & Recent Filings ---

    async def get_recent_filings(
        self,
        symbol: str,
        forms: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[SECFilingMetadata]:
        """Fetches list of recent filings for symbol matching given forms."""
        cik = await self.get_cik(symbol)
        if self.offline_mode:
            return self._load_recent_filings_fixture(symbol, cik, forms, limit)
        try:
            client = await self._get_client()
            url = f"{self.SEC_DATA_URL}/submissions/CIK{cik}.json"

            async def _fetch():
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()

            data = await execute_with_retry(_fetch, self.rate_limiter, self.circuit_breaker)
            return self._parse_submissions_json(symbol, cik, data, forms, limit)
        except Exception as e:
            logger.warning("Error fetching submissions for %s (%s). Falling back to fixture.", symbol, e)
            return self._load_recent_filings_fixture(symbol, cik, forms, limit)

    def _parse_submissions_json(
        self,
        symbol: str,
        cik: str,
        data: Dict[str, Any],
        forms: Optional[List[str]],
        limit: int
    ) -> List[SECFilingMetadata]:
        recent = data.get("filings", {}).get("recent", {})
        if not recent or "accessionNumber" not in recent:
            return []
        acc_nums = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        form_types = recent.get("form", [])
        primary_docs = recent.get("primaryDocument", [])
        is_xbrls = recent.get("isXBRL", [])
        descriptions = recent.get("primaryDocDescription", [])

        allowed_forms = {f.strip().upper() for f in forms} if forms else None
        cik_clean = str(int(cik))
        results: List[SECFilingMetadata] = []

        for i in range(len(acc_nums)):
            f_type = form_types[i].strip().upper() if i < len(form_types) else ""
            if allowed_forms and f_type not in allowed_forms:
                continue
            acc = acc_nums[i]
            acc_nodash = acc.replace("-", "")
            p_doc = primary_docs[i] if i < len(primary_docs) else ""
            doc_url = f"{self.SEC_WWW_URL}/Archives/edgar/data/{cik_clean}/{acc_nodash}/{p_doc}"
            results.append(SECFilingMetadata(
                symbol=symbol.upper(),
                cik=cik,
                accession_number=acc,
                form=form_types[i] if i < len(form_types) else "",
                filing_date=filing_dates[i] if i < len(filing_dates) else "",
                report_date=report_dates[i] if i < len(report_dates) else None,
                primary_document=p_doc,
                primary_doc_url=doc_url,
                is_xbrl=bool(is_xbrls[i]) if i < len(is_xbrls) else True,
                description=descriptions[i] if i < len(descriptions) else None,
            ))
            if len(results) >= limit:
                break
        return results

    def _load_recent_filings_fixture(
        self,
        symbol: str,
        cik: str,
        forms: Optional[List[str]],
        limit: int
    ) -> List[SECFilingMetadata]:
        for fn in (f"sec_submissions_{symbol.upper()}.json", "sec_submissions_AAPL.json"):
            path = self.fixtures_dir / fn
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return self._parse_submissions_json(symbol, cik, json.load(f), forms, limit)
        return []

    # --- Quantitative Track: XBRL Facts & Financial Metrics ---

    async def get_company_facts(self, symbol: str) -> Dict[str, Any]:
        """Retrieves full raw XBRL company facts JSON from SEC EDGAR API or fixture."""
        cik = await self.get_cik(symbol)
        if self.offline_mode:
            return self._load_company_facts_fixture(symbol)
        try:
            client = await self._get_client()
            url = f"{self.SEC_DATA_URL}/api/xbrl/companyfacts/CIK{cik}.json"

            async def _fetch():
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()

            return await execute_with_retry(_fetch, self.rate_limiter, self.circuit_breaker)
        except Exception as e:
            logger.warning("Error fetching companyfacts for %s (%s). Falling back to fixture.", symbol, e)
            return self._load_company_facts_fixture(symbol)

    def _load_company_facts_fixture(self, symbol: str) -> Dict[str, Any]:
        for fn in (f"sec_companyfacts_{symbol.upper()}.json", "sec_companyfacts_AAPL.json"):
            path = self.fixtures_dir / fn
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        raise FileNotFoundError(f"SEC company facts fixture not found in {self.fixtures_dir}")

    async def get_financial_metrics(
        self,
        symbol: str,
        years: int = 3,
        form: str = "10-K"
    ) -> Dict[int, SECGaapFinancialSummary]:
        """
        Extracts structured GAAP metrics across fiscal years and computes financial ratios.
        Returns dictionary mapping fiscal_year -> SECGaapFinancialSummary sorted descending.
        """
        raw_facts = await self.get_company_facts(symbol)
        cik = await self.get_cik(symbol)
        us_gaap = raw_facts.get("facts", {}).get("us-gaap", {})
        if not us_gaap:
            return {}

        concept_chains = {
            "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
            "net_income": ["NetIncomeLoss", "ProfitLoss"],
            "operating_income": ["OperatingIncomeLoss"],
            "gross_profit": ["GrossProfit"],
            "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
            "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
            "total_assets": ["Assets"],
            "total_liabilities": ["Liabilities"],
            "stockholders_equity": ["StockholdersEquity"],
            "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
            "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
        }

        # Year -> Concept -> latest value
        extracted_by_year: Dict[int, Dict[str, float]] = {}

        for metric_name, tag_list in concept_chains.items():
            for tag in tag_list:
                if tag in us_gaap and "units" in us_gaap[tag]:
                    units = us_gaap[tag]["units"].get("USD", [])
                    filtered = [
                        it for it in units
                        if it.get("form") == form and it.get("fy") is not None
                    ]
                    # Sort by filed date ascending so latest overwrites earlier
                    filtered.sort(key=lambda x: str(x.get("filed", "")))
                    for it in filtered:
                        fy = int(it["fy"])
                        if fy not in extracted_by_year:
                            extracted_by_year[fy] = {}
                        extracted_by_year[fy][metric_name] = float(it["val"])
                    if any(metric_name in extracted_by_year[y] for y in extracted_by_year):
                        break

        # Build summaries
        sorted_years = sorted(extracted_by_year.keys(), reverse=True)[:years]
        summaries: Dict[int, SECGaapFinancialSummary] = {}

        for y in sorted_years:
            yd = extracted_by_year[y]
            rev = yd.get("revenue")
            ni = yd.get("net_income")
            oi = yd.get("operating_income")
            gp = yd.get("gross_profit")
            ocf = yd.get("operating_cash_flow")
            capex = yd.get("capex")
            fcf = (ocf - capex) if (ocf is not None and capex is not None) else None
            eq = yd.get("stockholders_equity")
            debt = yd.get("long_term_debt")

            gm = (gp / rev) if (gp is not None and rev and rev > 0) else None
            om = (oi / rev) if (oi is not None and rev and rev > 0) else None
            nm = (ni / rev) if (ni is not None and rev and rev > 0) else None
            de = (debt / eq) if (debt is not None and eq and eq > 0) else None

            summaries[y] = SECGaapFinancialSummary(
                symbol=symbol.upper(),
                cik=cik,
                fiscal_year=y,
                revenue=rev,
                net_income=ni,
                operating_income=oi,
                gross_profit=gp,
                operating_cash_flow=ocf,
                capex=capex,
                free_cash_flow=fcf,
                total_assets=yd.get("total_assets"),
                total_liabilities=yd.get("total_liabilities"),
                stockholders_equity=eq,
                cash_and_equivalents=yd.get("cash_and_equivalents"),
                long_term_debt=debt,
                gross_margin=round(gm, 4) if gm is not None else None,
                operating_margin=round(om, 4) if om is not None else None,
                net_margin=round(nm, 4) if nm is not None else None,
                debt_to_equity=round(de, 4) if de is not None else None,
                source="fixture" if self.offline_mode else "live",
            )

        return summaries

    # --- Qualitative Track: Narrative Parsing with BeautifulSoup ---

    async def get_filing_document(
        self,
        symbol: str,
        form: str = "10-K",
        accession_number: Optional[str] = None
    ) -> Tuple[str, str]:
        """Retrieves raw HTML filing document content and canonical URL."""
        if self.offline_mode:
            return self._load_document_fixture(symbol, form)
        filings = await self.get_recent_filings(symbol, forms=[form], limit=5)
        if not filings:
            return self._load_document_fixture(symbol, form)
        target = filings[0]
        if accession_number:
            for f in filings:
                if f.accession_number == accession_number:
                    target = f
                    break
        try:
            client = await self._get_client()

            async def _fetch():
                resp = await client.get(target.primary_doc_url)
                resp.raise_for_status()
                return resp.text

            html_content = await execute_with_retry(_fetch, self.rate_limiter, self.circuit_breaker)
            return html_content, target.primary_doc_url
        except Exception as e:
            logger.warning("Error fetching live document (%s). Falling back to fixture.", e)
            return self._load_document_fixture(symbol, form)

    def _load_document_fixture(self, symbol: str, form: str) -> Tuple[str, str]:
        suffix = form.lower().replace("-", "")
        filenames = [
            f"sec_{suffix}_sample_{symbol.upper()}.html",
            f"sec_{suffix}_sample_AAPL.html",
            "sec_10k_sample_AAPL.html",
        ]
        for fn in filenames:
            path = self.fixtures_dir / fn
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return f.read(), f"https://www.sec.gov/Archives/edgar/data/fixtures/{fn}"
        raise FileNotFoundError(f"Filing HTML fixture not found in {self.fixtures_dir}")

    def parse_filing_sections(
        self,
        html_content: str,
        form: str = "10-K",
        max_chars_per_section: int = 15000
    ) -> Dict[str, str]:
        """
        Parses cleaned HTML filing and extracts key narrative sections
        using BeautifulSoup and anti-TOC regex boundary segmentation.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "ix:header", "ix:hidden"]):
            tag.decompose()

        # Clean text with preserved paragraph breaks
        raw_text = soup.get_text(separator="\n")
        lines = [line.strip() for line in raw_text.splitlines()]
        text = "\n".join(lines)

        sections: Dict[str, str] = {}
        form_upper = form.upper()

        if form_upper == "10-K":
            regex_map = {
                "item_1": (
                    r"(?i)(?:item\s+1[\.\s:\-—]+business)",
                    r"(?i)(?:(?:\n|^)\s*item\s+1a[\.\s:\-—]|(?:\n|^)\s*item\s+2[\.\s:\-—]|item\s+1a[\.\s:\-—]+risk)"
                ),
                "item_1a": (
                    r"(?i)(?:item\s+1a[\.\s:\-—]+risk\s+factors)",
                    r"(?i)(?:(?:\n|^)\s*item\s+1b[\.\s:\-—]|(?:\n|^)\s*item\s+2[\.\s:\-—])"
                ),
                "item_7": (
                    r"(?i)(?:item\s+7[\.\s:\-—]+management(?:['’]s)?\s+discussion)",
                    r"(?i)(?:(?:\n|^)\s*item\s+7a[\.\s:\-—]|(?:\n|^)\s*item\s+8[\.\s:\-—]|item\s+7a[\.\s:\-—]+quantitative|item\s+8[\.\s:\-—]+financial)"
                ),
                "item_7a": (
                    r"(?i)(?:item\s+7a[\.\s:\-—]+quantitative\s+and\s+qualitative)",
                    r"(?i)(?:(?:\n|^)\s*item\s+8[\.\s:\-—]|item\s+8[\.\s:\-—]+financial)"
                ),
                "item_8": (
                    r"(?i)(?:item\s+8[\.\s:\-—]+financial\s+statements)",
                    r"(?i)(?:(?:\n|^)\s*item\s+9[\.\s:\-—])"
                ),
            }
        elif form_upper == "10-Q":
            regex_map = {
                "part1_item1": (
                    r"(?i)(?:part\s+i[\s,\-—]+item\s+1[\.\s:\-—]+financial\s+statements)",
                    r"(?i)(?:item\s+2[\.\s:\-—])"
                ),
                "part1_item2": (
                    r"(?i)(?:item\s+2[\.\s:\-—]+management(?:['’]s)?\s+discussion)",
                    r"(?i)(?:item\s+3[\.\s:\-—]|part\s+ii)"
                ),
                "part2_item1a": (
                    r"(?i)(?:item\s+1a[\.\s:\-—]+risk\s+factors)",
                    r"(?i)(?:item\s+2[\.\s:\-—]|item\s+6[\.\s:\-—])"
                ),
            }
        elif form_upper == "8-K":
            regex_map = {
                "item_1_01": (
                    r"(?i)(?:item\s+1\.01[\.\s:\-—]+entry\s+into\s+a\s+material)",
                    r"(?i)(?:item\s+\d\.\d\d|signatures)"
                ),
                "item_2_02": (
                    r"(?i)(?:item\s+2\.02[\.\s:\-—]+results\s+of\s+operations)",
                    r"(?i)(?:item\s+\d\.\d\d|signatures)"
                ),
                "item_5_02": (
                    r"(?i)(?:item\s+5\.02[\.\s:\-—]+departure\s+of\s+directors)",
                    r"(?i)(?:item\s+\d\.\d\d|signatures)"
                ),
            }
        else:
            return {}

        for key, (start_pat, end_pat) in regex_map.items():
            matches = list(re.finditer(start_pat, text))
            if not matches:
                continue

            chosen_content = ""
            # Anti-TOC filtering: skip stub matches (< 400 chars)
            for m in matches:
                start_idx = m.end()
                remainder = text[start_idx:]
                end_match = re.search(end_pat, remainder)
                end_idx = end_match.start() if end_match else len(remainder)
                chunk = remainder[:end_idx].strip()
                if len(chunk) > 400:
                    chosen_content = chunk
                    break
                elif not chosen_content and len(chunk) > 0:
                    chosen_content = chunk

            if chosen_content:
                clean_chunk = " ".join(chosen_content.split())
                if len(clean_chunk) > max_chars_per_section:
                    clean_chunk = clean_chunk[:max_chars_per_section] + "... [truncated]"
                sections[key] = clean_chunk

        return sections

    async def get_narrative_sections(
        self,
        symbol: str,
        form: str = "10-K",
        sections: Optional[List[str]] = None,
        accession_number: Optional[str] = None
    ) -> Dict[str, SECNarrativeSection]:
        """Fetches document and extracts structured SECNarrativeSection objects."""
        html_content, doc_url = await self.get_filing_document(symbol, form, accession_number)
        cik = await self.get_cik(symbol)
        parsed_dict = self.parse_filing_sections(html_content, form)

        title_map = {
            "item_1": "Item 1. Business",
            "item_1a": "Item 1A. Risk Factors",
            "item_7": "Item 7. Management's Discussion and Analysis",
            "item_7a": "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
            "item_8": "Item 8. Financial Statements and Supplementary Data",
            "part1_item1": "Part I, Item 1. Financial Statements",
            "part1_item2": "Part I, Item 2. Management's Discussion and Analysis",
            "part2_item1a": "Part II, Item 1A. Risk Factors",
            "item_1_01": "Item 1.01. Entry into a Material Definitive Agreement",
            "item_2_02": "Item 2.02. Results of Operations and Financial Condition",
            "item_5_02": "Item 5.02. Departure of Directors or Principal Officers",
        }

        output: Dict[str, SECNarrativeSection] = {}
        for sec_key, content in parsed_dict.items():
            if sections and sec_key not in sections:
                continue
            output[sec_key] = SECNarrativeSection(
                symbol=symbol.upper(),
                cik=cik,
                form=form.upper(),
                accession_number=accession_number,
                section_key=sec_key,
                title=title_map.get(sec_key, sec_key.upper()),
                content=content,
                char_count=len(content),
                source_url=doc_url,
            )
        return output
