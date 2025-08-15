import asyncio
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from tinkoff.invest import Client

# ===== Настройка логирования =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ===== Конфигурация =====
TELEGRAM_TOKEN = "ВАШ_TELEGRAM_BOT_TOKEN"
TINKOFF_TOKEN = "ВАШ_TINKOFF_INVEST_API_TOKEN"
FIGI = "BBG004730N88"  # SBER
EMA_PERIOD = 100

# Список пользователей, которые нажали /start
CHAT_IDS = set()

# ===== Телеграм хэндлер /start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_IDS.add(chat_id)
    await context.bot.send_message(chat_id=chat_id, text="Бот активирован. Сигналы будут приходить автоматически.")

# ===== Получение данных с Tinkoff =====
def get_candles():
    with Client(TINKOFF_TOKEN) as client:
        now = datetime.utcnow()
        from_ = now.replace(hour=0, minute=0, second=0, microsecond=0)
        candles = client.market.candles_get(
            figi=FIGI,
            from_=from_,
            to=now,
            interval="1min"
        ).candles
        return candles

# ===== Рассчёт EMA =====
def calculate_ema(prices, period=EMA_PERIOD):
    if len(prices) < period:
        return None
    ema = sum(prices[:period]) / period
    k = 2 / (period + 1)
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema

# ===== Отправка сигнала всем пользователям =====
async def send_signal_to_all(price, app):
    for chat_id in CHAT_IDS:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"📈 Сигнал на покупку!\nЦена покупки: {price}"
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке сигнала {chat_id}: {e}")

# ===== Авто-проверка стратегии =====
async def auto_check(app):
    while True:
        try:
            candles = get_candles()
            if not candles:
                await asyncio.sleep(60)
                continue

            close_prices = [c.close.price for c in candles]
            ema = calculate_ema(close_prices)

            current_price = close_prices[-1]

            # Простая стратегия: цена выше EMA + объём свечи больше среднего
            volumes = [c.volume for c in candles]
            avg_volume = sum(volumes) / len(volumes)

            if current_price > ema and candles[-1].volume > avg_volume:
                await send_signal_to_all(current_price, app)

        except Exception as e:
            logging.error(f"Ошибка в auto_check: {e}")

        await asyncio.sleep(60)  # проверка каждую минуту

# ===== Основная функция =====
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Запускаем авто-проверку стратегии
    app.create_task(auto_check(app))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
