"""
Cycle Bot — Real-time Fill Tracking via WebSocket
Subscribes to Polymarket WS for user fills so inventory
updates instantly (no polling lag).

Includes polling fallback: if WS disconnects or auth fails,
polls get_trades() every 30s to sync inventory.
"""

import json
import time
import logging
import threading
import websocket
from config import Config

log = logging.getLogger("cycle.ws_fills")


class FillTracker:
    """
    Connects to Polymarket WebSocket and listens for fill events.
    Updates inventory dict in-place when fills arrive.

    Fallback: if WS is disconnected for >60s, polls REST API
    to sync inventory (prevents silent drift).
    """

    POLL_INTERVAL = 30  # seconds between fallback polls
    WS_GRACE_PERIOD = 60  # seconds before switching to polling

    def __init__(self, inventories: dict, lock: threading.Lock, poly_client=None):
        """
        inventories: dict of condition_id -> MarketState (shared ref)
        lock: threading.Lock for thread-safe updates
        poly_client: PolymarketClient instance for fallback polling
        """
        self.inventories = inventories
        self.lock = lock
        self.poly_client = poly_client
        self.ws = None
        self.connected = False
        self._ws_thread = None
        self._poll_thread = None
        self._last_connected = 0.0
        self._running = False

    def start(self):
        """Start WS listener + polling fallback in background threads."""
        self._running = True

        self._ws_thread = threading.Thread(
            target=self._ws_loop, daemon=True, name="fill-ws"
        )
        self._ws_thread.start()

        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="fill-poll"
        )
        self._poll_thread.start()

        log.info("Fill tracker started (WS + polling fallback)")

    def stop(self):
        """Close WS and stop polling."""
        self._running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.connected = False

    # ──────────────── WebSocket (Primary) ────────────────

    def _ws_loop(self):
        """Main WS loop with auto-reconnect."""
        while self._running:
            try:
                self.ws = websocket.WebSocketApp(
                    Config.POLY_WS,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                log.warning(f"Fill WS error, reconnecting in 5s: {e}")

            if self._running:
                time.sleep(5)

    def _on_open(self, ws):
        self.connected = True
        self._last_connected = time.time()
        log.info("Fill WS connected")

        sub_msg = {
            "type": "subscribe",
            "channel": "user",
            "markets": [],
        }
        ws.send(json.dumps(sub_msg))
        log.debug("Subscribed to user fills channel")

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type in ("trade", "fill", "order_fill"):
                self._process_fill(data)
            elif msg_type in ("order_update", "order"):
                self._process_order_update(data)

        except json.JSONDecodeError:
            log.debug(f"Non-JSON WS message: {message[:100]}")
        except Exception as e:
            log.warning(f"Fill message processing error: {e}")

    def _process_fill(self, data):
        asset_id = (
            data.get("asset_id")
            or data.get("market")
            or data.get("condition_id")
        )
        side = data.get("side", "").upper()
        size = float(data.get("size", 0) or data.get("matchSize", 0))
        price = float(data.get("price", 0) or data.get("matchPrice", 0))

        if not asset_id or not side or size == 0:
            return

        with self.lock:
            for cid, state in self.inventories.items():
                if cid == asset_id or state.yes_token_id == asset_id:
                    delta = size if side == "BUY" else -size
                    old_inv = state.inventory
                    state.inventory += delta

                    if side == "BUY":
                        state.total_buys += size * price
                    else:
                        state.total_sells += size * price

                    log.info(
                        f"FILL [WS]: {side} {size:.1f} @ {price:.4f} on "
                        f"{state.asset_type.upper()} | "
                        f"Inv {old_inv:.0f} -> {state.inventory:.0f}"
                    )
                    break

    def _process_order_update(self, data):
        status = data.get("status", "")
        order_id = data.get("id", "")[:12]
        if status in ("CANCELLED", "EXPIRED", "MATCHED"):
            log.debug(f"Order {order_id}... status: {status}")

    def _on_error(self, ws, error):
        log.warning(f"Fill WS error: {error}")
        self.connected = False

    def _on_close(self, ws, close_status, close_msg):
        log.info(f"Fill WS closed: {close_status} {close_msg}")
        self.connected = False

    # ──────────────── Polling Fallback ────────────────

    def _poll_loop(self):
        """
        Fallback: if WS has been disconnected for > WS_GRACE_PERIOD,
        poll Polymarket REST API for recent trades to sync inventory.
        Always runs but only acts when WS is down.
        """
        log.info(
            f"Polling fallback started (activates if WS down > "
            f"{self.WS_GRACE_PERIOD}s)"
        )
        while self._running:
            time.sleep(self.POLL_INTERVAL)

            if self.connected:
                continue  # WS is healthy, skip polling

            ws_downtime = time.time() - self._last_connected
            if ws_downtime < self.WS_GRACE_PERIOD:
                continue  # within grace period, give WS time to reconnect

            if not self.poly_client:
                continue

            log.info(
                f"WS down for {ws_downtime:.0f}s — polling for fills"
            )
            self._poll_fills()

    def _poll_fills(self):
        """Fetch recent trades from REST API and reconcile inventory."""
        try:
            positions = self.poly_client.get_positions()
            if not positions:
                return

            with self.lock:
                for pos in positions:
                    asset_id = (
                        pos.get("asset_id")
                        or pos.get("market")
                        or pos.get("condition_id", "")
                    )
                    size = float(pos.get("size", 0))

                    for cid, state in self.inventories.items():
                        if cid == asset_id or state.yes_token_id == asset_id:
                            old_inv = state.inventory
                            if abs(state.inventory - size) > 0.01:
                                state.inventory = size
                                log.info(
                                    f"SYNC [POLL]: {state.asset_type.upper()} "
                                    f"inv {old_inv:.0f} -> {state.inventory:.0f}"
                                )
                            break

        except Exception as e:
            log.warning(f"Polling fallback error: {e}")
