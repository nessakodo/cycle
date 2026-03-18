"""
Cycle Bot — Kalshi API Integration
CFTC-regulated, US-legal prediction market.
Market discovery, orderbook, limit orders, fill tracking.
"""

import os
import logging
import requests
from typing import Optional

from config import Config

log = logging.getLogger("cycle.kalshi")

# Optional: use kalshi_python_sync if available for authenticated calls
try:
    from kalshi_python_sync import Configuration, KalshiClient as KalshiSDKClient
    HAS_SDK = True
except ImportError:
    HAS_SDK = False
    KalshiSDKClient = None
    log.warning("kalshi_python_sync not installed — pip install kalshi_python_sync")


class KalshiClient:
    """Wrapper for Kalshi API: markets, orderbook, orders, fills."""

    def __init__(self):
        self.client = None
        self.authenticated = False
        self._base = Config.KALSHI_BASE_URL.rstrip("/")

    def connect(self):
        """Initialize and authenticate the Kalshi client."""
        pem_path = Config.KALSHI_PRIVATE_KEY_PATH
        if not pem_path or not os.path.exists(pem_path):
            log.error(f"PEM file not found at {pem_path}")
            raise FileNotFoundError(f"PEM file not found at {pem_path}")

        if HAS_SDK and KalshiSDKClient:
            try:
                with open(pem_path, "r") as f:
                    private_key = f.read()
                config = Configuration(host=Config.KALSHI_BASE_URL)
                config.api_key_id = Config.KALSHI_API_KEY
                config.private_key_pem = private_key
                self.client = KalshiSDKClient(config)
                self.authenticated = True
                log.info(f"Kalshi initialized with PEM file: {pem_path}")
            except Exception as e:
                log.error(f"Kalshi auth failed: {e}")
                self.authenticated = False
                raise
        else:
            log.error("Kalshi SDK required. pip install kalshi_python_sync")
            raise ImportError("kalshi_python_sync required")

    def discover_markets(self, limit: int = 50) -> list:
        """Discover open markets. Returns list of dicts with ticker, title, etc."""
        try:
            if self.client:
                resp = self.client.get_markets(limit=limit, status="open")
                markets = getattr(resp, "markets", []) or []
            else:
                resp = requests.get(
                    f"{self._base}/markets",
                    params={"limit": limit, "status": "open"},
                    timeout=10,
                )
                resp.raise_for_status()
                markets = resp.json().get("markets", [])
            result = []
            for m in markets:
                ticker = getattr(m, "ticker", None) or m.get("ticker", "")
                title = getattr(m, "title", None) or m.get("title", "")
                vol = getattr(m, "volume", 0) or m.get("volume", 0)
                result.append({
                    "id": ticker,
                    "ticker": ticker,
                    "question": title,
                    "volume": float(vol or 0),
                })
            log.info(f"Discovered {len(result)} open Kalshi markets")
            return result
        except Exception as e:
            log.warning(f"Kalshi market discovery error: {e}")
            return []

    def get_orderbook(self, ticker: str) -> Optional[dict]:
        """Get orderbook for a market. Returns {yes_bids, no_bids}."""
        if not self.client:
            return None
        try:
            resp = self.client.get_market_orderbook(ticker)
            ob = getattr(resp, "orderbook_fp", None) or {}
            if hasattr(ob, "yes_dollars"):
                yes_dollars = list(ob.yes_dollars) if ob.yes_dollars else []
                no_dollars = list(ob.no_dollars) if ob.no_dollars else []
            else:
                yes_dollars = ob.get("yes_dollars", [])
                no_dollars = ob.get("no_dollars", [])
            yes_bids = [[float(p[0]), float(p[1])] for p in yes_dollars] if yes_dollars else []
            no_bids = [[float(p[0]), float(p[1])] for p in no_dollars] if no_dollars else []
            return {"yes_bids": yes_bids, "no_bids": no_bids}
        except Exception as e:
            log.warning(f"Orderbook fetch error for {ticker}: {e}")
            return None

    def get_midpoint(self, ticker: str) -> Optional[float]:
        """Get midpoint from orderbook (yes best bid)."""
        book = self.get_orderbook(ticker)
        if not book:
            return None
        yes_bids = book.get("yes_bids", [])
        no_bids = book.get("no_bids", [])
        if yes_bids:
            return yes_bids[0][0]
        if no_bids:
            return 1.0 - no_bids[0][0]
        return 0.5

    def place_limit_order(
        self,
        ticker: str,
        side: str,
        action: str,
        yes_price: float,
        count: int,
        post_only: bool = True,
    ) -> Optional[dict]:
        """Place limit order. side=yes/no, action=buy/sell, yes_price 0.01-0.99."""
        if not self.client or not self.authenticated:
            return None
        try:
            from kalshi_python_sync import CreateOrderRequest
            price_cents = max(1, min(99, int(round(yes_price * 100))))
            req = CreateOrderRequest(
                ticker=ticker,
                side=side,
                action=action,
                count=count,
                yes_price=price_cents,
                post_only=post_only,
                time_in_force="good_till_canceled",
            )
            resp = self.client.create_order(create_order_request=req)
            order = getattr(resp, "order", None) or resp
            log.info(f"Posted {action} {side} {count} @ {yes_price:.2f} for {ticker}")
            return order
        except Exception as e:
            log.warning(f"Order placement error: {e}")
            return None

    def place_quote(
        self,
        ticker: str,
        bid_price: float,
        ask_price: float,
        count: int,
    ) -> tuple[Optional[dict], Optional[dict]]:
        """Place two-sided quote (yes bid + yes ask)."""
        self.cancel_market_orders(ticker)
        bid = self.place_limit_order(ticker, "yes", "buy", bid_price, count)
        ask = self.place_limit_order(ticker, "yes", "sell", ask_price, count)
        return bid, ask

    def cancel_market_orders(self, ticker: str):
        """Cancel all orders for a market."""
        if not self.client or not self.authenticated:
            return
        try:
            orders = self.client.get_orders(ticker=ticker, status="resting")
            order_list = getattr(orders, "orders", []) or []
            for o in order_list:
                oid = getattr(o, "order_id", None) or getattr(o, "id", None) or (o.get("order_id") if isinstance(o, dict) else None)
                if oid:
                    self.client.cancel_order(order_id=oid)
                    log.debug(f"Cancelled order {oid}")
        except Exception as e:
            log.warning(f"Cancel orders error: {e}")

    def cancel_all(self):
        """Cancel all open orders."""
        if not self.client or not self.authenticated:
            return
        try:
            orders = self.client.get_orders(status="resting")
            order_list = getattr(orders, "orders", []) or []
            for o in order_list:
                oid = getattr(o, "order_id", None) or getattr(o, "id", None) or (o.get("order_id") if isinstance(o, dict) else None)
                if oid:
                    self.client.cancel_order(order_id=oid)
            log.info("Cancelled all Kalshi orders")
        except Exception as e:
            log.warning(f"Cancel all error: {e}")

    def get_positions(self) -> list:
        """Get open positions."""
        if not self.client or not self.authenticated:
            return []
        try:
            resp = self.client.get_positions()
            return getattr(resp, "market_positions", []) or []
        except Exception as e:
            log.warning(f"Positions fetch error: {e}")
            return []

    def get_fills(self) -> list:
        """Get recent fills."""
        if not self.client or not self.authenticated:
            return []
        try:
            resp = self.client.get_fills()
            return getattr(resp, "fills", []) or []
        except Exception as e:
            log.warning(f"Fills fetch error: {e}")
            return []
