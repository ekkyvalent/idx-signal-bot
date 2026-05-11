#!/usr/bin/env python3
"""
Algorithm comparison: Old scoring vs New scoring + parameter tests.
Same 1-year data, side-by-side phase 1 and capital simulation results.
"""

import warnings
warnings.filterwarnings("ignore")

from collections import defaultdict
from datetime import date as date_type

import numpy as np
import pandas as pd
import yfinance as yf

from scanner import _UNIVERSE, _rsi, _atr, _hammer, fetch_ihsg, FEE_BUY, FEE_SELL

MIN_WINDOW = 60
MIN_SCORE  = 8


# ── Old scoring function (pre-improvement model) ──────────────────────────────

def _score_old(df, ticker, tier, ihsg_df=None):
    """
    Original algorithm:
    - RSI thresholds at 35/45/55
    - Non-directional volume (just ratio)
    - 1-day momentum as separate +1 signal
    - MA20 scored (price > MA20 = +1)
    - Fixed 3% stop
    - 20-day resistance as target
    """
    try:
        close  = df["Close"].squeeze()
        volume = df["Volume"].squeeze()
        price  = float(close.iloc[-1])

        if price <= 0 or price > 1000:
            return None

        avg_vol = float(volume.iloc[-21:-1].mean())
        if avg_vol < 500_000:
            return None

        r         = float(_rsi(close).iloc[-1])
        vol_td    = float(volume.iloc[-1])
        vol_ratio = vol_td / avg_vol
        mom1d     = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        mom5d     = (float(close.iloc[-1]) - float(close.iloc[-6])) / float(close.iloc[-6]) * 100
        sup_20    = float(close.iloc[-20:].min())
        res_20    = float(close.iloc[-20:].max())
        ma20      = float(close.iloc[-20:].mean())

        sc = 0

        # RSI (old thresholds: 35/45/55)
        if   r < 35: sc += 3
        elif r < 45: sc += 2
        elif r < 55: sc += 1

        # Volume — non-directional
        if   vol_ratio >= 2.0: sc += 3
        elif vol_ratio >= 1.5: sc += 2
        elif vol_ratio >= 1.2: sc += 1

        # 1-day momentum (separate signal)
        if mom1d > 1: sc += 1

        # 5-day pullback
        if -8 < mom5d < -2: sc += 2

        # 20-day support
        if price <= sup_20 * 1.02: sc += 2

        # MA20 trend (was scored, not just display)
        if price > ma20: sc += 1

        sc = min(sc, 10)

        # Old stop: fixed 3%
        stop   = round(price * 0.97)
        # Old target: 20-day resistance
        target = round(res_20)

        max_lots = max(1, int(100_000 / (price * 100)))
        if   sc >= 8: lots = max_lots
        elif sc >= 6: lots = max(1, int(max_lots * 0.6))
        else:         lots = max(1, int(max_lots * 0.4))

        return {
            "ticker": ticker, "tier": tier,
            "price": round(price), "rsi": round(r, 1),
            "vol_ratio": round(vol_ratio, 2),
            "mom1d": round(mom1d, 1), "mom5d": round(mom5d, 1),
            "support": round(sup_20), "resistance": round(res_20),
            "target": target, "stop": stop,
            "lots": lots, "score": sc,
        }
    except Exception:
        return None


# ── New scoring function (current model) ─────────────────────────────────────

def _score_new(df, ticker, tier, ihsg_df=None, **kwargs):
    """
    Current algorithm:
    - RSI thresholds at 30/40/50
    - Directional volume (capitulation vs momentum)
    - Hammer candle detection
    - 50-day support layer
    - Relative strength vs IHSG
    - MA20 display only (not scored)
    - ATR-based stop
    - Fixed +5% target
    """
    try:
        close  = df["Close"].squeeze()
        volume = df["Volume"].squeeze()
        price  = float(close.iloc[-1])

        if price <= 0 or price > 1000:
            return None

        avg_vol = float(volume.iloc[-21:-1].mean())
        if avg_vol < 500_000:
            return None

        r         = float(_rsi(close).iloc[-1])
        vol_td    = float(volume.iloc[-1])
        vol_ratio = vol_td / avg_vol
        mom1d     = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        mom5d     = (float(close.iloc[-1]) - float(close.iloc[-6])) / float(close.iloc[-6]) * 100
        sup_20    = float(close.iloc[-20:].min())
        res_20    = float(close.iloc[-20:].max())
        ma20      = float(close.iloc[-20:].mean())
        sup_50    = float(close.iloc[-50:].min()) if len(close) >= 50 else sup_20
        atr14     = _atr(df)

        sc = 0

        # RSI (tighter thresholds: 30/40/50)
        if   r < 30: sc += 3
        elif r < 40: sc += 2
        elif r < 50: sc += 1

        # Directional volume
        if   vol_ratio >= 1.5 and mom1d < -2: sc += 3  # capitulation
        elif vol_ratio >= 1.2 and mom1d < -2: sc += 2
        elif vol_ratio >= 2.0 and mom1d > 1:  sc += 2  # strong momentum
        elif vol_ratio >= 1.5 and mom1d > 1:  sc += 1

        # 5-day pullback
        if  -8 < mom5d < -2: sc += 2
        elif mom5d <= -8:     sc += 1

        # Multi-timeframe support
        if price <= sup_20 * 1.02: sc += 2
        if price <= sup_50 * 1.02: sc += 1

        # Hammer candle
        if _hammer(df): sc += 2

        # Relative strength vs IHSG
        if ihsg_df is not None and len(ihsg_df) >= 6:
            ihsg_close = ihsg_df["Close"].squeeze()
            ihsg_mom5d = (float(ihsg_close.iloc[-1]) - float(ihsg_close.iloc[-6])) \
                         / float(ihsg_close.iloc[-6]) * 100
            if mom5d > ihsg_mom5d:
                sc += 1

        sc = min(sc, 10)

        stop        = max(round(sup_20 - 1.5 * atr14), round(price * 0.92))
        target_mult = kwargs.get("target_mult", 1.05)
        target      = round(price * target_mult)

        max_lots = max(1, int(100_000 / (price * 100)))
        if   sc >= 8: lots = max_lots
        elif sc >= 6: lots = max(1, int(max_lots * 0.6))
        else:         lots = max(1, int(max_lots * 0.4))

        return {
            "ticker": ticker, "tier": tier,
            "price": round(price), "rsi": round(r, 1),
            "vol_ratio": round(vol_ratio, 2),
            "mom1d": round(mom1d, 1), "mom5d": round(mom5d, 1),
            "support": round(sup_20), "resistance": round(res_20),
            "target": target, "stop": stop,
            "lots": lots, "score": sc,
        }
    except Exception:
        return None


# ── Data download ─────────────────────────────────────────────────────────────

def download_1y(tickers):
    jk = [f"{t}.JK" for t in tickers]
    print(f"  Downloading 1 year of data for {len(tickers)} tickers...")
    raw = yf.download(
        jk, period="1y", interval="1d",
        progress=False, auto_adjust=True, group_by="ticker",
    )
    result = {}
    for ticker, jk_ticker in zip(tickers, jk):
        try:
            lvl0 = raw.columns.get_level_values(0)
            df   = raw[jk_ticker].dropna(how="all") if jk_ticker in lvl0 \
                   else raw.dropna(how="all")
            df.index = pd.to_datetime(df.index)
            if len(df) >= MIN_WINDOW + 6:
                result[ticker] = df
        except Exception:
            continue
    return result


# ── Signal generation ─────────────────────────────────────────────────────────

def generate_signals(data_map, ihsg_df, tier_map, score_fn, label, min_score=8, score_kwargs=None):
    score_kwargs = score_kwargs or {}
    signals = []
    total   = sum(max(0, len(df) - MIN_WINDOW - 5) for df in data_map.values())
    done    = 0

    for ticker, df in data_map.items():
        tier = tier_map.get(ticker, "Blue Chip")
        n    = len(df)

        for i in range(MIN_WINDOW, n - 5):
            df_slice = df.iloc[:i + 1]

            ihsg_slice = None
            if ihsg_df is not None:
                cut = df_slice.index[-1]
                ihsg_slice = ihsg_df[ihsg_df.index <= cut]

            s = score_fn(df_slice, ticker, tier, ihsg_slice, **score_kwargs)
            done += 1
            if done % 5000 == 0:
                print(f"  [{label}] Scoring... {done:,}/{total:,}", end="\r")

            if s is None or s["score"] < min_score:
                continue

            signals.append({
                "ticker":      ticker,
                "idx":         i,
                "score":       s["score"],
                "entry_price": float(df_slice["Close"].iloc[-1]),
                "stop":        s["stop"],
                "target":      s["target"],
                "date":        df_slice.index[-1],
            })

    signals.sort(key=lambda x: x["date"])
    print(f"  [{label}] Done. {len(signals)} signals (score ≥ {min_score}).        ")
    return signals


# ── Trade simulation ──────────────────────────────────────────────────────────

STRATEGIES = [
    {"name": "Exit Day 1",  "max_days": 1, "use_target": False},
    {"name": "Exit Day 3",  "max_days": 3, "use_target": True},
    {"name": "Exit Day 5",  "max_days": 5, "use_target": True},
]


def sim_trade(df, entry_idx, entry_price, stop, target, max_days):
    close = df["Close"].values
    n     = len(close)
    for d in range(1, max_days + 1):
        if entry_idx + d >= n:
            return float(close[-1]), d, "end"
        day_close = float(close[entry_idx + d])
        if day_close >= target:
            return day_close, d, "target"
        if day_close <= stop:
            return day_close, d, "stop"
        if d == max_days:
            return day_close, d, "time"
    return entry_price, 0, "none"


def run_comparison(signals, data_map, label):
    rows = []
    for strat in STRATEGIES:
        returns, reasons = [], []
        for sig in signals:
            df = data_map.get(sig["ticker"])
            if df is None:
                continue
            target = sig["target"] if strat["use_target"] else 1e9
            ex, days, reason = sim_trade(
                df, sig["idx"], sig["entry_price"],
                sig["stop"], target, strat["max_days"]
            )
            shares  = 100
            gross   = (ex - sig["entry_price"]) * shares
            fees    = sig["entry_price"] * shares * FEE_BUY + ex * shares * FEE_SELL
            net_pct = (gross - fees) / (sig["entry_price"] * shares) * 100
            returns.append(net_pct)
            reasons.append(reason)

        if not returns:
            continue

        wins     = sum(1 for r in returns if r > 0)
        win_pct  = wins / len(returns) * 100
        avg_r    = np.mean(returns)
        med_r    = np.median(returns)
        targets  = reasons.count("target")
        stops    = reasons.count("stop")
        times    = reasons.count("time")

        rows.append({
            "algo":    label,
            "strat":   strat["name"],
            "signals": len(returns),
            "win_pct": win_pct,
            "avg_r":   avg_r,
            "med_r":   med_r,
            "targets": targets,
            "stops":   stops,
            "times":   times,
        })
    return rows


# ── Capital simulation ────────────────────────────────────────────────────────

INITIAL_CAP   = 1_000_000
PER_TRADE     = 100_000
MAX_POSITIONS = 10


def capital_sim(signals, data_map, label):
    """Run Rp 1M capital simulation using Exit Day 3 strategy."""
    cash      = float(INITIAL_CAP)
    positions = []
    all_trades = []

    signals_by_date = defaultdict(list)
    for s in signals:
        signals_by_date[s["date"]].append(s)

    all_dates = sorted(set(ts for df in data_map.values() for ts in df.index))

    for current_ts in all_dates:
        current_date = current_ts.date()

        still_open = []
        for pos in positions:
            df = data_map.get(pos["ticker"])
            if df is None or current_ts not in df.index:
                still_open.append(pos)
                continue

            today_close = float(df.loc[current_ts, "Close"])
            td_held     = int(np.busday_count(pos["entry_date"], current_date))
            hit_target  = today_close >= pos["target"]
            hit_stop    = today_close <= pos["stop"]
            hit_time    = td_held >= 3  # always Exit Day 3

            if hit_target or hit_stop or hit_time:
                shares = pos["lots"] * 100
                fees   = pos["entry_price"] * shares * FEE_BUY + today_close * shares * FEE_SELL
                pnl    = (today_close - pos["entry_price"]) * shares - fees
                cash  += pos["cost"] + pnl
                reason = "target" if hit_target else "stop" if hit_stop else "time"
                all_trades.append({"pnl": pnl, "win": pnl > 0, "reason": reason})
            else:
                still_open.append(pos)
        positions = still_open

        todays = sorted(signals_by_date.get(current_ts, []),
                        key=lambda x: x["score"], reverse=True)
        held = {p["ticker"] for p in positions}

        for sig in todays:
            if len(positions) >= MAX_POSITIONS or cash < PER_TRADE:
                break
            if sig["ticker"] in held:
                continue
            lots = max(1, int(PER_TRADE / (sig["entry_price"] * 100)))
            cost = sig["entry_price"] * lots * 100
            fee  = cost * FEE_BUY
            if cash < cost + fee:
                continue
            cash -= (cost + fee)
            held.add(sig["ticker"])
            positions.append({
                "ticker": sig["ticker"], "entry_price": sig["entry_price"],
                "stop": sig["stop"], "target": sig["target"],
                "lots": lots, "cost": cost, "entry_date": current_date,
            })

    # Close remaining positions at last price
    for pos in positions:
        df = data_map.get(pos["ticker"])
        if df is None:
            continue
        last_close = float(df["Close"].iloc[-1])
        shares = pos["lots"] * 100
        fees   = pos["entry_price"] * shares * FEE_BUY + last_close * shares * FEE_SELL
        pnl    = (last_close - pos["entry_price"]) * shares - fees
        cash  += pos["cost"] + pnl
        all_trades.append({"pnl": pnl, "win": pnl > 0, "reason": "still_open"})

    gain     = cash - INITIAL_CAP
    gain_pct = gain / INITIAL_CAP * 100
    trades   = len(all_trades)
    wins     = sum(1 for t in all_trades if t["win"])
    win_rate = wins / trades * 100 if trades else 0
    return {"label": label, "final": cash, "gain": gain, "gain_pct": gain_pct,
            "trades": trades, "win_rate": win_rate}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 70)
    print("  IDX Algorithm Comparison — Old vs New (1 Year)")
    print("=" * 70 + "\n")

    tickers  = [t for t, _ in _UNIVERSE]
    tier_map = {t: tier for t, tier in _UNIVERSE}

    data_map = download_1y(tickers)
    ihsg_df  = fetch_ihsg(period="1y")
    if ihsg_df is not None:
        ihsg_df.index = pd.to_datetime(ihsg_df.index)

    print(f"  Loaded {len(data_map)}/{len(tickers)} tickers.\n")

    # Baseline: current live model (score ≥ 8, +5% target)
    print("  [Baseline] score ≥ 8, +5% target...")
    sig_base = generate_signals(data_map, ihsg_df, tier_map, _score_new, "Baseline",
                                min_score=8, score_kwargs={"target_mult": 1.05})

    # Test A: score ≥ 8, +3% target
    print("  [A] score ≥ 8, +3% target...")
    sig_a = generate_signals(data_map, ihsg_df, tier_map, _score_new, "A",
                             min_score=8, score_kwargs={"target_mult": 1.03})

    # Test B: score ≥ 9, +5% target
    print("  [B] score ≥ 9, +5% target...")
    sig_b = generate_signals(data_map, ihsg_df, tier_map, _score_new, "B",
                             min_score=9, score_kwargs={"target_mult": 1.05})

    # Test C: score ≥ 9, +3% target
    print("  [C] score ≥ 9, +3% target...")
    sig_c = generate_signals(data_map, ihsg_df, tier_map, _score_new, "C",
                             min_score=9, score_kwargs={"target_mult": 1.03})

    tests = [
        ("Baseline (≥8, +5%)", sig_base),
        ("A  (≥8,  +3%)",      sig_a),
        ("B  (≥9,  +5%)",      sig_b),
        ("C  (≥9,  +3%)",      sig_c),
    ]

    print("\n" + "=" * 78)
    print("  RESULTS — Exit Day 3 only (best strategy from prior backtest)")
    print("=" * 78)
    print(f"\n  {'Test':<22} {'Signals':>8} {'Win%':>7} {'Avg Net':>9} {'Med Net':>9} {'Targets':>8} {'Stops':>7} {'Times':>7}")
    print("  " + "-" * 76)

    for label, sigs in tests:
        rows = run_comparison(sigs, data_map, label)
        # Only show Exit Day 3
        row = next((r for r in rows if r["strat"] == "Exit Day 3"), None)
        if row:
            print(
                f"  {label:<22} {row['signals']:>8} "
                f"{row['win_pct']:>6.1f}% {row['avg_r']:>+8.2f}% {row['med_r']:>+8.2f}% "
                f"{row['targets']:>8} {row['stops']:>7} {row['times']:>7}"
            )

    print("\n" + "=" * 78)
    print("  FULL TABLE — All exit strategies")
    print("=" * 78)
    print(f"\n  {'Test':<22} {'Strategy':<12} {'Signals':>8} {'Win%':>7} {'Avg Net':>9} {'Targets':>8} {'Times':>7}")
    print("  " + "-" * 76)

    prev_label = None
    for label, sigs in tests:
        rows = run_comparison(sigs, data_map, label)
        for row in rows:
            if prev_label and label != prev_label:
                print()
            print(
                f"  {label:<22} {row['strat']:<12} {row['signals']:>8} "
                f"{row['win_pct']:>6.1f}% {row['avg_r']:>+8.2f}% "
                f"{row['targets']:>8} {row['times']:>7}"
            )
            prev_label = label

    print("\n" + "=" * 78)
    print(f"  CAPITAL SIMULATION — Rp {INITIAL_CAP:,} starting, Exit Day 3")
    print("=" * 78)
    print(f"\n  {'Test':<22} {'Final Capital':>16} {'Annual Gain':>13} {'Trades':>8} {'Win%':>7}")
    print("  " + "-" * 70)

    for label, sigs in tests:
        r = capital_sim(sigs, data_map, label)
        print(
            f"  {label:<22} Rp {r['final']:>12,.0f}  {r['gain_pct']:>+8.1f}%"
            f"  {r['trades']:>8}  {r['win_rate']:>6.1f}%"
        )

    print()


if __name__ == "__main__":
    main()
