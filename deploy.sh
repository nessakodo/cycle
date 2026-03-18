#!/usr/bin/env bash
# Cycle Bot — VPS Deploy Script
# Run this on your droplet after cloning the repo.
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
#
# What it does:
#   1. Installs system deps (python3, pip, venv)
#   2. Creates virtualenv + installs requirements
#   3. Copies .env.example -> .env if missing (you still fill keys)
#   4. Installs systemd service for 24/7 operation
#   5. Starts in paper mode by default

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="cycle"
VENV_DIR="${SCRIPT_DIR}/venv"

echo ""
echo "================================================"
echo "  CYCLE — Deploying to VPS"
echo "================================================"
echo ""

# 0. Python version check (python3 required)
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install with: sudo apt install python3 python3-venv"
    exit 1
fi
PY3_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "?")
echo "[0/6] Python: $(which python3) (${PY3_VER})"
if command -v python &>/dev/null; then
    PY_VER=$(python -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo "?")
    if [ "$PY_VER" = "2" ]; then
        echo "  Note: 'python' points to Python 2. Use 'python3' or: sudo update-alternatives --install /usr/bin/python python /usr/bin/python3 1"
    fi
fi
echo ""

# 1. System dependencies
echo "[1/5] Installing system dependencies..."
sudo apt update -qq
sudo apt install -y -qq python3 python3-pip python3-venv git curl > /dev/null 2>&1
echo "  Done."

# 2. Python virtualenv
echo "[2/5] Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "  Created venv at ${VENV_DIR}"
else
    echo "  Venv already exists."
fi

source "${VENV_DIR}/bin/activate"
pip install --upgrade pip -q
pip install -r "${SCRIPT_DIR}/requirements.txt" -q
echo "  Dependencies installed."

# 3. Environment file
echo "[3/5] Checking .env configuration..."
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
    echo ""
    echo "  !! .env created from .env.example"
    echo "  !! You MUST edit it now and fill in your API keys:"
    echo ""
    echo "     nano ${SCRIPT_DIR}/.env"
    echo ""
    echo "  Required keys:"
    echo "    - POLY_PRIVATE_KEY  (your Polymarket wallet EOA hex key)"
    echo "    - KRAKEN_API_KEY    (Kraken Futures API key)"
    echo "    - KRAKEN_API_SECRET (Kraken Futures API secret)"
    echo ""
    echo "  Optional (but recommended):"
    echo "    - GLASSNODE_API_KEY (free tier works)"
    echo "    - NEWSAPI_KEY       (free tier works)"
    echo "    - X_BEARER_TOKEN    (X/Twitter API bearer)"
    echo ""
else
    echo "  .env already exists."
fi

# 4. Systemd service
echo "[4/5] Installing systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<SYSTEMD
[Unit]
Description=Cycle Polymarket Market-Making Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${SCRIPT_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${VENV_DIR}/bin/python ${SCRIPT_DIR}/main.py
ExecStop=/bin/kill -SIGTERM \$MAINPID
Restart=on-failure
RestartSec=10
StandardOutput=append:${SCRIPT_DIR}/cycle.log
StandardError=append:${SCRIPT_DIR}/cycle.log

# Safety: stop cleanly on reboot/shutdown
TimeoutStopSec=30
KillMode=mixed
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
SYSTEMD

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
echo "  Service installed and enabled."

# 5. Summary
echo "[5/5] Deploy complete."
echo ""
echo "================================================"
echo "  Next steps:"
echo "================================================"
echo ""
echo "  1. Fill your keys:    nano ${SCRIPT_DIR}/.env"
echo ""
echo "  2. Paper test first:  source venv/bin/activate && python main.py"
echo "     (runs in foreground so you can watch logs)"
echo "     (Ctrl+C to stop)"
echo ""
echo "  3. When ready for 24/7:"
echo "     sudo systemctl start cycle"
echo "     sudo journalctl -u cycle -f    # tail logs"
echo ""
echo "  4. Go live (after 24-48h paper):"
echo "     Edit .env: PAPER_MODE=false"
echo "     sudo systemctl restart cycle"
echo ""
echo "  5. Emergency stop:"
echo "     python killswitch.py"
echo "     (cancels all orders + closes hedges)"
echo ""
echo "  6. Check status:"
echo "     sudo systemctl status cycle"
echo "     tail -f cycle.log"
echo ""
