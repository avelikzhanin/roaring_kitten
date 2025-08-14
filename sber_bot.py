import os
import logging
import time
import requests
import pandas as pd
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from threading import Thread

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Переменные окружения ---
TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"  # SBER
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR
HISTORY_HOURS = 200
TRAIL_PCT = 0.015
CHAT_ID_FILE = "chat_id.txt"

# --- Позиция ---
position_type = None
entry_price = None
best_price = None
trailing_stop = None

# --- Telegram ---
def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(chat_id=chat_id, text="😺 Ревущий котёнок на связи! Буду присылать сигналы по SBER")

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = generate_signal_message()
    await context.bot.send_message(chat_id=chat_id, text=text)

# --- Индикаторы ---
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = abs(100 * (minus_dm.rolling(period).mean() / atr))
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx_val = dx.rolling(period).mean()
    return adx_val, plus_di, minus_di

# --- Получение свечей ---
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

# --- Проверка сигнала ---
def check_signal():
    df = get_candles()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])
    vol_ma = df["volume"].rolling(20).mean()
    last = df.iloc[-1]
    if last["ADX"] > 23 and last["+DI"] > last["-DI"] and last["volume"] > vol_ma.iloc[-1] and last["close"] > last["ema100"]:
        return "BUY"
    elif last["ADX"] < 20 or last["close"] < last["ema100"]:
        return "SELL"
    return None

# --- Трейлинг-стоп ---
def update_trailing(curr_price):
    global trailing_stop, best_price
    if position_type == "long":
        best_price = max(best_price, curr_price)
        trailing_stop = best_price * (1 - TRAIL_PCT)
    elif position_type == "short":
        best_price = min(best_price, curr_price)
        trailing_stop = best_price * (1 + TRAIL_PCT)

# --- Генерация сообщения с параметрами стратегии и позицией ---
def generate_signal_message():
    global position_type, entry_price, trailing_stop, best_price
    df = get_candles()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])
    vol_ma = df["volume"].rolling(20).mean()
    last = df.iloc[-1]

    last_price = last["close"]

    # Эмодзи по условиям
    adx_ok = "✅" if last["ADX"] > 23 else "❌"
    plus_di_ok = "✅" if last["+DI"] > last["-DI"] else "❌"
    vol_ok = "✅" if last["volume"] > vol_ma.iloc[-1] else "❌"
    ema_ok = "✅" if last_price > last["ema100"] else "❌"

    text = (
        f"📊 Параметры стратегии:\n"
        f"ADX: {last['ADX']:.2f} {adx_ok} (цель > 23)\n"
        f"+DI: {last['+DI']:.2f} {plus_di_ok} (цель > -DI)\n"
        f"-DI: {last['-DI']:.2f}\n"
        f"Объём: {last['volume']:.0f} {vol_ok} (среднее за 20 свечей {vol_ma.iloc[-1]:.0f})\n"
        f"EMA100: {last['ema100']:.2f} {ema_ok} (цель < текущая цена {last_price:.2f})\n"
    )

    signal = check_signal()
    if signal:
        text += f"\n✅ Сигнал стратегии: {signal}"
    else:
        text += "\n❌ Сейчас нет сигнала для открытия позиции."

    # Информация по позиции
    if position_type:
        pnl = (last_price - entry_price)/entry_price*100 if position_type=="long" else (entry_price - last_price)/entry_price*100
        ts_text = f"{trailing_stop:.2f}" if trailing_stop else "-"
        text += (
            f"\n\nТекущая цена: {last_price:.2f}"
            f"\nЦена входа: {entry_price if entry_price else '-'}"
            f"\nТрейлинг-стоп: {ts_text}"
            f"\nТекущая прибыль: {pnl:.2f}%"
        )
    else:
        text += (
            f"\n\nТекущая цена: {last_price:.2f}"
            f"\nЦена входа: -"
            f"\nТрейлинг-стоп: -"
            f"\nТекущая прибыль: -"
        )

    return text


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
        msg = generate_signal_message()
        if msg:
            send_telegram_message(msg)
        time.sleep(300)  # каждые 5 минут

# --- Запуск бота ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))

    Thread(target=main_loop, daemon=True).start()
    app.run_polling()
