import os
import asyncio
import pandas as pd
import numpy as np
from tinkoff.invest import Client, CandleInterval
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==== Настройки ====
TOKEN_TINKOFF = os.getenv("TINKOFF_TOKEN")
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "215592311"))
FIGI_SBER = "BBG004730N88"  # FIGI Сбера
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR

# ==== Позиция ====
in_position = False  # Флаг открытой позиции

# ==== Индикаторы ====
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def adx(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = low.diff()

    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), -minus_dm, 0.0)

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()

    plus_di = 100 * (pd.Series(plus_dm).rolling(period).mean() / atr)
    minus_di = 100 * (pd.Series(abs(minus_dm)).rolling(period).mean() / atr)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx_val = dx.rolling(period).mean()

    df["+DI"] = plus_di
    df["-DI"] = minus_di
    df["ADX"] = adx_val
    return df

# ==== Получение данных ====
def get_candles(hours_back=200):
    now = pd.Timestamp.now(tz="Europe/Moscow")
    with Client(TOKEN_TINKOFF) as client:
        candles = client.market_data.get_candles(
            figi=FIGI_SBER,
            from_=now - pd.Timedelta(hours=hours_back),
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

# ==== Логика сигналов ====
def check_signal():
    df = get_candles()
    df["EMA100"] = ema(df["close"], 100)
    df = adx(df)
    df["Volume_MA"] = df["volume"].rolling(20).mean()
    df.dropna(inplace=True)
    last = df.iloc[-1]

    entry = (
        last["ADX"] > 23 and
        last["+DI"] > last["-DI"] and
        last["close"] > last["EMA100"] and
        last["volume"] > last["Volume_MA"]
    )

    exit_ = (
        last["+DI"] < last["-DI"] or
        last["close"] < last["EMA100"]
    )

    return entry, exit_

# ==== Функция для команды /signal ====
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global in_position
    entry, exit_ = await asyncio.to_thread(check_signal)
    if not in_position and entry:
        await update.message.reply_text("📈 Сейчас есть сигнал на ВХОД в сделку!")
    elif in_position and exit_:
        await update.message.reply_text("📉 Сейчас есть сигнал на ВЫХОД из сделки!")
    else:
        await update.message.reply_text("⚪ Сейчас сигналов нет.")

# ==== Цикл авто-сигналов ====
async def signal_loop(app):
    global in_position
    while True:
        entry, exit_ = await asyncio.to_thread(check_signal)
        if not in_position and entry:
            await app.bot.send_message(CHAT_ID, "📈 Сигнал на ВХОД в сделку по Сберу!")
            in_position = True
        elif in_position and exit_:
            await app.bot.send_message(CHAT_ID, "📉 Сигнал на ВЫХОД из сделки по Сберу!")
            in_position = False
        await asyncio.sleep(300)  # каждые 5 минут

# ==== Telegram команды ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен. Автоматические сигналы включены.")

# ==== Запуск ====
def main():
    app = Application.builder().token(TOKEN_TELEGRAM).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))

    # === Запуск цикла сигналов после инициализации приложения ===
    loop = asyncio.get_event_loop()
    loop.create_task(signal_loop(app))

    app.run_polling()

if __name__ == "__main__":
    main()
