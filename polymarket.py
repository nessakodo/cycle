"""
Cycle Bot — Polymarket CLOB Integration
Market discovery (Gamma API), signed order placement (py-clob-client),
orderbook reads, and cancellation.
"""

import logging
import requests
from typing import Optional
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL
from config import Config

log = logging.getLogger("cycle.polymarket")

PROXIES = {}
if Config.PROXY_HTTP or Config.PROXY_HTTPS:
    PROXIES = {"http": Config.PROXY_HTTP, "https": Config.PROXY_HTTPS}
    log.info(f"Using proxies: {PROXIES}")


class PolymarketClient:
    """Wrapper around py-clob-client with Gamma API market discovery."""

    def __init__(self):
        self.client = None
        self.authenticated = False
        self.api_creds = None

    def connect(self):
        """Initialize and authenticate the CLOB client."""
        try:
            self.client = ClobClient(
                host=Config.POLY_HOST,
                key=Config.POLY_PRIVATE_KEY,
                chain_id=Config.CHAIN_ID,
            )
            self.api_creds = self.client.create_or_derive_api_creds()
            self.client.set_api_creds(self.api_creds)
            self.authenticated = True
            log.info("Polymarket CLOB client authenticated")
        except Exception as e:
            log.error(f"Polymarket auth failed: {e}")
            self.authenticated = False
            raise

    # ──────────────── Market Discovery (Gamma API) ────────────────

    def discover_markets(self, keywords: list[str], time_buckets: list[str] = None):
        """
        Find active short-term markets from Gamma API.
        Returns list of dicts: {id, question, slug, volume, tokens, spread}
        Matching is case-insensitive (question/slug lowercased).
        """
        if time_buckets is None:
            time_buckets = [
                "minute", "min", "5-minute", "15-minute", "hour",
                "5m", "15m", "1h", "m", "h",
            ]

        try:
            resp = requests.get(
                f"{Config.POLY_GAMMA}/markets",
                params={
                    "active": "true",
                    "limit": 100,
                    "order": "volume",
                    "ascending": "false",
                },
                proxies=PROXIES if PROXIES else None,
                timeout=10,
            )
            resp.raise_for_status()
            all_markets = resp.json()

            # Before filtering: log top 5 raw markets (question + slug + ID[:12])
            for i, m in enumerate((all_markets or [])[:5]):
                q = m.get("question", "No question")
                s = m.get("slug", "No slug")
                mid = (m.get("id") or m.get("condition_id") or "No ID")
                mid_short = str(mid)[:12] if mid else "No ID"
                log.info(f"Top 5 raw [{i+1}]: {q} | {s} | ID: {mid_short}...")

            matched = []
            for m in all_markets:
                question = (m.get("question", "") or "").lower()
                slug = (m.get("slug", "") or "").lower()
                combined = question + " " + slug

                kw_match = any(kw.lower() in combined for kw in keywords)
                if not kw_match:
                    continue

                bucket_match = any(tb.lower() in combined for tb in time_buckets)
                if not bucket_match:
                    continue

                tokens = m.get("tokens", [])
                if not tokens:
                    clobTokenIds = m.get("clobTokenIds", [])
                    if clobTokenIds:
                        tokens = [{"token_id": tid} for tid in clobTokenIds]

                matched.append({
                    "id": m.get("condition_id") or m.get("id"),
                    "question": m.get("question", ""),
                    "slug": m.get("slug", ""),
                    "volume": float(m.get("volume", 0) or 0),
                    "tokens": tokens,
                    "spread": float(m.get("spread", 0) or 0),
                })

            matched.sort(key=lambda x: x["volume"], reverse=True)
            log.info(f"Discovered {len(matched)} markets for {keywords}")
            for i, m in enumerate(matched):
                mid = m.get("id", "")
                mid_short = mid[:12] if mid else ""
                log.info(f"Matched market {i+1}: {m['question']} | ID: {mid_short}... | slug: {m.get('slug', '')}")
            return matched

        except Exception as e:
            log.warning(f"Market discovery error: {e}")
            return []

    def find_btc_markets(self):
        return self.discover_markets(
            keywords=[
                "bitcoin", "btc", "crypto", "price", "up", "down",
                "bin", "future", "next", "minute", "min",
                "5-minute", "15-minute", "hour", "5m", "15m", "1h",
            ],
            time_buckets=[
                "minute", "min", "5-minute", "15-minute", "hour",
                "5m", "15m", "1h", "m", "h",
            ],
        )

    def find_meme_markets(self):
        return self.discover_markets(
            keywords=[
                "pepe", "doge", "dogecoin", "shib", "shiba",
                "meme", "memecoin",
            ],
            time_buckets=[
                "minute", "min", "5-minute", "15-minute", "hour",
                "5m", "15m", "1h", "m", "h",
            ],
        )

    # ──────────────── Orderbook ────────────────

    def get_orderbook(self, token_id: str) -> Optional[dict]:
        if not self.client:
            return None
        try:
            return self.client.get_order_book(token_id)
        except Exception as e:
            log.warning(f"Orderbook fetch error for {token_id}: {e}")
            return None

    def get_midpoint(self, token_id: str) -> Optional[float]:
        if not self.client:
            return None
        try:
            return float(self.client.get_midpoint(token_id))
        except Exception as e:
            log.warning(f"Midpoint fetch error: {e}")
            return None

    # ──────────────── Order Management ────────────────

    def cancel_market_orders(self, condition_id: str):
        if not self.client or not self.authenticated:
            return
        try:
            self.client.cancel_market_orders(market=condition_id)
            log.debug(f"Cancelled orders for market {condition_id}")
        except Exception as e:
            log.warning(f"Cancel orders error: {e}")

    def cancel_all(self):
        if not self.client or not self.authenticated:
            return
        try:
            self.client.cancel_all()
            log.info("Cancelled all open orders")
        except Exception as e:
            log.warning(f"Cancel all error: {e}")

    def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> Optional[dict]:
        """
        Create, sign, and post a POST_ONLY limit order.
        POST_ONLY = always maker = always earn rebates.
        """
        if not self.client or not self.authenticated:
            log.error("Cannot place order: not authenticated")
            return None

        try:
            order_side = BUY if side.upper() == "BUY" else SELL

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side,
            )

            signed = self.client.create_order(order_args)
            result = self.client.post_order(
                signed, orderType=OrderType.GTC, post_only=True
            )

            log.info(
                f"Posted {side} order: {size:.1f} @ {price:.4f} "
                f"for token {token_id[:16]}..."
            )
            return result

        except Exception as e:
            log.warning(f"Order placement error: {e}")
            return None

    def place_quote(
        self,
        token_id: str,
        condition_id: str,
        bid_price: float,
        ask_price: float,
        size: float,
    ) -> tuple[Optional[dict], Optional[dict]]:
        """Place two-sided quote. Cancels stale orders first."""
        self.cancel_market_orders(condition_id)
        bid_result = self.place_limit_order(token_id, "BUY", bid_price, size)
        ask_result = self.place_limit_order(token_id, "SELL", ask_price, size)
        return bid_result, ask_result

    # ──────────────── Position Tracking ────────────────

    def get_positions(self) -> list:
        if not self.client or not self.authenticated:
            return []
        try:
            return self.client.get_positions() or []
        except Exception as e:
            log.warning(f"Position fetch error: {e}")
            return []

    def get_open_orders(self) -> list:
        if not self.client or not self.authenticated:
            return []
        try:
            return self.client.get_orders() or []
        except Exception as e:
            log.warning(f"Open orders fetch error: {e}")
            return []
