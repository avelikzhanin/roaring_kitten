import os
import logging
import time
import json
from tinkoff.invest import Client
from tinkoff.invest.services import InstrumentsService
from tinkoff.invest.schemas import CandleInterval
import pandas as pd
import numpy as np
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Переменные окружения ---
TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"  # SBER
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR
HISTORY_HOURS = 200

CHAT_ID_FILE = "chat_id.txt"

def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
    logging.info(f"Chat ID saved: {chat_id}")

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    return None

# --- Telegram /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(chat_id=chat_id, text="✅ Chat ID сохранён! Теперь буду присылать сигналы.")

# --- Индикаторы ---
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()

    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0

    tr1 = pd.DataFrame(high - low)
    tr2 = pd.DataFrame(abs(high - close.shift()))
    tr3 = pd.DataFrame(abs(low - close.shift()))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()

    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = abs(100 * (minus_dm.rolling(window=period).mean() / atr))

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(window=period).mean()

    return adx, plus_di, minus_di

# --- Получение данных ---
def get_candles():
    with Client(TOKEN) as client:
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

# --- Логика сигналов ---
def check_signal():
    df = get_candles()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])

    vol_ma = df["volume"].rolling(window=20).mean()
    last = df.iloc[-1]

    if (
        last["ADX"] > 23 and
        last["+DI"] > last["-DI"] and
        last["volume"] > vol_ma.iloc[-1] and
        last["close"] > last["ema100"]
    ):
        return f"📈 BUY сигнал — ADX={last['ADX']:.2f}, цена={last['close']:.2f}"
    elif last["ADX"] < 20 or last["close"] < last["ema100"]:
        return f"📉 SELL сигнал — ADX={last['ADX']:.2f}, цена={last['close']:.2f}"
    else:
        return None

# --- Отправка в Telegram ---
def send_telegram_message(text):
    chat_id = load_chat_id()
    if not chat_id:
        logging.warning("❌ Chat ID не найден — напиши /start боту")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

# --- Основной цикл ---
def main_loop():
    while True:
        signal = check_signal()
        if signal:
            send_telegram_message(signal)
        time.sleep(300)  # каждые 5 минут

if __name__ == "__main__":
    from threading import Thread
    from telegram.ext import Application

    # Telegram-бот
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # Запуск цикла сигналов в отдельном потоке
    Thread(target=main_loop, daemon=True).start()

    # Запуск Telegram-поллинга
    app.run_polling()
