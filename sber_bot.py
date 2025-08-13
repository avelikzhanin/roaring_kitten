import os
import logging
import asyncio
import pandas as pd
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TINKOFF_TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"  # SBER
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR
HISTORY_HOURS = 200

chat_ids = set()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_ids.add(chat_id)
    await context.bot.send_message(chat_id=chat_id, text="✅ Chat ID сохранён! Теперь буду присылать сигналы.")

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
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = abs(100 * (minus_dm.rolling(window=period).mean() / atr))
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx_val = dx.rolling(window=period).mean()
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
    df = get_candles()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])
    vol_ma = df["volume"].rolling(window=20).mean()
    last = df.iloc[-1]
    if last["ADX"] > 23 and last["+DI"] > last["-DI"] and last["volume"] > vol_ma.iloc[-1] and last["close"] > df["ema100"].iloc[-1]:
        return f"📈 BUY сигнал — ADX={last['ADX']:.2f}, цена={last['close']:.2f}"
    elif last["ADX"] < 20 or last["close"] < df["ema100"].iloc[-1]:
        return f"📉 SELL сигнал — ADX={last['ADX']:.2f}, цена={last['close']:.2f}"
    else:
        return "⚪ Сигнал отсутствует"

async def send_telegram_message(bot, text):
    if not chat_ids:
        logging.warning("❌ Chat ID не найден — напиши /start боту")
        return
    for chat_id in chat_ids:
        await bot.send_message(chat_id=chat_id, text=text)

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signal = check_signal()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=signal)

async def main_loop(bot):
    while True:
        try:
            signal = check_signal()
            if signal != "⚪ Сигнал отсутствует":
                logging.info(f"Отправка сигнала: {signal}")
                await send_telegram_message(bot, signal)
        except Exception as e:
            logging.error(f"Ошибка в main_loop: {e}")
        await asyncio.sleep(300)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))

    # Устанавливаем команды Telegram
    async def set_commands(app):
        from telegram import BotCommand
        commands = [
            BotCommand("start", "Запустить бота и сохранить Chat ID"),
            BotCommand("signal", "Получить текущий сигнал")
        ]
        await app.bot.set_my_commands(commands)

    # Запуск авто-сигналов перед polling
    async def start_loop(app):
        asyncio.create_task(main_loop(app.bot))
        await set_commands(app)

    app.post_init = start_loop  # запускаем после инициализации
    app.run_polling()  # правильный способ запускать бот
