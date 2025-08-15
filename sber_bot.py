import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta
import pandas as pd
from ta.trend import ADXIndicator, EMAIndicator
from tinkoff.invest import AsyncClient, CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TINKOFF_TOKEN = os.environ["TINKOFF_TOKEN"]

USERS = set()
FIGI = "BBG004730N88"  # Сбербанк
INTERVAL = CandleInterval.CANDLE_INTERVAL_1_MIN
ADX_PERIOD = 14
EMA_PERIOD = 100
VOLUME_PERIOD = 20

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USERS.add(update.effective_chat.id)
    await update.message.reply_text("Вы подписались на сигналы стратегии!")

# Проверка стратегии
def check_strategy(candles):
    df = pd.DataFrame([{
        "time": c.time,
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume
    } for c in candles])

    if len(df) < max(EMA_PERIOD, ADX_PERIOD, VOLUME_PERIOD):
        return None

    df["ema"] = EMAIndicator(close=df["close"], window=EMA_PERIOD).ema_indicator()
    adx = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=ADX_PERIOD)
    df["adx"] = adx.adx()
    df["+di"] = adx.adx_pos()
    df["-di"] = adx.adx_neg()
    df["vol_ma"] = df["volume"].rolling(VOLUME_PERIOD).mean()

    last = df.iloc[-1]
    if last["adx"] > 23 and last["+di"] > last["-di"] and last["volume"] > last["vol_ma"] and last["close"] > last["ema"]:
        return last["close"]
    return None

# Отправка сигнала всем пользователям
async def send_signal(app, price):
    for chat_id in USERS:
        try:
            await app.bot.send_message(chat_id, f"Сигнал на покупку!\nЦена покупки: {price:.2f}")
        except Exception as e:
            logger.error(f"Ошибка при отправке сигналу пользователю {chat_id}: {e}")

# Автоматическая проверка стратегии каждые 1 минуту
async def auto_check(app):
    async with AsyncClient(TINKOFF_TOKEN) as client:
        while True:
            try:
                now = datetime.now(timezone.utc)
                from_time = now - timedelta(minutes=30)
                candles_resp = await client.market_data.get_candles(
                    figi=FIGI,
                    from_=from_time,
                    to=now,
                    interval=INTERVAL
                )
                price = check_strategy(candles_resp.candles)
                if price:
                    await send_signal(app, price)
            except Exception as e:
                logger.error(f"Ошибка в auto_check: {e}")
            await asyncio.sleep(60)  # проверка каждую минуту

# Создание приложения
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    # Запуск фона auto_check
    app.create_task(auto_check(app))
    app.run_polling()  # блокирующий вызов, идеально для Railway

if __name__ == "__main__":
    main()
