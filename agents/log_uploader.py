"""
Trade Log Uploader
==================
After each trade, pushes the trade to the live Render dashboard server
AND saves to local disk and GitHub.
"""
import urllib.request, json, os
from datetime import datetime
from pathlib import Path

# Render server URL
RENDER_URL = os.environ.get("RENDER_URL", "https://shariah-trading-lab.onrender.com")

# Local backup
HOME = Path(os.path.expanduser("~"))
LOCAL_LOG_DIR = HOME / "AppData" / "Local" / "hermes" / "trade_logs"
LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)


def upload_trade_log_for_agent(agent, side, price, qty, reason, entry_price=0, pnl=0):
    """Upload a trade: push to Render server + save locally + upload to GitHub."""
    trade = {
        "type": f"{side.lower()}_filled",
        "side": side,
        "price": price,
        "qty": qty,
        "reason": reason,
        "entry_price": entry_price,
        "pnl": round(pnl, 2),
        "timestamp": datetime.now().isoformat(),
    }

    # 1. Push to Render server (so dashboard shows it immediately)
    try:
        payload = json.dumps({"agent": agent, "trade": trade}).encode()
        req = urllib.request.Request(
            f"{RENDER_URL}/api/trades/push",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        print(f"[{agent}] Render push OK: {result.get('trades_stored')} trades stored")
    except Exception as e:
        print(f"[{agent}] Render push failed: {e}")

    # 2. Save locally
    local_file = LOCAL_LOG_DIR / f"{agent}_trades.json"
    trades = []
    if local_file.exists():
        try:
            data = json.loads(local_file.read_text())
            trades = data.get("trades", [])
        except Exception:
            pass
    trades.append(trade)
    trades = trades[-100:]
    local_file.write_text(json.dumps({
        "trades": trades,
        "last_updated": datetime.now().isoformat(),
        "agent": agent
    }, indent=2))

    return True
