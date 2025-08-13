import asyncio
from datetime import datetime
from tinkoff.invest import Client, CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TINKOFF_TOKEN = "твой_токен_tinkoff"
TELEGRAM_TOKEN = "твой_токен_telegram"
CHAT_ID = "твой_chat_id"

# Хранение сделок
trades = []

def get_candles():
    """Получение последних свечей (пример, можно адаптировать под стратегию)."""
    with Client(TINKOFF_TOKEN) as client:
        candles = client.market_data.get_candles(
            figi="BBG004730N88",  # пример SBER
            from_=datetime.utcnow(),
            to=datetime.utcnow(),
            interval=CandleInterval.CANDLE_INTERVAL_HOUR
        )
    return candles

def check_signal():
    """Проверка сигнала для входа/выхода."""
    candles = get_candles()
    # Простейший пример: если закрытие последней свечи выше открытия → long сигнал
    last = candles.candles[-1]
    if last.c > last.o:
        return "LONG"
    elif last.c < last.o:
        return "SHORT"
    else:
        return None

async def signal_loop(app):
    """Фоновая проверка сигналов каждые 10 минут."""
    while True:
        signal = await asyncio.to_thread(check_signal)
        if signal:
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            trades.append({"time": now, "signal": signal})
            await app.bot.send_message(chat_id=CHAT_ID, text=f"{now}: Сигнал {signal}")
        await asyncio.sleep(600)  # 10 минут

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка истории сделок в чат."""
    if not trades:
        await update.message.reply_text("Сделок пока нет.")
        return
    msg = "\n".join([f"{t['time']} — {t['signal']}" for t in trades])
    await update.message.reply_text(msg)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие."""
    await update.message.reply_text("Бот запущен! Авто-сигналы каждые 10 минут.")

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("history", history_command))

    # Запуск фонового цикла
    app.create_task(signal_loop(app))

    # Запуск бота
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
