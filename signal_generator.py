#!/usr/bin/env python3
"""
Local runner — generates signals_latest.md and sends a Mac notification.
The bot (bot.py) uses the same scanner.py logic.
"""

import os
import subprocess
from datetime import date

from scanner import run_scan, review_portfolio

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
TRANSACTIONS_FILE = os.path.join(SCRIPT_DIR, "transactions.json")
OUTPUT_FILE       = os.path.join(SCRIPT_DIR, "signals_latest.md")


def fmt_portfolio_md(rows):
    if not rows:
        return "No open positions.\n"
    lines = ["| Stock | Bought | Now | Change | Lots | Unrealised P&L | Action |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["now"] is None:
            lines.append(f"| {r['ticker']} | {r['buy_price']:,} | N/A | — | {r['lots']} | — | Check manually |")
            continue
        sign = "+" if r["pnl"] >= 0 else ""
        lines.append(
            f"| {r['ticker']} | {r['buy_price']:,} | {r['now']:,} | {r['pct']:+.1f}% "
            f"| {r['lots']} | {sign}Rp {r['pnl']:,} | {r['action']} |"
        )
    return "\n".join(lines) + "\n"


def fmt_signals_md(results):
    if not results:
        return "No strong signals today. Market may be overextended.\n"
    lines = []
    for rank, s in enumerate(results[:5], 1):
        upside = (s["target"] - s["price"]) / s["price"] * 100
        risk   = (s["price"] - s["stop"]) / s["price"] * 100
        cost   = s["price"] * s["lots"] * 100
        lines.append(
            f"### {rank}. {s['ticker']} [{s.get('tier','')}] — Score {s['score']}/10\n"
            f"- **Buy at:** Rp {s['price']:,}\n"
            f"- **Target:** Rp {s['target']:,} (+3%) — take profit here\n"
            f"- **Stop-loss:** Rp {s['stop']:,} (-{risk:.1f}%) | Exit after 3 trading days regardless\n"
            f"- **Lots:** {s['lots']} lots ({s['lots']*100:,} shares) ≈ Rp {cost:,}\n"
            f"- **Why:** RSI {s['rsi']} | Volume {s['vol_ratio']}x avg | "
            f"1d {s['mom1d']:+.1f}% | 5d {s['mom5d']:+.1f}% | {s.get('trend','')} | "
            f"Support Rp {s['support']:,} / Resistance Rp {s['resistance']:,}\n"
        )
    return "\n".join(lines)


def main():
    today = date.today().strftime("%A, %d %B %Y")
    print(f"Scanning LQ45 + IDX80 + small caps...")

    def progress(i, total, ticker):
        print(f"  [{i}/{total}] {ticker}          ", end="\r")

    results = run_scan(on_progress=progress)
    signals_map = {s["ticker"]: s for s in results}
    portfolio   = review_portfolio(TRANSACTIONS_FILE, signals_map)

    output = "\n".join([
        f"# IDX Signal Report — {today}\n",
        "## Portfolio Check\n",
        fmt_portfolio_md(portfolio),
        "\n## Buy Signals\n",
        fmt_signals_md(results),
        "\n---\n_Generated automatically. Always apply your own judgment._\n",
    ])

    with open(OUTPUT_FILE, "w") as f:
        f.write(output)

    print(f"\n\nDone. → {OUTPUT_FILE}\n")
    print(output)

    count = min(len(results), 5)
    subprocess.run([
        "osascript", "-e",
        f'display notification "{count} signals ready." with title "IDX Signals — {today}"'
    ], check=False)


if __name__ == "__main__":
    main()
