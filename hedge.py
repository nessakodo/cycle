"""
Cycle Bot — Kraken Futures Hedge
Uses python-kraken-sdk (maintained, official-ish) for perpetual futures.
Hedges Polymarket inventory skew with opposite leveraged positions.
Includes funding rate guard + auto-adjust.
"""

import logging
from typing import Optional
from kraken.futures import Trade, Market
from config import Config

log = logging.getLogger("cycle.hedge")


class KrakenFuturesHedge:
    """
    Kraken Futures hedge using python-kraken-sdk.
    No custom auth needed — the SDK handles signing.
    """

    # Asset type -> Kraken futures symbol
    SYMBOL_MAP = {
        "btc": "PI_XBTUSD",
        "eth": "PI_ETHUSD",
        "pepe": "PF_PEPEUSD",
        "doge": "PF_DOGEUSD",
        "shib": "PF_SHIBUSD",
    }

    def __init__(self):
        self.trade = Trade(
            key=Config.KRAKEN_API_KEY,
            secret=Config.KRAKEN_API_SECRET,
        )
        self.market = Market(
            key=Config.KRAKEN_API_KEY,
            secret=Config.KRAKEN_API_SECRET,
        )
        self.leverage = Config.HEDGE_LEVERAGE
        self.max_funding = Config.MAX_FUNDING_RATE

    # ──────────────── Funding Rate ────────────────

    def get_funding_rate(self, symbol: str = "PI_XBTUSD") -> float:
        """
        Get current funding rate for a futures symbol.
        Returns absolute rate (e.g. 0.0003 = 0.03%).
        """
        try:
            tickers = self.market.get_tickers()
            ticker_list = tickers.get("tickers", [])
            for t in ticker_list:
                if t.get("symbol", "").upper() == symbol.upper():
                    rate = float(t.get("fundingRate", 0))
                    log.debug(f"Funding rate {symbol}: {rate:.6f}")
                    return abs(rate)
            return 0.0
        except Exception as e:
            log.warning(f"Funding rate fetch error: {e}")
            return 0.0

    def get_funding_rate_for_asset(self, asset_type: str) -> float:
        """Get funding rate by asset type (btc, eth, pepe, etc.)."""
        symbol = self.SYMBOL_MAP.get(asset_type, "PI_XBTUSD")
        return self.get_funding_rate(symbol)

    def should_hedge(self, asset_type: str) -> bool:
        """Check if funding rate is acceptable for hedging."""
        rate = self.get_funding_rate_for_asset(asset_type)
        if rate > self.max_funding:
            log.info(
                f"Skipping hedge ({asset_type}): funding {rate:.6f} > "
                f"max {self.max_funding:.6f}"
            )
            return False
        return True

    # ──────────────── Leverage ────────────────

    def set_leverage(self, symbol: str):
        """Set leverage preference for a symbol."""
        try:
            self.market.set_leverage_preference(
                symbol=symbol,
                maxLeverage=str(self.leverage),
            )
            log.info(f"Set leverage {self.leverage}x for {symbol}")
        except Exception as e:
            log.warning(f"Set leverage error: {e}")

    # ──────────────── Order Placement ────────────────

    def place_hedge(
        self,
        asset_type: str,
        direction: str,
        size_usd: float,
    ) -> Optional[dict]:
        """
        Place a market order on Kraken Futures to hedge Polymarket exposure.
        direction: "buy" (long) or "sell" (short)
        size_usd: approximate USD value to hedge
        """
        symbol = self.SYMBOL_MAP.get(asset_type)
        if not symbol:
            log.warning(f"No futures symbol for asset: {asset_type}")
            return None

        if Config.PAPER_MODE:
            log.info(
                f"[PAPER] HEDGE {direction.upper()} ${size_usd:.0f} "
                f"on {symbol} @ {self.leverage}x"
            )
            return {
                "paper": True,
                "symbol": symbol,
                "side": direction,
                "size": size_usd,
            }

        # Check funding rate first
        if not self.should_hedge(asset_type):
            return None

        # Set leverage
        self.set_leverage(symbol)

        try:
            result = self.trade.create_order(
                orderType="mkt",
                size=size_usd,
                symbol=symbol,
                side=direction,
            )
            log.info(
                f"HEDGE placed: {direction.upper()} ${size_usd:.0f} "
                f"on {symbol} @ {self.leverage}x"
            )
            return result
        except Exception as e:
            log.error(f"Hedge order failed: {e}")
            return None

    def close_hedge(self, asset_type: str, direction: str, size_usd: float):
        """Close an existing hedge by placing opposite order."""
        opposite = "sell" if direction == "buy" else "buy"
        return self.place_hedge(asset_type, opposite, size_usd)

    # ──────────────── Position Info ────────────────

    def get_open_positions(self) -> list:
        """Get all open futures positions."""
        try:
            result = self.trade.get_fills()
            return result.get("fills", [])
        except Exception as e:
            log.warning(f"Get positions error: {e}")
            return []
