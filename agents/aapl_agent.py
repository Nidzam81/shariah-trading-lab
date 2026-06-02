"""
AAPL Intraday Trading Agent
============================
Strategy: RSI(14) <= 30 + SMA 200 trend filter on 5-min candles
Asset: Apple (US.AAPL)
Account: moomoo SIMULATE (US, acc_id=4584160)

Backtest (Apr-Jun 2026): 13 trades, 53.8% WR, PF 2.29, $44.79 PnL
"""
import subprocess, os, sys, json
from datetime import datetime, timezone, timedelta

MOOMOO_PYTHON = r"C:\ProgramData\chocolatey\bin\python3.13"
MOOMOO_SCRIPTS = r"C:\Users\Nidzam\AppData\Local\hermes\skills\moomooapi\scripts"

ACC_ID = 4584160
TRD_ENV = "SIMULATE"
SECURITY_FIRM = "FUTUINC"
TICKER = "US.AAPL"
QTY = 2

RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 30
SMA_PERIOD = 200
PROFIT_TARGET_PCT = 0.02
STOP_LOSS_PCT = 0.01
KLINE_BARS = 250

LOG_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Local", "hermes", "aapl_agent")
STATE_FILE = os.path.join(LOG_DIR, "state.json")
LOG_FILE = os.path.join(LOG_DIR, "trading_log.jsonl")

def ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)

def log_event(entry):
    ensure_dirs()
    entry["ts"] = datetime.now().isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[{entry['ts']}] {entry.get('msg', '')}")

def send_telegram(text):
    try:
        subprocess.run(["hermes", "send", "--platform", "telegram", "--message", text],
                       capture_output=True, timeout=15, text=True)
    except Exception:
        pass

def upload_trade(side, price, qty, reason, entry_price=0, pnl=0):
    """Push trade to Render dashboard server."""
    try:
        import urllib.request
        render_url = os.environ.get("RENDER_URL", "https://shariah-trading-lab.onrender.com")
        trade = {
            "agent": "aapl", "side": side, "price": price, "qty": qty,
            "reason": reason, "entry_price": entry_price, "pnl": round(pnl, 2),
            "type": f"{side.lower()}_filled", "timestamp": datetime.now().isoformat(),
        }
        payload = json.dumps({"agent": "aapl", "trade": trade}).encode()
        req = urllib.request.Request(
            f"{render_url}/api/trades/push", data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
        log_event({"type": "log_upload", "status": "ok", "msg": f"AAPL trade pushed to dashboard"})
    except Exception as e:
        log_event({"type": "log_upload", "status": "failed", "error": str(e)})

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f: return json.load(f)
        except: pass
    return {"position_open": False, "entry_price": 0.0, "qty": 0, "order_id": None}

def save_state(state):
    ensure_dirs()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def run_moomoo(script, args):
    cmd = [MOOMOO_PYTHON, os.path.join(MOOMOO_SCRIPTS, script)] + args
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30, text=True)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except Exception as e:
        return "", str(e), -1

def get_json(out, err=""):
    dec = json.JSONDecoder()
    for text in [err, out]:
        if not text: continue
        results = []; pos = 0
        while pos < len(text):
            while pos < len(text) and text[pos] not in '{[': pos += 1
            if pos >= len(text): break
            try:
                obj, end = dec.raw_decode(text, pos)
                results.append(obj); pos = end
            except: pos += 1
        if results:
            for o in reversed(results):
                if isinstance(o, dict) and ("data" in o or "order_id" in o or "error" in o): return o
            return results[-1]
    return None

def is_entry_window():
    est = datetime.now(timezone.utc) - timedelta(hours=5)
    return 570 <= est.hour * 60 + est.minute < 930

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    g, l = [], []
    for i in range(1, len(closes)):
        c = closes[i] - closes[i-1]; g.append(max(c, 0)); l.append(max(-c, 0))
    ag = sum(g[-period:]) / period; al = sum(l[-period:]) / period
    return round(100 - 100/(1+ag/al), 2) if al > 0 else 100

def calc_sma(vals, period):
    return round(sum(vals[-period:]) / period, 4) if len(vals) >= period else None

def fetch_data():
    out, err, rc = run_moomoo(os.path.join("quote", "get_kline.py"),
        [TICKER, "--ktype", "5m", "--num", str(KLINE_BARS), "--json"])
    parsed = get_json(out, err)
    if not parsed or "data" not in parsed or not parsed.get("data"):
        return None, None, None, None
    records = parsed["data"]
    if len(records) < SMA_PERIOD: return None, None, None, None
    closes = [r["close"] for r in records if "close" in r and r["close"] is not None]
    if not closes: return None, None, None, None
    return closes[-1], calc_sma(closes, SMA_PERIOD), calc_rsi(closes, RSI_PERIOD), closes[-1]

def place_order(side, qty):
    out, err, rc = run_moomoo(os.path.join("trade", "place_order.py"),
        ["--code", TICKER, "--side", side, "--quantity", str(qty),
         "--order-type", "MARKET", "--trd-env", TRD_ENV,
         "--acc-id", str(ACC_ID), "--security-firm", SECURITY_FIRM, "--json"])
    parsed = get_json(out, err)
    if isinstance(parsed, dict) and "order_id" in parsed:
        return True, parsed["order_id"]
    if isinstance(parsed, dict) and "error" in parsed:
        return False, parsed.get("error", "unknown")
    return False, (out + " | " + err)[:200]

def get_price():
    out, err, rc = run_moomoo(os.path.join("quote", "get_snapshot.py"), [TICKER, "--json"])
    parsed = get_json(out, err)
    if isinstance(parsed, dict) and "data" in parsed:
        d = parsed["data"]
        if isinstance(d, list) and d: return d[0].get("last_price")
        if isinstance(d, dict): return d.get("last_price")
    return None

def main():
    state = load_state()
    position_open = state.get("position_open", False)
    entry_price = state.get("entry_price", 0.0)
    in_window = is_entry_window()
    price = get_price()

    # EXIT
    if position_open and entry_price > 0:
        ep = entry_price
        tp = round(ep * (1 + PROFIT_TARGET_PCT), 4)
        sl = round(ep * (1 - STOP_LOSS_PCT), 4)

        if price is None:
            log_event({"type": "exit_check", "status": "no_price"})
        elif price >= tp:
            log_event({"type": "exit_signal", "reason": "TP", "entry": ep, "current": price,
                        "msg": f"AAPL TP! Entry={ep:.2f} -> {price:.2f} (+{(price/ep-1)*100:.2f}%)"})
            ok, res = place_order("SELL", state.get("qty", QTY))
            if ok:
                pnl = (price - ep) * state.get("qty", QTY)
                save_state({"position_open": False, "entry_price": 0.0, "qty": 0, "order_id": None})
                log_event({"type": "order_filled", "side": "SELL", "reason": "TP", "order_id": res})
                send_telegram(f"AAPL TP HIT (SIMULATE)\nSELL {state.get('qty',QTY)} @ ${price:.2f}\nEntry: ${ep:.2f} (+{(price/ep-1)*100:.2f}%)\nOrder: {res}")
                upload_trade("SELL", price, state.get("qty", QTY), "TP", ep, pnl)
            else:
                log_event({"type": "order_failed", "side": "SELL", "reason": "TP", "error": res})
        elif price <= sl:
            log_event({"type": "exit_signal", "reason": "SL", "entry": ep, "current": price,
                        "msg": f"AAPL SL! Entry={ep:.2f} -> {price:.2f} ({(price/ep-1)*100:.2f}%)"})
            ok, res = place_order("SELL", state.get("qty", QTY))
            if ok:
                pnl = (price - ep) * state.get("qty", QTY)
                save_state({"position_open": False, "entry_price": 0.0, "qty": 0, "order_id": None})
                log_event({"type": "order_filled", "side": "SELL", "reason": "SL", "order_id": res})
                send_telegram(f"AAPL STOP LOSS (SIMULATE)\nSELL {state.get('qty',QTY)} @ ${price:.2f}\nEntry: ${ep:.2f} ({(price/ep-1)*100:.2f}%)\nOrder: {res}")
                upload_trade("SELL", price, state.get("qty", QTY), "SL", ep, pnl)
            else:
                log_event({"type": "order_failed", "side": "SELL", "reason": "SL", "error": res})
        else:
            pct = round((price/entry_price-1)*100, 2) if price else None
            log_event({"type": "position_monitor", "entry": ep, "current": price, "tp": tp, "sl": sl,
                        "pnl_pct": pct, "msg": f"Holding AAPL: entry={ep:.2f} current={price} TP={tp:.2f} SL={sl:.2f} PnL={pct}%"})
        return

    # ENTRY
    if not in_window:
        log_event({"type": "skip", "reason": "outside_window", "msg": "Outside 9:30-15:30 EST"})
        return

    current_price, sma200, rsi14, _ = fetch_data()
    if current_price is None or sma200 is None or rsi14 is None:
        log_event({"type": "data_fail", "msg": "Failed to fetch AAPL data"})
        return

    log_event({"type": "market_data", "price": current_price, "sma200": sma200, "rsi14": rsi14,
                "msg": f"AAPL: price={current_price:.2f} SMA200={sma200:.2f} RSI14={rsi14}"})

    if current_price <= sma200:
        log_event({"type": "trend_filter", "passed": False,
                    "msg": f"Bearish: price={current_price:.2f} <= SMA200={sma200:.2f}"})
        return

    if rsi14 <= RSI_BUY_THRESHOLD:
        log_event({"type": "buy_signal", "rsi": rsi14, "price": current_price,
                    "msg": f"AAPL BUY! RSI={rsi14} <= {RSI_BUY_THRESHOLD} price={current_price:.2f} BUYING {QTY}"})
        ok, res = place_order("BUY", QTY)
        if ok:
            save_state({"position_open": True, "entry_price": current_price, "qty": QTY,
                         "order_id": res, "entry_time": datetime.now().isoformat()})
            tp = round(current_price * (1 + PROFIT_TARGET_PCT), 2)
            sl = round(current_price * (1 - STOP_LOSS_PCT), 2)
            log_event({"type": "order_filled", "side": "BUY", "price": current_price, "qty": QTY, "order_id": res,
                        "msg": f"BUY {QTY} AAPL @ {current_price:.2f} order={res} TP={tp:.2f} SL={sl:.2f}"})
            send_telegram(f"AAPL BUY SIGNAL (SIMULATE)\nBUY {QTY} @ ${current_price:.2f}\nRSI: {rsi14} SMA200: ${sma200:.2f}\nTP: ${tp:.2f} SL: ${sl:.2f}\nOrder: {res}")
            upload_trade("BUY", current_price, QTY, "ENTRY", 0, 0)
        else:
            log_event({"type": "order_failed", "side": "BUY", "error": res, "msg": f"BUY FAILED: {res}"})
    else:
        log_event({"type": "no_signal", "rsi": rsi14, "msg": f"RSI not oversold ({rsi14} > {RSI_BUY_THRESHOLD})"})

if __name__ == "__main__":
    main()
