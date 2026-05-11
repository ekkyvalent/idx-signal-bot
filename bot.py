"""
IDX Signal Telegram Bot
Commands: /signals /portfolio /bought /sold /help
Scheduled morning report at 08:15 WIB every weekday.
"""

import asyncio
import logging
import os
from datetime import date, time

import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from scanner import (
    run_scan, review_portfolio,
    log_buy, log_sell, load_transactions,
    FEE_BUY, FEE_SELL,
)

# ── Config ────────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = int(os.environ["CHAT_ID"])
DATA_DIR  = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
TXN_FILE  = os.path.join(DATA_DIR, "transactions.json")

WIB = pytz.timezone("Asia/Jakarta")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_portfolio(rows):
    if not rows:
        return "No open positions."
    lines = []
    for r in rows:
        if r["now"] is None:
            lines.append(f"• *{r['ticker']}* — price unavailable. {r['action']}")
            continue
        sign    = "+" if r["pnl"] >= 0 else ""
        day_str = f"Day {r.get('td_held', '?')}/3"
        lines.append(
            f"• *{r['ticker']}* {day_str} | bought @ {r['buy_price']:,} | now {r['now']:,} "
            f"({r['pct']:+.1f}%)\n"
            f"  P&L: {sign}Rp {r['pnl']:,}\n"
            f"  → {r['action']}"
        )
    return "\n\n".join(lines)


def fmt_signals(results, today_str):
    if not results:
        return "No strong signals today. Consider waiting for a better setup."
    tier_emoji = {"Blue Chip": "🔵", "Mid-cap": "🟡", "Small Cap": "🔴"}
    market_note = ""
    if results and results[0].get("market") == "bear":
        market_note = "⚠️ _IHSG is in a downtrend — only the strongest signals shown._\n\n"
    lines = []
    for rank, s in enumerate(results[:5], 1):
        upside  = (s["target"] - s["price"]) / s["price"] * 100
        risk    = (s["price"] - s["stop"])   / s["price"] * 100
        cost    = s["price"] * s["lots"] * 100
        emoji   = tier_emoji.get(s.get("tier", ""), "⚪")
        hammer  = " 🔨" if s.get("hammer") else ""
        lines.append(
            f"*{rank}. {s['ticker']}*{hammer} {emoji} {s.get('tier','')} — Score {s['score']}/10\n"
            f"• Buy: Rp {s['price']:,}\n"
            f"• Target: Rp {s['target']:,} (+3%) — take profit here\n"
            f"• Stop: Rp {s['stop']:,} (-{risk:.1f}%) | Exit after 3 trading days regardless\n"
            f"• Lots: {s['lots']} lots ≈ Rp {cost:,}\n"
            f"• RSI {s['rsi']} | Vol {s['vol_ratio']}x | 1d {s['mom1d']:+.1f}% | 5d {s['mom5d']:+.1f}% | {s.get('trend','')}"
        )
    return market_note + "\n\n".join(lines)


def fmt_summary(pnl_list):
    closed = [t for t in pnl_list if t["status"] in ("closed", "stopped")]
    if not closed:
        return ""
    total = sum(t["pnl"] for t in closed if t["pnl"] is not None)
    sign = "+" if total >= 0 else ""
    return f"\n\n*Total realised P&L:* {sign}Rp {total:,} across {len(closed)} trades"


# ── Scan (runs in thread — takes ~2 min) ─────────────────────────────────────

def _blocking_scan():
    results = run_scan()
    signals_map = {s["ticker"]: s for s in results}
    portfolio   = review_portfolio(TXN_FILE, signals_map)
    return results, portfolio


# ── Handlers ──────────────────────────────────────────────────────────────────

def authorized(update: Update) -> bool:
    return update.effective_user.id == CHAT_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    await update.message.reply_text(
        "👋 IDX Signal Bot ready.\n\n"
        "/signals — run today's scan\n"
        "/portfolio — check open positions\n"
        "/bought TICKER LOTS PRICE — log a buy\n"
        "/sold TICKER PRICE — log a sell\n"
        "/summary — total P&L\n"
        "/help — show this menu"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    await cmd_start(update, context)


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    await update.message.reply_text("Scanning LQ45 + IDX80 + small caps... takes about 60–90 seconds.")
    today_str = date.today().strftime("%d %b %Y")

    results, portfolio = await asyncio.to_thread(_blocking_scan)

    port_text = fmt_portfolio(portfolio)
    sig_text  = fmt_signals(results, today_str)

    await update.message.reply_text(
        f"📋 *Portfolio — {today_str}*\n\n{port_text}",
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        f"📊 *Buy Signals — {today_str}*\n\n{sig_text}",
        parse_mode="Markdown"
    )


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    await update.message.reply_text("Fetching prices...")
    rows = await asyncio.to_thread(review_portfolio, TXN_FILE)
    text = fmt_portfolio(rows)
    await update.message.reply_text(f"📋 *Portfolio*\n\n{text}", parse_mode="Markdown")


async def cmd_bought(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /bought TICKER LOTS PRICE"""
    if not authorized(update):
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Usage: /bought TICKER LOTS PRICE\nExample: /bought HRUM 5 910")
        return

    try:
        ticker    = args[0].upper()
        lots      = int(args[1])
        buy_price = int(args[2])
    except ValueError:
        await update.message.reply_text("LOTS and PRICE must be numbers. Example: /bought HRUM 5 910")
        return

    entry = log_buy(TXN_FILE, ticker, lots, buy_price)
    shares = lots * 100
    total  = buy_price * shares
    fee    = entry["fee_buy"]

    await update.message.reply_text(
        f"✅ *Logged: {entry['id']}*\n\n"
        f"• {ticker} — {lots} lots ({shares:,} shares)\n"
        f"• Buy price: Rp {buy_price:,}\n"
        f"• Total cost: Rp {total:,} + fee Rp {fee:,}\n\n"
        f"Tell me when you sell with:\n/sold {ticker} SELL\\_PRICE",
        parse_mode="Markdown"
    )


async def cmd_sold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /sold TICKER PRICE"""
    if not authorized(update):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /sold TICKER PRICE\nExample: /sold HRUM 970")
        return

    try:
        ticker     = args[0].upper()
        sell_price = int(args[1])
    except ValueError:
        await update.message.reply_text("PRICE must be a number. Example: /sold HRUM 970")
        return

    match = log_sell(TXN_FILE, ticker, sell_price)
    if not match:
        await update.message.reply_text(f"No open position found for {ticker}.")
        return

    pnl  = match["pnl"]
    sign = "+" if pnl >= 0 else ""
    emoji = "🟢" if pnl >= 0 else "🔴"

    await update.message.reply_text(
        f"{emoji} *Closed: {match['id']}*\n\n"
        f"• {ticker} — sold at Rp {sell_price:,}\n"
        f"• Bought at Rp {match['buy_price']:,}\n"
        f"• P&L: *{sign}Rp {pnl:,}*",
        parse_mode="Markdown"
    )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    data = load_transactions(TXN_FILE)
    txns = data["transactions"]

    closed   = [t for t in txns if t["status"] in ("closed", "stopped")]
    open_pos = [t for t in txns if t["status"] == "open"]
    wins     = [t for t in closed if (t["pnl"] or 0) > 0]
    total_pnl = sum((t["pnl"] or 0) for t in closed)
    sign = "+" if total_pnl >= 0 else ""

    await update.message.reply_text(
        f"📈 *Summary*\n\n"
        f"• Open positions: {len(open_pos)}\n"
        f"• Closed trades: {len(closed)}\n"
        f"• Win rate: {len(wins)}/{len(closed)} ({int(len(wins)/len(closed)*100) if closed else 0}%)\n"
        f"• Total P&L: *{sign}Rp {total_pnl:,}*",
        parse_mode="Markdown"
    )


# ── Scheduled morning report ──────────────────────────────────────────────────

async def morning_report(context: ContextTypes.DEFAULT_TYPE):
    today_str = date.today().strftime("%d %b %Y")
    results, portfolio = await asyncio.to_thread(_blocking_scan)

    port_text = fmt_portfolio(portfolio)
    sig_text  = fmt_signals(results, today_str)

    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=f"☀️ *Good morning! IDX Report — {today_str}*\n\n{port_text}",
        parse_mode="Markdown"
    )
    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=f"📊 *Buy Signals — {today_str}*\n\n{sig_text}",
        parse_mode="Markdown"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Init transactions file if missing
    if not os.path.exists(TXN_FILE):
        import json
        with open(TXN_FILE, "w") as f:
            json.dump({"transactions": []}, f)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("signals",   cmd_signals))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("bought",    cmd_bought))
    app.add_handler(CommandHandler("sold",      cmd_sold))
    app.add_handler(CommandHandler("summary",   cmd_summary))

    # Morning report — 08:15 WIB = 01:15 UTC
    app.job_queue.run_daily(
        morning_report,
        time=time(hour=1, minute=15, tzinfo=pytz.utc),
        days=(0, 1, 2, 3, 4),  # Mon–Fri only
    )

    logging.info("Bot started. Polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
