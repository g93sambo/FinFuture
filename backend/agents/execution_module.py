import os
import logging
from typing import Dict, Any

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False

logger = logging.getLogger(__name__)

class ExecutionModule:
    def __init__(self):
        self.api_key = os.getenv("ALPACA_API_KEY", "")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        self.paper = True
        
        if HAS_ALPACA and self.api_key and self.secret_key:
            self.client = TradingClient(self.api_key, self.secret_key, paper=self.paper)
        else:
            self.client = None
            logger.warning("Alpaca credentials not found or alpaca-py not installed. Execution will run in dry-run mode.")

    def place_order(self, symbol: str, qty: float, side: str, user_approved: bool) -> Dict[str, Any]:
        """
        Place a market order via Alpaca after confirming user approval.
        """
        if not user_approved:
            raise ValueError("Cannot execute trade: User has not approved.")
            
        if not self.client:
            logger.info(f"[DRY-RUN] Placing {side} order for {qty} shares of {symbol}")
            return {
                "status": "mock_filled",
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "filled_price": 100.0, # dummy
                "order_id": "dummy-order-123"
            }
            
        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        
        order_request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY
        )
        
        try:
            order = self.client.submit_order(order_request)
            return {
                "status": order.status,
                "symbol": order.symbol,
                "qty": order.qty,
                "side": order.side,
                "order_id": str(order.id)
            }
        except Exception as e:
            logger.error(f"Alpaca API error: {e}")
            raise
