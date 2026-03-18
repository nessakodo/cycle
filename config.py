"""
Cycle Bot — Configuration
Loads from .env file or environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Polymarket
    POLY_HOST = "https://clob.polymarket.com"
    POLY_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    POLY_GAMMA = "https://gamma-api.polymarket.com"
    CHAIN_ID = 137  # Polygon mainnet
    POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY", "")
    PROXY_HTTP = os.getenv("PROXY_HTTP") or None
    PROXY_HTTPS = os.getenv("PROXY_HTTPS") or None

    # Kraken Futures
    KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
    KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")

    # Signal Feed Keys
    GLASSNODE_API_KEY = os.getenv("GLASSNODE_API_KEY", "")
    NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
    X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")

    # Bot Parameters
    PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
    SPREAD_BPS = int(os.getenv("SPREAD_BPS", "50"))
    MAX_INVENTORY_USDC = float(os.getenv("MAX_INVENTORY_USDC", "1000"))
    HEDGE_LEVERAGE = int(os.getenv("HEDGE_LEVERAGE", "3"))
    QUOTE_SIZE_USDC = float(os.getenv("QUOTE_SIZE_USDC", "10"))
    QUOTE_INTERVAL_SEC = int(os.getenv("QUOTE_INTERVAL_SEC", "5"))
    PIVOT_INTERVAL_SEC = int(os.getenv("PIVOT_INTERVAL_SEC", "1800"))
    MAX_FUNDING_RATE = float(os.getenv("MAX_FUNDING_RATE", "0.0005"))

    # Signal Weights (sum to 1.0)
    WEIGHT_ONCHAIN = 0.35
    WEIGHT_NEWS = 0.25
    WEIGHT_SOCIAL = 0.20
    WEIGHT_TA = 0.20

    # Risk
    RISK_PCT = 0.01
    INV_SKEW_THRESHOLD = 0.7

    @classmethod
    def validate(cls):
        errors = []
        if not cls.POLY_PRIVATE_KEY:
            errors.append("POLY_PRIVATE_KEY is required")
        if not cls.KRAKEN_API_KEY:
            errors.append("KRAKEN_API_KEY is required (for futures hedge)")
        if not cls.KRAKEN_API_SECRET:
            errors.append("KRAKEN_API_SECRET is required")
        if errors:
            return False, errors
        return True, []

    @classmethod
    def print_status(cls):
        feeds = []
        if cls.GLASSNODE_API_KEY:
            feeds.append("Glassnode")
        if cls.NEWSAPI_KEY:
            feeds.append("NewsAPI")
        if cls.X_BEARER_TOKEN:
            feeds.append("X/Twitter")
        feeds.append("Binance TA (public)")
        feeds.append("VADER Sentiment")

        print(f"  Mode:       {'PAPER' if cls.PAPER_MODE else 'LIVE'}")
        print(f"  Spread:     {cls.SPREAD_BPS} bps ({cls.SPREAD_BPS / 100:.1f}%)")
        print(f"  Max Inv:    ${cls.MAX_INVENTORY_USDC:.0f} USDC")
        print(f"  Hedge:      {cls.HEDGE_LEVERAGE}x Kraken Futures")
        print(f"  Quote Size: ${cls.QUOTE_SIZE_USDC:.0f} USDC")
        print(f"  Feeds:      {', '.join(feeds)}")
