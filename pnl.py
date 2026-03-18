#!/usr/bin/env python3
"""
Cycle Bot — Daily PnL Reporter
Fetches fills from Kalshi + Tradier and summarizes PnL.

Usage:
    python pnl.py              # today's PnL
    python pnl.py --verbose   # detailed breakdown

US-legal: Kalshi + Tradier.
"""

import sys
import logging
from datetime import datetime
from config import Config
from kalshi import KalshiClient
from tradier import TradierClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger()

VERBOSE = "--verbose" in sys.argv


def get_kalshi_pnl():
    """Fetch Kalshi fills and compute PnL."""
    try:
        kalshi = KalshiClient()
        kalshi.connect()
        fills = kalshi.get_fills()
        if not fills:
            log.info("  No Kalshi fills found.")
            return 0.0, 0, 0.0, 0.0

        total_buys = 0.0
        total_sells = 0.0
        count = 0
        for f in fills:
            action = (getattr(f, "action", None) or f.get("action", "buy")).lower()
            count_fp = getattr(f, "count_fp", None) or f.get("count_fp", "0") or f.get("count", 0)
            count_val = float(count_fp) if isinstance(count_fp, str) else float(count_fp or 0)
            yes_price = float(getattr(f, "yes_price", 0) or f.get("yes_price", 0) or 0) / 100.0
            value = count_val * yes_price
            if action == "buy":
                total_buys += value
            else:
                total_sells += value
            count += 1
            if VERBOSE:
                log.info(f"    {action} {count_val:.0f} @ {yes_price:.2f} = ${value:.2f}")

        pnl = total_sells - total_buys
        return pnl, count, total_buys, total_sells
    except Exception as e:
        log.warning(f"  Kalshi PnL error: {e}")
        return 0.0, 0, 0.0, 0.0


def get_tradier_pnl():
    """Fetch Tradier positions PnL."""
    if not Config.TRADIER_ACCESS_TOKEN or not Config.TRADIER_ACCOUNT_ID:
        return 0.0, 0
    try:
        tradier = TradierClient()
        positions = tradier.get_positions()
        if not positions:
            log.info("  No Tradier positions found.")
            return 0.0, 0
        total_pnl = 0.0
        for p in positions:
            cost = float(p.get("cost_basis", 0) or 0)
            value = float(p.get("market_value", 0) or p.get("current_value", 0) or 0)
            total_pnl += value - cost
            if VERBOSE:
                log.info(f"    {p.get('symbol')} | cost ${cost:.2f} value ${value:.2f}")
        return total_pnl, len(positions)
    except Exception as e:
        log.warning(f"  Tradier PnL error: {e}")
        return 0.0, 0


def main():
    print()
    print("=" * 55)
    print(f"  CYCLE PnL Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("  US-legal: Kalshi + Tradier")
    print("=" * 55)
    print()

    print("  Kalshi (spread capture):")
    kalshi_pnl, kalshi_count, buys, sells = get_kalshi_pnl()
    print(f"    Fills:      {kalshi_count}")
    print(f"    Total buys: ${buys:.2f}")
    print(f"    Total sells:${sells:.2f}")
    print(f"    Spread PnL: ${kalshi_pnl:+.2f}")
    print()

    print("  Tradier (margin):")
    tradier_pnl, tradier_count = get_tradier_pnl()
    print(f"    Positions:  {tradier_count}")
    print(f"    PnL:        ${tradier_pnl:+.2f}")
    print()

    total = kalshi_pnl + tradier_pnl
    print("─" * 55)
    print(f"  TOTAL ESTIMATED PnL: ${total:+.2f}")
    print("─" * 55)
    print()


if __name__ == "__main__":
    main()
