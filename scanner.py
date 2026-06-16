"""
Core scanning logic — imported by signal_generator.py (local) and bot.py (Telegram).
Also used by backtest.py — keep _score() pure (no side effects, slice-safe).
"""

import json
import os
import warnings
warnings.filterwarnings("ignore")

from datetime import date as date_type

import numpy as np
import pandas as pd
import yfinance as yf

# ── Constants ─────────────────────────────────────────────────────────────────

FEE_BUY        = 0.0015     # 0.15% Stockbit buy fee
FEE_SELL       = 0.0035     # 0.25% broker + 0.1% PPh Final sell tax

# IDX public holidays 2026 — market closed on these dates
IDX_HOLIDAYS_2026 = np.busdaycalendar(holidays=[
    "2026-01-01",  # New Year's Day
    "2026-01-16",  # Isra Mi'raj
    "2026-02-16",  # Chinese New Year
    "2026-02-17",  # Chinese New Year Holiday
    "2026-03-18",  # Bali Hindu New Year
    "2026-03-19",  # Bali Hindu New Year Holiday
    "2026-03-20",  # Eid-ul-Fitr (1st day)
    "2026-03-23",  # Eid-ul-Fitr Holiday
    "2026-03-24",  # Eid-ul-Fitr Holiday
    "2026-04-03",  # Good Friday
    "2026-05-01",  # International Worker's Day
    "2026-05-14",  # Ascension Day of Jesus Christ
    "2026-05-27",  # Eid-al-Adha
    "2026-05-28",  # Eid-al-Adha Holiday
    "2026-06-01",  # Pancasila Day
    "2026-06-16",  # Islamic New Year
    "2026-08-17",  # Independence Day
    "2026-08-25",  # Mawlid
    "2026-12-24",  # Christmas Holiday
    "2026-12-25",  # Christmas Day
    "2026-12-31",  # Market Holiday
])
BUDGET         = 100_000    # Rp 100K per trade
MAX_PRICE      = BUDGET // 100  # Must afford ≥ 1 lot (100 shares)
MIN_AVG_VOLUME = 500_000    # 500K shares/day — filters illiquid stocks

# Min score to appear in results. Raised by 1 when IHSG is in a downtrend.
MIN_SCORE = {
    "Blue Chip": 8,
    "Mid-cap":   8,
    "Small Cap": 8,
}

# ── Stock universes ───────────────────────────────────────────────────────────

LQ45 = [
    "AALI", "ADRO", "AKRA", "AMMN", "AMRT", "ANTM", "ARTO", "ASII",
    "BBCA", "BBNI", "BBRI", "BBTN", "BMRI", "BRPT", "BUKA",
    "CPIN", "CUAN", "DEWA", "EMTK", "ESSA", "EXCL",
    "GOTO", "HEAL", "HRUM", "HRTA", "ICBP", "INCO", "INDF",
    "INTP", "ISAT", "ITMG", "KLBF", "MAPA", "MBMA", "MDKA",
    "MEDC", "MIKA", "MNCN", "PGAS", "PTBA",
    "SMGR", "TBIG", "TLKM", "TOWR", "UNTR", "UNVR", "WIFI",
]

IDX80_EXTRA = [
    "ACES", "ADHI", "AGII", "BJBR", "BJTM", "BKSL", "BSDE", "BULL",
    "CLEO", "CMRY", "CSAP", "DMAS", "DSNG", "ELSA", "ERAA",
    "GGRM", "HMSP", "INDY", "INKP", "JPFA", "KAEF", "KIJA",
    "LPKR", "LSIP", "MAPI", "MYOR", "NISP", "NCKL",
    "PGEO", "PTPP", "SCMA", "SIDO", "SMDR", "SSMS",
    "TINS", "ULTJ", "WIKA", "WSKT",
]

SMALL_CAPS = [
    "BRIS", "BSSR", "BWPT", "DPUM", "ENRG",
    "HITS", "MBSS", "SIMP",
    "SMRU", "TOBA", "WINS", "BANK", "BGTG",
    "COAL", "EDGE", "GTSI",
]

_UNIVERSE = (
    [(t, "Blue Chip") for t in LQ45] +
    [(t, "Mid-cap")   for t in IDX80_EXTRA if t not in LQ45] +
    [(t, "Small Cap") for t in SMALL_CAPS
     if t not in LQ45 and t not in IDX80_EXTRA]
)


# ── Technical helpers ─────────────────────────────────────────────────────────

def _rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series, fast=12, slow=26, signal=9):
    """Return (macd_line, signal_line, histogram) using exponential moving averages."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_histogram = macd_line - macd_signal
    return macd_line, macd_signal, macd_histogram


def _atr(df, period=14):
    high  = df["High"].squeeze()
    low   = df["Low"].squeeze()
    close = df["Close"].squeeze()
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def _hammer(df):
    """True if the last candle is a hammer — buyers defended the low aggressively."""
    try:
        o = float(df["Open"].iloc[-1])
        h = float(df["High"].iloc[-1])
        l = float(df["Low"].iloc[-1])
        c = float(df["Close"].iloc[-1])
        candle_range = h - l
        if candle_range <= 0:
            return False
        body         = abs(c - o)
        lower_shadow = min(o, c) - l
        upper_shadow = h - max(o, c)
        min_body     = max(body, candle_range * 0.05)  # avoid doji false positives
        return lower_shadow > 2 * min_body and upper_shadow < lower_shadow * 0.4
    except Exception:
        return False


def _adx(df, period=14):
    """Return ADX (trend strength) for the last candle. >25 = trending."""
    try:
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        close = df["Close"].squeeze()

        high_diff = high.diff()
        low_diff  = low.diff()
        pos_dm = high_diff.where((high_diff > 0) & (high_diff > -low_diff), 0)
        neg_dm = -low_diff.where((-low_diff > 0) & (-low_diff > high_diff), 0)

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        tr_s = tr.rolling(period).mean()
        pos_dm_s = pos_dm.rolling(period).mean()
        neg_dm_s = neg_dm.rolling(period).mean()

        pos_di = 100 * pos_dm_s / tr_s.replace(0, np.nan)
        neg_di = 100 * neg_dm_s / tr_s.replace(0, np.nan)

        dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di).replace(0, np.nan)
        adx = dx.rolling(period).mean()
        return float(adx.iloc[-1])
    except Exception:
        return 0.0


# ── Data fetching ─────────────────────────────────────────────────────────────

def _batch_fetch(tickers, period="3mo"):
    """Batch download OHLCV. Returns {ticker: DataFrame}."""
    jk = [f"{t}.JK" for t in tickers]
    try:
        raw = yf.download(
            jk, period=period, interval="1d",
            progress=False, auto_adjust=True, group_by="ticker",
        )
    except Exception:
        return {}

    result = {}
    for ticker, jk_ticker in zip(tickers, jk):
        try:
            lvl0 = raw.columns.get_level_values(0)
            df = raw[jk_ticker].dropna(how="all") if jk_ticker in lvl0 \
                 else raw.dropna(how="all")
            if len(df) >= 22:
                result[ticker] = df
        except Exception:
            continue
    return result


def fetch_current_prices(tickers):
    """Intraday price snapshot for a small set of tickers. Returns {ticker: float}."""
    if not tickers:
        return {}
    jk = [f"{t}.JK" for t in tickers]
    try:
        raw = yf.download(
            jk, period="1d", interval="5m",
            progress=False, auto_adjust=True, group_by="ticker",
        )
    except Exception:
        return {}
    prices = {}
    for ticker, jk_ticker in zip(tickers, jk):
        try:
            lvl0 = raw.columns.get_level_values(0)
            df = raw[jk_ticker].dropna(how="all") if jk_ticker in lvl0 \
                 else raw.dropna(how="all")
            val = df["Close"].dropna()
            if not val.empty:
                prices[ticker] = float(val.iloc[-1])
        except Exception:
            continue
    return prices


def fetch_ihsg(period="3mo"):
    """Download IHSG index separately (^JKSE ticker, no .JK suffix)."""
    try:
        df = yf.download("^JKSE", period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(how="all")
        return df if len(df) >= 22 else None
    except Exception:
        return None


# ── Core scoring (pure function — slice-safe for backtesting) ─────────────────

def _score(df, ticker, tier, ihsg_df=None):
    """
    Score a stock across 3 categories — Reversal, Breakout, Momentum.
    Returns the best-matching category with score and setup details.
    Returns None if the stock fails any filter or doesn't meet minimums.
    """
    try:
        close  = df["Close"].squeeze()
        volume = df["Volume"].squeeze()
        price  = float(close.iloc[-1])

        if price <= 0 or price > MAX_PRICE:
            return None

        avg_vol = float(volume.iloc[-21:-1].mean())
        if avg_vol < MIN_AVG_VOLUME:
            return None

        # ── Shared metrics ──────────────────────────────────────────────────
        r           = float(_rsi(close).iloc[-1])
        vol_td      = float(volume.iloc[-1])
        vol_ratio   = vol_td / avg_vol

        mom1d  = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        mom5d  = (float(close.iloc[-1]) - float(close.iloc[-6])) / float(close.iloc[-6]) * 100

        macd_line, macd_signal_line, macd_hist = _macd(close)
        macd_hist_now   = float(macd_hist.iloc[-1])
        macd_hist_prev  = float(macd_hist.iloc[-2])
        macd_hist_cross = False
        if len(macd_hist) >= 3:
            macd_hist_prev2 = float(macd_hist.iloc[-3])
            macd_hist_cross = (macd_hist_now > 0 and macd_hist_prev <= 0) or \
                              (macd_hist_prev > 0 and macd_hist_prev2 <= 0)

        sup_20 = float(close.iloc[-20:].min())
        res_20 = float(close.iloc[-20:].max())
        ma20   = float(close.iloc[-20:].mean())

        sup_50 = float(close.iloc[-50:].min()) if len(close) >= 50 else sup_20
        res_50 = float(close.iloc[-50:].max()) if len(close) >= 50 else res_20
        ma50   = float(close.iloc[-50:].mean()) if len(close) >= 50 else ma20

        atr14  = _atr(df)
        adx14  = _adx(df)

        above_ma20 = price > ma20
        above_ma50 = price > ma50
        near_high  = price >= res_20 * 0.98

        # ── Category 1: Reversal 🔄 (oversold bounce / support bounce) ──────
        rev_sc = 0
        if   r < 30: rev_sc += 3
        elif r < 40: rev_sc += 2
        elif r < 50: rev_sc += 1

        if   vol_ratio >= 1.5 and mom1d < -2:  rev_sc += 3  # capitulation
        elif vol_ratio >= 1.2 and mom1d < -2:  rev_sc += 2
        elif vol_ratio >= 2.0 and mom1d > 1:   rev_sc += 2  # strong bounce
        elif vol_ratio >= 1.5 and mom1d > 1:   rev_sc += 1  # mild bounce

        if  -8 < mom5d < -2:  rev_sc += 2
        elif mom5d <= -8:      rev_sc += 1

        if price <= sup_20 * 1.02: rev_sc += 2
        if price <= sup_50 * 1.02: rev_sc += 1

        if _hammer(df): rev_sc += 2

        if ihsg_df is not None and len(ihsg_df) >= 6:
            ihsg_close  = ihsg_df["Close"].squeeze()
            ihsg_mom5d  = (float(ihsg_close.iloc[-1]) - float(ihsg_close.iloc[-6])) \
                          / float(ihsg_close.iloc[-6]) * 100
            if mom5d > ihsg_mom5d:
                rev_sc += 1

        if macd_hist_now > 0:  rev_sc += 1
        if macd_hist_cross:    rev_sc += 1
        rev_sc = min(rev_sc, 10)
        rev_stop = max(round(sup_20 - 1.5 * atr14), round(price * 0.92))

        # ── Category 2: Breakout 🚀 (range breakout / consolidation end) ────
        brk_sc = 0

        # 1. Price near high + volume confirmation
        if near_high and vol_ratio >= 1.2 and mom1d > 0:
            brk_sc += 2  # volume-confirmed breakout
        elif near_high:
            brk_sc += 1  # price breaking out, volume pending

        # 2. Volume + direction — rising volume on an up day
        if vol_ratio >= 1.5 and mom1d > 0:
            brk_sc += 2
        elif vol_ratio >= 1.2 and mom1d > 0:
            brk_sc += 1

        # 3. Price structure
        if above_ma20: brk_sc += 1
        if above_ma50: brk_sc += 1

        # 4. RSI breakout zone (not exhausted)
        if 50 <= r <= 65:
            brk_sc += 1

        # 5. 5d momentum — breaking out of consolidation
        if 2 < mom5d < 10:
            brk_sc += 2
        elif mom5d > 10:
            brk_sc += 1

        # 6. ADX trend strength (broad)
        if adx14 > 30:
            brk_sc += 2
        elif adx14 > 25:
            brk_sc += 1

        # 7. MACD
        if macd_hist_cross:
            brk_sc += 1

        brk_sc = min(brk_sc, 10)
        brk_stop = max(round(ma20 - 1.5 * atr14), round(price * 0.94))

        # ── Category 3: Momentum 🏄 (trending / continuation) ───────────────
        mom_sc = 0

        # 1. Price structure — above key MAs
        if above_ma20 and above_ma50:
            mom_sc += 2  # bull structure
        elif above_ma20:
            mom_sc += 1

        # 2. ADX trend strength
        if adx14 > 30:
            mom_sc += 2
        elif adx14 > 25:
            mom_sc += 1

        # 3. Volume + direction — rising volume on an up day
        if vol_ratio >= 1.5 and mom1d > 1:
            mom_sc += 2
        elif vol_ratio >= 1.2 and mom1d > 1:
            mom_sc += 1

        # 4. RSI momentum zone (healthy, not exhausted)
        if 50 <= r <= 70:
            mom_sc += 1

        # 5. MACD momentum
        if macd_hist_now > 0:
            mom_sc += 1
        if macd_hist_cross:
            mom_sc += 1

        # 6. Near 20-day high
        if near_high:
            mom_sc += 1

        # 7. Healthy 5d momentum
        if 2 < mom5d < 10:
            mom_sc += 1

        mom_sc = min(mom_sc, 10)
        mom_stop = max(round(ma20 - 1.5 * atr14), round(price * 0.94))

        # ── Pick best category ──────────────────────────────────────────────
        # Priority tiebreaker: Reversal > Breakout > Momentum
        # (reversal is most time-sensitive)
        candidates = [
            (rev_sc, "reversal", "\U0001f504", rev_stop),
            (brk_sc, "breakout", "\U0001f680", brk_stop),
            (mom_sc, "momentum", "\U0001f3c4", mom_stop),
        ]
        # Sort by score desc, then by priority (index in list)
        by_priority = [("reversal", 0), ("breakout", 1), ("momentum", 2)]
        def sort_key(c):
            cat_priority = next(p[1] for p in by_priority if p[0] == c[1])
            return (-c[0], cat_priority)
        candidates.sort(key=sort_key)
        best_sc, best_cat, best_icon, best_stop = candidates[0]

        # ── Post-scoring ────────────────────────────────────────────────────
        sc = min(best_sc, 10)
        max_lots = max(1, int(BUDGET / (price * 100)))
        if   sc >= 8: lots = max_lots
        elif sc >= 6: lots = max(1, int(max_lots * 0.6))
        else:         lots = max(1, int(max_lots * 0.4))

        trend = "\u2191 uptrend" if price > ma20 else "\u2193 downtrend"
        target = round(price * 1.05)

        return {
            "ticker":      ticker,
            "tier":        tier,
            "price":       round(price),
            "rsi":         round(r, 1),
            "vol_ratio":   round(vol_ratio, 2),
            "mom1d":       round(mom1d, 1),
            "mom5d":       round(mom5d, 1),
            "support":     round(sup_20),
            "sup_50":      round(sup_50),
            "resistance":  round(res_20),
            "target":      target,
            "stop":        best_stop,
            "atr":         round(atr14, 1),
            "ma20":        round(ma20),
            "ma50":        round(ma50),
            "trend":       trend,
            "hammer":      _hammer(df),
            "adx":         round(adx14, 1),
            "lots":        lots,
            "score":       sc,
            "category":    best_cat,
            "category_icon": best_icon,
            "scores": {
                "reversal": rev_sc,
                "breakout": brk_sc,
                "momentum": mom_sc,
            },
            "macd_histogram": round(macd_hist_now, 2),
            "macd_line":    round(float(macd_line.iloc[-1]), 2),
            "macd_signal":  round(float(macd_signal_line.iloc[-1]), 2),
        }
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def run_scan(on_progress=None):
    """
    Full universe scan. Returns list of scored dicts, sorted by score desc.
    Downloads IHSG first for market context, then batch-fetches all stocks.
    """
    tickers = [t for t, _ in _UNIVERSE]

    if on_progress:
        on_progress(0, len(tickers), "fetching IHSG + stock data...")

    ihsg_df  = fetch_ihsg()
    data_map = _batch_fetch(tickers)

    # IHSG trend filter: if market is in downtrend, raise bar for all tiers
    ihsg_bearish = False
    if ihsg_df is not None and len(ihsg_df) >= 20:
        ihsg_close   = ihsg_df["Close"].squeeze()
        ihsg_bearish = float(ihsg_close.iloc[-1]) < float(ihsg_close.iloc[-20:].mean())

    min_score_adj = {tier: min(v + (1 if ihsg_bearish else 0), 10) for tier, v in MIN_SCORE.items()}

    results = []
    for i, (ticker, tier) in enumerate(_UNIVERSE):
        if on_progress:
            on_progress(i + 1, len(tickers), ticker)
        df = data_map.get(ticker)
        if df is None:
            continue
        s = _score(df, ticker, tier, ihsg_df)
        if s and s["score"] >= min_score_adj[tier]:
            s["market"] = "bear" if ihsg_bearish else "bull"
            results.append(s)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def current_price(ticker):
    try:
        data = _batch_fetch([ticker])
        df   = data.get(ticker)
        return round(float(df["Close"].squeeze().iloc[-1])) if df is not None else None
    except Exception:
        return None


def review_portfolio(transactions_file, signals_map=None):
    if not os.path.exists(transactions_file):
        return []
    with open(transactions_file) as f:
        data = json.load(f)

    rows = []
    for t in data["transactions"]:
        if t["status"] != "open":
            continue

        ticker    = t["ticker"]
        buy_price = t["buy_price"]
        lots      = t["lots"]
        shares    = lots * 100

        now = signals_map.get(ticker, {}).get("price") if signals_map else None
        if now is None:
            now = current_price(ticker)

        if now is None:
            rows.append({**t, "now": None, "pct": None, "pnl": None, "action": "Check manually"})
            continue

        pct   = (now - buy_price) / buy_price * 100
        gross = (now - buy_price) * shares
        fee   = buy_price * shares * FEE_BUY + now * shares * FEE_SELL
        pnl   = gross - fee

        target = t.get("target_price") or 0
        stop   = t.get("stop_loss") or 0

        # Trading days held (Mon–Fri, excluding IDX public holidays)
        try:
            buy_dt  = pd.Timestamp(t["date_buy"]).date()
            td_held = int(np.busday_count(buy_dt, date_type.today(), busdaycal=IDX_HOLIDAYS_2026))
        except Exception:
            td_held = 0

        if td_held >= 3:
            # Time stop — exit regardless of P&L
            action = f"EXIT — 3-day limit reached ({'up' if pct >= 0 else 'down'} {pct:+.1f}%)"
        elif target and now >= target:
            action = "TAKE PROFIT — hit target"
        elif stop and now <= stop:
            action = "CUT LOSS — below stop"
        elif pct >= 5:
            action = "TAKE PROFIT — up 5%"
        else:
            action = f"Hold — day {td_held}/3"

        rows.append({**t, "now": now, "pct": round(pct, 1), "pnl": round(pnl),
                     "td_held": td_held, "action": action})

    return rows


def load_transactions(transactions_file):
    if not os.path.exists(transactions_file):
        return {"transactions": []}
    with open(transactions_file) as f:
        return json.load(f)


def save_transactions(data, transactions_file):
    with open(transactions_file, "w") as f:
        json.dump(data, f, indent=2)


def log_buy(transactions_file, ticker, lots, buy_price, target=None, stop=None):
    data   = load_transactions(transactions_file)
    trx_id = f"TRX-{len(data['transactions']) + 1:03d}"
    shares = lots * 100
    fee    = round(buy_price * shares * FEE_BUY)
    entry  = {
        "id": trx_id, "date_buy": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "ticker": ticker.upper(), "lots": lots, "shares": shares,
        "buy_price": buy_price, "total_buy": buy_price * shares, "fee_buy": fee,
        "target_price": target, "stop_loss": stop,
        "date_sell": None, "sell_price": None, "total_sell": None,
        "fee_sell": None, "pnl": None, "status": "open",
    }
    data["transactions"].append(entry)
    save_transactions(data, transactions_file)
    return entry


def log_sell(transactions_file, ticker, sell_price):
    data   = load_transactions(transactions_file)
    ticker = ticker.upper()
    match  = next((t for t in reversed(data["transactions"])
                   if t["ticker"] == ticker and t["status"] == "open"), None)
    if not match:
        return None

    shares   = match["lots"] * 100
    fee_sell = round(sell_price * shares * FEE_SELL)
    pnl      = round((sell_price - match["buy_price"]) * shares
                     - match["fee_buy"] - fee_sell)

    match.update({
        "sell_price": sell_price, "total_sell": sell_price * shares,
        "fee_sell": fee_sell, "pnl": pnl,
        "date_sell": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "status": "closed" if pnl >= 0 else "stopped",
    })
    save_transactions(data, transactions_file)
    return match
