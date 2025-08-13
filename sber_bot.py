import os
import logging
import time
import pandas as pd
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import requests

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Переменные окружения ---
TINKOFF_TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"  # SBER
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR
HISTORY_HOURS = 200

CHAT_ID_FILE = "chat_id.txt"

# --- Сохранение chat_id ---
def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
    logging.info(f"Chat ID сохранён: {chat_id}")

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    return None

# --- /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(chat_id=chat_id, text="✅ Chat ID сохранён! Теперь буду присылать сигналы.")

# --- EMA ---
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

# --- ADX ---
def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()

    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = abs(100 * (minus_dm.rolling(window=period).mean() / atr))

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx_val = dx.rolling(window=period).mean()
    return adx_val, plus_di, minus_di

# --- Получение свечей ---
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

# --- Проверка сигнала ---
def get_signal(df):
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])
    vol_ma = df["volume"].rolling(window=20).mean()
    last = df.iloc[-1]

    if last["ADX"] > 23 and last["+DI"] > last["-DI"] and last["volume"] > vol_ma.iloc[-1] and last["close"] > df["ema100"].iloc[-1]:
        return "BUY", last["close"]
    elif last["ADX"] < 20 or last["close"] < df["ema100"].iloc[-1]:
        return "SELL", last["close"]
    else:
        return None, last["close"]

# --- Отправка в Telegram ---
def send_telegram_message(text):
    chat_id = load_chat_id()
    if not chat_id:
        logging.warning("❌ Chat ID не найден — напиши /start боту")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

# --- Команда /signal ---
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_candles()
    sig, price = get_signal(df)
    if sig is None:
        sig_text = "⚪ Сигнал отсутствует"
    elif sig == "BUY":
        sig_text = f"📈 BUY сигнал — цена={price:.2f}"
    else:
        sig_text = f"📉 SELL сигнал — цена={price:.2f}"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=sig_text)

# --- Основной цикл с отслеживанием позиции ---
def main_loop():
    position = None
    entry_price = None

    while True:
        df = get_candles()
        sig, price = get_signal(df)

        if sig == "BUY" and position is None:
            position = "long"
            entry_price = price
            send_telegram_message(f"📈 Открываем сделку: BUY по цене {price:.2f}")
        elif sig == "SELL" and position == "long":
            exit_price = price
            profit_percent = (exit_price - entry_price) / entry_price * 100
            send_telegram_message(f"📉 Закрываем сделку: SELL по цене {exit_price:.2f}\n💰 Результат: {profit_percent:.2f}%")
            position = None
            entry_price = None

        time.sleep(300)  # каждые 5 минут

# --- Запуск ---
if __name__ == "__main__":
    from threading import Thread

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))

    Thread(target=main_loop, daemon=True).start()
    app.run_polling()
