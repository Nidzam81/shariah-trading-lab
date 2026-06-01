"""
Trade Log Uploader
==================
After each trade, uploads the trade log to GitHub repo (logs/ folder)
so the live dashboard can fetch it from the deployed Render server.
"""
import urllib.request, json, os, subprocess
from datetime import datetime
from pathlib import Path

# GitHub config
GITHUB_API = "https://api.github.com"
REPO = "Nidzam81/shariah-trading-lab"
TOKEN = None  # Will be read from environment


def get_token():
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def github_request(path, data=None, method="GET"):
    """Make an authenticated GitHub API request."""
    token = get_token()
    if not token:
        return None

    url = f"{GITHUB_API}/repos/{REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    if data:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except Exception as e:
        return None


def get_file_sha(path):
    """Get the SHA of a file in the repo (needed for updates)."""
    result = github_request(path)
    if result and "sha" in result:
        return result["sha"]
    return None


def upload_trade_log(agent, trade_data):
    """
    Upload a trade log entry to the GitHub repo.
    agent: 'nvda' or 'amd'
    trade_data: dict with trade details
    """
    token = get_token()
    if not token:
        return False

    file_path = f"logs/{agent}_trades.json"

    # Read existing log from repo
    existing = github_request(file_path)
    trades = []
    if existing and "content" in existing:
        try:
            import base64
            content = base64.b64decode(existing["content"]).decode()
            data = json.loads(content)
            trades = data.get("trades", [])
        except Exception:
            trades = []

    # Append new trade
    trade_data["uploaded_at"] = datetime.now().isoformat()
    trades.append(trade_data)

    # Keep last 100 trades
    trades = trades[-100:]

    # Upload
    import base64
    content = json.dumps(
        {"trades": trades, "last_updated": datetime.now().isoformat(), "agent": agent},
        indent=2,
    )
    encoded = base64.b64encode(content.encode()).decode()

    sha = get_file_sha(file_path)
    data = {
        "message": f"Trade log update: {agent.upper()} - {trade_data.get('type', 'unknown')}",
        "content": encoded,
    }
    if sha:
        data["sha"] = sha

    result = github_request(file_path, data=data, method="PUT")
    return result is not None


def upload_trade_log_for_agent(agent, side, price, qty, reason, entry_price=0, pnl=0):
    """Convenience wrapper for a completed trade."""
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
    return upload_trade_log(agent, trade)
