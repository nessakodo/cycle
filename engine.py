"""
Cycle Bot — Quoting Engine
Kalshi market-making with signal-driven skew, Tradier margin execution,
Odds API enrichment, and real-time fill tracking.

US-legal: Kalshi (CFTC) + Tradier (Reg T) + Odds API.
"""

import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from config import Config
from signals import get_composite_signal
from kalshi import KalshiClient
from tradier import TradierClient
from ws_fills_kalshi import KalshiFillTracker

log = logging.getLogger("cycle.engine")


class MarketState:
    """Tracks state for a single Kalshi market."""

    def __init__(self, market_info: dict, asset_type: str):
        self.market_info = market_info
        self.asset_type = asset_type
        self.condition_id = market_info.get("ticker", market_info.get("id", ""))
        self.ticker = self.condition_id
        self.question = market_info.get("question", "")
        self.volume = market_info.get("volume", 0)

        # Inventory (updated by KalshiFillTracker)
        self.inventory = 0.0
        self.total_buys = 0.0
        self.total_sells = 0.0
        self.quote_count = 0
        self.hedge_position = 0.0

    @property
    def inventory_pct(self) -> float:
        if Config.MAX_INVENTORY_USDC == 0:
            return 0
        return abs(self.inventory) / Config.MAX_INVENTORY_USDC

    @property
    def pnl_estimate(self) -> float:
        return self.total_sells - self.total_buys

    def __repr__(self):
        return (
            f"Market({self.asset_type.upper()} | inv={self.inventory:.0f} "
            f"| vol={self.volume:.0f} | quotes={self.quote_count} "
            f"| pnl~${self.pnl_estimate:.1f})"
        )


class QuotingEngine:
    """
    Core engine: Kalshi markets, Tradier margin, Odds API signals.
    """

    MAX_QUOTE_WORKERS = 4

    def __init__(self):
        self.kalshi = KalshiClient()
        self.tradier = TradierClient()
        self.markets: dict[str, MarketState] = {}
        self.running = False
        self._lock = threading.Lock()
        self.fill_tracker = None
        self._executor = None

    def start(self):
        """Initialize connections and start all loops."""
        log.info("Starting Cycle quoting engine (US-legal mode)...")

        self.kalshi.connect()
        self._refresh_markets()

        if not self.markets:
            log.warning("No markets found. Will retry on next pivot cycle.")

        self.running = True
        self._executor = ThreadPoolExecutor(
            max_workers=self.MAX_QUOTE_WORKERS,
            thread_name_prefix="quote",
        )

        self.fill_tracker = KalshiFillTracker(
            inventories=self.markets,
            lock=self._lock,
            kalshi_client=self.kalshi,
        )
        self.fill_tracker.start()

        threads = [
            threading.Thread(target=self._quote_loop, daemon=True, name="quoter"),
            threading.Thread(target=self._pivot_loop, daemon=True, name="pivoter"),
            threading.Thread(target=self._status_loop, daemon=True, name="status"),
        ]
        for t in threads:
            t.start()

        log.info(f"Engine running with {len(self.markets)} market(s)")
        return threads

    def stop(self):
        """Graceful shutdown."""
        log.info("Stopping engine...")
        self.running = False
        if self.fill_tracker:
            self.fill_tracker.stop()
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
        try:
            self.kalshi.cancel_all()
            log.info("All Kalshi orders cancelled")
        except Exception as e:
            log.error(f"Error cancelling orders: {e}")
        log.info("Engine stopped")

    def _refresh_markets(self):
        """Discover and select Kalshi markets."""
        with self._lock:
            all_markets = self.kalshi.discover_markets(limit=50)
            new_markets = {}

            # Use MANUAL_KALSHI_TICKERS if discovery is empty
            if not all_markets and Config.MANUAL_KALSHI_TICKERS:
                for ticker in Config.MANUAL_KALSHI_TICKERS:
                    m = {"ticker": ticker, "id": ticker, "question": ticker, "volume": 0}
                    new_markets[ticker] = MarketState(m, self._detect_asset_type(m))
                log.info(
                    f"Using {len(new_markets)} manual ticker(s): "
                    f"{', '.join(Config.MANUAL_KALSHI_TICKERS)}"
                )
            else:
                for m in all_markets:
                    cid = m.get("ticker", m.get("id", ""))
                    if cid and cid not in new_markets:
                        asset = self._detect_asset_type(m)
                        new_markets[cid] = MarketState(m, asset)

            n = len(new_markets)
            if n > 0:
                first_three = list(new_markets.items())[:3]
                for cid, state in first_three:
                    log.info(f"Kalshi market: {cid} — {state.question[:50]}...")
                log.info(f"Kalshi discovery: {n} market(s) found")
            else:
                log.warning(
                    "Kalshi discovery empty — add MANUAL_KALSHI_TICKERS in .env "
                    "or switch to live API"
                )

            for old_cid in self.markets:
                if old_cid not in new_markets:
                    self.kalshi.cancel_market_orders(old_cid)

            self.markets = new_markets
            if self.fill_tracker:
                self.fill_tracker.inventories = self.markets

    def _detect_asset_type(self, market_info: dict) -> str:
        text = (market_info.get("question", "") + " " + market_info.get("ticker", "")).lower()
        if "btc" in text or "bitcoin" in text:
            return "btc"
        if "eth" in text or "ethereum" in text:
            return "eth"
        if "trump" in text or "biden" in text:
            return "politics"
        return "general"

    def _compute_quotes(self, state: MarketState) -> Optional[tuple[float, float]]:
        """Compute bid/ask for a Kalshi market."""
        book = self.kalshi.get_orderbook(state.ticker)
        if not book:
            mid = self.kalshi.get_midpoint(state.ticker)
            if mid is None:
                return None
        else:
            yes_bids = book.get("yes_bids", [])
            no_bids = book.get("no_bids", [])
            if yes_bids:
                best_yes = yes_bids[0][0]
                best_no_implied = 1.0 - (no_bids[0][0] if no_bids else 0.5)
                mid = (best_yes + best_no_implied) / 2
            elif no_bids:
                mid = 1.0 - no_bids[0][0]
            else:
                mid = self.kalshi.get_midpoint(state.ticker) or 0.5

        sig = get_composite_signal(state.asset_type)
        half_spread = Config.SPREAD_BPS / 20000
        skew = 0.001 * sig

        bid_price = mid - half_spread + skew
        ask_price = mid + half_spread - skew

        if state.inventory > Config.MAX_INVENTORY_USDC * 0.5:
            bid_price -= 0.002 * (state.inventory_pct - 0.5)
        elif state.inventory < -Config.MAX_INVENTORY_USDC * 0.5:
            ask_price += 0.002 * (abs(state.inventory) / Config.MAX_INVENTORY_USDC - 0.5)

        bid_price = max(0.01, min(0.99, round(bid_price, 4)))
        ask_price = max(0.01, min(0.99, round(ask_price, 4)))
        if bid_price >= ask_price:
            bid_price = round(mid - half_spread, 4)
            ask_price = round(mid + half_spread, 4)

        return bid_price, ask_price

    def _quote_market(self, state: MarketState):
        """Execute one quoting cycle."""
        quotes = self._compute_quotes(state)
        if quotes is None:
            return
        bid_price, ask_price = quotes
        size = Config.QUOTE_SIZE_CONTRACTS

        if Config.PAPER_MODE:
            log.info(
                f"[PAPER] {state.asset_type.upper()} | "
                f"BID {bid_price:.4f} ASK {ask_price:.4f} | "
                f"Inv {state.inventory:.0f} | Size {size}"
            )
            state.quote_count += 1
            return

        self.kalshi.place_quote(
            ticker=state.ticker,
            bid_price=bid_price,
            ask_price=ask_price,
            count=size,
        )
        state.quote_count += 1
        log.info(
            f"LIVE {state.asset_type.upper()} | "
            f"BID {bid_price:.4f} ASK {ask_price:.4f} | Inv {state.inventory:.0f}"
        )

    def _check_tradier_hedge(self, state: MarketState):
        """Execute Tradier margin trade when inventory skew is high."""
        threshold = Config.MAX_INVENTORY_USDC * Config.INV_SKEW_THRESHOLD
        if abs(state.inventory) < threshold:
            return
        if not Config.TRADIER_ACCESS_TOKEN or not Config.TRADIER_ACCOUNT_ID:
            return

        direction = "sell" if state.inventory > 0 else "buy"
        size_usd = abs(state.inventory) * 0.5

        # Map asset to Tradier symbol
        symbol_map = {"btc": "BTC", "eth": "ETH", "politics": "SPY", "general": "SPY"}
        symbol = symbol_map.get(state.asset_type, "SPY")

        result = self.tradier.place_margin_trade(
            symbol=symbol,
            direction=direction,
            size_usd=size_usd,
        )
        if result:
            adj = size_usd if direction == "buy" else -size_usd
            state.hedge_position += adj

    def _quote_loop(self):
        log.info(f"Quote loop started (every {Config.QUOTE_INTERVAL_SEC}s)")
        while self.running:
            try:
                with self._lock:
                    market_states = list(self.markets.values())
                if not market_states:
                    time.sleep(Config.QUOTE_INTERVAL_SEC)
                    continue
                futures = {
                    self._executor.submit(self._safe_quote_and_hedge, s): s
                    for s in market_states
                }
                for future in as_completed(futures, timeout=Config.QUOTE_INTERVAL_SEC):
                    try:
                        future.result()
                    except Exception as e:
                        log.error(f"Quote future error: {e}")
            except Exception as e:
                log.error(f"Quote loop error: {e}", exc_info=True)
            time.sleep(Config.QUOTE_INTERVAL_SEC)

    def _safe_quote_and_hedge(self, state: MarketState):
        try:
            self._quote_market(state)
            self._check_tradier_hedge(state)
        except Exception as e:
            log.error(f"Error quoting {state.asset_type}: {e}", exc_info=True)

    def _pivot_loop(self):
        log.info(f"Pivot loop started (every {Config.PIVOT_INTERVAL_SEC}s)")
        while self.running:
            time.sleep(Config.PIVOT_INTERVAL_SEC)
            try:
                self._refresh_markets()
            except Exception as e:
                log.error(f"Pivot loop error: {e}", exc_info=True)

    def _status_loop(self):
        while self.running:
            time.sleep(60)
            try:
                with self._lock:
                    if not self.markets:
                        log.info("No active markets")
                        continue
                    for cid, state in self.markets.items():
                        log.info(f"  {state}")
            except Exception as e:
                log.debug(f"Status loop error: {e}")
