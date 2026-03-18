#!/usr/bin/env python3
"""
Cycle Bot — Entry Point
US-legal Kalshi market-making + Tradier margin + Odds API signals.

DISCLAIMER: This bot uses CFTC-regulated Kalshi and Reg T margin via Tradier.
No VPN/proxy required. Paper test first, then live with small size.

Usage:
    1. cp .env.example .env && nano .env
    2. pip install -r requirements.txt
    3. python main.py                       (paper mode)
    4. Set PAPER_MODE=false when ready
"""

import sys
import signal
import logging
import time
from config import Config
from engine import QuotingEngine

if sys.version_info[0] < 3:
    print("Cycle requires Python 3. Use: python3 main.py")
    sys.exit(1)


def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("cycle.log", mode="a"),
        ],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websocket").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    setup_logging()
    log = logging.getLogger("cycle.main")

    print()
    print("=" * 60)
    print("  CYCLE — US-LEGAL Market Maker")
    print("  Kalshi (CFTC) + Tradier (Reg T) + Odds API")
    print("  No VPN/proxy required.")
    print("=" * 60)
    print()
    print("  ⚠️  US LEGAL MODE — Kalshi + Tradier + Odds API.")
    print("  Finnhub integrated + Odds API rotation (6 keys) + Tradier sandbox.")
    print("  Kalshi using PEM file path from .env — file must be present on droplet.")
    print("  Paper test first, then live with small size.")
    print()

    valid, errors = Config.validate()
    if not valid:
        print("Configuration errors:")
        for e in errors:
            print(f"  - {e}")
        print()
        print("Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

    Config.print_status()
    print()

    if Config.PAPER_MODE:
        log.info("Running in PAPER MODE — no real orders will be placed")
        log.info("PAPER MODE — Tradier sandbox active (if configured)")
        log.info(
            f"Paper testing: Finnhub + Odds API ({len(Config.ODDS_API_KEYS)} keys) + "
            "Tradier sandbox. Watch logs for signal feeds."
        )
    else:
        log.warning("LIVE MODE — real money at stake")
        print("  Starting in 5 seconds... Ctrl+C to abort")
        time.sleep(5)

    engine = QuotingEngine()

    def shutdown(signum, frame):
        log.info("Shutdown signal received")
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        threads = engine.start()
        while engine.running:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
    except Exception as e:
        log.critical(f"Fatal error: {e}", exc_info=True)
        engine.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
