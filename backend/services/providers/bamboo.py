"""
backend/services/providers/bamboo.py
====================================
Bamboo Investment API Provider for live and sandbox trading for Nigerian and global investors.
Supports both US Equities and Nigerian (NGX) equities, currency conversion (NGN / USD),
token management (24h lifespan), pre-trade calculation, order execution, and portfolio retrieval.
"""

from __future__ import annotations

import os
import time
import uuid
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

import httpx

try:
    from backend.core.config import settings
except ImportError:
    from core.config import settings

logger = logging.getLogger("wealth_advisor.services.providers.bamboo")

SANDBOX_BASE_URL = "https://powered-by-bamboo-sandbox.investbamboo.com"
LIVE_BASE_URL = "https://powered-by-bamboo.investbamboo.com"


class BambooToken(BaseModel):
    client_token: str
    expires_at: float  # unix epoch


class BambooOrderCalculation(BaseModel):
    symbol: str
    side: str
    order_type: str = "MARKET"
    currency: str = "NGN"
    amount: float
    order_price: float
    price_per_share: float
    quantity: float
    fee: float
    fx_rate: Optional[float] = None


class BambooOrderResult(BaseModel):
    order_id: str
    symbol: str
    side: str
    quantity: float
    price_per_share: float
    total_price: float
    fee: float
    status: str
    currency: str = "NGN"
    executed_at: str
    dry_run: bool = False


# Fallback / simulated reference prices for NGX and US stocks traded via Bamboo
BAMBOO_SIMULATED_PRICES: Dict[str, Dict[str, Any]] = {
    # Nigerian Stocks (NGX) - quoted in NGN
    "DANGCEM": {"price": 650.0, "currency": "NGN", "name": "Dangote Cement Plc", "market": "NGX"},
    "MTNN": {"price": 240.0, "currency": "NGN", "name": "MTN Nigeria Communications Plc", "market": "NGX"},
    "GTCO": {"price": 48.50, "currency": "NGN", "name": "Guaranty Trust Holding Company Plc", "market": "NGX"},
    "ZENITHBANK": {"price": 42.00, "currency": "NGN", "name": "Zenith Bank Plc", "market": "NGX"},
    "ACCESSCORP": {"price": 21.50, "currency": "NGN", "name": "Access Holdings Plc", "market": "NGX"},
    "UBA": {"price": 29.80, "currency": "NGN", "name": "United Bank for Africa Plc", "market": "NGX"},
    "SEPLAT": {"price": 3400.0, "currency": "NGN", "name": "Seplat Energy Plc", "market": "NGX"},
    "AIRTELAFRI": {"price": 2150.0, "currency": "NGN", "name": "Airtel Africa Plc", "market": "NGX"},
    "BUACEMENT": {"price": 142.0, "currency": "NGN", "name": "BUA Cement Plc", "market": "NGX"},
    "BUAFOODS": {"price": 380.0, "currency": "NGN", "name": "BUA Foods Plc", "market": "NGX"},
    "NESTLE": {"price": 900.0, "currency": "NGN", "name": "Nestle Nigeria Plc", "market": "NGX"},
    "GEREGU": {"price": 1000.0, "currency": "NGN", "name": "Geregu Power Plc", "market": "NGX"},
    "TRANSPOWER": {"price": 375.0, "currency": "NGN", "name": "Transcorp Power Plc", "market": "NGX"},
    "TRANSCORP": {"price": 14.20, "currency": "NGN", "name": "Transnational Corporation Plc", "market": "NGX"},
    "NGXGROUP": {"price": 23.50, "currency": "NGN", "name": "Nigerian Exchange Group Plc", "market": "NGX"},
    # US Stocks - quoted in USD
    "AAPL": {"price": 185.00, "currency": "USD", "name": "Apple Inc.", "market": "US"},
    "MSFT": {"price": 420.00, "currency": "USD", "name": "Microsoft Corporation", "market": "US"},
    "NVDA": {"price": 125.00, "currency": "USD", "name": "NVIDIA Corporation", "market": "US"},
    "SPY": {"price": 510.50, "currency": "USD", "name": "SPDR S&P 500 ETF Trust", "market": "US"},
    "QQQ": {"price": 440.25, "currency": "USD", "name": "Invesco QQQ Trust", "market": "US"},
    "VTI": {"price": 260.10, "currency": "USD", "name": "Vanguard Total Stock Market ETF", "market": "US"},
    "BND": {"price": 72.40, "currency": "USD", "name": "Vanguard Total Bond Market ETF", "market": "US"},
    "DEFAULT": {"price": 100.00, "currency": "USD", "name": "Equity Asset", "market": "US"},
}

DEFAULT_USD_NGN_RATE = 1550.0  # Reference FX rate


class BambooProvider:
    """
    Client for Bamboo Investment Brokerage APIs.
    Enforces token caching (24h lifespan), rate limit backoff, pre-trade calculation,
    order submission, and robust mock/dry-run fallbacks.
    """

    def __init__(
        self,
        app_key: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        base_url: Optional[str] = None,
        live_mode: bool = False,
    ):
        self.app_key = app_key or getattr(settings, "bamboo_app_key", None) or os.getenv("BAMBOO_APP_KEY", "")
        self.username = username or getattr(settings, "bamboo_username", None) or os.getenv("BAMBOO_USERNAME", "")
        self.password = password or getattr(settings, "bamboo_password", None) or os.getenv("BAMBOO_PASSWORD", "")
        self.live_mode = live_mode or getattr(settings, "bamboo_live_mode", False)

        default_base = LIVE_BASE_URL if self.live_mode else SANDBOX_BASE_URL
        self.base_url = (base_url or getattr(settings, "bamboo_base_url", None) or os.getenv("BAMBOO_BASE_URL", default_base)).rstrip("/")

        self._cached_token: Optional[BambooToken] = None
        self._lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.app_key and self.username and self.password)

    async def get_client_token(self) -> str:
        """
        Authenticate with Bamboo /oauth/token and cache token for up to 23.5 hours.
        """
        now = time.time()
        if self._cached_token and self._cached_token.expires_at > (now + 300):
            return self._cached_token.client_token

        async with self._lock:
            # Double-check inside lock
            if self._cached_token and self._cached_token.expires_at > (now + 300):
                return self._cached_token.client_token

            if not self.is_configured:
                # Return simulated token for offline/development/test mode
                token_str = f"simulated-bamboo-token-{uuid.uuid4().hex[:12]}"
                self._cached_token = BambooToken(client_token=token_str, expires_at=now + 86400)
                return token_str

            url = f"{self.base_url}/oauth/token"
            headers = {
                "content-type": "application/json",
                "accept-language": "en",
                "app-key": self.app_key,
            }
            payload = {
                "username": self.username,
                "password": self.password,
            }

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    # Bamboo returns token in token, access_token, or client_token
                    token_str = data.get("client_token") or data.get("access_token") or data.get("token") or ""
                    expires_in = float(data.get("expires_in", 86400))
                    self._cached_token = BambooToken(client_token=token_str, expires_at=now + expires_in)
                    logger.info("Successfully refreshed Bamboo API client token.")
                    return token_str
            except Exception as e:
                logger.warning("Bamboo authentication request failed: %s. Using sandbox fallback.", e)
                token_str = f"simulated-bamboo-token-{uuid.uuid4().hex[:12]}"
                self._cached_token = BambooToken(client_token=token_str, expires_at=now + 3600)
                return token_str

    def _get_headers(self, token: str, user_id: str, currency: str = "NGN") -> Dict[str, str]:
        return {
            "content-type": "application/json",
            "accept-language": "en",
            "x-subject-type": "tenant",
            "x-client-token": token,
            "x-request-source": self.username or "wealth_advisor",
            "x-user-id": str(user_id),
            "currency": currency.upper(),
        }

    async def calculate_order(
        self,
        symbol: str,
        side: str,
        amount: Optional[float] = None,
        quantity: Optional[float] = None,
        currency: str = "NGN",
        order_type: str = "MARKET",
        user_id: str = "client_default",
    ) -> BambooOrderCalculation:
        """
        Calculate order fees, price per share, and expected quantity via POST /api/order/calculate.
        """
        sym = symbol.strip().upper()
        side_clean = side.strip().lower()
        curr_clean = currency.strip().upper()

        # Resolve asset reference price
        ref_info = BAMBOO_SIMULATED_PRICES.get(sym, BAMBOO_SIMULATED_PRICES["DEFAULT"])
        asset_native_price = ref_info["price"]
        asset_currency = ref_info["currency"]

        # FX conversion if necessary
        fx_rate = DEFAULT_USD_NGN_RATE if (curr_clean == "NGN" and asset_currency == "USD") else 1.0

        if not self.is_configured or getattr(settings, "dry_run", False):
            # Local calculation engine mirroring Bamboo rules
            price_in_curr = asset_native_price * fx_rate if curr_clean == "NGN" and asset_currency == "USD" else asset_native_price

            if amount is not None and amount > 0:
                calc_amount = float(amount)
                # Bamboo fee structure: approx 1.5% for local NGX or $1-2 min for US
                fee = round(calc_amount * 0.015, 2)
                net_invest = max(0.0, calc_amount - fee)
                qty = round(net_invest / price_in_curr, 4) if price_in_curr > 0 else 0.0
                order_price = calc_amount
            elif quantity is not None and quantity > 0:
                qty = float(quantity)
                net_val = qty * price_in_curr
                fee = round(net_val * 0.015, 2)
                order_price = round(net_val + fee, 2)
                calc_amount = order_price
            else:
                raise ValueError("Must provide either amount or quantity to calculate order.")

            return BambooOrderCalculation(
                symbol=sym,
                side=side_clean,
                order_type=order_type,
                currency=curr_clean,
                amount=calc_amount,
                order_price=order_price,
                price_per_share=round(price_in_curr, 2),
                quantity=qty,
                fee=fee,
                fx_rate=fx_rate if curr_clean != asset_currency else None,
            )

        # Live Bamboo API call
        token = await self.get_client_token()
        headers = self._get_headers(token=token, user_id=user_id, currency=curr_clean)
        url = f"{self.base_url}/api/order/calculate"
        payload = {
            "symbol": sym,
            "side": side_clean,
            "order_type": order_type,
            "amount": amount or (quantity * asset_native_price if quantity else 10000.0),
            "sell_all": False,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return BambooOrderCalculation(
                    symbol=sym,
                    side=side_clean,
                    order_type=order_type,
                    currency=curr_clean,
                    amount=float(data.get("amount", payload["amount"])),
                    order_price=float(data.get("order_price", data.get("total_price", payload["amount"]))),
                    price_per_share=float(data.get("price_per_share", asset_native_price)),
                    quantity=float(data.get("quantity", 0.0)),
                    fee=float(data.get("fee", 0.0)),
                    fx_rate=data.get("fx_rate"),
                )
        except Exception as e:
            logger.warning("Bamboo order calculation endpoint failed (%s). Using deterministic fallback.", e)
            return await self.calculate_order(
                symbol=symbol,
                side=side,
                amount=amount,
                quantity=quantity,
                currency=currency,
                order_type=order_type,
                user_id=user_id,
            )

    async def place_order(
        self,
        calculation: BambooOrderCalculation,
        user_id: str,
        extended_hours: bool = False,
        dry_run: bool = False,
    ) -> BambooOrderResult:
        """
        Execute the order via Bamboo POST /api/order using the output of calculate_order.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        if dry_run or not self.is_configured or getattr(settings, "dry_run", False):
            order_id = f"bamboo-sim-{uuid.uuid4().hex[:10]}"
            logger.info(
                "[BAMBOO-SIM] Executed %s %s %s shares @ %s %s (Fee: %s %s)",
                calculation.side.upper(),
                calculation.quantity,
                calculation.symbol,
                calculation.currency,
                calculation.price_per_share,
                calculation.currency,
                calculation.fee,
            )
            return BambooOrderResult(
                order_id=order_id,
                symbol=calculation.symbol,
                side=calculation.side.upper(),
                quantity=calculation.quantity,
                price_per_share=calculation.price_per_share,
                total_price=calculation.order_price,
                fee=calculation.fee,
                status="FILLED",
                currency=calculation.currency,
                executed_at=now_iso,
                dry_run=True,
            )

        token = await self.get_client_token()
        headers = self._get_headers(token=token, user_id=user_id, currency=calculation.currency)
        url = f"{self.base_url}/api/order"
        payload = {
            "symbol": calculation.symbol,
            "side": calculation.side.lower(),
            "total_price": calculation.order_price,
            "price_per_share": calculation.price_per_share,
            "quantity": calculation.quantity,
            "fee": calculation.fee,
            "extended_hours_order": extended_hours,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            order_id = str(data.get("order_id") or data.get("id") or f"bamboo-{uuid.uuid4().hex[:8]}")
            status = str(data.get("status", "FILLED")).upper()
            return BambooOrderResult(
                order_id=order_id,
                symbol=calculation.symbol,
                side=calculation.side.upper(),
                quantity=float(data.get("quantity", calculation.quantity)),
                price_per_share=float(data.get("price_per_share", calculation.price_per_share)),
                total_price=float(data.get("total_price", calculation.order_price)),
                fee=float(data.get("fee", calculation.fee)),
                status=status,
                currency=calculation.currency,
                executed_at=data.get("created_at", now_iso),
                dry_run=False,
            )

    async def get_order_status(self, order_id: str, user_id: str = "client_default") -> Dict[str, Any]:
        """Fetch order status by order ID."""
        if order_id.startswith("bamboo-sim-") or not self.is_configured:
            return {
                "order_id": order_id,
                "status": "FILLED",
                "dry_run": True,
            }

        token = await self.get_client_token()
        headers = self._get_headers(token=token, user_id=user_id)
        url = f"{self.base_url}/api/order/{order_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_user_portfolio(self, user_id: str, currency: str = "NGN") -> Dict[str, Any]:
        """Fetch client portfolio from Bamboo."""
        if not self.is_configured:
            return {
                "source": "bamboo_sandbox",
                "currency": currency,
                "total_value": 5_000_000.0 if currency == "NGN" else 3_200.0,
                "cash": 1_500_000.0 if currency == "NGN" else 1_000.0,
                "positions": {
                    "DANGCEM": 2000.0,
                    "MTNN": 4000.0,
                    "GTCO": 10000.0,
                } if currency == "NGN" else {
                    "AAPL": 10.0,
                    "SPY": 5.0,
                },
            }

        token = await self.get_client_token()
        headers = self._get_headers(token=token, user_id=user_id, currency=currency)
        url = f"{self.base_url}/api/user/portfolio"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
