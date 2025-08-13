import asyncio
import nest_asyncio
import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Применяем patch для уже существующего event loop
nest_asyncio.apply()

# --- Настройки ---
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

# Хранилище сигналов и истории сделок
current_signal = None  # "LONG" / "SHORT" / None
entry_price = None
trades_history = []  # список словарей: {'type': ..., 'entry': ..., 'exit': ..., 'profit': ...}

# --- Логика сигналов ---
async def check_signal_logic():
    """
    Тут должна быть логика расчёта сигнала по стратегии.
    Для примера — случайный сигнал каждые 10 секунд.
    """
    import random
    await asyncio.sleep(1)  # эмуляция вычислений
    price = 318.0 + random.uniform(-1, 1)  # пример текущей цены
    signal_type = random.choice(["LONG", "SHORT", None])
    return signal_type, price

async def signal_loop(app):
    global current_signal, entry_price, trades_history
    while True:
        signal, price = await check_signal_logic()
        if signal:
            # Если нет открытой сделки
            if current_signal is None:
                current_signal = signal
                entry_price = price
                text = f"📈 {signal} сигнал на вход: {price:.2f}"
                await app.bot.send_message(chat_id="YOUR_CHAT_ID", text=text)
            # Если сигнал на закрытие текущей сделки
            elif current_signal and signal != current_signal:
                exit_price = price
                profit = ((exit_price - entry_price)/entry_price*100 
                          if current_signal=="LONG" else (entry_price - exit_price)/entry_price*100)
                trades_history.append({
                    "type": current_signal,
                    "entry": entry_price,
                    "exit": exit_price,
                    "profit": profit,
                    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                })
                text = f"✅ Закрыта {current_signal} сделка\nВход: {entry_price:.2f}, Выход: {exit_price:.2f}\nПрибыль: {profit:.2f}%"
                await app.bot.send_message(chat_id="YOUR_CHAT_ID", text=text)
                current_signal = None
                entry_price = None
        await asyncio.sleep(10)  # периодичность проверки

# --- Команды Telegram ---
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка текущего сигнала по запросу /signal"""
    if current_signal:
        text = f"Текущий сигнал: {current_signal}\nВход по цене: {entry_price:.2f}"
    else:
        text = "Сигналов на данный момент нет"
    await update.message.reply_text(text)

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка истории сделок и общей прибыли"""
    if not trades_history:
        await update.message.reply_text("История сделок пуста")
        return
    total_profit = sum(trade["profit"] for trade in trades_history)
    lines = [f"{t['date']} | {t['type']} | Вход: {t['entry']:.2f} | Выход: {t['exit']:.2f} | Прибыль: {t['profit']:.2f}%" 
             for t in trades_history]
    text = "\n".join(lines) + f"\n\n💰 Общая прибыль: {total_profit:.2f}%"
    await update.message.reply_text(text)

# --- Main ---
async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("history", history_command))

    # Запуск loop сигналов
    asyncio.create_task(signal_loop(app))

    # Запуск бота
    await app.run_polling()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
