#!/usr/bin/env python3
"""
Cycle Bot — Daily PnL Reporter
Fetches recent fills from Polymarket + Kraken Futures and
summarizes daily profit/loss.

Usage:
    python pnl.py              # today's PnL
    python pnl.py --verbose    # detailed fill-by-fill breakdown

Run manually or schedule via cron for daily email/log.
"""

import sys
import logging
from datetime import datetime, timedelta
from config import Config
from polymarket import PolymarketClient
from hedge import KrakenFuturesHedge

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger()

VERBOSE = "--verbose" in sys.argv


def get_poly_pnl():
    """Fetch Polymarket fills and compute PnL."""
    try:
        poly = PolymarketClient()
        poly.connect()

        # Get recent trades (fills)
        trades = []
        if poly.client:
            trades = poly.client.get_trades() or []

        if not trades:
            log.info("  No Polymarket fills found.")
            return 0.0, 0, 0.0, 0.0

        total_buys = 0.0
        total_sells = 0.0
        count = 0

        for t in trades:
            side = t.get("side", "").upper()
            size = float(t.get("size", 0))
            price = float(t.get("price", 0))
            value = size * price

            if side == "BUY":
                total_buys += value
            else:
                total_sells += value
            count += 1

            if VERBOSE:
                ts = t.get("created_at", "?")
                market = t.get("market", t.get("asset_id", "?"))[:20]
                log.info(
                    f"    {ts} | {side:4s} {size:8.1f} @ {price:.4f} "
                    f"= ${value:8.2f} | {market}..."
                )

        pnl = total_sells - total_buys
        return pnl, count, total_buys, total_sells

    except Exception as e:
        log.warning(f"  Polymarket PnL error: {e}")
        return 0.0, 0, 0.0, 0.0


def get_kraken_pnl():
    """Fetch Kraken Futures fills and compute hedge PnL."""
    try:
        hedge = KrakenFuturesHedge()
        fills = hedge.get_open_positions()

        if not fills:
            log.info("  No Kraken Futures fills found.")
            return 0.0, 0

        total_pnl = 0.0
        count = 0

        for f in fills:
            pnl = float(f.get("unrealizedPnl", 0) or f.get("pnl", 0))
            total_pnl += pnl
            count += 1

            if VERBOSE:
                symbol = f.get("symbol", "?")
                side = f.get("side", "?")
                size = f.get("size", "?")
                log.info(
                    f"    {symbol} | {side} {size} | PnL: ${pnl:.2f}"
                )

        return total_pnl, count

    except Exception as e:
        log.warning(f"  Kraken PnL error: {e}")
        return 0.0, 0


def estimate_rebates(poly_fill_count: int, avg_fill_value: float):
    """
    Estimate maker rebates.
    Polymarket redistributes ~20% of taker fees to makers daily.
    Taker fee max is 0.44% on 50/50 odds, lower on skewed markets.
    Conservative estimate: ~0.05-0.10% rebate per fill value.
    """
    rebate_rate = 0.0007  # ~0.07% conservative estimate
    return poly_fill_count * avg_fill_value * rebate_rate


def main():
    print()
    print("=" * 55)
    print(f"  CYCLE PnL Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)
    print()

    # Polymarket
    print("  Polymarket (spread capture):")
    poly_pnl, poly_count, buys, sells = get_poly_pnl()
    avg_fill = (buys + sells) / max(poly_count * 2, 1)
    print(f"    Fills:      {poly_count}")
    print(f"    Total buys: ${buys:.2f}")
    print(f"    Total sells:${sells:.2f}")
    print(f"    Spread PnL: ${poly_pnl:+.2f}")
    print()

    # Rebate estimate
    rebate_est = estimate_rebates(poly_count, avg_fill)
    print(f"  Estimated rebates:  ${rebate_est:+.2f}")
    print(f"    (based on {poly_count} fills @ ~0.07% rebate rate)")
    print()

    # Kraken hedge
    print("  Kraken Futures (hedge):")
    kraken_pnl, kraken_count = get_kraken_pnl()
    print(f"    Positions:  {kraken_count}")
    print(f"    Hedge PnL:  ${kraken_pnl:+.2f}")
    print()

    # Total
    total = poly_pnl + rebate_est + kraken_pnl
    print("─" * 55)
    print(f"  TOTAL ESTIMATED PnL: ${total:+.2f}")
    print("─" * 55)
    print()

    if total > 0:
        print("  Status: profitable")
    elif total > -10:
        print("  Status: roughly flat (normal for early days)")
    else:
        print("  Status: check signals + hedge timing")
    print()


if __name__ == "__main__":
    main()
