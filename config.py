"""
Cycle Bot — Configuration
Loads from .env file or environment variables.
US-legal: Kalshi (CFTC) + Tradier (Reg T margin) + The Odds API.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Kalshi (CFTC-regulated, US-legal prediction market)
    KALSHI_API_KEY = os.getenv("KALSHI_API_KEY", "")
    KALSHI_PRIVATE_KEY_PATH = os.getenv(
        "KALSHI_PRIVATE_KEY_PATH",
        "/home/nessa/cycle/kalshi_private_key.pem",
    )
    KALSHI_BASE_URL = os.getenv(
        "KALSHI_BASE_URL",
        "https://trading-api.kalshi.com/trade-api/v2",
    )

    # The Odds API (6 keys for rotation, stay under 500/day free tier)
    ODDS_API_KEYS = [
        k.strip()
        for k in os.getenv("ODDS_API_KEYS", "").split(",")
        if k.strip()
    ]

    # Tradier (Reg T margin, equities/options)
    TRADIER_ACCESS_TOKEN = os.getenv("TRADIER_ACCESS_TOKEN", "")
    TRADIER_ACCOUNT_ID = os.getenv("TRADIER_ACCOUNT_ID", "")
    TRADIER_BASE_URL = os.getenv(
        "TRADIER_BASE_URL",
        "https://sandbox.tradier.com/v1",
    )  # Use https://api.tradier.com/v1 for live

    # Signal Feed Keys
    FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
    NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
    X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")

    # Bot Parameters
    PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
    SPREAD_BPS = int(os.getenv("SPREAD_BPS", "50"))
    MAX_INVENTORY_USDC = float(os.getenv("MAX_INVENTORY_USDC", "1000"))
    QUOTE_SIZE_CONTRACTS = int(os.getenv("QUOTE_SIZE_CONTRACTS", "10"))
    QUOTE_INTERVAL_SEC = int(os.getenv("QUOTE_INTERVAL_SEC", "5"))
    PIVOT_INTERVAL_SEC = int(os.getenv("PIVOT_INTERVAL_SEC", "1800"))

    # Signal Weights (sum to 1.0)
    WEIGHT_FINNHUB = 0.35
    WEIGHT_NEWS = 0.20
    WEIGHT_SOCIAL = 0.15
    WEIGHT_TA = 0.15
    WEIGHT_ODDS = 0.15

    # Risk
    RISK_PCT = 0.01
    INV_SKEW_THRESHOLD = 0.7

    @classmethod
    def validate(cls):
        errors = []
        if not cls.KALSHI_API_KEY:
            errors.append("KALSHI_API_KEY is required")
        if not cls.KALSHI_PRIVATE_KEY_PATH or not os.path.isfile(cls.KALSHI_PRIVATE_KEY_PATH):
            errors.append(
                f"KALSHI_PRIVATE_KEY_PATH must point to existing PEM file "
                f"(current: {cls.KALSHI_PRIVATE_KEY_PATH})"
            )
        if errors:
            return False, errors
        return True, []

    @classmethod
    def print_status(cls):
        feeds = []
        if cls.FINNHUB_API_KEY:
            feeds.append("Finnhub")
        if cls.NEWSAPI_KEY:
            feeds.append("NewsAPI")
        if cls.X_BEARER_TOKEN:
            feeds.append("X/Twitter")
        if cls.ODDS_API_KEYS:
            feeds.append(f"Odds API ({len(cls.ODDS_API_KEYS)} keys)")
        feeds.append("Binance TA (public)")
        feeds.append("VADER Sentiment")

        print(f"  Mode:       {'PAPER' if cls.PAPER_MODE else 'LIVE'}")
        print(f"  Spread:     {cls.SPREAD_BPS} bps ({cls.SPREAD_BPS / 100:.1f}%)")
        print(f"  Max Inv:    ${cls.MAX_INVENTORY_USDC:.0f}")
        print(f"  Quote Size: {cls.QUOTE_SIZE_CONTRACTS} contracts")
        print(f"  Feeds:      {', '.join(feeds)}")
