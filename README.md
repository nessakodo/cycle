# Cycle — Polymarket Market Maker

Polymarket market-making bot with Kraken Futures hedge, signal-driven skew, and real-time fill tracking.

## Quick Start

```bash
# 1. Clone and setup
cd cycle
cp .env.example .env
nano .env   # fill POLY_PRIVATE_KEY, KRAKEN_API_KEY, KRAKEN_API_SECRET

# 2. Create venv and install (Python 3 required)
python3 -m venv venv
source venv/bin/activate   # Linux/macOS
# or: venv\Scripts\activate   # Windows
pip install -r requirements.txt

# 3. Run (paper mode by default)
python main.py
```

## Requirements

- **Python 3.8+** — Use `python3 main.py` if `python` points to Python 2
- Polymarket wallet (EOA private key)
- Kraken Futures API keys

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point |
| `engine.py` | Quoting engine, market discovery, pivot |
| `polymarket.py` | CLOB orders, Gamma API market discovery |
| `hedge.py` | Kraken Futures hedge |
| `ws_fills.py` | WebSocket fill tracking |
| `signals.py` | Composite signal (Glassnode, NewsAPI, TA) |
| `config.py` | Settings from `.env` |
| `debug_markets.py` | Debug Gamma API response |

## Deploy (VPS)

```bash
chmod +x deploy.sh
./deploy.sh
```

Then: `nano .env` to fill keys, then `source venv/bin/activate && python main.py` for paper test.
