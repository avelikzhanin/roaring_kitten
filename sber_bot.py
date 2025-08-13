import asyncio
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Настройки ---
TELEGRAM_TOKEN = "ТВОЙ_ТЕЛЕГРАМ_ТОКЕН"
CHAT_ID = "ТВОЙ_CHAT_ID"

# --- История сделок ---
trades = []  # {"time": ..., "type": "LONG"/"SHORT", "action": "ENTRY"/"EXIT", "price": ...}

# --- Пример функции получения сигнала ---
# Заменить на свою логику с Tinkoff API и индикаторами
async def get_signal():
    # Пример сигнала
    # Возвращает tuple: ("LONG"/"SHORT"/None, "ENTRY"/"EXIT")
    # Здесь пока просто циклично LONG -> EXIT -> SHORT -> EXIT
    if not trades or trades[-1]["action"] == "EXIT":
        if not trades or trades[-1]["type"] == "SHORT":
            return ("LONG", "ENTRY")
        else:
            return ("SHORT", "ENTRY")
    else:
        return (trades[-1]["type"], "EXIT")

# --- Цикл сигналов ---
async def signal_loop(app):
    while True:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        signal_type, action = await get_signal()
        price = 100  # Заглушка для цены, можно получать с Tinkoff API

        trades.append({"time": now, "type": signal_type, "action": action, "price": price})

        msg = f"{now} — {action} {signal_type} по цене {price}"
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)

        await asyncio.sleep(600)  # Проверка каждые 10 минут

# --- Команды бота ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен!")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trades:
        await update.message.reply_text("Сделок пока нет.")
        return

    # Красивое отображение истории
    msg = ""
    profit = 0
    last_entry_price = None
    last_entry_type = None
    for t in trades:
        msg += f"{t['time']} — {t['action']} {t['type']} по {t['price']}\n"
        if t["action"] == "ENTRY":
            last_entry_price = t["price"]
            last_entry_type = t["type"]
        elif t["action"] == "EXIT" and last_entry_price is not None:
            # Простой расчет прибыли в процентах
            if last_entry_type == "LONG":
                profit += (t["price"] - last_entry_price) / last_entry_price * 100
            else:  # SHORT
                profit += (last_entry_price - t["price"]) / last_entry_price * 100
            last_entry_price = None
            last_entry_type = None

    msg += f"\nОбщая прибыль: {profit:.2f}%"
    await update.message.reply_text(msg)

# --- Главная функция ---
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Добавляем команды
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("history", history_command))

    # Запуск цикла сигналов
    app.create_task(signal_loop(app))

    # Запуск бота
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()

# --- Запуск без asyncio.run() для Railway ---
loop = asyncio.get_event_loop()
loop.create_task(main())
loop.run_forever()
