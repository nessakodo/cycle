"""
Cycle Bot — Kalshi Fill Tracking
Polls Kalshi REST API for fills to update inventory.
(Kalshi WS user-fills available with auth; polling is simpler fallback.)
"""

import time
import logging
import threading

log = logging.getLogger("cycle.ws_fills_kalshi")


class KalshiFillTracker:
    """
    Polls Kalshi get_fills() to sync inventory.
    Updates MarketState.inventory when fills arrive.
    """

    POLL_INTERVAL = 30

    def __init__(self, inventories: dict, lock: threading.Lock, kalshi_client=None):
        self.inventories = inventories
        self.lock = lock
        self.kalshi_client = kalshi_client
        self._seen_fill_ids = set()
        self._running = False
        self._thread = None

    def start(self):
        """Start polling in background."""
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="kalshi-fill-poll",
        )
        self._thread.start()
        log.info("Kalshi fill tracker started (polling)")

    def stop(self):
        """Stop polling."""
        self._running = False

    def _poll_loop(self):
        while self._running:
            time.sleep(self.POLL_INTERVAL)
            if not self.kalshi_client or not self.kalshi_client.authenticated:
                continue
            self._poll_fills()

    def _poll_fills(self):
        try:
            fills = self.kalshi_client.get_fills()
            if not fills:
                return
            with self.lock:
                for f in fills:
                    fid = getattr(f, "id", None) or f.get("id") or f.get("fill_id")
                    if fid and fid in self._seen_fill_ids:
                        continue
                    if fid:
                        self._seen_fill_ids.add(fid)
                    ticker = getattr(f, "ticker", None) or f.get("ticker", "")
                    side = (getattr(f, "side", None) or f.get("side", "yes")).lower()
                    action = (getattr(f, "action", None) or f.get("action", "buy")).lower()
                    count = float(getattr(f, "count", 0) or f.get("count", 0))
                    price = float(getattr(f, "yes_price", 0) or f.get("yes_price", 0) or 0) / 100.0
                    if not ticker or count == 0:
                        continue
                    for cid, state in self.inventories.items():
                        if cid == ticker or getattr(state, "condition_id", "") == ticker:
                            delta = count if action == "buy" else -count
                            if side == "no":
                                delta = -delta
                            old_inv = state.inventory
                            state.inventory += delta
                            if action == "buy":
                                state.total_buys += count * price
                            else:
                                state.total_sells += count * price
                            log.info(
                                f"FILL [POLL]: {action} {count:.0f} @ {price:.2f} "
                                f"on {state.asset_type.upper()} | "
                                f"Inv {old_inv:.0f} -> {state.inventory:.0f}"
                            )
                            break
        except Exception as e:
            log.warning(f"Kalshi fill poll error: {e}")
