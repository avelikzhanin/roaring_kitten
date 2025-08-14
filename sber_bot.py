import os
import talib
import pandas as pd
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# === Конфигурация ===
TINKOFF_TOKEN = "ТВОЙ_TINKOFF_API_TOKEN"
TELEGRAM_TOKEN = "ТВОЙ_TELEGRAM_BOT_TOKEN"
CHAT_ID = 215592311  # твой chat_id
FIGI = "BBG004730N88"  # SBER
LOT_SIZE = 1

# === Функция получения исторических данных ===
def get_candles():
    now = datetime.utcnow()
    from_time = now - timedelta(days=30)
    with Client(TINKOFF_TOKEN) as client:
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=from_time,
            to=now,
            interval=CandleInterval.CANDLE_INTERVAL_HOUR
        ).candles

    df = pd.DataFrame([{
        "time": c.time,
        "open": float(c.open.units + c.open.nano / 1e9),
        "high": float(c.high.units + c.high.nano / 1e9),
        "low": float(c.low.units + c.low.nano / 1e9),
        "close": float(c.close.units + c.close.nano / 1e9),
        "volume": c.volume
    } for c in candles])

    return df

# === Анализ стратегии ===
def analyze_strategy():
    df = get_candles()

    # Индикаторы
    adx = talib.ADX(df["high"], df["low"], df["close"], timeperiod=14).iloc[-1]
    plus_di = talib.PLUS_DI(df["high"], df["low"], df["close"], timeperiod=14).iloc[-1]
    minus_di = talib.MINUS_DI(df["high"], df["low"], df["close"], timeperiod=14).iloc[-1]
    ema100 = talib.EMA(df["close"], timeperiod=100).iloc[-1]
    current_price = df["close"].iloc[-1]
    avg_volume = df["volume"].rolling(window=20).mean().iloc[-1]
    current_volume = df["volume"].iloc[-1]

    # BUY условия
    buy_conditions = {
        "ADX": adx > 23,
        "+DI": plus_di > minus_di,
        "Объём": current_volume > avg_volume,
        "EMA100": current_price > ema100
    }

    # SELL условия
    sell_conditions = {
        "ADX": adx > 23,
        "+DI": plus_di < minus_di,
        "Объём": current_volume > avg_volume,
        "EMA100": current_price < ema100
    }

    # Определение сигнала
    if all(buy_conditions.values()):
        signal = "BUY"
    elif all(sell_conditions.values()):
        signal = "SELL"
    else:
        signal = "-"

    return {
        "signal": signal,
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "ema100": ema100,
        "current_price": current_price,
        "avg_volume": avg_volume,
        "current_volume": current_volume,
        "buy_conditions": buy_conditions,
        "sell_conditions": sell_conditions
    }

# === Формирование сообщения ===
def format_signal(data):
    def emoji(cond): return "✅" if cond else "❌"

    if data["signal"] == "BUY":
        plus_di_status = emoji(data["buy_conditions"]["+DI"])
        minus_di_status = emoji(data["plus_di"] > data["minus_di"] is False)
    elif data["signal"] == "SELL":
        plus_di_status = emoji(data["sell_conditions"]["+DI"])
        minus_di_status = emoji(data["minus_di"] > data["plus_di"])
    else:
        plus_di_status = "❌"
        minus_di_status = "❌"

    text = f"""
Параметры стратегии:
ADX: {data["adx"]:.2f} {emoji(data["adx"] > 23)} (цель > 23)
+DI: {data["plus_di"]:.2f} {plus_di_status}
-DI: {data["minus_di"]:.2f} {minus_di_status}
Объём: {data["current_volume"]} {emoji(data["current_volume"] > data["avg_volume"])} (среднее: {int(data["avg_volume"])})
EMA100: {data["ema100"]:.2f} {emoji(data["current_price"] > data["ema100"])}

📢 Сигнал стратегии: {data["signal"]}

Текущая цена: {data["current_price"]:.2f}
Цена входа: -
Трейлинг-стоп: -
Текущая прибыль: -
"""
    return text

# === Обработчики команд ===
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = analyze_strategy()
    msg = format_signal(data)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

# === Запуск бота ===
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("signal", signal_command))

if __name__ == "__main__":
    app.run_polling()
