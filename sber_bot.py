import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime

# Токен Telegram
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

# Словарь для хранения открытых сделок
open_trades = {
    "long": None,
    "short": None
}

# История сделок
trade_history = []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен! Используй /signal для проверки сигналов.")

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = []
    for direction in ["long", "short"]:
        trade = open_trades[direction]
        if trade is None:
            messages.append(f"No open {direction.upper()} trades.")
        else:
            messages.append(f"{direction.upper()} trade open since {trade['entry_time']}, entry price: {trade['entry_price']:.2f}")
    await update.message.reply_text("\n".join(messages))

async def signal_loop(app):
    """
    Цикл, который проверяет сигналы и отправляет их в чат.
    """
    chat_id = "YOUR_CHAT_ID"
    while True:
        # Здесь нужно подключить ваш метод проверки сигналов
        signal_long, price_long = check_long_signal()
        signal_short, price_short = check_short_signal()

        # Обрабатываем Long
        if signal_long and open_trades["long"] is None:
            # Вход в сделку
            open_trades["long"] = {"entry_time": datetime.now(), "entry_price": price_long}
            await app.bot.send_message(chat_id=chat_id, text=f"📈 LONG вход — цена {price_long:.2f}")
        elif signal_long is False and open_trades["long"]:
            # Выход из сделки
            entry_price = open_trades["long"]["entry_price"]
            profit = (price_long - entry_price) / entry_price * 100
            trade_history.append({"type": "long", "entry": entry_price, "exit": price_long, "profit_pct": profit})
            await app.bot.send_message(chat_id=chat_id, text=f"📉 LONG выход — цена {price_long:.2f}, профит {profit:.2f}%")
            open_trades["long"] = None

        # Обрабатываем Short
        if signal_short and open_trades["short"] is None:
            open_trades["short"] = {"entry_time": datetime.now(), "entry_price": price_short}
            await app.bot.send_message(chat_id=chat_id, text=f"📉 SHORT вход — цена {price_short:.2f}")
        elif signal_short is False and open_trades["short"]:
            entry_price = open_trades["short"]["entry_price"]
            profit = (entry_price - price_short) / entry_price * 100
            trade_history.append({"type": "short", "entry": entry_price, "exit": price_short, "profit_pct": profit})
            await app.bot.send_message(chat_id=chat_id, text=f"📈 SHORT выход — цена {price_short:.2f}, профит {profit:.2f}%")
            open_trades["short"] = None

        await asyncio.sleep(60)  # Проверяем сигналы каждую минуту

def check_long_signal():
    """
    Здесь подключается ваша логика сигналов на Long.
    Возвращает (True = вход, False = выход, None = нет действия) и текущую цену.
    """
    # Заглушка
    from random import random
    price = 318.0 + random()
    return random() > 0.7, price

def check_short_signal():
    """
    Здесь подключается ваша логика сигналов на Short.
    """
    from random import random
    price = 318.0 + random()
    return random() > 0.7, price

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))

    # Запуск цикла сигналов
    asyncio.create_task(signal_loop(app))

    # Старт polling
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
