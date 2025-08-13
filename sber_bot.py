import os
import asyncio
import nest_asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Разрешаем повторное использование event loop на Railway
nest_asyncio.apply()

# Токены и chat_id из переменных окружения Railway
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = int(os.environ.get("CHAT_ID"))

# История сделок
trade_history = []

# Текущие открытые позиции
current_positions = {"long": None, "short": None}

CHECK_INTERVAL = 10 * 60  # каждые 10 минут

async def check_signals():
    """
    Заглушка функции проверки сигналов.
    Здесь нужно подключить твою логику анализа свечей
    и возвращать сигналы вида: {"long": True/False, "short": True/False, "exit_long": True/False, "exit_short": True/False}
    """
    # TODO: заменить на реальный анализ
    return {
        "long": False,
        "short": False,
        "exit_long": False,
        "exit_short": False
    }

async def signal_loop(app):
    while True:
        try:
            signals = await check_signals()
            
            # Обрабатываем long
            if signals["long"] and current_positions["long"] is None:
                current_positions["long"] = {"entry_time": datetime.utcnow(), "entry_price": 100}  # пример цены
                await app.bot.send_message(chat_id=CHAT_ID, text="🚀 Long сигнал! Входим в сделку.")
            
            if signals["exit_long"] and current_positions["long"] is not None:
                entry = current_positions["long"]
                exit_price = 105  # пример
                profit_pct = (exit_price - entry["entry_price"]) / entry["entry_price"] * 100
                trade_history.append({
                    "type": "long",
                    "entry_price": entry["entry_price"],
                    "exit_price": exit_price,
                    "profit_pct": profit_pct,
                    "entry_time": entry["entry_time"],
                    "exit_time": datetime.utcnow()
                })
                current_positions["long"] = None
                await app.bot.send_message(chat_id=CHAT_ID, text=f"✅ Выход из Long! Прибыль: {profit_pct:.2f}%")

            # Обрабатываем short
            if signals["short"] and current_positions["short"] is None:
                current_positions["short"] = {"entry_time": datetime.utcnow(), "entry_price": 100}
                await app.bot.send_message(chat_id=CHAT_ID, text="📉 Short сигнал! Входим в сделку.")
            
            if signals["exit_short"] and current_positions["short"] is not None:
                entry = current_positions["short"]
                exit_price = 95
                profit_pct = (entry["entry_price"] - exit_price) / entry["entry_price"] * 100
                trade_history.append({
                    "type": "short",
                    "entry_price": entry["entry_price"],
                    "exit_price": exit_price,
                    "profit_pct": profit_pct,
                    "entry_time": entry["entry_time"],
                    "exit_time": datetime.utcnow()
                })
                current_positions["short"] = None
                await app.bot.send_message(chat_id=CHAT_ID, text=f"✅ Выход из Short! Прибыль: {profit_pct:.2f}%")
                
        except Exception as e:
            await app.bot.send_message(chat_id=CHAT_ID, text=f"Ошибка в signal_loop: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# Команда /signal для ручной проверки
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📊 История сделок:\n"
    total_profit = 0
    for t in trade_history[-10:]:  # показываем последние 10 сделок
        msg += f"{t['type'].upper()}: {t['entry_price']} → {t['exit_price']} ({t['profit_pct']:.2f}%)\n"
        total_profit += t['profit_pct']
    msg += f"\n💰 Общая прибыль за показанный период: {total_profit:.2f}%"
    await update.message.reply_text(msg)

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("signal", signal_command))

    # Фоновая проверка сигналов
    app.create_task(signal_loop(app))

    # Запуск бота
    await app.run_polling()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
