"""
Cycle Bot — Tradier API Integration
Reg T margin trading (equities/options).
Execute directional or hedged trades based on Kalshi trends.
"""

import logging
import requests
from typing import Optional

from config import Config

log = logging.getLogger("cycle.tradier")


class TradierClient:
    """
    Tradier Brokerage API client.
    Paper: sandbox.tradier.com
    Live: api.tradier.com
    """

    SANDBOX_URL = "https://sandbox.tradier.com/v1"
    LIVE_URL = "https://api.tradier.com/v1"

    def __init__(self):
        self.token = Config.TRADIER_ACCESS_TOKEN
        self.account_id = Config.TRADIER_ACCOUNT_ID
        # Paper mode always uses sandbox
        if Config.PAPER_MODE:
            self.base = self.SANDBOX_URL.rstrip("/")
            if self.token and self.account_id:
                log.info("PAPER MODE — Tradier sandbox active")
        else:
            self.base = (Config.TRADIER_BASE_URL or self.LIVE_URL).rstrip("/")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def get_balances(self) -> Optional[dict]:
        """Get account balances (margin, buying power)."""
        if not self.token or not self.account_id:
            return None
        try:
            resp = requests.get(
                f"{self.base}/accounts/{self.account_id}/balances",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning(f"Tradier balances error: {e}")
            return None

    def place_equity_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Place equity order. side=buy/sell, quantity in shares.
        Uses margin (Reg T up to 4x) when available.
        """
        if not self.token or not self.account_id:
            return None
        try:
            data = {
                "class": "equity",
                "symbol": symbol,
                "side": side,
                "quantity": str(quantity),
                "type": order_type,
            }
            if limit_price and order_type == "limit":
                data["price"] = str(limit_price)
            resp = requests.post(
                f"{self.base}/accounts/{self.account_id}/orders",
                headers=self._headers(),
                data=data,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            log.info(f"Tradier order: {side} {quantity} {symbol} @ {order_type}")
            return result
        except Exception as e:
            log.warning(f"Tradier order error: {e}")
            return None

    def place_margin_trade(
        self,
        symbol: str,
        direction: str,
        size_usd: float,
    ) -> Optional[dict]:
        """
        Place margin trade. direction=buy/sell.
        size_usd: approximate dollar value (uses market order).
        """
        if Config.PAPER_MODE:
            log.info(
                f"[PAPER] TRADIER MARGIN {direction.upper()} ${size_usd:.0f} {symbol}"
            )
            return {"paper": True, "symbol": symbol, "side": direction}
        # Get quote for share count
        try:
            q = requests.get(
                f"{self.base}/markets/quotes",
                params={"symbols": symbol},
                headers=self._headers(),
                timeout=5,
            )
            q.raise_for_status()
            quotes = q.json().get("quotes", {}).get("quote", {})
            if isinstance(quotes, list):
                quotes = quotes[0] if quotes else {}
            price = float(quotes.get("last", 0) or quotes.get("ask", 1))
            if price <= 0:
                return None
            quantity = max(1, int(size_usd / price))
            return self.place_equity_order(
                symbol=symbol,
                side=direction,
                quantity=quantity,
                order_type="market",
            )
        except Exception as e:
            log.warning(f"Tradier margin trade error: {e}")
            return None

    def get_positions(self) -> list:
        """Get open positions."""
        if not self.token or not self.account_id:
            return []
        try:
            resp = requests.get(
                f"{self.base}/accounts/{self.account_id}/positions",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("positions", []) or []
        except Exception as e:
            log.warning(f"Tradier positions error: {e}")
            return []

    def close_position(self, symbol: str, quantity: int, side: str) -> Optional[dict]:
        """Close a position. side=buy to close short, sell to close long."""
        return self.place_equity_order(symbol=symbol, side=side, quantity=quantity)
