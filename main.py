#!/usr/bin/env python3
"""
Cycle Bot — Entry Point
Polymarket market-making + Kraken futures hedge.

Usage:
    1. cp .env.example .env && nano .env    (fill your keys)
    2. pip install -r requirements.txt
    3. python main.py                       (starts paper mode)
    4. Set PAPER_MODE=false when ready

Architecture:
    config.py      -> All settings from .env
    signals.py     -> Composite signal: Glassnode + NewsAPI + X + Binance TA
    polymarket.py  -> Signed CLOB orders via py-clob-client
    hedge.py       -> Kraken Futures hedge via python-kraken-sdk
    ws_fills.py    -> Real-time fill tracking via WebSocket
    engine.py      -> Multi-market parallel quoting, meme pivot, inventory mgmt
"""

import sys
import signal
import logging
import time
from config import Config
from engine import QuotingEngine


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
    print("=" * 50)
    print("  CYCLE — Polymarket Market Maker")
    print("  Kraken Futures Hedge | Signal Skew")
    print("  Real-time Fills | Meme Pivot")
    print("=" * 50)
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
