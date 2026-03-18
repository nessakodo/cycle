# Cycle — US-Legal Market Maker

Kalshi market-making bot with Tradier margin execution and Odds API signal enrichment.

**US-legal:** CFTC-regulated Kalshi + Reg T margin via Tradier. No VPN/proxy required.

## Quick Start

```bash
# 1. Clone and setup
cd cycle
cp .env.example .env
nano .env   # fill KALSHI_API_KEY, KALSHI_PRIVATE_KEY (PEM string), etc.

# 2. Create venv (Python 3.8+)
python3 -m venv venv
source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt

# 3. Run (paper mode by default)
python main.py
```

## Requirements

- **Python 3.8+**
- Kalshi account + API key + private key PEM (paste in .env)
- Tradier account (optional, for margin hedge)
- Odds API key (optional, for signal enrichment)

## Architecture

| File | Purpose |
|------|---------|
| `main.py` | Entry point, US-legal banner |
| `engine.py` | Quoting engine, Kalshi + Tradier |
| `kalshi.py` | Kalshi API (markets, orderbook, orders) |
| `tradier.py` | Tradier margin trades |
| `odds_api.py` | The Odds API (sports/politics) |
| `signals.py` | Composite signal (Finnhub, NewsAPI, TA, Odds) |
| `ws_fills_kalshi.py` | Kalshi fill tracking (polling) |
| `config.py` | Settings from .env |
| `killswitch.py` | Emergency cancel all |
| `pnl.py` | PnL reporter |

## Paper Testing on Droplet

1. Deploy: `chmod +x deploy.sh && ./deploy.sh`
2. Fill keys: `nano .env`
3. Paper test: `source venv/bin/activate && python main.py`
4. Watch logs for `[PAPER]` quotes
5. After 24–48h paper, set `PAPER_MODE=false` for live
6. Start small: `QUOTE_SIZE_CONTRACTS=5`, `MAX_INVENTORY_USDC=500`

## Disclaimer

This bot is for educational purposes. Paper test first. Use small size when going live. Kalshi and Tradier are US-legal; no VPN/proxy needed.
