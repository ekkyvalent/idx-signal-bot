# IDX Signal Bot

A Telegram bot that scans 103 stocks on the Indonesia Stock Exchange (IDX) every morning and sends you the top buy signals for the day. Built for short-term swing trading with a simple 3-day exit rule.

**Backtested result:** Score ≥ 9 signals, 3-day exit → +5.8% annual return on Rp 1M capital, 54.9% win rate (May 2025–May 2026).

---

## How It Works

Every weekday at **08:15 WIB**, the bot sends you two messages:

1. **Portfolio check** — for each open position: current price, unrealised P&L, and whether to hold or exit
2. **Buy signals** — top 5 stocks that score ≥ 9/10 based on technical indicators

You act on the signals manually through your broker (Stockbit or any IDX broker).

### Exit Strategy

There are only two ways a trade ends:
- **Take profit** — set a Stockbit auto-sell at the target price (+3%) when you buy
- **Day 3** — sell at market price on the 3rd trading day regardless of P&L

No manual stop-loss. No panic selling. Hold until one of those two things happens.

The 3-day counter skips weekends and **IDX public holidays** (full 2026 calendar included).

---

## Scoring System (max 10 points)

| Signal | Points | Logic |
|---|---|---|
| RSI < 30 | +3 | Very oversold — sellers exhausted |
| RSI 30–40 | +2 | Oversold |
| RSI 40–50 | +1 | Neutral lean |
| High vol + down day (≥1.5x, <-2%) | +3 | Capitulation — strong mean-reversion signal |
| High vol + down day (≥1.2x, <-2%) | +2 | Elevated sell pressure |
| High vol + up day (≥2x, >+1%) | +2 | Strong momentum |
| High vol + up day (≥1.5x, >+1%) | +1 | Mild momentum |
| 5-day pullback -2% to -8% | +2 | Healthy dip, not a crash |
| 5-day drop > -8% | +1 | Bigger drop — higher risk/reward |
| Price ≤ 20-day support × 1.02 | +2 | Sitting on support |
| Price ≤ 50-day support × 1.02 | +1 | Also at longer-term support |
| Hammer candle | +2 | Buyers defended the low aggressively |
| Stock outperformed IHSG (5d) | +1 | Relative strength vs market |

**Minimum score to appear:** 9 (raised to 11 automatically when IHSG is in a downtrend).

**Additional filter:** Average daily volume ≥ 500,000 shares over last 20 days. Illiquid stocks are excluded even if they score well.

---

## Stock Universe — 103 tickers across 3 tiers

| Tier | Count | Stocks |
|---|---|---|
| 🔵 Blue Chip | 47 | LQ45 (May–Jul 2026 list) |
| 🟡 Mid-cap | 38 | IDX80 extras beyond LQ45 |
| 🔴 Small Cap | 18 | Liquid penny stocks (price ≤ Rp 1,000) |

The LQ45 list rebalances every Feb, May, Aug, Nov — update `scanner.py` accordingly.

---

## Setup

### Requirements

- Python 3.10+
- A Telegram bot token (create via [@BotFather](https://t.me/BotFather))
- Your Telegram chat ID (get it from [@userinfobot](https://t.me/userinfobot))

### Install dependencies

```bash
pip install -r requirements.txt
```

### Environment variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from BotFather |
| `CHAT_ID` | Your Telegram numeric chat ID |
| `DATA_DIR` | Path to store `transactions.json` (default: script directory) |

### Run locally

```bash
BOT_TOKEN=xxx CHAT_ID=123456789 python3 bot.py
```

The bot will start polling Telegram and send the morning report automatically at 08:15 WIB on weekdays.

---

## Telegram Commands

| Command | Description |
|---|---|
| `/signals` | Run a full scan now (~60–90 seconds) |
| `/portfolio` | Check all open positions with current price and P&L |
| `/bought TICKER LOTS PRICE` | Log a buy, e.g. `/bought BKSL 9 102` |
| `/sold TICKER PRICE` | Log a sell and see realised P&L, e.g. `/sold BKSL 120` |
| `/summary` | Total realised P&L and win rate across all trades |
| `/help` | Show command list |

---

## Deploy to Railway

This bot is designed to run as a persistent worker on [Railway](https://railway.app).

1. Create a new Railway project
2. Add a service from your GitHub repo (or push with the Railway CLI)
3. Set environment variables: `BOT_TOKEN`, `CHAT_ID`, `DATA_DIR=/data`
4. Add a persistent volume mounted at `/data` — this is where `transactions.json` lives
5. Railway uses `Procfile` to start the bot: `worker: python bot.py`

To redeploy after changes:

```bash
railway up
```

To check logs:

```bash
railway logs
```

---

## Run a Backtest

To see how the model would have performed over the past year on your machine:

```bash
python3 backtest.py
```

This will:
1. Download 1 year of OHLCV data for all 103 tickers from Yahoo Finance
2. Score every stock on every day using only data available at that point (no lookahead)
3. Compare three exit strategies: 1-day, 3-day, and 5-day holds
4. Run a capital simulation starting from Rp 1,000,000 using the best strategy
5. Print a monthly P&L breakdown and full trade stats

Takes about 5–10 minutes to run. Prices are end-of-day closes — real results will differ slightly due to gap opens.

---

## Local Mac Runner (Optional)

If you want signals delivered as a Mac notification without Telegram, use `signal_generator.py`:

```bash
python3 signal_generator.py
```

This saves output to `signals_latest.md` and sends a macOS notification with the signal count.

To run it automatically every weekday at 08:15, set up a LaunchAgent at `~/Library/LaunchAgents/com.ekky.stocksignals.plist`.

---

## Files

```
stock-trading/
  scanner.py            Core logic — scoring, data fetching, portfolio tracking
  signal_generator.py   Local runner — saves signals_latest.md + Mac notification
  bot.py                Telegram bot — deployed on Railway
  backtest.py           Strategy backtester and capital simulator
  transactions.json     Local trade log (auto-created on first run)
  requirements.txt      Python dependencies
  Procfile              Railway worker config
```

---

## Data Source & Limitations

- **Data:** Yahoo Finance end-of-day prices via `yfinance`. Signals are based on the previous day's close, not the current open.
- **No macro awareness:** A stock can look oversold and still be in a fundamental downtrend. Always apply your own judgment.
- **Fees assumed:** 0.1% buy / 0.2% sell (Stockbit standard). Adjust `FEE_BUY` and `FEE_SELL` in `scanner.py` if your broker charges differently.
- **Holiday calendar:** Hardcoded for 2026 (source: IDX announcement No. Peng-00171/BEI.POP/09-2025). Update `IDX_HOLIDAYS_2026` in `scanner.py` at the start of each year.

---

_This tool is for informational purposes only. It is not financial advice. Always do your own research before trading._
