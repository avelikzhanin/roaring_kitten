import os
import asyncio
import logging
from datetime import datetime, timezone
import pandas as pd
from ta.trend import ADXIndicator
from ta.trend import EMAIndicator
from tinkoff.invest import Client, CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получаем токены из переменных окружения
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TINKOFF_TOKEN = os.environ["TINKOFF_TOKEN"]

# Список chat_id пользователей
USERS = set()

# Таймфрейм и инструмент
FIGI = "BBG004730N88"  # Пример: Сбербанк
INTERVAL = CandleInterval.CANDLE_INTERVAL_1_MIN

# Период для индикаторов
ADX_PERIOD = 14
EMA_PERIOD = 100
VOLUME_PERIOD = 20

# ================= Команды =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USERS.add(update.effective_chat.id)
    await update.message.reply_text("Вы подписались на сигналы стратегии!")

# ================= Проверка стратегии =================
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

    # EMA100
    df["ema"] = EMAIndicator(close=df["close"], window=EMA_PERIOD).ema_indicator()

    # ADX + DI
    adx = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=ADX_PERIOD)
    df["adx"] = adx.adx()
    df["+di"] = adx.adx_pos()
    df["-di"] = adx.adx_neg()

    # Средний объем
    df["vol_ma"] = df["volume"].rolling(VOLUME_PERIOD).mean()

    last = df.iloc[-1]
    if last["adx"] > 23 and last["+di"] > last["-di"] and last["volume"] > last["vol_ma"] and last["close"] > last["ema"]:
        return last["close"]
    return None

# ================= Отправка сигналов =================
async def send_signal(app, price):
    for chat_id in USERS:
        try:
            await app.bot.send_message(chat_id, f"Сигнал на покупку!\nЦена покупки: {price:.2f}")
        except Exception as e:
            logger.error(f"Ошибка при отправке сигналу пользователю {chat_id}: {e}")

# ================= Автопроверка =================
async def auto_check(app):
    client = Client(TINKOFF_TOKEN)
    while True:
        try:
            candles = client.market.get_candles(figi=FIGI, interval=INTERVAL, from_=datetime.now(timezone.utc))
            price = check_strategy(candles.candles)
            if price:
                await send_signal(app, price)
        except Exception as e:
            logger.error(f"Ошибка в auto_check: {e}")
        await asyncio.sleep(60)  # проверка каждую минуту

# ================= Основная функция =================
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # Запускаем проверку стратегии
    app.create_task(auto_check(app))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
