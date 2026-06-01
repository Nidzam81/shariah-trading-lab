# Shariah Trading Lab -- Dashboard

Live trading dashboard for NVDA and AMD automated trading agents.

## Setup

### Local Development

```bash
pip install -r requirements.txt
python server.py
# Opens at http://localhost:8080
```

### Deploy to Render

1. Create a new GitHub repo and push this folder
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Set build command: `pip install -r requirements.txt`
5. Set start command: `python server.py`
6. Render auto-deploys on every push

### Auto-Deploy on Update

```bash
pip install -r requirements.txt   # local testing
python server.py                  # local dev server at :8080
git add -A && git commit -m "update" && git push  # triggers Render deploy
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check |
| `GET /api/nvda` | NVDA live data (price, RSI, SMA200, trend) |
| `GET /api/amd` | AMD live data (price, RSI, BB, signal) |
| `GET /api/portfolio` | SIMULATE account portfolio & positions |
| `GET /api/trades/{agent}` | Recent trades (nvda or amd) |
| `GET /` | Dashboard HTML |

## Trading Agents

- **NVDA Agent**: Mean-reversion (RSI≤30 + SMA200 trend) on US.NVDA
- **AMD Agent**: Bollinger Band (BB lower touch + RSI<40) on US.AMD
- Both use FUTUINC SIMULATE account 
- Cron schedule: every 5 min, 10PM-5AM MYT, Mon-Fri
