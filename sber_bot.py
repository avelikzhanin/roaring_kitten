import time
import pandas as pd
import numpy as np
import requests
from tinkoff.invest import Client, CandleInterval
from datetime import datetime, timedelta
import talib

# === Конфигурация ===
TOKEN = "TINKOFF_INVEST_API_TOKEN"
TELEGRAM_TOKEN = "TELEGRAM_BOT_TOKEN"
CHAT_ID_FILE = "chat_id.txt"
FIGI = "BBG004730N88"  # SBER
TIMEFRAME = CandleInterval.CANDLE_INTERVAL_5_MIN
ADX_PERIOD = 14
ADX_THRESHOLD = 23  # Порог для сигнала
EMA_PERIOD = 100
VOLUME_MA_PERIOD = 20
CHECK_INTERVAL = 300  # каждые 5 минут

# === Получаем chat_id ===
try:
    with open(CHAT_ID_FILE, "r") as f:
        CHAT_ID = f.read().strip()
except FileNotFoundError:
    CHAT_ID = None

# === Функция отправки сообщений в Telegram ===
def send_telegram_message(message):
    global CHAT_ID
    if not CHAT_ID:
        print("❌ CHAT_ID не найден. Сначала запусти бота с командой /start.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    requests.post(url, json=payload)

# === Загрузка данных с Tinkoff API ===
def get_candles():
    with Client(TOKEN) as client:
        now = datetime.utcnow()
        candles = client.get_market_candles(
            figi=FIGI,
            from_=now - timedelta(days=5),
            to=now,
            interval=TIMEFRAME
        ).candles

    df = pd.DataFrame([{
        "time": c.time,
        "open": float(c.o),
        "high": float(c.h),
        "low": float(c.l),
        "close": float(c.c),
        "volume": c.v
    } for c in candles])

    return df

# === Логика стратегии ===
def check_signals():
    df = get_candles()

    # EMA100
    df["EMA100"] = talib.EMA(df["close"], timeperiod=EMA_PERIOD)

    # ADX, +DI, -DI
    df["ADX"] = talib.ADX(df["high"], df["low"], df["close"], timeperiod=ADX_PERIOD)
    df["+DI"] = talib.PLUS_DI(df["high"], df["low"], df["close"], timeperiod=ADX_PERIOD)
    df["-DI"] = talib.MINUS_DI(df["high"], df["low"], df["close"], timeperiod=ADX_PERIOD)

    # Средний объём
    df["Volume_MA20"] = df["volume"].rolling(VOLUME_MA_PERIOD).mean()

    last = df.iloc[-1]

    # Условия
    adx_ok = last["ADX"] > ADX_THRESHOLD
    volume_ok = last["volume"] > last["Volume_MA20"]
    ema_buy = last["close"] > last["EMA100"]
    ema_sell = last["close"] < last["EMA100"]
    di_buy = last["+DI"] > last["-DI"]
    di_sell = last["-DI"] > last["+DI"]

    buy_signal = adx_ok and volume_ok and ema_buy and di_buy
    sell_signal = adx_ok and volume_ok and ema_sell and di_sell

    # Эмодзи для DI
    buy_emoji = "🟢" if di_buy else "⚪"
    sell_emoji = "🔴" if di_sell else "⚪"

    if buy_signal or sell_signal:
        msg = (
            f"📊 <b>Сигнал стратегии</b>\n\n"
            f"ADX: {last['ADX']:.2f} (>{ADX_THRESHOLD})\n"
            f"Объём: {last['volume']} / MA20={int(last['Volume_MA20'])}\n"
            f"EMA100: {last['EMA100']:.2f} | Цена: {last['close']:.2f}\n"
            f"+DI {buy_emoji}: {last['+DI']:.2f} | -DI {sell_emoji}: {last['-DI']:.2f}\n\n"
            f"💡 Сигнал: {'BUY ✅' if buy_signal else ''}{'SELL ❌' if sell_signal else ''}"
        )
        send_telegram_message(msg)

# === Основной цикл ===
print("🚀 Бот запущен. Проверка каждые 5 минут.")
while True:
    try:
        check_signals()
    except Exception as e:
        print(f"Ошибка: {e}")
    time.sleep(CHECK_INTERVAL)
