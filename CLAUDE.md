# Stock Trading Assistant

## What This Is
Daily buy/sell signals for IDX (Indonesia Stock Exchange) day trading.
Starting capital Rp 100K per trade. Not a daily buyer — only acts on strong signals.

## Trading Setup
- **Broker:** Stockbit
- **Budget per trade:** Rp 100,000 (starting, grows with performance)
- **Fees:** 0.15% buy / 0.35% sell (0.25% broker + 0.1% PPh Final)
- **Min lot:** 100 shares
- **Max price per share:** Rp 1,000 (so 1 lot fits within Rp 100K budget)

## Stock Universe — 103 tickers across 3 tiers

| Tier | Count | Min Score to Show | Notes |
|---|---|---|---|
| 🔵 Blue Chip | 47 | 9 | LQ45 — most liquid IDX stocks |
| 🟡 Mid-cap | 38 | 9 | IDX80 extras beyond LQ45 |
| 🔴 Small Cap | 18 | 9 | Liquid penny stocks |

**Why score ≥ 9:** Backtested against 1 year of IDX data. Score ≥ 9 cuts trade frequency in half but produces 3× better annual return (+5.8% vs +1.8%) by eliminating weak setups that expire flat and pay fees for nothing.

**Additional filter:** Stocks must have average daily volume ≥ 500,000 shares over the last 20 days. This prevents illiquid penny stocks from showing up even if they look cheap.

### LQ45 (Blue Chip) — May–July 2026
AALI, ADRO, AKRA, AMMN, AMRT, ANTM, ARTO, ASII, BBCA, BBNI, BBRI, BBTN, BMRI,
BRPT, BUKA, CPIN, CUAN, DEWA, EMTK, ESSA, EXCL, GOTO, HEAL, HRUM, HRTA, ICBP,
INCO, INDF, INTP, ISAT, ITMG, KLBF, MAPA, MBMA, MDKA, MEDC, MIKA, MNCN, PGAS,
PTBA, SMGR, TBIG, TLKM, TOWR, UNTR, UNVR, WIFI

New in May 2026 rebalancing: CUAN, DEWA, ESSA, HRTA, WIFI.
Update every rebalancing period: Feb, May, Aug, Nov.

### IDX80 Extra (Mid-cap)
ACES, ADHI, AGII, BJBR, BJTM, BKSL, BSDE, BULL, CLEO, CMRY, CSAP, DMAS, DSNG,
ELSA, ERAA, GGRM, HMSP, INDY, INKP, JPFA, KAEF, KIJA, LPKR, LSIP, MAPI, MYOR,
NISP, NCKL, PGEO, PTPP, SCMA, SIDO, SMDR, SSMS, TINS, ULTJ, WIKA, WSKT

### Small Caps
BRIS, BSSR, BWPT, DPUM, ENRG, FREN, HITS, MBSS, MFIN, SIMP,
SMRU, TOBA, WINS, BANK, BGTG, COAL, EDGE, GTSI

## How Signals Are Scored (max 10 points)

| Signal | Points | Why |
|---|---|---|
| RSI < 35 | +3 | Strongly oversold — sellers exhausted |
| RSI 35–45 | +2 | Oversold |
| RSI 45–55 | +1 | Neutral lean |
| Volume ≥ 2x 20-day avg | +3 | Major buying interest |
| Volume 1.5–2x | +2 | Elevated interest |
| Volume 1.2–1.5x | +1 | Slightly above normal |
| 1-day momentum > +1% | +1 | Positive close |
| 5-day pullback -2% to -8% | +2 | Healthy dip, not a crash |
| Price ≤ 20-day support × 1.02 | +2 | Sitting on support |
| Price > 20-day MA | +1 | Uptrend confirmation |

**Support/resistance** uses 20-day window (upgraded from 10-day — more meaningful levels).
**MA20 trend** shown on every signal so you know if you're buying into a trend or against one.

## Lot Recommendation Logic
Lots are based on both budget and signal strength — not just "max affordable":

| Score | Allocation |
|---|---|
| 8–10 | 100% of budget |
| 6–7 | 60% of budget |
| 5 | 40% of budget |

Example: Budget Rp 100K, stock at Rp 200/share (max 5 lots):
- Score 9 → 5 lots (Rp 100K)
- Score 7 → 3 lots (Rp 60K)
- Score 5 → 2 lots (Rp 40K)

## Portfolio Recommendations
Open positions are reviewed first every morning:
- **TAKE PROFIT** — price reached target (set in Stockbit auto-sell)
- **CUT LOSS** — price hit stop-loss (set in Stockbit auto-sell)
- **EXIT — 3-day limit reached** — hold expired, exit regardless of P&L
- **Hold — day X/3** — within normal range, let it run

**Exit strategy:**
- **Take profit** — set via Stockbit auto-sell at purchase. Fires automatically if price hits target.
- **Day 3** — sell at market price regardless of P&L. This is the only cut-loss mechanism.
- No percentage-based cut-loss. No Stockbit auto-sell for stop-loss. Hold until day 3 or take-profit triggers, whichever comes first.

## Files
```
stock-trading/
  scanner.py            Core logic — all scoring, batch download, transactions
  signal_generator.py   Local runner — saves signals_latest.md + Mac notification
  bot.py                Telegram bot — deployed on Railway
  transactions.json     Local trade log
  signals_latest.md     Latest local output (auto-generated, not committed)
  requirements.txt      Python deps
  Procfile              Railway: worker: python bot.py
  CLAUDE.md             This file
```

## Telegram Bot
Live on Railway. Only responds to Ekky's Telegram (chat ID locked in `authorized()` check).

**Commands:**
- `/signals` — full universe scan, ~60–90 seconds
- `/portfolio` — open positions + action per position
- `/bought TICKER LOTS PRICE` — log a buy (e.g. `/bought BKSL 9 102`)
- `/sold TICKER PRICE` — log a sell, shows P&L (e.g. `/sold BKSL 120`)
- `/summary` — total P&L + win rate across all trades
- `/help` — show command menu

**Morning report:** auto-fires every Mon–Fri at 08:15 WIB.
Format: portfolio review first, then top 5 buy signals with tier labels.

## Railway Deployment
- Project: `idx-signals`
- Service: `idx-signals`
- Env vars: `BOT_TOKEN`, `CHAT_ID`, `DATA_DIR=/data`
- Persistent volume at `/data` — transactions.json lives here
- To redeploy: `cd ~/Claude/projects/stock-trading && railway up`
- To check logs: `railway service idx-signals && railway logs`

**BOT_TOKEN is sensitive.** If ever exposed, regenerate via BotFather:
`/mybots → API Token → Revoke`, then `railway variables set BOT_TOKEN="new_token"`

## Local Mac Runner (Backup)
LaunchAgent at `~/Library/LaunchAgents/com.ekky.stocksignals.plist` runs signal_generator.py at 08:15 daily.
Output: `signals_latest.md` + Mac notification.
Manual run: `python3 ~/Claude/projects/stock-trading/signal_generator.py`

## Transaction Log Format
Stored in `transactions.json` locally and `/data/transactions.json` on Railway.

```json
{
  "id": "TRX-001",
  "date_buy": "2026-05-10",
  "ticker": "BKSL",
  "lots": 9,
  "shares": 900,
  "buy_price": 102,
  "total_buy": 91800,
  "fee_buy": 92,
  "target_price": 125,
  "stop_loss": 99,
  "date_sell": "2026-05-11",
  "sell_price": 120,
  "total_sell": 108000,
  "fee_sell": 216,
  "pnl": 15892,
  "status": "closed"
}
```

**Status values:** `open` / `closed` (profit) / `stopped` (hit stop-loss)

## Holiday Calendar
The scanner uses a hardcoded IDX 2026 holiday calendar (`IDX_HOLIDAYS_2026` in `scanner.py`) so the 3-day time stop correctly skips public holidays. The list was sourced from the official IDX announcement (No. Peng-00171/BEI.POP/09-2025).

**Update required:** At the start of 2027, replace `IDX_HOLIDAYS_2026` with the new year's holiday list from idx.co.id and redeploy.

## Known Limitations & Future Improvements
- Data source is Yahoo Finance end-of-day — signals use yesterday's close, not today's open
- No macro/news awareness — a stock can look oversold but be in a fundamental downtrend
- Backtested against 1 year of IDX data (May 2025–May 2026)
- Best config: score ≥ 9, +5% target, Exit Day 3 → +5.8% annual on Rp 1M simulation, 54.9% win rate
