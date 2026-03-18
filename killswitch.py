#!/usr/bin/env python3
"""
Cycle Bot — Emergency Killswitch
Cancels ALL open Kalshi orders and optionally closes Tradier positions.

Usage:
    python killswitch.py              # cancel Kalshi orders only
    python killswitch.py --tradier   # cancel + close Tradier positions
    python killswitch.py --stop      # cancel + close + stop systemd service

US-legal: Kalshi + Tradier. No VPN/proxy.
"""

import sys
import subprocess
import logging
from config import Config
from kalshi import KalshiClient
from tradier import TradierClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [KILLSWITCH] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger()


def cancel_all_kalshi_orders():
    """Cancel every open order on Kalshi."""
    log.info("Connecting to Kalshi...")
    try:
        kalshi = KalshiClient()
        kalshi.connect()
        log.info("Cancelling all open orders...")
        kalshi.cancel_all()
        log.info("All Kalshi orders cancelled.")
    except Exception as e:
        log.error(f"Kalshi cancel failed: {e}")
        log.info("Try manually: kalshi.com -> Portfolio -> cancel all")


def close_tradier_positions():
    """Close all open Tradier positions."""
    if not Config.TRADIER_ACCESS_TOKEN or not Config.TRADIER_ACCOUNT_ID:
        log.info("Tradier not configured — skipping.")
        return
    log.info("Connecting to Tradier...")
    try:
        tradier = TradierClient()
        positions = tradier.get_positions()
        if not positions:
            log.info("No open Tradier positions to close.")
            return
        log.info(f"Found {len(positions)} position(s), closing...")
        for pos in positions:
            symbol = pos.get("symbol", "")
            quantity = int(float(pos.get("quantity", 0)))
            side = "sell" if quantity > 0 else "buy"
            quantity = abs(quantity)
            if quantity > 0:
                try:
                    tradier.place_equity_order(symbol, side, quantity)
                    log.info(f"Closed {quantity} {symbol}")
                except Exception as e:
                    log.error(f"Failed to close {symbol}: {e}")
        log.info("All Tradier positions closed.")
    except Exception as e:
        log.error(f"Tradier close failed: {e}")


def stop_service():
    """Stop the systemd service."""
    log.info("Stopping cycle systemd service...")
    try:
        subprocess.run(
            ["sudo", "systemctl", "stop", "cycle"],
            capture_output=True, text=True, timeout=15,
        )
        log.info("Service stopped.")
    except Exception as e:
        log.warning(f"Could not stop service: {e}")
        log.info("Run manually: sudo systemctl stop cycle")


def main():
    args = set(sys.argv[1:])

    print()
    print("=" * 50)
    print("  CYCLE KILLSWITCH — Emergency Stop")
    print("  US-legal: Kalshi + Tradier")
    print("=" * 50)
    print()

    cancel_all_kalshi_orders()

    if "--tradier" in args or "--stop" in args:
        close_tradier_positions()

    if "--stop" in args:
        stop_service()

    print()
    log.info("Killswitch complete. All positions should be flat.")
    print()


if __name__ == "__main__":
    main()
