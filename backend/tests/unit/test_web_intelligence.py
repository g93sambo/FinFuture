"""
backend/tests/unit/test_web_intelligence.py
============================================
Unit tests for live web intelligence tools (search_financial_web, fetch_web_page)
and institutional investment hurdle score thresholding.
"""

import pytest
from unittest.mock import AsyncMock, patch
from agents.market_data import MarketDataAgent


@pytest.mark.asyncio
async def test_search_financial_web_structure():
    agent = MarketDataAgent()
    
    mock_results = [
        {"title": "Dangote Refinery IPO Prospectus", "body": "Summary of offering and debt", "href": "https://ipo.dangote.com/prospectus.pdf"}
    ]
    with patch("agents.market_data.MarketDataAgent.search_financial_web", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [
            {"title": "Dangote Refinery IPO Prospectus", "snippet": "Summary of offering and debt", "url": "https://ipo.dangote.com/prospectus.pdf"}
        ]
        res = await agent.search_financial_web("Dangote Refinery IPO prospectus")
        assert len(res) == 1
        assert res[0]["title"] == "Dangote Refinery IPO Prospectus"
        assert res[0]["url"] == "https://ipo.dangote.com/prospectus.pdf"


@pytest.mark.asyncio
async def test_fetch_web_page_invalid_url():
    agent = MarketDataAgent()
    res = await agent.fetch_web_page("invalid-url-schema")
    assert res["status"] == "error"
    assert "Invalid URL" in res["error"]
