import asyncio
from datetime import datetime, timedelta
import pandas as pd
from ta.trend import ADXIndicator
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from tinkoff.invest import Client, CandleInterval
import nest_asyncio

nest_asyncio.apply()

TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TINKOFF_TOKEN = "YOUR_TINKOFF_INVEST_TOKEN"
FIGI = "BBG004730N88"  # Сбербанк
INTERVAL = CandleInterval.CANDLE_INTERVAL_1_MIN

# Храним всех пользователей, которые нажали /start
CHAT_IDS = set()
EMA_PERIOD = 100

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    CHAT_IDS.add(update.effective_chat.id)
    await update.message.reply_text("Вы подписались на сигналы по стратегии!")

def calculate_ema(prices, period=EMA_PERIOD):
    if len(prices) < period:
        return None
    ema = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

async def check_strategy():
    try:
        async with Client(TINKOFF_TOKEN) as client:
            now = datetime.utcnow()
            start_time = now - timedelta(minutes=EMA_PERIOD + 20)
            candles = client.market.get_candles(figi=FIGI, from_=start_time, to=now, interval=INTERVAL).candles
            if len(candles) < EMA_PERIOD:
                return None, None

            # Преобразуем свечи в DataFrame для расчета индикаторов
            data = pd.DataFrame({
                "open": [c.open.units + c.open.nano / 1e9 for c in candles],
                "high": [c.high.units + c.high.nano / 1e9 for c in candles],
                "low": [c.low.units + c.low.nano / 1e9 for c in candles],
                "close": [c.close.units + c.close.nano / 1e9 for c in candles],
                "volume": [c.volume for c in candles]
            })

            # EMA
            closes = data['close'].tolist()
            ema = calculate_ema(closes)

            # Средний объем
            avg_volume = data['volume'].tail(EMA_PERIOD).mean()

            # ADX и DI
            adx_ind = ADXIndicator(high=data['high'], low=data['low'], close=data['close'], window=14)
            adx = adx_ind.adx().iloc[-1]
            plus_di = adx_ind.adx_pos().iloc[-1]
            minus_di = adx_ind.adx_neg().iloc[-1]

            current_price = closes[-1]

            # Условия стратегии
            signal = False
            if adx > 23 and plus_di > minus_di and data['volume'].iloc[-1] > avg_volume and current_price > ema:
                signal = True

            return signal, current_price

    except Exception as e:
        print("Ошибка в check_strategy:", e)
        return None, None

async def auto_check(app):
    while True:
        signal, price = await check_strategy()
        if signal:
            for chat_id in CHAT_IDS:
                try:
                    await app.bot.send_message(chat_id, f"Сигнал на покупку!\nЦена покупки: {price:.2f}")
                except Exception as e:
                    print("Ошибка при отправке сообщения:", e)
        await asyncio.sleep(60)  # проверка каждую минуту

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.create_task(auto_check(app))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
