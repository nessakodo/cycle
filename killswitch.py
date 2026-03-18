#!/usr/bin/env python3
"""
Cycle Bot — Emergency Killswitch
Cancels ALL open Polymarket orders and closes ALL Kraken futures hedges.

Usage:
    python killswitch.py              # cancel orders only
    python killswitch.py --hedge      # cancel orders + close hedge positions
    python killswitch.py --stop       # cancel + close + stop systemd service

Run this if something goes wrong and you need everything flat immediately.
"""

import sys
import subprocess
import logging
from config import Config
from polymarket import PolymarketClient
from hedge import KrakenFuturesHedge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [KILLSWITCH] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger()


def cancel_all_poly_orders():
    """Cancel every open order on Polymarket."""
    log.info("Connecting to Polymarket...")
    try:
        poly = PolymarketClient()
        poly.connect()
        log.info("Cancelling all open orders...")
        poly.cancel_all()
        log.info("All Polymarket orders cancelled.")
    except Exception as e:
        log.error(f"Polymarket cancel failed: {e}")
        log.info("Try manually: go to polymarket.com -> open orders -> cancel all")


def close_kraken_hedges():
    """Close all open Kraken futures positions."""
    log.info("Connecting to Kraken Futures...")
    try:
        hedge = KrakenFuturesHedge()
        positions = hedge.get_open_positions()

        if not positions:
            log.info("No open Kraken positions to close.")
            return

        log.info(f"Found {len(positions)} open position(s), closing...")
        for pos in positions:
            symbol = pos.get("symbol", "")
            side = pos.get("side", "")
            size = float(pos.get("size", 0))
            if size > 0:
                opposite = "sell" if side == "long" else "buy"
                try:
                    hedge.trade.create_order(
                        orderType="mkt",
                        size=size,
                        symbol=symbol,
                        side=opposite,
                        reduceOnly=True,
                    )
                    log.info(f"Closed {side} {size} on {symbol}")
                except Exception as e:
                    log.error(f"Failed to close {symbol}: {e}")

        log.info("All Kraken hedges closed.")
    except Exception as e:
        log.error(f"Kraken close failed: {e}")
        log.info("Close manually: Kraken Pro -> Futures -> close all positions")


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
    print("=" * 50)
    print()

    # Always cancel Polymarket orders
    cancel_all_poly_orders()

    # Close hedges if --hedge or --stop
    if "--hedge" in args or "--stop" in args:
        close_kraken_hedges()

    # Stop service if --stop
    if "--stop" in args:
        stop_service()

    print()
    log.info("Killswitch complete. All positions should be flat.")
    print()


if __name__ == "__main__":
    main()
