"""
Cycle Bot — The Odds API Integration
Fetches odds for sports, politics, crypto events.
Uses 6 rotating keys to stay under 500/day free tier.
"""

import logging
import requests
from typing import Optional

from config import Config

log = logging.getLogger("cycle.odds_api")

ODDS_BASE = "https://api.the-odds-api.com/v4"

# Round-robin key index
_odds_key_index = 0


def _get_next_odds_key() -> Optional[str]:
    """Get next API key in rotation. Returns None if no keys configured."""
    global _odds_key_index
    keys = Config.ODDS_API_KEYS
    if not keys:
        return None
    key = keys[_odds_key_index % len(keys)]
    idx = _odds_key_index % len(keys)
    _odds_key_index += 1
    log.info(f"Using Odds API key index {idx + 1} of {len(keys)}")
    return key


def get_sports() -> list:
    """Get available sports. Returns list of sport keys."""
    api_key = _get_next_odds_key()
    if not api_key:
        return []
    try:
        resp = requests.get(
            f"{ODDS_BASE}/sports",
            params={"apiKey": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [s.get("key", "") for s in data if s.get("key")]
    except Exception as e:
        log.warning(f"Odds API sports error: {e}")
        return []


def get_odds(
    sport: str = "americanfootball_nfl",
    regions: str = "us",
    markets: str = "h2h",
) -> list:
    """
    Get odds for a sport. Returns list of events with bookmaker odds.
    Uses rotating API key.
    """
    api_key = _get_next_odds_key()
    if not api_key:
        return []
    try:
        resp = requests.get(
            f"{ODDS_BASE}/sports/{sport}/odds",
            params={
                "apiKey": api_key,
                "regions": regions,
                "markets": markets,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning(f"Odds API fetch error: {e}")
        return []


def get_odds_signal(sport: str = "americanfootball_nfl") -> float:
    """
    Derive a simple signal from odds (e.g. home team implied prob).
    Returns -1.0 to 1.0 (bearish to bullish).
    Uses rotating API key.
    """
    if not Config.ODDS_API_KEYS:
        return 0.0
    try:
        events = get_odds(sport=sport)
        if not events:
            return 0.0
        # Use first event's first bookmaker
        event = events[0]
        bookmakers = event.get("bookmakers", [])
        if not bookmakers:
            return 0.0
        markets = bookmakers[0].get("markets", [])
        if not markets:
            return 0.0
        outcomes = markets[0].get("outcomes", [])
        if len(outcomes) < 2:
            return 0.0
        # Implied prob from decimal odds: 1/odds
        probs = [1.0 / float(o.get("price", 2)) for o in outcomes]
        if sum(probs) > 0:
            home_prob = probs[0] / sum(probs)
            # Map to -1..1 (0.5 = neutral)
            return (home_prob - 0.5) * 2
        return 0.0
    except Exception as e:
        log.warning(f"Odds signal error: {e}")
        return 0.0
