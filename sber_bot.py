import os
import asyncio
import pandas as pd
import numpy as np
import yfinance as yf
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === Настройки ===
TOKEN = os.getenv("TELEGRAM_TOKEN")  # токен Telegram-бота
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "215592311"))  # твой chat_id
SYMBOL = "SBER.ME"
INTERVAL = "1h"

# Флаг позиции
in_position = False

# === Расчёт индикаторов ===
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_adx(df, period=14):
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    plus_dm = high.diff()
    minus_dm = low.diff()

    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), -minus_dm, 0.0)

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.DataFrame({"tr1": tr1, "tr2": tr2, "tr3": tr3}).max(axis=1)

    atr = tr.rolling(period).mean()

    plus_di = 100 * (pd.Series(plus_dm).rolling(period).mean() / atr)
    minus_di = 100 * (pd.Series(abs(minus_dm)).rolling(period).mean() / atr)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(period).mean()

    df["+DI"] = plus_di
    df["-DI"] = minus_di
    df["ADX"] = adx
    return df

# === Получение данных ===
async def fetch_data():
    df = yf.download(SYMBOL, period="5d", interval=INTERVAL)
    df.dropna(inplace=True)
    df["EMA100"] = ema(df["Close"], 100)
    df = calculate_adx(df)
    df["Volume_Mean"] = df["Volume"].rolling(window=20).mean()
    df.dropna(inplace=True)
    return df

# === Логика сигналов ===
def check_entry(df):
    last = df.iloc[-1]
    return (
        last["ADX"] > 23 and
        last["+DI"] > last["-DI"] and
        last["Close"] > last["EMA100"] and
        last["Volume"] > last["Volume_Mean"]
    )

def check_exit(df):
    last = df.iloc[-1]
    return (
        last["+DI"] < last["-DI"] or
        last["Close"] < last["EMA100"]
    )

# === Цикл проверки сигналов ===
async def signal_loop(app):
    global in_position
    while True:
        df = await asyncio.to_thread(fetch_data)
        if not in_position and check_entry(df):
            await app.bot.send_message(CHAT_ID, "📈 Сигнал на ВХОД в сделку по Сберу!")
            in_position = True
        elif in_position and check_exit(df):
            await app.bot.send_message(CHAT_ID, "📉 Сигнал на ВЫХОД из сделки по Сберу!")
            in_position = False
        await asyncio.sleep(60 * 5)  # каждые 5 минут

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен. Автоматические сигналы включены.")

# === Запуск ===
if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.post_init(lambda _: asyncio.create_task(signal_loop(app)))
    app.run_polling()
