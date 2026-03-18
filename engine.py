"""
Cycle Bot — Quoting Engine
Multi-market market-making with signal-driven skew, inventory management,
Kraken futures hedge, meme coin auto-pivot, and real-time fill tracking.

Uses ThreadPoolExecutor for parallel quoting (cleaner shutdown than raw threads).
Includes WS fill tracker with polling fallback.
Logs funding rate every status cycle.
"""

import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from config import Config
from signals import get_composite_signal
from polymarket import PolymarketClient
from hedge import KrakenFuturesHedge
from ws_fills import FillTracker

log = logging.getLogger("cycle.engine")


class MarketState:
    """Tracks state for a single Polymarket market."""

    def __init__(self, market_info: dict, asset_type: str):
        self.market_info = market_info
        self.asset_type = asset_type
        self.condition_id = market_info["id"]
        self.question = market_info.get("question", "")
        self.volume = market_info.get("volume", 0)

        tokens = market_info.get("tokens", [])
        self.yes_token_id = tokens[0].get("token_id", "") if tokens else ""

        # Inventory (updated in real-time by FillTracker)
        self.inventory = 0.0
        self.total_buys = 0.0
        self.total_sells = 0.0
        self.quote_count = 0

        # Hedge tracking
        self.hedge_position = 0.0

    @property
    def inventory_pct(self) -> float:
        if Config.MAX_INVENTORY_USDC == 0:
            return 0
        return abs(self.inventory) / Config.MAX_INVENTORY_USDC

    @property
    def pnl_estimate(self) -> float:
        """Rough PnL from total buys vs sells."""
        return self.total_sells - self.total_buys

    def __repr__(self):
        return (
            f"Market({self.asset_type.upper()} | inv={self.inventory:.0f} "
            f"| vol={self.volume:.0f} | quotes={self.quote_count} "
            f"| pnl~${self.pnl_estimate:.1f})"
        )


class QuotingEngine:
    """
    Core engine: discovers markets, quotes in parallel, hedges, pivots.
    Uses ThreadPoolExecutor for clean parallel quoting + shutdown.
    """

    MAX_QUOTE_WORKERS = 4  # max parallel quoting threads

    def __init__(self):
        self.poly = PolymarketClient()
        self.hedge_client = KrakenFuturesHedge()
        self.markets: dict[str, MarketState] = {}
        self.running = False
        self._lock = threading.Lock()
        self.fill_tracker = None
        self._executor = None

    def start(self):
        """Initialize connections and start all loops."""
        log.info("Starting Cycle quoting engine...")

        # Connect to Polymarket
        self.poly.connect()

        # Discover initial markets
        self._refresh_markets()

        if not self.markets:
            log.warning("No markets found. Will retry on next pivot cycle.")

        self.running = True

        # Thread pool for parallel quoting
        self._executor = ThreadPoolExecutor(
            max_workers=self.MAX_QUOTE_WORKERS, thread_name_prefix="quote"
        )

        # Start real-time fill tracker (WS + polling fallback)
        self.fill_tracker = FillTracker(
            inventories=self.markets,
            lock=self._lock,
            poly_client=self.poly,
        )
        self.fill_tracker.start()

        # Start background loops
        threads = [
            threading.Thread(
                target=self._quote_loop, daemon=True, name="quoter"
            ),
            threading.Thread(
                target=self._pivot_loop, daemon=True, name="pivoter"
            ),
            threading.Thread(
                target=self._status_loop, daemon=True, name="status"
            ),
        ]
        for t in threads:
            t.start()

        log.info(f"Engine running with {len(self.markets)} market(s)")
        return threads

    def stop(self):
        """Graceful shutdown: cancel orders, close WS, shut down pool."""
        log.info("Stopping engine...")
        self.running = False

        # Stop fill tracker (closes WS)
        if self.fill_tracker:
            self.fill_tracker.stop()

        # Shut down thread pool
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
            log.info("Thread pool shut down")

        # Cancel all Polymarket orders
        try:
            self.poly.cancel_all()
            log.info("All Polymarket orders cancelled")
        except Exception as e:
            log.error(f"Error cancelling orders: {e}")

        log.info("Engine stopped")

    # ──────────────── Market Discovery & Pivot ────────────────

    def _refresh_markets(self):
        """Discover and select best markets (BTC + top meme)."""
        with self._lock:
            btc_markets = self.poly.find_btc_markets()
            meme_markets = self.poly.find_meme_markets()

            new_markets = {}

            # TEMP FOR DEBUG — replace with real IDs from polymarket.com inspect / Gamma API
            if not btc_markets and not meme_markets:
                fallback = [
                    {"id": "PLACEHOLDER_BTC_5MIN_ID", "question": "BTC up or down in next 5 minutes?", "tokens": [{"token_id": "PLACEHOLDER_YES_TOKEN_ID"}]},
                    {"id": "PLACEHOLDER_PEPE_15MIN_ID", "question": "PEPE up or down in next 15 minutes?", "tokens": [{"token_id": "PLACEHOLDER_YES_TOKEN_ID"}]},
                ]
                for m in fallback:
                    if m["id"] not in self.markets:
                        asset_type = "btc" if "btc" in m["question"].lower() else "pepe"
                        self.markets[m["id"]] = MarketState(m, asset_type)
                log.info("No markets discovered — using fallback test markets (temporary)")
                new_markets = dict(self.markets)

            # Always include top BTC market
            if btc_markets:
                m = btc_markets[0]
                cid = m["id"]
                if cid in self.markets:
                    new_markets[cid] = self.markets[cid]
                    new_markets[cid].market_info = m
                    new_markets[cid].volume = m.get("volume", 0)
                else:
                    new_markets[cid] = MarketState(m, "btc")
                log.info(f"BTC market: {m.get('question', '')[:60]}...")

            # Add top meme if it beats BTC on volume or spread
            if meme_markets:
                best_meme = meme_markets[0]
                btc_vol = btc_markets[0].get("volume", 0) if btc_markets else 0

                if (
                    best_meme.get("volume", 0) > btc_vol * 1.3
                    or best_meme.get("spread", 0) > 0.008
                    or not btc_markets
                ):
                    cid = best_meme["id"]
                    asset = self._detect_asset_type(best_meme)
                    if cid in self.markets:
                        new_markets[cid] = self.markets[cid]
                    else:
                        new_markets[cid] = MarketState(best_meme, asset)
                    log.info(
                        f"MEME pivot: {best_meme.get('question', '')[:60]}... "
                        f"(vol={best_meme.get('volume', 0):.0f})"
                    )

            # Cancel orders for markets we're exiting
            for old_cid in self.markets:
                if old_cid not in new_markets:
                    self.poly.cancel_market_orders(old_cid)
                    log.info(f"Exited market {old_cid}")

            self.markets = new_markets

            # Update fill tracker reference
            if self.fill_tracker:
                self.fill_tracker.inventories = self.markets

    def _detect_asset_type(self, market_info: dict) -> str:
        text = (
            market_info.get("question", "")
            + " "
            + market_info.get("slug", "")
        ).lower()
        if "pepe" in text:
            return "pepe"
        if "doge" in text or "dogecoin" in text:
            return "doge"
        if "shib" in text:
            return "shib"
        if "eth" in text or "ethereum" in text:
            return "eth"
        return "btc"

    # ──────────────── Quoting Logic ────────────────

    def _compute_quotes(self, state: MarketState) -> Optional[tuple[float, float]]:
        """Compute bid/ask for a market. Returns (bid, ask) or None."""
        if not state.yes_token_id:
            return None

        book = self.poly.get_orderbook(state.yes_token_id)
        if not book:
            return None

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            mid = self.poly.get_midpoint(state.yes_token_id)
            if mid is None:
                return None
        else:
            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 0))
            if best_bid <= 0 or best_ask <= 0:
                return None
            mid = (best_bid + best_ask) / 2

        # Signal skew
        sig = get_composite_signal(state.asset_type)
        half_spread = Config.SPREAD_BPS / 20000
        skew = 0.001 * sig

        bid_price = mid - half_spread + skew
        ask_price = mid + half_spread - skew

        # Inventory skew: lean against position
        if state.inventory > Config.MAX_INVENTORY_USDC * 0.5:
            inv_adj = 0.002 * (state.inventory_pct - 0.5)
            bid_price -= inv_adj
        elif state.inventory < -Config.MAX_INVENTORY_USDC * 0.5:
            inv_adj = 0.002 * (abs(state.inventory) / Config.MAX_INVENTORY_USDC - 0.5)
            ask_price += inv_adj

        # Clamp to valid Polymarket range
        bid_price = max(0.01, min(0.99, round(bid_price, 4)))
        ask_price = max(0.01, min(0.99, round(ask_price, 4)))

        # Sanity: bid < ask
        if bid_price >= ask_price:
            bid_price = round(mid - half_spread, 4)
            ask_price = round(mid + half_spread, 4)

        return bid_price, ask_price

    def _quote_market(self, state: MarketState):
        """Execute one quoting cycle for a single market."""
        quotes = self._compute_quotes(state)
        if quotes is None:
            log.debug(f"Skipping quote for {state.asset_type}: no data")
            return

        bid_price, ask_price = quotes
        size = Config.QUOTE_SIZE_USDC

        if Config.PAPER_MODE:
            log.info(
                f"[PAPER] {state.asset_type.upper()} | "
                f"BID {bid_price:.4f} ASK {ask_price:.4f} | "
                f"Inv {state.inventory:.0f} | Size {size:.0f}"
            )
            state.quote_count += 1
            return

        bid_result, ask_result = self.poly.place_quote(
            token_id=state.yes_token_id,
            condition_id=state.condition_id,
            bid_price=bid_price,
            ask_price=ask_price,
            size=size,
        )

        state.quote_count += 1

        log.info(
            f"LIVE {state.asset_type.upper()} | "
            f"BID {bid_price:.4f} ASK {ask_price:.4f} | "
            f"Inv {state.inventory:.0f}"
        )

    def _check_hedge(self, state: MarketState):
        """Hedge inventory skew on Kraken Futures if threshold breached."""
        threshold = Config.MAX_INVENTORY_USDC * Config.INV_SKEW_THRESHOLD
        if abs(state.inventory) < threshold:
            return

        direction = "sell" if state.inventory > 0 else "buy"
        size_usd = abs(state.inventory) * 0.5

        result = self.hedge_client.place_hedge(
            asset_type=state.asset_type,
            direction=direction,
            size_usd=size_usd,
        )

        if result:
            adj = size_usd if direction == "buy" else -size_usd
            state.hedge_position += adj

    # ──────────────── Main Loops ────────────────

    def _quote_loop(self):
        """
        Main quoting loop — uses ThreadPoolExecutor for parallel quoting.
        Submits all markets simultaneously, waits for completion.
        """
        log.info(f"Quote loop started (every {Config.QUOTE_INTERVAL_SEC}s)")
        while self.running:
            try:
                with self._lock:
                    market_states = list(self.markets.values())

                if not market_states:
                    time.sleep(Config.QUOTE_INTERVAL_SEC)
                    continue

                # Submit all markets to thread pool in parallel
                futures = {
                    self._executor.submit(
                        self._safe_quote_and_hedge, state
                    ): state
                    for state in market_states
                }

                # Wait for all to complete (with timeout)
                for future in as_completed(
                    futures, timeout=Config.QUOTE_INTERVAL_SEC
                ):
                    state = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        log.error(
                            f"Quote future error ({state.asset_type}): {e}"
                        )

            except Exception as e:
                log.error(f"Quote loop error: {e}", exc_info=True)

            time.sleep(Config.QUOTE_INTERVAL_SEC)

    def _safe_quote_and_hedge(self, state: MarketState):
        """Quote + hedge for one market, with error isolation."""
        try:
            self._quote_market(state)
            self._check_hedge(state)
        except Exception as e:
            log.error(
                f"Error quoting {state.asset_type}: {e}", exc_info=True
            )

    def _pivot_loop(self):
        """Market refresh/pivot — runs every PIVOT_INTERVAL_SEC."""
        log.info(f"Pivot loop started (every {Config.PIVOT_INTERVAL_SEC}s)")
        while self.running:
            time.sleep(Config.PIVOT_INTERVAL_SEC)
            try:
                self._refresh_markets()
            except Exception as e:
                log.error(f"Pivot loop error: {e}", exc_info=True)

    def _status_loop(self):
        """Periodic status + funding rate log — every 60 seconds."""
        while self.running:
            time.sleep(60)
            try:
                with self._lock:
                    if not self.markets:
                        log.info("No active markets")
                        continue

                    for cid, state in self.markets.items():
                        log.info(f"  {state}")

                        # Funding rate per asset
                        funding = self.hedge_client.get_funding_rate_for_asset(
                            state.asset_type
                        )
                        symbol = self.hedge_client.SYMBOL_MAP.get(
                            state.asset_type, "?"
                        )
                        log.info(
                            f"  Funding {symbol}: {funding:.6f} "
                            f"({'OK' if funding <= Config.MAX_FUNDING_RATE else 'HIGH - hedge paused'})"
                        )

                    # Fill tracker status
                    if self.fill_tracker:
                        ws_status = (
                            "connected" if self.fill_tracker.connected
                            else "disconnected (polling fallback active)"
                        )
                        log.info(f"  Fill WS: {ws_status}")

            except Exception as e:
                log.debug(f"Status loop error: {e}")
