"""
Cycle Bot — Signal Aggregator
Combines on-chain, news, social, and technical analysis feeds
into a single composite score from -1.0 (max bearish) to +1.0 (max bullish).

Caches results for 30s to avoid hammering APIs every quote cycle.
On error: clears stale cache so next call retries fresh.
"""

import time
import logging
import requests
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config import Config

log = logging.getLogger("cycle.signals")
analyzer = SentimentIntensityAnalyzer()

_cache = {}
CACHE_TTL = 30  # seconds


def _cached(key, ttl=CACHE_TTL):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < ttl:
        return entry["val"]
    return None


def _set_cache(key, val):
    _cache[key] = {"val": val, "ts": time.time()}


def _clear_cache(key):
    """Clear stale cache on error so next call retries fresh."""
    _cache.pop(key, None)


# ────────────────────────────────────────────
# 1. ON-CHAIN: Glassnode Exchange Net Flow
# ────────────────────────────────────────────
def get_onchain_signal() -> float:
    """
    Glassnode exchange net flow volume (BTC).
    Positive net flow = coins TO exchanges = bearish (selling pressure).
    Negative net flow = coins leaving = bullish (accumulation).
    """
    if not Config.GLASSNODE_API_KEY:
        return 0.0

    cache_key = "onchain"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            "https://api.glassnode.com/v1/metrics/transactions/transfers_volume_exchanges_net",
            params={
                "a": "BTC",
                "api_key": Config.GLASSNODE_API_KEY,
                "i": "1h",
                "s": str(int(time.time()) - 7200),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return 0.0

        latest = data[-1].get("v", 0)

        if latest > 500:
            sig = -1.0
        elif latest > 200:
            sig = -0.5
        elif latest < -500:
            sig = 1.0
        elif latest < -200:
            sig = 0.5
        else:
            sig = 0.0

        log.debug(f"Onchain net flow: {latest:.0f} BTC -> signal {sig}")
        _set_cache(cache_key, sig)
        return sig

    except Exception as e:
        log.warning(f"Glassnode feed error: {e}")
        _clear_cache(cache_key)
        return 0.0


# ────────────────────────────────────────────
# 2. NEWS: NewsAPI Headlines via VADER
# ────────────────────────────────────────────
def get_news_signal(query: str = "bitcoin OR crypto") -> float:
    """Fetches latest headlines from NewsAPI, scores with VADER."""
    if not Config.NEWSAPI_KEY:
        return 0.0

    cache_key = f"news_{query}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "sortBy": "publishedAt",
                "pageSize": 10,
                "apiKey": Config.NEWSAPI_KEY,
                "language": "en",
            },
            timeout=10,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])

        if not articles:
            return 0.0

        scores = []
        for a in articles:
            text = f"{a.get('title', '')} {a.get('description', '')}"
            compound = analyzer.polarity_scores(text)["compound"]
            scores.append(compound)

        avg = sum(scores) / len(scores)

        if avg > 0.25:
            sig = 1.0
        elif avg > 0.1:
            sig = 0.5
        elif avg < -0.25:
            sig = -1.0
        elif avg < -0.1:
            sig = -0.5
        else:
            sig = 0.0

        log.debug(f"News sentiment ({query}): avg={avg:.3f} -> signal {sig}")
        _set_cache(cache_key, sig)
        return sig

    except Exception as e:
        log.warning(f"NewsAPI feed error: {e}")
        _clear_cache(cache_key)
        return 0.0


# ────────────────────────────────────────────
# 3. SOCIAL: X/Twitter Sentiment via VADER
# ────────────────────────────────────────────
def get_social_signal(query: str = "bitcoin") -> float:
    """Pulls recent tweets via X API v2, scores with VADER."""
    if not Config.X_BEARER_TOKEN:
        return 0.0

    cache_key = f"social_{query}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {Config.X_BEARER_TOKEN}"},
            params={
                "query": f"{query} lang:en -is:retweet",
                "max_results": 20,
                "tweet.fields": "text",
            },
            timeout=10,
        )
        resp.raise_for_status()
        tweets = resp.json().get("data", [])

        if not tweets:
            return 0.0

        scores = [
            analyzer.polarity_scores(t["text"])["compound"] for t in tweets
        ]
        avg = sum(scores) / len(scores)

        if avg > 0.3:
            sig = 1.0
        elif avg > 0.15:
            sig = 0.5
        elif avg < -0.3:
            sig = -1.0
        elif avg < -0.15:
            sig = -0.5
        else:
            sig = 0.0

        log.debug(f"Social sentiment ({query}): avg={avg:.3f} -> signal {sig}")
        _set_cache(cache_key, sig)
        return sig

    except Exception as e:
        log.warning(f"X/Twitter feed error: {e}")
        _clear_cache(cache_key)
        return 0.0


# ────────────────────────────────────────────
# 4. TECHNICAL ANALYSIS: Binance Public Klines
# ────────────────────────────────────────────
def get_ta_signal(symbol: str = "BTCUSDT", interval: str = "5m") -> float:
    """
    EMA crossover + RSI from Binance public klines (no auth needed).
    EMA(9) > EMA(21) = bullish. RSI > 70 = overbought, < 30 = oversold.
    """
    cache_key = f"ta_{symbol}_{interval}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": 50},
            timeout=10,
        )
        resp.raise_for_status()
        klines = resp.json()

        closes = pd.Series([float(k[4]) for k in klines])

        # EMA crossover
        ema_fast = closes.ewm(span=9, adjust=False).mean().iloc[-1]
        ema_slow = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        ema_sig = 1.0 if ema_fast > ema_slow else -1.0

        # RSI (14-period)
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean().iloc[-1]
        if loss == 0:
            rsi = 100.0
        else:
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

        rsi_sig = 0.0
        if rsi > 70:
            rsi_sig = -0.5
        elif rsi < 30:
            rsi_sig = 0.5

        sig = max(-1.0, min(1.0, ema_sig * 0.7 + rsi_sig * 0.3))

        log.debug(
            f"TA ({symbol} {interval}): EMA9={ema_fast:.1f} EMA21={ema_slow:.1f} "
            f"RSI={rsi:.1f} -> signal {sig:.2f}"
        )
        _set_cache(cache_key, sig)
        return sig

    except Exception as e:
        log.warning(f"Binance TA feed error: {e}")
        _clear_cache(cache_key)
        return 0.0


# ────────────────────────────────────────────
# 5. ODDS API: Sports/Politics Odds
# ────────────────────────────────────────────
def get_odds_signal() -> float:
    """Odds API signal (sports/politics implied prob). Returns -1.0 to 1.0."""
    if not Config.ODDS_API_KEY:
        return 0.0

    cache_key = "odds"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        from odds_api import get_odds_signal as fetch_odds
        sig = fetch_odds(sport="americanfootball_nfl")
        _set_cache(cache_key, sig)
        return sig
    except Exception as e:
        log.warning(f"Odds API feed error: {e}")
        _clear_cache(cache_key)
        return 0.0


# ────────────────────────────────────────────
# COMPOSITE SIGNAL
# ────────────────────────────────────────────
def get_composite_signal(asset: str = "btc") -> float:
    """Weighted composite of all feeds. Returns -1.0 to 1.0."""
    query_map = {
        "btc": ("bitcoin OR BTC", "bitcoin", "BTCUSDT"),
        "eth": ("ethereum OR ETH", "ethereum", "ETHUSDT"),
        "pepe": ("PEPE memecoin", "PEPE", "PEPEUSDT"),
        "doge": ("dogecoin DOGE", "dogecoin", "DOGEUSDT"),
        "shib": ("SHIB shiba", "SHIB", "SHIBUSDT"),
        "politics": ("election OR trump OR biden", "election", "SPY"),
        "general": ("bitcoin OR BTC", "bitcoin", "BTCUSDT"),
    }

    news_q, social_q, ta_sym = query_map.get(asset, query_map["btc"])

    onchain = get_onchain_signal()
    news = get_news_signal(news_q)
    social = get_social_signal(social_q)
    ta = get_ta_signal(ta_sym)
    odds = get_odds_signal()

    composite = (
        Config.WEIGHT_ONCHAIN * onchain
        + Config.WEIGHT_NEWS * news
        + Config.WEIGHT_SOCIAL * social
        + Config.WEIGHT_TA * ta
        + Config.WEIGHT_ODDS * odds
    )

    composite = max(-1.0, min(1.0, composite))

    log.info(
        f"Signal [{asset}]: onchain={onchain:.1f} news={news:.1f} "
        f"social={social:.1f} ta={ta:.2f} odds={odds:.2f} -> composite={composite:.2f}"
    )

    return composite
