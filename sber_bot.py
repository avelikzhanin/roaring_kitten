import os
import logging
import time
import pandas as pd
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import requests

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Переменные окружения ---
TINKOFF_TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"  # SBER
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR
HISTORY_HOURS = 200

# Трейлинг-стоп (доля): 0.015 = 1.5%
TRAIL_PCT = float(os.getenv("TRAIL_PCT", "0.015"))

CHAT_ID_FILE = "chat_id.txt"

# --- Состояние стратегии ---
position = None          # None / "long" / "short"
entry_price = None       # цена входа
best_price = None        # max для long, min для short с момента входа
trail_stop = None        # актуальный уровень трейлинг-стопа

# --- Утилиты Telegram ---
def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
    logging.info(f"Chat ID сохранён: {chat_id}")

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    return None

def send_telegram_message(text):
    chat_id = load_chat_id()
    if not chat_id:
        logging.warning("❌ Chat ID не найден — напиши /start боту")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения Telegram: {e}")

# --- Команды Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text="😺 Привет! Бот активирован. Буду открывать/закрывать позиции по сигналам и трейлингу."
    )

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_candles()
    sig, curr_price = get_signal(df)

    # текущая (плавающая) PnL
    pnl_text = "-"
    if position == "long" and entry_price:
        pnl = (curr_price - entry_price) / entry_price * 100
        pnl_text = f"{pnl:.2f}%"
    elif position == "short" and entry_price:
        pnl = (entry_price - curr_price) / entry_price * 100
        pnl_text = f"{pnl:.2f}%"

    text = (
        f"Сигнал стратегии: {sig or 'None'}\n"
        f"Текущая цена: {curr_price:.2f}\n"
        f"Тип позиции: {position or '-'}\n"
        f"Цена входа: {entry_price:.2f}" if entry_price else
        f"Сигнал стратегии: {sig or 'None'}\nТекущая цена: {curr_price:.2f}\nТип позиции: {position or '-'}\nЦена входа: -"
    )
    # Добавим трейлинг и PnL
    if trail_stop:
        text += f"\nТрейлинг-стоп: {trail_stop:.2f}"
    else:
        text += "\nТрейлинг-стоп: -"
    text += f"\nТекущая прибыль: {pnl_text}"

    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

# --- Индикаторы ---
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()

    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = abs(100 * (minus_dm.rolling(window=period).mean() / atr))

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx_val = dx.rolling(window=period).mean()
    return adx_val, plus_di, minus_di

# --- Данные ---
def get_candles():
    with Client(TINKOFF_TOKEN) as client:
        now = pd.Timestamp.now(tz="Europe/Moscow")
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=now - pd.Timedelta(hours=HISTORY_HOURS),
            to=now,
            interval=INTERVAL
        ).candles

        df = pd.DataFrame([{
            "time": c.time,
            "open": c.open.units + c.open.nano / 1e9,
            "high": c.high.units + c.high.nano / 1e9,
            "low": c.low.units + c.low.nano / 1e9,
            "close": c.close.units + c.close.nano / 1e9,
            "volume": c.volume
        } for c in candles])
    return df

# --- Логика сигналов стратегии ---
def get_signal(df):
    """
    Возвращает ('BUY' | 'SELL' | None, current_price)
    BUY  -> хотим long
    SELL -> хотим short
    """
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])
    vol_ma = df["volume"].rolling(window=20).mean()
    last = df.iloc[-1]

    curr_price = last["close"]

    if (
        last["ADX"] > 23 and
        last["+DI"] > last["-DI"] and
        last["volume"] > vol_ma.iloc[-1] and
        last["close"] > df["ema100"].iloc[-1]
    ):
        return "BUY", curr_price
    elif last["ADX"] < 20 or last["close"] < df["ema100"].iloc[-1]:
        return "SELL", curr_price
    else:
        return None, curr_price

# --- Управление трейлинг-стопом ---
def init_trailing_for_long(price):
    global best_price, trail_stop
    best_price = price
    trail_stop = best_price * (1 - TRAIL_PCT)

def init_trailing_for_short(price):
    global best_price, trail_stop
    best_price = price
    trail_stop = best_price * (1 + TRAIL_PCT)

def update_trailing(curr_price):
    """
    Обновляет best_price и trail_stop для текущей позиции.
    Для long: best = max(best, price), стоп = best*(1 - TRAIL_PCT)
    Для short: best = min(best, price), стоп = best*(1 + TRAIL_PCT)
    """
    global best_price, trail_stop
    if position == "long":
        if curr_price > best_price:
            best_price = curr_price
            trail_stop = best_price * (1 - TRAIL_PCT)
    elif position == "short":
        if curr_price < best_price:
            best_price = curr_price
            trail_stop = best_price * (1 + TRAIL_PCT)

def should_stop_out(curr_price):
    """
    Проверка срабатывания трейлинга:
    - long: выходим если price <= trail_stop
    - short: выходим если price >= trail_stop
    """
    if trail_stop is None or position is None:
        return False
    if position == "long":
        return curr_price <= trail_stop
    else:  # short
        return curr_price >= trail_stop

# --- Основной цикл: сигналы + трейлинг ---
def main_loop():
    global position, entry_price, best_price, trail_stop

    while True:
        try:
            df = get_candles()
            sig, curr_price = get_signal(df)

            # 1) Если есть позиция — сначала обновляем трейлинг и проверяем выход по нему
            if position is not None:
                update_trailing(curr_price)
                if should_stop_out(curr_price):
                    # Закрываем по трейлингу
                    if position == "long":
                        pnl = (curr_price - entry_price) / entry_price * 100
                        send_telegram_message(
                            f"🔔 Трейлинг-стоп сработал (LONG)\n"
                            f"Выход по цене: {curr_price:.2f}\n"
                            f"PnL: {pnl:.2f}%"
                        )
                    else:
                        pnl = (entry_price - curr_price) / entry_price * 100
                        send_telegram_message(
                            f"🔔 Трейлинг-стоп сработал (SHORT)\n"
                            f"Выход по цене: {curr_price:.2f}\n"
                            f"PnL: {pnl:.2f}%"
                        )
                    position = None
                    entry_price = None
                    best_price = None
                    trail_stop = None
                    # После стопа не открываем сразу новую позицию, ждём явного сигнала в следующем цикле

            # 2) Проверка обратного сигнала стратегии (может закрыть и перевернуть позицию)
            if sig == "BUY":
                if position == "short":
                    # Закрываем short по сигналу
                    pnl = (entry_price - curr_price) / entry_price * 100
                    send_telegram_message(
                        f"📈 Обратный сигнал: закрываем SHORT по {curr_price:.2f}\nPnL: {pnl:.2f}%"
                    )
                    position = None
                    entry_price = None
                    best_price = None
                    trail_stop = None

                if position is None:
                    # Открываем long
                    position = "long"
                    entry_price = curr_price
                    init_trailing_for_long(entry_price)
                    send_telegram_message(
                        f"📈 Открываем LONG по {entry_price:.2f}\nТрейлинг: {trail_stop:.2f} (−{TRAIL_PCT*100:.2f}%)"
                    )

            elif sig == "SELL":
                if position == "long":
                    # Закрываем long по сигналу
                    pnl = (curr_price - entry_price) / entry_price * 100
                    send_telegram_message(
                        f"📉 Обратный сигнал: закрываем LONG по {curr_price:.2f}\nPnL: {pnl:.2f}%"
                    )
                    position = None
                    entry_price = None
                    best_price = None
                    trail_stop = None

                if position is None:
                    # Открываем short
                    position = "short"
                    entry_price = curr_price
                    init_trailing_for_short(entry_price)
                    send_telegram_message(
                        f"📉 Открываем SHORT по {entry_price:.2f}\nТрейлинг: {trail_stop:.2f} (+{TRAIL_PCT*100:.2f}%)"
                    )

        except Exception as e:
            logging.error(f"Ошибка в main_loop: {e}")

        time.sleep(300)  # каждые 5 минут

# --- Запуск ---
if __name__ == "__main__":
    from threading import Thread

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))

    Thread(target=main_loop, daemon=True).start()
    app.run_polling()
