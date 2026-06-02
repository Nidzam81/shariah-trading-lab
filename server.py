"""
Shariah Trading Lab -- Live Backend Server
==========================================
FastAPI server reads agent log/state files and serves live dashboard data.

API Endpoints:
  GET /api/health          -- Health check
  GET /api/nvda            -- NVDA agent live data (price, RSI, SMA, etc.)
  GET /api/amd             -- AMD agent live data (price, RSI, BB, etc.)
  GET /api/portfolio       -- SIMULATE account portfolio
  GET /api/trades/{agent}  -- Recent trades (nvda or amd)
  GET /                    -- Dashboard HTML

Deploy to Render.com free tier.
Auto-deploys from GitHub on push.
"""
import os, json, subprocess, http.server
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
# Use the directory where this script lives (works on both local and Render)
SCRIPT_DIR = Path(__file__).parent
DASHBOARD_HTML = SCRIPT_DIR / "index.html"

# Local Windows paths (only used when running locally)
HOME = Path(os.path.expanduser("~"))
HERMES = HOME / "AppData" / "Local" / "hermes"
NVDA_LOG = HERMES / "nvda_agent" / "trading_log.jsonl"
NVDA_STATE = HERMES / "nvda_agent" / "state.json"
AMD_LOG = HERMES / "amd_agent" / "trading_log.jsonl"
AMD_STATE = HERMES / "amd_agent" / "state.json"

MOOMOO_PYTHON = r"C:\ProgramData\chocolatey\bin\python3.13"
MOOMOO_SCRIPTS = str(HERMES / "skills" / "moomooapi" / "scripts")

# ── Helpers ────────────────────────────────────────────────────────────────────

def read_jsonl(path, max_lines=50):
    """Read last N lines of a JSONL file. Also accepts a URL to fetch from GitHub."""
    # If it's a URL, fetch it
    if str(path).startswith("http"):
        try:
            req = urllib.request.Request(str(path), headers={"User-Agent": "shariah-trading-lab"})
            resp = urllib.request.urlopen(req, timeout=10)
            lines = resp.read().decode("utf-8").splitlines()
            results = []
            for line in lines[-max_lines:]:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return results
        except Exception:
            return []
    # Local file
    p = Path(path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
        results = []
        for line in lines[-max_lines:]:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return results
    except Exception:
        return []

def read_json(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}

def parse_moomoo_output(stdout, stderr=""):
    dec = json.JSONDecoder()
    for text in [stderr, stdout]:
        if not text:
            continue
        results = []
        pos = 0
        while pos < len(text):
            while pos < len(text) and text[pos] not in "{[":
                pos += 1
            if pos >= len(text):
                break
            try:
                obj, end = dec.raw_decode(text, pos)
                results.append(obj)
                pos = end
            except Exception:
                pos += 1
        if results:
            for o in reversed(results):
                if isinstance(o, dict) and (
                    "data" in o or "order_id" in o or "positions" in o or "funds" in o or "error" in o
                ):
                    return o
            return results[-1]
    return {}

def run_moomoo(script, args, timeout=15):
    cmd = [MOOMOO_PYTHON, os.path.join(MOOMOO_SCRIPTS, script)] + args
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
        return parse_moomoo_output(r.stdout, r.stderr)
    except Exception as e:
        return {"error": str(e)}

def compute_indicators_for_agent(ticker, log_file, state_file):
    """Fetch live klines and compute RSI, SMA, BB for an agent."""
    result = run_moomoo(
        os.path.join("quote", "get_kline.py"),
        [ticker, "--ktype", "5m", "--num", "250", "--json"],
        timeout=20,
    )

    indicators = {
        "rsi14": None, "sma200": None, "bb_lower": None,
        "bb_mid": None, "bb_upper": None, "trend": "N/A",
        "current_price": None, "current_low": None,
    }

    if isinstance(result, dict) and "data" in result and result["data"]:
        records = result["data"]
        closes = [r["close"] for r in records if "close" in r and r["close"] is not None]
        lows = [r["low"] for r in records if "low" in r and r["low"] is not None]

        if closes:
            indicators["current_price"] = closes[-1]
            indicators["current_low"] = lows[-1] if lows else closes[-1]

            # RSI 14
            if len(closes) >= 15:
                g, l = [], []
                for j in range(1, len(closes)):
                    c = closes[j] - closes[j - 1]
                    g.append(max(c, 0))
                    l.append(max(-c, 0))
                ag = sum(g[-14:]) / 14
                al = sum(l[-14:]) / 14
                indicators["rsi14"] = round(100 - 100 / (1 + ag / al), 2) if al > 0 else 100.0

            # SMA 200
            if len(closes) >= 200:
                sma = sum(closes[-200:]) / 200
                indicators["sma200"] = round(sma, 4)
                indicators["trend"] = "BULL" if closes[-1] > sma else "BEAR"

            # Bollinger Bands (20, 2)
            if len(closes) >= 20:
                w = closes[-20:]
                mid = sum(w) / 20
                std = (sum((x - mid) ** 2 for x in w) / 20) ** 0.5
                indicators["bb_mid"] = round(mid, 4)
                indicators["bb_lower"] = round(mid - 2 * std, 4)
                indicators["bb_upper"] = round(mid + 2 * std, 4)

    # Read agent state
    state = read_json(state_file)
    indicators["position_open"] = state.get("position_open", False)
    indicators["entry_price"] = state.get("entry_price", 0)
    indicators["qty"] = state.get("qty", 0)

    # Read recent logs
    logs = read_jsonl(log_file, max_lines=20)
    indicators["recent_logs"] = [l for l in logs if "msg" in l][-10:]

    # Count trades
    all_logs = read_jsonl(log_file, max_lines=500)
    trade_logs = [l for l in all_logs if l.get("type") == "order_filled"]
    indicators["total_trades"] = len(trade_logs)
    indicators["tp_count"] = len([l for l in trade_logs if l.get("reason") == "TP"])
    indicators["sl_count"] = len([l for l in trade_logs if l.get("reason") == "SL"])

    return indicators

def fetch_portfolio():
    """Fetch SIMULATE portfolio from moomoo."""
    result = run_moomoo(
        os.path.join("trade", "get_portfolio.py"),
        ["--acc-id", "4584160", "--trd-env", "SIMULATE", "--security-firm", "FUTUINC", "--json"],
    )
    if isinstance(result, dict):
        funds = result.get("funds", {})
        positions = result.get("positions", [])
        return {
            "cash": funds.get("cash", 0),
            "total_assets": funds.get("total_assets", 0),
            "market_val": funds.get("market_val", 0),
            "buying_power": funds.get("power", 0),
            "us_cash": funds.get("us_cash", 0),
            "positions": [
                {
                    "code": p.get("code", ""),
                    "name": p.get("name", ""),
                    "qty": p.get("qty", 0),
                    "avg_cost": p.get("average_cost", 0),
                    "price": p.get("nominal_price", 0),
                    "market_val": p.get("market_val", 0),
                    "unrealized_pl": p.get("unrealized_pl", 0),
                    "pl_pct": p.get("pl_ratio_avg_cost", 0),
                }
                for p in positions
            ],
        }
    return None

# ── FastAPI App ────────────────────────────────────────────────────────────────

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Shariah Trading Lab", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.get("/api/nvda")
def nvda_data():
    return JSONResponse(compute_indicators_for_agent("US.NVDA", NVDA_LOG, NVDA_STATE))


@app.get("/api/amd")
def amd_data():
    return JSONResponse(compute_indicators_for_agent("US.AMD", AMD_LOG, AMD_STATE))


@app.get("/api/aapl")
def aapl_data():
    return JSONResponse(compute_indicators_for_agent("US.AAPL", 
        os.path.join(HERMES, "aapl_agent", "trading_log.jsonl"),
        os.path.join(HERMES, "aapl_agent", "state.json")))


@app.get("/api/portfolio")
def portfolio():
    data = fetch_portfolio()
    return JSONResponse(data or {"error": "Failed to fetch portfolio"})


@app.post("/api/trades/push")
def push_trade(data: dict):
    """Receive a trade push from an agent (called by nvda_agent.py / amd_agent.py)."""
    agent = data.get("agent", "unknown")
    trade = data.get("trade", {})
    print(f"[PUSH] {agent}: {trade.get('side')} {trade.get('reason')} @ ${trade.get('price')}")

    # Save to in-memory store (resets on Render restart, but that's OK -- trades also in GitHub)
    if agent not in _trade_store:
        _trade_store[agent] = []
    _trade_store[agent].append(trade)
    _trade_store[agent] = _trade_store[agent][-100:]  # keep last 100

    return JSONResponse({"status": "ok", "trades_stored": len(_trade_store[agent])})


@app.get("/api/trades/{agent}")
def recent_trades(agent: str):
    """Return trades from in-memory store (pushed by agents)."""
    trades = _trade_store.get(agent, [])
    if trades:
        return JSONResponse({"trades": trades})

    # Fallback: try GitHub
    raw_url = f"https://raw.githubusercontent.com/Nidzam81/shariah-trading-lab/main/logs/{agent}_trades.json"
    try:
        req = urllib.request.Request(raw_url, headers={"User-Agent": "shariah-trading-lab"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        trades = data.get("trades", [])
        if trades:
            return JSONResponse(data)
    except Exception as e:
        print(f"[{agent}] GitHub fetch error: {e}")

    return JSONResponse({"trades": []})


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def dashboard():
    if DASHBOARD_HTML.exists():
        return HTMLResponse(DASHBOARD_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found.</h1>")


# ── In-Memory Trade Store ──────────────────────────────────────────────────────

_trade_store: dict = {}


def _seed_trades_from_github():
    """Load existing trades from GitHub on startup so the dashboard has data immediately."""
    for agent in ["nvda", "amd"]:
        raw_url = f"https://raw.githubusercontent.com/Nidzam81/shariah-trading-lab/main/logs/{agent}_trades.json"
        try:
            req = urllib.request.Request(raw_url, headers={"User-Agent": "shariah-trading-lab"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            trades = data.get("trades", [])
            if trades:
                _trade_store[agent] = trades[-100:]
                print(f"[SEED] {agent}: loaded {len(trades)} trades from GitHub")
        except Exception as e:
            print(f"[SEED] {agent}: GitHub seed failed ({e}), starting empty")


@app.on_event("startup")
async def startup_seed():
    _seed_trades_from_github()


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # Also try to seed on startup (non-async context)
    _seed_trades_from_github()
    print(f"Starting Shariah Trading Lab on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
