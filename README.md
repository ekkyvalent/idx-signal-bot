# IDX Signal Bot

A Telegram bot that scans **103 stocks** on the Indonesia Stock Exchange (IDX) every morning, scores them with a **dual-mode technical system**, and sends buy signals to your Telegram group. Built for short-term swing trading (3-day hold, +5% take-profit target).

The bot automatically detects the market regime (bull vs bear) and selects the appropriate scoring mode — **momentum** in uptrends, **mean-reversion** in downtrends. So you get relevant signals whether the market is rallying or crashing.

**Backtested result:** Score >= 9 signals, 3-day exit, +5% target -> **+5.8% annual return**, **54.9% win rate** (May 2025 to May 2026).

---

## How It Works

Every weekday at **08:15 AM WIB** (Western Indonesia Time), the bot posts two messages to your Telegram group:

1. **Portfolio check** — current price for each open position, unrealised P&L, and whether to hold, take profit, or exit
2. **Buy signals** — top 5 stocks scoring >= 9/10, ranked by score, with tier labels and mode tags

You act on the signals manually through your IDX broker (Stockbit or any other).

### Exit Strategy

Every trade ends exactly one of two ways:

- **Take profit** — set a Stockbit auto-sell at the +5% target when you buy
- **Day 3** — sell at market price on the 3rd trading day, no exceptions, skip weekends and IDX holidays

No percentage-based stop-loss. No panic selling. Hold until one triggers.

---

## Scoring System

Each stock is scored across **3 independent categories** simultaneously. The best match wins. Priority tiebreaker: Reversal > Breakout > Momentum (reversal is most time-sensitive).

Every signal displays a category tag: **🔄 Reversal**, **🚀 Breakout**, or **🏄 Momentum**.

### 🔄 Reversal (Oversold bounce / support bounce)

Best for bear markets, overreactions, and capitulation events.

| Signal | Points | Logic |
|---|---|---|
| RSI < 30 | +3 | Extremely oversold — sellers exhausted |
| RSI 30-40 | +2 | Oversold |
| RSI 40-50 | +1 | Neutral-leaning oversold |
| Volume >= 1.5x + down day < -2% | +3 | Capitulation — high-volume selloff, best reversal signal |
| Volume >= 1.2x + down day < -2% | +2 | Elevated selling pressure |
| Volume >= 2x + up day > +1% | +2 | Strong accumulation bounce |
| Volume >= 1.5x + up day > +1% | +1 | Mild accumulation bounce |
| 5-day pullback -2% to -8% | +2 | Healthy dip within normal range |
| 5-day drop > -8% | +1 | Bigger drop, higher risk/reward |
| Price at or near 20-day support | +2 | Sitting on the nearest floor |
| Price at or near 50-day support | +1 | Also at longer-term support |
| Hammer candle | +2 | Buyers aggressively defended the low |
| Outperformed IHSG (5d) | +1 | Relative strength vs the market |
| MACD histogram positive | +1 | Bullish momentum |
| MACD bullish crossover | +1 | Fresh momentum trigger |

**Max: 10 points | Stop:** ATR below 20-day support (max -8%)

### 🚀 Breakout (Range breakout / consolidation end)

Best for sideways-to-bull transitions and stocks emerging from consolidation.

| Signal | Points | Logic |
|---|---|---|
| Near 20-day high + vol >= 1.2x + up day | +2 | Volume-confirmed breakout from range |
| Near 20-day high only | +1 | Breaking out, volume confirmation pending |
| Volume >= 1.5x + up day | +2 | Strong accumulation on up day |
| Volume >= 1.2x + up day | +1 | Mild accumulation on up day |
| Above MA20 | +1 | Short-term uptrend |
| Above MA50 | +1 | Medium-term uptrend |
| RSI 50-65 | +1 | Breakout zone — not exhausted |
| 5-day return +2% to +10% | +2 | Breaking out of consolidation |
| 5-day return > +10% | +1 | Already running, late to breakout |
| ADX > 30 | +2 | Confirmed trend |
| ADX 25-30 | +1 | Trending, but not extreme |
| MACD bullish crossover | +1 | Fresh momentum trigger |

**Max: 10 points | Stop:** ATR below MA20 (max -6%)

### 🏄 Momentum (Trending continuation)

Best for established bull markets and strong ADX trends.

| Signal | Points | Logic |
|---|---|---|
| Price > MA20 **and** MA50 | +2 | Bull structure confirmed |
| Price > MA20 only | +1 | Early uptrend |
| ADX > 30 | +2 | Strong trend confirmed |
| ADX 25-30 | +1 | Trending, but not extreme |
| Volume >= 1.5x + up day > +1% | +2 | Strong accumulation |
| Volume >= 1.2x + up day > +1% | +1 | Mild accumulation |
| RSI 50-70 | +1 | Healthy momentum zone |
| MACD histogram positive | +1 | Bullish momentum |
| MACD bullish crossover | +1 | Fresh momentum trigger |
| Near 20-day high | +1 | Price confirming trend |
| 5-day return +2% to +10% | +1 | Healthy trending momentum |

**Max: 10 points | Stop:** ATR below MA20 (max -6%)

### Additional Filters

| **Minimum score to appear:** 8 for all tiers
| **When IHSG is in a downtrend:** threshold raised to 9 — only the strongest setups qualify
- **Average daily volume:** must be >= 500,000 shares over 20 days — illiquid stocks are always excluded

### Signal Context

Every signal includes:
- RSI, volume ratio, 1-d and 5-d returns, trend direction (MA20)
- Support, resistance, MA20, MA50 levels
- ADX (trend strength), MACD histogram
- Suggested lots based on budget allocation
- Mode tag (Momentum or Reversal)

---

## Stock Universe

103 tickers across three tiers:

| Tier | Count | Source |
|---|---|---|
| 🔵 Blue Chip | 47 | LQ45 (rebalances Feb/May/Aug/Nov) |
| 🟡 Mid-cap | 38 | IDX80 extras beyond LQ45 |
| 🔴 Small Cap | 18 | Liquid stocks priced <= Rp 1,000 |

LQ45 tickers (May to July 2026):
AALI, ADRO, AKRA, AMMN, AMRT, ANTM, ARTO, ASII, BBCA, BBNI, BBRI, BBTN, BMRI, BRPT, BUKA, CPIN, CUAN, DEWA, EMTK, ESSA, EXCL, GOTO, HEAL, HRUM, HRTA, ICBP, INCO, INDF, INTP, ISAT, ITMG, KLBF, MAPA, MBMA, MDKA, MEDC, MIKA, MNCN, PGAS, PTBA, SMGR, TBIG, TLKM, TOWR, UNTR, UNVR, WIFI

Update `scanner.py` with the latest LQ45 list every rebalancing period.

---

## Telegram Bot

### Commands

| Command | Description |
|---|---|
| `/signals` | Run a full universe scan now (~60-90 seconds) |
| `/portfolio` | Check all open positions with current prices and P&L |
| `/bought TICKER LOTS PRICE` | Log a buy, e.g. `/bought BKSL 9 102` |
| `/sold TICKER PRICE` | Log a sell and see realised P&L, e.g. `/sold BKSL 120` |
| `/summary` | Total realised P&L and win rate across all trades |
| `/help` | Show command list |

### Automatic Reports

- **Morning report:** every weekday at 08:15 WIB — portfolio check + buy signals
- **Price alerts:** every 5 minutes during IDX market hours (09:00-15:30 WIB) — alerts when an open position hits +5% target or -5% danger zone

### Authorization

The bot has two separate settings:
- `GROUP_CHAT_ID` — the group/channel that receives all reports and alerts
- `AUTHORIZED_UID` — your personal Telegram user ID, the only account allowed to run commands

This means anyone in the group can read signals, but only you can log trades or run `/signals`.

---

## Setup

### Requirements

- Python 3.10+
- A Telegram bot token (create via BotFather)
- Railway account (for persistent deployment)

### Install

```bash
pip install -r requirements.txt
```

### Environment Variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from BotFather |
| `GROUP_CHAT_ID` | Chat/group ID for receiving reports (use `-100XXXX:200` for Telegram topics) |
| `AUTHORIZED_UID` | Your Telegram user ID — only this user can run commands |
| `DATA_DIR` | Path to store `transactions.json` (default: script directory) |

### Run Locally

```bash
BOT_TOKEN=xxx GROUP_CHAT_ID=-1001234567890 AUTHORIZED_UID=123456789 python3 bot.py
```

---

## Deploy to Railway

1. Create a new Railway project from your GitHub repo
2. Set the environment variables listed above
3. Add a persistent volume mounted at `/data` — this is where `transactions.json` lives
4. Railway uses `Procfile`: `worker: python bot.py`

Redeploy after changes:

```bash
railway up
```

Check logs:

```bash
railway logs
```

---

## Files

```
stock-trading/
  scanner.py            Core logic — dual-mode scoring, data fetching, portfolio tracking
  signal_generator.py   Local runner — saves signals_latest.md + Mac notification
  bot.py                Telegram bot with morning report, price alerts, commands
  backtest.py           Strategy backtester and capital simulator
  transactions.json     Local trade log (auto-created, gitignored)
  requirements.txt      Python dependencies
  Procfile              Railway worker config
```

---

## Run a Backtest

```bash
python3 backtest.py
```

Downloads 1 year of OHLCV data for all 103 tickers, scores every stock on every day (no lookahead), and simulates trading the top signals. Takes 5-10 minutes.

---

## Data Source and Limitations

- **Data:** Yahoo Finance end-of-day via `yfinance`. Signals use yesterday's close, not today's open. Intraday price alerts use 5-minute data.
- **No macro awareness:** The system is purely technical. A stock can look perfect on the charts and still be in a fundamental downtrend. Always do your own due diligence.
- **Fees assumed:** 0.15% buy / 0.35% sell (0.25% broker + 0.1% PPh final). Adjust `FEE_BUY` and `FEE_SELL` in `scanner.py` if your broker charges differently.
- **Holiday calendar:** IDX 2026 holidays are hardcoded in `scanner.py` (`IDX_HOLIDAYS_2026`). Update at the start of each year from idx.co.id.

---

_This tool is for informational purposes only. It is not financial advice. Always do your own research before trading._
