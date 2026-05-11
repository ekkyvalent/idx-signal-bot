#!/usr/bin/env python3
"""
Backtest + Capital Simulation for IDX Signal Model.

Phase 1 — Strategy comparison: 1-day vs 3-day vs 5-day exit, all with +5% target.
           Tells you which holding period actually works best.

Phase 2 — Capital simulation: Starting with Rp 1,000,000, how much would you have
           made over the past year trading only score ≥ 8 signals?

Run: python3 backtest.py
Results are honest. Uses only data available at time of signal (no cheating).
Prices are end-of-day closes — real results will vary slightly due to gap opens.
"""

import warnings
warnings.filterwarnings("ignore")

from collections import defaultdict
from datetime import date as date_type

import numpy as np
import pandas as pd
import yfinance as yf

from scanner import (
    _UNIVERSE, _score, fetch_ihsg,
    FEE_BUY, FEE_SELL,
)

MIN_WINDOW    = 60       # days of history before scoring starts
MIN_SCORE     = 8        # only strong signals
INITIAL_CAP   = 1_000_000
PER_TRADE     = 100_000
MAX_POSITIONS = 10       # max concurrent open trades


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
                result[ticker] = df   # keep DatetimeIndex throughout
        except Exception:
            continue
    return result


# ── Signal generation (no lookahead) ─────────────────────────────────────────

def generate_signals(data_map, ihsg_df, tier_map):
    """
    For every stock, for every eligible day, score it using only past data.
    Returns list of signal dicts sorted by date.
    """
    signals = []
    total   = sum(max(0, len(df) - MIN_WINDOW - 5) for df in data_map.values())
    done    = 0

    for ticker, df in data_map.items():
        tier = tier_map.get(ticker, "Blue Chip")
        n    = len(df)

        for i in range(MIN_WINDOW, n - 5):
            df_slice = df.iloc[:i + 1]   # DatetimeIndex already

            ihsg_slice = None
            if ihsg_df is not None:
                cut = df_slice.index[-1]
                ihsg_slice = ihsg_df[ihsg_df.index <= cut]

            s = _score(df_slice, ticker, tier, ihsg_slice)
            done += 1
            if done % 5000 == 0:
                print(f"  Scoring... {done:,}/{total:,}", end="\r")

            if s is None or s["score"] < MIN_SCORE:
                continue

            signals.append({
                "ticker":       ticker,
                "tier":         tier,
                "date":         df_slice.index[-1],
                "idx":          i,
                "score":        s["score"],
                "entry_price":  float(df_slice["Close"].iloc[-1]),
                "stop":         s["stop"],
                "target":       s["target"],
            })

    signals.sort(key=lambda x: x["date"])
    print(f"  Scoring done. {len(signals)} strong signals found (score ≥ {MIN_SCORE}).\n")
    return signals


# ── Trade simulation ──────────────────────────────────────────────────────────

def sim_trade(df, entry_idx, entry_price, stop, target, max_days):
    """
    Simulate one trade. Returns (exit_price, days_held, reason).
    Checks each day's close for stop/target hit, otherwise exits at max_days.
    """
    close = df["Close"].values
    n     = len(close)

    for d in range(1, max_days + 1):
        if entry_idx + d >= n:
            return float(close[-1]), d, "end_of_data"
        day_close = float(close[entry_idx + d])
        if day_close >= target:
            return day_close, d, "target"
        if day_close <= stop:
            return day_close, d, "stop"
        if d == max_days:
            return day_close, d, "time"

    return entry_price, 0, "none"


def net_return(entry, exit_p, lots=1):
    shares = lots * 100
    gross  = (exit_p - entry) * shares
    fees   = entry * shares * FEE_BUY + exit_p * shares * FEE_SELL
    return gross - fees


# ── Phase 1: Strategy comparison ─────────────────────────────────────────────

STRATEGIES = [
    {"name": "Exit Day 1 (no target)",  "max_days": 1, "use_target": False},
    {"name": "Exit Day 3 (+5% target)", "max_days": 3, "use_target": True},
    {"name": "Exit Day 5 (+5% target)", "max_days": 5, "use_target": True},
]


def compare_strategies(signals, data_map):
    print("=" * 65)
    print("  PHASE 1 — STRATEGY COMPARISON  (score ≥ 8 signals)")
    print("=" * 65)
    print(f"  {'Strategy':<28} {'Signals':>8} {'Win%':>7} {'Avg Net':>9} {'Med Net':>9}")
    print("  " + "-" * 63)

    best_name, best_score = None, -999

    for strat in STRATEGIES:
        returns = []
        for sig in signals:
            df      = data_map.get(sig["ticker"])
            if df is None:
                continue
            target  = sig["target"] if strat["use_target"] else 1e9
            ex, days, reason = sim_trade(
                df, sig["idx"], sig["entry_price"],
                sig["stop"], target, strat["max_days"]
            )
            # Net return in % after fees
            shares  = 100
            gross   = (ex - sig["entry_price"]) * shares
            fees    = sig["entry_price"] * shares * FEE_BUY + ex * shares * FEE_SELL
            net_pct = (gross - fees) / (sig["entry_price"] * shares) * 100
            returns.append(net_pct)

        if not returns:
            continue

        wins    = sum(1 for r in returns if r > 0)
        win_pct = wins / len(returns) * 100
        avg_r   = np.mean(returns)
        med_r   = np.median(returns)

        print(f"  {strat['name']:<28} {len(returns):>8} {win_pct:>6.1f}% {avg_r:>+8.2f}% {med_r:>+8.2f}%")

        if avg_r > best_score:
            best_score = avg_r
            best_name  = strat["name"]

    print(f"\n  → Best strategy by avg net return: {best_name}")
    print()
    return best_name


# ── Phase 2: Capital simulation ───────────────────────────────────────────────

def capital_simulation(signals, data_map, best_strategy_name):
    strat = next(s for s in STRATEGIES if s["name"] == best_strategy_name)

    print("=" * 65)
    print(f"  PHASE 2 — CAPITAL SIMULATION")
    print(f"  Starting capital : Rp {INITIAL_CAP:,}")
    print(f"  Per trade        : Rp {PER_TRADE:,}")
    print(f"  Max positions    : {MAX_POSITIONS}")
    print(f"  Strategy         : {best_strategy_name}")
    print("=" * 65)

    cash      = float(INITIAL_CAP)
    positions = []      # active: {ticker, entry_price, stop, target, lots, cost, entry_date, idx}
    all_trades = []
    monthly_capital = {}

    # Group signals by date for fast lookup
    signals_by_date = defaultdict(list)
    for s in signals:
        signals_by_date[s["date"]].append(s)

    # All trading dates across all stocks
    all_dates = sorted(set(
        ts for df in data_map.values() for ts in df.index
    ))

    for current_ts in all_dates:
        current_date = current_ts.date()

        # ── Close positions that exit today ───────────────────────────
        still_open = []
        for pos in positions:
            df = data_map.get(pos["ticker"])
            if df is None:
                still_open.append(pos)
                continue

            if current_ts not in df.index:
                still_open.append(pos)
                continue

            today_close = float(df.loc[current_ts, "Close"])
            td_held     = int(np.busday_count(pos["entry_date"], current_date))

            hit_target = today_close >= pos["target"]
            hit_stop   = today_close <= pos["stop"]
            hit_time   = td_held >= strat["max_days"]

            if hit_target or hit_stop or hit_time:
                lots   = pos["lots"]
                shares = lots * 100
                fees   = pos["entry_price"] * shares * FEE_BUY + today_close * shares * FEE_SELL
                pnl    = (today_close - pos["entry_price"]) * shares - fees
                cash  += pos["cost"] + pnl  # return cost + profit/loss

                reason = "target" if hit_target else "stop" if hit_stop else "time"
                all_trades.append({
                    "date":    current_date,
                    "ticker":  pos["ticker"],
                    "entry":   pos["entry_price"],
                    "exit":    today_close,
                    "pnl":     pnl,
                    "td":      td_held,
                    "reason":  reason,
                    "win":     pnl > 0,
                })
            else:
                still_open.append(pos)

        positions = still_open

        # ── Open new positions ─────────────────────────────────────────
        todays_signals = sorted(
            signals_by_date.get(current_ts, []),
            key=lambda x: x["score"], reverse=True
        )
        held_tickers = {p["ticker"] for p in positions}

        for sig in todays_signals:
            if len(positions) >= MAX_POSITIONS:
                break
            if sig["ticker"] in held_tickers:
                continue
            if cash < PER_TRADE:
                break

            lots  = max(1, int(PER_TRADE / (sig["entry_price"] * 100)))
            cost  = sig["entry_price"] * lots * 100
            fee   = cost * FEE_BUY

            if cash < cost + fee:
                continue

            cash -= (cost + fee)
            held_tickers.add(sig["ticker"])
            positions.append({
                "ticker":      sig["ticker"],
                "entry_price": sig["entry_price"],
                "stop":        sig["stop"],
                "target":      sig["target"],
                "lots":        lots,
                "cost":        cost,
                "entry_date":  current_date,
                "idx":         sig["idx"],
            })

        # ── Monthly snapshot ───────────────────────────────────────────
        month_key = current_ts.strftime("%b %Y")
        open_value = sum(
            p["entry_price"] * p["lots"] * 100 for p in positions
        )
        monthly_capital[month_key] = cash + open_value

    # Close any remaining open positions at last known price
    for pos in positions:
        df = data_map.get(pos["ticker"])
        if df is None:
            continue
        last_close = float(df["Close"].iloc[-1])
        lots   = pos["lots"]
        shares = lots * 100
        fees   = pos["entry_price"] * shares * FEE_BUY + last_close * shares * FEE_SELL
        pnl    = (last_close - pos["entry_price"]) * shares - fees
        cash  += pos["cost"] + pnl
        all_trades.append({
            "date":   date_type.today(), "ticker": pos["ticker"],
            "entry":  pos["entry_price"], "exit": last_close,
            "pnl":    pnl, "td": 99, "reason": "still_open", "win": pnl > 0,
        })

    # ── Monthly report ─────────────────────────────────────────────────
    print(f"\n  {'Month':<12} {'Capital':>14}  {'vs Start':>9}")
    print("  " + "-" * 40)

    prev_cap = INITIAL_CAP
    peak_cap = INITIAL_CAP
    max_dd   = 0.0
    monthly_returns = []

    for month, cap in monthly_capital.items():
        chg = (cap - INITIAL_CAP) / INITIAL_CAP * 100
        mom = (cap - prev_cap) / prev_cap * 100
        monthly_returns.append(mom)
        peak_cap = max(peak_cap, cap)
        dd = (peak_cap - cap) / peak_cap * 100
        max_dd = max(max_dd, dd)
        print(f"  {month:<12} Rp {cap:>12,.0f}  {chg:>+8.1f}%")
        prev_cap = cap

    # ── Summary ────────────────────────────────────────────────────────
    wins       = [t for t in all_trades if t["win"]]
    losses     = [t for t in all_trades if not t["win"]]
    total_pnl  = sum(t["pnl"] for t in all_trades)
    win_rate   = len(wins) / len(all_trades) * 100 if all_trades else 0
    avg_win    = np.mean([t["pnl"] for t in wins])    if wins   else 0
    avg_loss   = np.mean([t["pnl"] for t in losses])  if losses else 0

    by_reason = defaultdict(list)
    for t in all_trades:
        by_reason[t["reason"]].append(t["pnl"])

    print("\n" + "=" * 65)
    print(f"  Final capital    : Rp {cash:>12,.0f}")
    print(f"  Total gain       : Rp {cash - INITIAL_CAP:>+12,.0f}  "
          f"({(cash - INITIAL_CAP) / INITIAL_CAP * 100:+.1f}%)")
    print(f"  Total trades     : {len(all_trades)}")
    print(f"  Win rate         : {win_rate:.1f}%  "
          f"({len(wins)} wins / {len(losses)} losses)")
    print(f"  Avg win          : Rp {avg_win:>+,.0f}")
    print(f"  Avg loss         : Rp {avg_loss:>+,.0f}")
    print(f"  Best month       : {max(monthly_returns):+.1f}%")
    print(f"  Worst month      : {min(monthly_returns):+.1f}%")
    print(f"  Max drawdown     : -{max_dd:.1f}%")

    if by_reason:
        print(f"\n  Exit breakdown:")
        for reason, pnls in by_reason.items():
            w = sum(1 for p in pnls if p > 0)
            print(f"    {reason:<12} {len(pnls):>3} trades  "
                  f"win {w/len(pnls)*100:.0f}%  "
                  f"avg Rp {np.mean(pnls):>+,.0f}")

    print("\n  NOTE: Uses end-of-day prices. Real results will differ slightly")
    print("  due to opening gaps. Treat as directional estimate, not guarantee.")
    print("=" * 65 + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 65)
    print("  IDX Signal Model Backtest — 1 Year")
    print("=" * 65 + "\n")

    tickers  = [t for t, _ in _UNIVERSE]
    tier_map = {t: tier for t, tier in _UNIVERSE}

    data_map = download_1y(tickers)
    ihsg_df  = fetch_ihsg(period="1y")

    if ihsg_df is not None:
        ihsg_df.index = pd.to_datetime(ihsg_df.index)

    print(f"  Loaded {len(data_map)}/{len(tickers)} tickers.\n")

    signals  = generate_signals(data_map, ihsg_df, tier_map)

    if not signals:
        print("  No signals found. Check data or lower MIN_SCORE.")
        return

    best = compare_strategies(signals, data_map)
    capital_simulation(signals, data_map, best)


if __name__ == "__main__":
    main()
