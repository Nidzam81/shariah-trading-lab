"""
Trade Log + State Uploader
==========================
After each trade or state change, uploads:
  1. Trade log ({agent}_trades.json) -- all trades
  2. State ({agent}_state.json) -- current position + latest indicators
  3. Event log ({agent}_log.jsonl) -- recent meaningful events

All files go to GitHub repo logs/ folder so Render dashboard can read them.
Also pushes trade to Render server for real-time display.
"""
import urllib.request, json, os, base64, subprocess, sys
from datetime import datetime
from pathlib import Path

# Render server URL
RENDER_URL = os.environ.get("RENDER_URL", "https://shariah-trading-lab.onrender.com")

# GitHub config
GITHUB_REPO = "Nidzam81/shariah-trading-lab"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/logs"

# Local backup
HOME = Path(os.path.expanduser("~"))
LOCAL_LOG_DIR = HOME / "AppData" / "Local" / "hermes" / "trade_logs"
LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _get_github_token():
    """Read GITHUB_TOKEN from Windows registry or env."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        v, _ = winreg.QueryValueEx(k, "GITHUB_TOKEN")
        return v.strip()
    except Exception:
        return os.environ.get("GITHUB_TOKEN", "")


def _github_upload(local_path, repo_filename, message=None):
    """Upload a file to GitHub repo logs/ folder using the Contents API."""
    token = _get_github_token()
    if not token:
        print(f"[GITHUB] No token, skipping upload of {repo_filename}")
        return False

    url = f"{GITHUB_API}/{repo_filename}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "shariah-trading-lab",
    }

    content = Path(local_path).read_bytes()
    encoded = base64.b64encode(content).decode()

    # Get existing SHA (needed for update)
    sha = None
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        existing = json.loads(resp.read())
        sha = existing.get("sha")
    except Exception:
        pass

    payload = {
        "message": message or f"Update {repo_filename} [{datetime.now().isoformat()}]",
        "content": encoded,
    }
    if sha:
        payload["sha"] = sha

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="PUT")
        resp = urllib.request.urlopen(req, timeout=15)
        print(f"[GITHUB] Uploaded {repo_filename} ({len(content)} bytes)")
        return True
    except Exception as e:
        print(f"[GITHUB] Upload failed for {repo_filename}: {e}")
        return False


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

    # 1. Push to Render server
    try:
        payload = json.dumps({"agent": agent, "trade": trade}).encode()
        req = urllib.request.Request(
            f"{RENDER_URL}/api/trades/push",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        print(f"[{agent}] Render push OK: {result.get('trades_stored')} trades stored")
    except Exception as e:
        print(f"[{agent}] Render push failed: {e}")

    # 2. Save locally and upload to GitHub
    local_file = LOCAL_LOG_DIR / f"{agent}_trades.json"
    trades = []
    if local_file.exists():
        try:
            existing = json.loads(local_file.read_text())
            trades = existing.get("trades", [])
        except Exception:
            pass
    trades.append(trade)
    trades = trades[-100:]
    local_file.write_text(json.dumps({
        "trades": trades,
        "last_updated": datetime.now().isoformat(),
        "agent": agent
    }, indent=2))
    _github_upload(local_file, f"{agent}_trades.json")

    return True


def upload_state_for_agent(agent, state_data, latest_entry=None, latest_exit=None, exits=None):
    """Upload agent state to GitHub so Render dashboard can read it."""
    state = {
        "agent": agent,
        "position_open": state_data.get("position_open", False),
        "entry_price": state_data.get("entry_price", 0),
        "qty": state_data.get("qty", 0),
        "order_id": state_data.get("order_id"),
        "entry_time": state_data.get("entry_time"),
        "last_updated": datetime.now().isoformat(),
        "latest_entry": latest_entry or {},
        "latest_exit": latest_exit or {},
        "exits": exits or [],
    }
    local_file = LOCAL_LOG_DIR / f"{agent}_state.json"
    local_file.write_text(json.dumps(state, indent=2))
    _github_upload(local_file, f"{agent}_state.json")


def upload_log_for_agent(agent, log_entries):
    """Upload recent meaningful log entries to GitHub as JSONL."""
    local_file = LOCAL_LOG_DIR / f"{agent}_log.jsonl"
    with open(local_file, "a", encoding="utf-8") as f:
        for entry in log_entries:
            entry["ts"] = entry.get("ts", datetime.now().isoformat())
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    # Keep only last 200 lines
    try:
        lines = local_file.read_text(encoding="utf-8").splitlines()
        if len(lines) > 200:
            local_file.write_text("\n".join(lines[-200:]) + "\n")
    except Exception:
        pass
    _github_upload(local_file, f"{agent}_log.jsonl")
