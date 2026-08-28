"""
Core scanning logic — imported by bot.py (Telegram, VPS) and backtest.py.
Also used by signal_generator.py.

Data backend (live): TradingView scanner API — free, no API key, works from VPS.
Data backend (backtest): yfinance — kept for backtest.py compatibility only.
                          yfinance is BLOCKED from this VPS (Yahoo 429 on China IP).
"""

import json
import logging
import os
import time
import warnings
warnings.filterwarnings("ignore")

from datetime import date as date_type

import numpy as np
import pandas as pd

# yfinance is optional — only needed by backtest.py (blocked on VPS anyway).
try:
    import yfinance as yf
except ImportError:
    yf = None

# TradingView backend — curl_cffi browser impersonation avoids Cloudflare blocks.
from curl_cffi import requests as cr

logger = logging.getLogger(__name__)

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

# ── TradingView backend ───────────────────────────────────────────────────────

TV_SCAN_URL = "https://scanner.tradingview.com/indonesia/scan"
IHSG_TV     = "IDX:COMPOSITE"

TV_COLUMNS = [
    "open", "high", "low", "close", "volume",
    "average_volume_30d_calc",
    "RSI", "ADX", "ATR",
    "MACD.macd", "MACD.signal", "MACD.hist", "MACD.hist|1",
    "SMA20", "SMA50",
    "change", "Perf.W",
    "High.1M", "Low.1M", "High.3M", "Low.3M",
]


def _tv_scan(tickers):
    """
    One POST to TradingView scanner for all tickers.
    Returns {tv_symbol: {column: value}}. Raises on failure.
    """
    body = {"symbols": {"tickers": tickers}, "columns": TV_COLUMNS}
    last_err = None
    for attempt in range(3):
        try:
            r = cr.post(TV_SCAN_URL, json=body, impersonate="chrome", timeout=30)
            r.raise_for_status()
            out = {}
            for item in r.json().get("data", []):
                out[item["s"]] = dict(zip(TV_COLUMNS, item["d"]))
            return out
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"TradingView scan failed after 3 attempts: {last_err}")


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


def _hammer_candle(o, h, l, c):
    """True if this candle is a hammer — buyers defended the low aggressively."""
    try:
        o, h, l, c = float(o), float(h), float(l), float(c)
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


def _hammer(df):
    """DataFrame wrapper (backtest compat) — checks the last candle."""
    try:
        return _hammer_candle(
            df["Open"].iloc[-1], df["High"].iloc[-1],
            df["Low"].iloc[-1],  df["Close"].iloc[-1],
        )
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


# ── Metrics extraction (single source of truth for scoring input) ─────────────

def _metrics_from_df(df, ihsg_df=None):
    """
    Build the metrics dict from an OHLCV DataFrame (yfinance style).
    Used by backtest.py path. Semantics identical to the original _score().
    """
    close  = df["Close"].squeeze()
    volume = df["Volume"].squeeze()
    price  = float(close.iloc[-1])
    if price <= 0:
        return None

    avg_vol = float(volume.iloc[-21:-1].mean())

    r = float(_rsi(close).iloc[-1])
    vol_td    = float(volume.iloc[-1])
    vol_ratio = vol_td / avg_vol

    mom1d = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
    mom5d = (float(close.iloc[-1]) - float(close.iloc[-6])) / float(close.iloc[-6]) * 100

    macd_line, macd_signal_line, macd_hist = _macd(close)
    macd_hist_now  = float(macd_hist.iloc[-1])
    macd_hist_prev = float(macd_hist.iloc[-2])
    macd_cross = False
    if len(macd_hist) >= 3:
        macd_hist_prev2 = float(macd_hist.iloc[-3])
        macd_cross = (macd_hist_now > 0 and macd_hist_prev <= 0) or \
                     (macd_hist_prev > 0 and macd_hist_prev2 <= 0)

    sup_20 = float(close.iloc[-20:].min())
    res_20 = float(close.iloc[-20:].max())
    ma20   = float(close.iloc[-20:].mean())

    sup_50 = float(close.iloc[-50:].min()) if len(close) >= 50 else sup_20
    ma50   = float(close.iloc[-50:].mean()) if len(close) >= 50 else ma20

    atr14 = _atr(df)
    adx14 = _adx(df)

    beats_ihsg = False
    if ihsg_df is not None and len(ihsg_df) >= 6:
        ihsg_close = ihsg_df["Close"].squeeze()
        ihsg_mom5d = (float(ihsg_close.iloc[-1]) - float(ihsg_close.iloc[-6])) \
                     / float(ihsg_close.iloc[-6]) * 100
        beats_ihsg = mom5d > ihsg_mom5d

    o = float(df["Open"].iloc[-1])
    h = float(df["High"].iloc[-1])
    l = float(df["Low"].iloc[-1])

    return {
        "price": price, "o": o, "h": h, "l": l,
        "rsi": r, "vol_ratio": vol_ratio, "avg_vol": avg_vol,
        "mom1d": mom1d, "mom5d": mom5d,
        "macd_hist_now": macd_hist_now, "macd_cross": macd_cross,
        "macd_line": float(macd_line.iloc[-1]),
        "macd_signal": float(macd_signal_line.iloc[-1]),
        "sup_20": sup_20, "res_20": res_20, "ma20": ma20,
        "sup_50": sup_50, "ma50": ma50,
        "atr": atr14, "adx": adx14,
        "hammer": _hammer_candle(o, h, l, price),
        "beats_ihsg_5d": beats_ihsg,
    }


def _metrics_from_tv(f, ihsg=None):
    """
    Build the metrics dict from one TradingView scanner row.
    Approximations vs the yfinance path (documented in SKILL.md):
      - avg_vol: 30d average (was 20d ex-today)
      - mom5d: Perf.W (1 trading week %)
      - sup/res_20: Low/High.1M (~22 trading days)
      - sup_50: Low.3M (~63 days, was 50)
      - MACD cross: 1-bar lookback (was 2-bar)
    """
    price = f.get("close")
    if not price or price <= 0:
        return None
    vol     = f.get("volume")
    avg_vol = f.get("average_volume_30d_calc")
    if not vol or not avg_vol or avg_vol <= 0:
        return None

    hist_now = f.get("MACD.hist")
    hist_prev = f.get("MACD.hist|1")
    macd_cross = False
    if hist_now is not None and hist_prev is not None:
        macd_cross = (hist_now > 0 and hist_prev <= 0)

    o, h, l, c = f.get("open"), f.get("high"), f.get("low"), price
    perfw   = f.get("Perf.W")
    ihsg_pw = (ihsg or {}).get("Perf.W")

    def _num(v, default=0.0):
        return float(v) if v is not None else default

    return {
        "price": float(price), "o": _num(o), "h": _num(h), "l": _num(l),
        "rsi": _num(f.get("RSI"), 50.0),
        "vol_ratio": float(vol) / float(avg_vol),
        "avg_vol": float(avg_vol),
        "mom1d": _num(f.get("change")),
        "mom5d": _num(perfw),
        "macd_hist_now": _num(hist_now),
        "macd_cross": macd_cross,
        "macd_line": _num(f.get("MACD.macd")),
        "macd_signal": _num(f.get("MACD.signal")),
        "sup_20": _num(f.get("Low.1M")), "res_20": _num(f.get("High.1M")),
        "ma20": _num(f.get("SMA20")), "ma50": _num(f.get("SMA50")),
        "sup_50": _num(f.get("Low.3M")),
        "atr": _num(f.get("ATR")), "adx": _num(f.get("ADX")),
        "hammer": _hammer_candle(o, h, l, c),
        "beats_ihsg_5d": (perfw is not None and ihsg_pw is not None
                          and float(perfw) > float(ihsg_pw)),
    }


# ── Core scoring (pure function — no side effects) ────────────────────────────

def _score_metrics(m, ticker, tier):
    """
    Score a stock across 3 categories — Reversal, Breakout, Momentum.
    `m` = metrics dict from _metrics_from_df or _metrics_from_tv.
    Returns the best-matching category with score and setup details,
    or None if the stock fails any filter or doesn't meet minimums.
    """
    try:
        price = m["price"]
        if price <= 0 or price > MAX_PRICE:
            return None
        if m["avg_vol"] < MIN_AVG_VOLUME:
            return None

        r          = m["rsi"]
        vol_ratio  = m["vol_ratio"]
        mom1d      = m["mom1d"]
        mom5d      = m["mom5d"]

        macd_hist_now   = m["macd_hist_now"]
        macd_hist_cross = m["macd_cross"]

        sup_20 = m["sup_20"]
        res_20 = m["res_20"]
        ma20   = m["ma20"]
        sup_50 = m["sup_50"]
        ma50   = m["ma50"]

        atr14 = m["atr"]
        adx14 = m["adx"]

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

        if m["hammer"]: rev_sc += 2

        if m["beats_ihsg_5d"]:
            rev_sc += 1

        if macd_hist_now > 0:  rev_sc += 1
        if macd_hist_cross:    rev_sc += 1
        rev_sc = min(rev_sc, 10)
        rev_stop = max(round(sup_20 - 1.5 * atr14), round(price * 0.92))

        # ── Category 2: Breakout 🚀 (range breakout / consolidation end) ────
        brk_sc = 0

        if near_high and vol_ratio >= 1.2 and mom1d > 0:
            brk_sc += 2
        elif near_high:
            brk_sc += 1

        if vol_ratio >= 1.5 and mom1d > 0:
            brk_sc += 2
        elif vol_ratio >= 1.2 and mom1d > 0:
            brk_sc += 1

        if above_ma20: brk_sc += 1
        if above_ma50: brk_sc += 1

        if 50 <= r <= 65:
            brk_sc += 1

        if 2 < mom5d < 10:
            brk_sc += 2
        elif mom5d > 10:
            brk_sc += 1

        if adx14 > 30:
            brk_sc += 2
        elif adx14 > 25:
            brk_sc += 1

        if macd_hist_cross:
            brk_sc += 1

        brk_sc = min(brk_sc, 10)
        brk_stop = max(round(ma20 - 1.5 * atr14), round(price * 0.94))

        # ── Category 3: Momentum 🏄 (trending / continuation) ───────────────
        mom_sc = 0

        if above_ma20 and above_ma50:
            mom_sc += 2
        elif above_ma20:
            mom_sc += 1

        if adx14 > 30:
            mom_sc += 2
        elif adx14 > 25:
            mom_sc += 1

        if vol_ratio >= 1.5 and mom1d > 1:
            mom_sc += 2
        elif vol_ratio >= 1.2 and mom1d > 1:
            mom_sc += 1

        if 50 <= r <= 70:
            mom_sc += 1

        if macd_hist_now > 0:
            mom_sc += 1
        if macd_hist_cross:
            mom_sc += 1

        if near_high:
            mom_sc += 1

        if 2 < mom5d < 10:
            mom_sc += 1

        mom_sc = min(mom_sc, 10)
        mom_stop = max(round(ma20 - 1.5 * atr14), round(price * 0.94))

        # ── Pick best category ──────────────────────────────────────────────
        # Priority tiebreaker: Reversal > Breakout > Momentum
        candidates = [
            (rev_sc, "reversal", "\U0001f504", rev_stop),
            (brk_sc, "breakout", "\U0001f680", brk_stop),
            (mom_sc, "momentum", "\U0001f3c4", mom_stop),
        ]
        by_priority = [("reversal", 0), ("breakout", 1), ("momentum", 2)]
        def sort_key(c):
            cat_priority = next(p[1] for p in by_priority if p[0] == c[1])
            return (-c[0], cat_priority)
        candidates.sort(key=sort_key)
        best_sc, best_cat, best_icon, best_stop = candidates[0]

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
            "hammer":      m["hammer"],
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
            "macd_line":    round(m["macd_line"], 2),
            "macd_signal":  round(m["macd_signal"], 2),
        }
    except Exception:
        logger.exception("scoring failed for %s", ticker)
        return None


def _score(df, ticker, tier, ihsg_df=None):
    """DataFrame path — backtest.py compatibility wrapper."""
    m = _metrics_from_df(df, ihsg_df)
    return _score_metrics(m, ticker, tier) if m else None


# ── Data fetching (live) ──────────────────────────────────────────────────────

def fetch_current_prices(tickers):
    """Live price snapshot for a small set of tickers. Returns {ticker: float}."""
    if not tickers:
        return {}
    try:
        rows = _tv_scan([f"IDX:{t}" for t in tickers])
    except Exception:
        logger.exception("fetch_current_prices failed")
        return {}
    prices = {}
    for ticker in tickers:
        row = rows.get(f"IDX:{ticker}")
        if row and row.get("close"):
            prices[ticker] = float(row["close"])
    return prices


def fetch_ihsg(period="3mo"):
    """Download IHSG index as a DataFrame (^JKSE). Backtest path — needs yfinance."""
    if yf is None:
        return None
    try:
        df = yf.download("^JKSE", period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(how="all")
        return df if len(df) >= 22 else None
    except Exception:
        return None


# ── Live scan (TradingView) ───────────────────────────────────────────────────

def run_scan(on_progress=None):
    """
    Full universe scan via TradingView — ONE request for all tickers + IHSG.
    Returns list of scored dicts, sorted by score desc.
    """
    tickers = [t for t, _ in _UNIVERSE]

    if on_progress:
        on_progress(0, len(tickers), "fetching via TradingView...")

    try:
        rows = _tv_scan([IHSG_TV] + [f"IDX:{t}" for t in tickers])
    except Exception:
        logger.exception("TradingView scan failed — returning empty")
        return []

    ihsg = rows.get(IHSG_TV, {})
    if on_progress:
        on_progress(1, len(tickers), "scoring...")

    # IHSG trend filter: below its own SMA20 = bearish market
    ihsg_bearish = False
    if ihsg.get("close") and ihsg.get("SMA20"):
        ihsg_bearish = float(ihsg["close"]) < float(ihsg["SMA20"])

    min_score_adj = {tier: min(v + (1 if ihsg_bearish else 0), 10)
                     for tier, v in MIN_SCORE.items()}

    results = []
    for i, (ticker, tier) in enumerate(_UNIVERSE):
        if on_progress:
            on_progress(i + 1, len(tickers), ticker)
        row = rows.get(f"IDX:{ticker}")
        if not row:
            continue
        m = _metrics_from_tv(row, ihsg)
        if not m:
            continue
        s = _score_metrics(m, ticker, tier)
        if s and s["score"] >= min_score_adj[tier]:
            s["market"] = "bear" if ihsg_bearish else "bull"
            results.append(s)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def current_price(ticker):
    prices = fetch_current_prices([ticker])
    return round(prices[ticker]) if ticker in prices else None


# ── Portfolio / transactions ──────────────────────────────────────────────────

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
