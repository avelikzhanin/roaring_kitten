import os
import logging
import asyncio
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
import pandas as pd
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TINKOFF_TOKEN = os.getenv("TINKOFF_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FIGI = "BBG004730N88"  # SBER
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR
HISTORY_HOURS = 200

position = None  # None = нет сделки, "long" = купили
entry_price = None
entry_time = None
trades = []

CHAT_ID_FILE = "chat_id.txt"

def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
    logging.info(f"Chat ID saved: {chat_id}")

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return int(f.read().strip())
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(chat_id=chat_id, text="✅ Chat ID сохранён!")

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean().abs() / atr)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    adx_val = dx.rolling(period).mean()
    return adx_val, plus_di, minus_di

def get_candles():
    with Client(TINKOFF_TOKEN) as client:
        now = pd.Timestamp.now(tz="Europe/Moscow")
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=now - pd.Timedelta(hours=HISTORY_HOURS),
            to=now,
            interval=INTERVAL
        ).candles

        df = pd.DataFrame([{
            "time": c.time,
            "open": c.open.units + c.open.nano / 1e9,
            "high": c.high.units + c.high.nano / 1e9,
            "low": c.low.units + c.low.nano / 1e9,
            "close": c.close.units + c.close.nano / 1e9,
            "volume": c.volume
        } for c in candles])
    return df

def check_signal():
    global position, entry_price, entry_time, trades
    df = get_candles()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])
    vol_ma = df["volume"].rolling(20).mean()
    last = df.iloc[-1]

    if position is None:  # Ждем вход
        if last["ADX"] > 23 and last["+DI"] > last["-DI"] and last["close"] > last["ema100"] and last["volume"] > vol_ma.iloc[-1]:
            position = "long"
            entry_price = last["close"]
            entry_time = last["time"]
            return f"📈 BUY сигнал — вход в сделку, цена={entry_price:.2f}"
    elif position == "long":  # Ждем выход
        if last["ADX"] < 20 or last["close"] < last["ema100"]:
            exit_price = last["close"]
            exit_time = last["time"]
            profit_percent = (exit_price - entry_price) / entry_price * 100
            trades.append({
                "entry_price": entry_price,
                "exit_price": exit_price,
                "profit_percent": profit_percent,
                "entry_time": entry_time,
                "exit_time": exit_time
            })
            position = None
            entry_price = None
            entry_time = None
            return f"📉 SELL сигнал — выход из сделки, цена={exit_price:.2f}, прибыль={profit_percent:.2f}%"
    return None

def send_telegram_message(text):
    chat_id = load_chat_id()
    if not chat_id:
        logging.warning("❌ Chat ID не найден — напиши /start боту")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signal = await asyncio.to_thread(check_signal)
    if signal:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=signal)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Сигналов нет.")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trades:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Сделок пока нет.")
        return
    text = "📊 История сделок:\n"
    total_profit = 0
    for i, t in enumerate(trades, 1):
        text += (f"{i}) Вход: {t['entry_price']:.2f} ({t['entry_time']}) → "
                 f"Выход: {t['exit_price']:.2f} ({t['exit_time']}), "
                 f"Прибыль: {t['profit_percent']:.2f}%\n")
        total_profit += t['profit_percent']
    text += f"\n💰 Общая прибыль: {total_profit:.2f}%"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

async def signal_loop(app):
    while True:
        signal = await asyncio.to_thread(check_signal)
        if signal:
            send_telegram_message(signal)
        await asyncio.sleep(300)  # каждые 5 минут

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("history", history_command))
    app.create_task(signal_loop(app))
    app.run_polling()

if __name__ == "__main__":
    main()
