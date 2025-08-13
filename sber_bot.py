import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from tinkoff.invest import Client
import os

# --- Конфигурация ---
TINKOFF_TOKEN = os.environ.get("TINKOFF_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")  # Ваш chat_id
SYMBOL = "SBER"  # тикер
TIMEFRAME = "H1"  # часовой график

# --- Хранилище сигналов и истории ---
current_position = None  # None, "long" или "short"
trade_history = []

# --- Функции анализа сигналов ---
def get_signal():  
    """
    Пример функции, возвращающей сигнал на основе анализа свечей.
    Возвращает: "long", "short", "exit" или None
    """
    # Здесь подключаем Tinkoff API и расчет индикаторов
    # Заглушка для примера:
    import random
    return random.choice(["long", "short", "exit", None])

async def check_signals(app):
    global current_position
    signal = get_signal()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    
    if signal in ["long", "short"] and current_position is None:
        current_position = signal
        trade_history.append({"type": signal, "entry_time": now})
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=f"📈 Вход в {signal.upper()} сделку: {now}"
        )
    elif signal == "exit" and current_position:
        last_trade = trade_history[-1]
        last_trade["exit_time"] = now
        # Пример: считаем условную прибыль в процентах
        last_trade["profit_percent"] = round((1.5 if current_position=="long" else 1.2),2)
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=f"📉 Выход из {current_position.upper()} сделки: {now}\nПрибыль: {last_trade['profit_percent']}%"
        )
        current_position = None

# --- Команда /signal для проверки текущих сигналов ---
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signal = get_signal()
    text = f"Текущий сигнал: {signal}" if signal else "Сигналов нет"
    await update.message.reply_text(text)

# --- Команда /history для просмотра сделок ---
async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trade_history:
        await update.message.reply_text("История сделок пуста.")
        return
    text = "📊 История сделок:\n"
    for t in trade_history:
        text += f"{t['type'].upper()} | Вход: {t['entry_time']} | "
        text += f"Выход: {t.get('exit_time', '-')}"
        if "profit_percent" in t:
            text += f" | Прибыль: {t['profit_percent']}%"
        text += "\n"
    await update.message.reply_text(text)

# --- Фоновый цикл проверки сигналов ---
async def signal_loop(app):
    while True:
        try:
            await check_signals(app)
        except Exception as e:
            await app.bot.send_message(chat_id=CHAT_ID, text=f"Ошибка в сигнале: {e}")
        await asyncio.sleep(600)  # каждые 10 минут

# --- Основная функция ---
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("history", history_command))
    
    # Запуск фонового цикла
    app.create_task(signal_loop(app))
    
    # Запуск бота
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
