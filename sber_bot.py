#!/usr/bin/env python3
# sber_bot.py — telegram notifier for SBER using Tinkoff Invest API
import os
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
from tinkoff.invest import Client, CandleInterval
import ta

# === Настройка логов ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# === Конфиг через переменные окружения ===
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")           # ОБЯЗАТЕЛЬНО
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")         # ОБЯЗАТЕЛЬНО
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")             # опционально
FIGI_SBER = os.getenv("FIGI_SBER", "BBG004730N88")
CANDLES_DAYS = int(os.getenv("CANDLES_DAYS", "7"))
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "5"))  # как часто проверяем в цикле
ADX_THRESHOLD = float(os.getenv("ADX_THRESHOLD", "23.0"))
VOLUME_MA = int(os.getenv("VOLUME_MA", "20"))
EMA_WINDOW = int(os.getenv("EMA_WINDOW", "100"))

if not TINKOFF_API_TOKEN or not TELEGRAM_BOT_TOKEN:
    logging.error("TINKOFF_API_TOKEN and TELEGRAM_BOT_TOKEN must be set in environment.")
    raise SystemExit(1)

TG_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# === Утилиты Telegram ===
def get_chat_id_from_updates():
    # Попробуем получить chat_id из последних апдейтов
    try:
        r = requests.get(f"{TG_API_BASE}/getUpdates", timeout=10).json()
        res = r.get("result", [])
        for item in reversed(res):
            # ищем последний update с message
            msg = item.get("message") or item.get("edited_message")
            if msg and "chat" in msg:
                return msg["chat"]["id"]
    except Exception as e:
        logging.debug("getUpdates failed: %s", e)
    return None

def send_telegram(text: str):
    chat_id = TELEGRAM_CHAT_ID or get_chat_id_from_updates()
    if not chat_id:
        logging.warning("No TELEGRAM_CHAT_ID found and bot hasn't received messages — send one message to the bot and retry.")
        return False
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(f"{TG_API_BASE}/sendMessage", json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logging.exception("Failed to send telegram message: %s", e)
        return False

# === Загрузка свечей из Tinkoff ===
def fetch_hourly_candles(days: int = 7) -> pd.DataFrame:
    """Возвращаем DataFrame с закрытыми часовыми свечами за days назад."""
    now_utc = datetime.now(timezone.utc)
    start = now_utc - timedelta(days=days)
    with Client(TINKOFF_API_TOKEN) as client:
        # market_data.get_candles
        resp = client.market_data.get_candles(
            figi=FIGI_SBER,
            from_=start,
            to=now_utc,
            interval=CandleInterval.CANDLE_INTERVAL_HOUR
        )
        candles = resp.candles
    if not candles:
        return pd.DataFrame()
    rows = []
    for c in candles:
        rows.append({
            "time": c.time, 
            "open": c.open.units + c.open.nano / 1e9,
            "high": c.high.units + c.high.nano / 1e9,
            "low": c.low.units + c.low.nano / 1e9,
            "close": c.close.units + c.close.nano / 1e9,
            "volume": c.volume
        })
    df = pd.DataFrame(rows)
    df.set_index("time", inplace=True)
    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    return df

# === Индикаторы ===
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # EMA
    df["ema100"] = ta.trend.ema_indicator(df["close"], window=EMA_WINDOW)
    # ADX + DI
    adx_i = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
    df["adx"] = adx_i.adx()
    df["plus_di"] = adx_i.adx_pos()
    df["minus_di"] = adx_i.adx_neg()
    # volume MA
    df["vol_ma20"] = df["volume"].rolling(window=VOLUME_MA, min_periods=1).mean()
    return df

# === Логика сигналов ===
def check_entry_exit(df: pd.DataFrame):
    """
    Возвращает ('buy'|'sell'|'hold', reason_text)
    Проверяет последнюю ЗАКРЫТУЮ свечу (df.iloc[-1]).
    """
    if df.empty or len(df) < max(EMA_WINDOW, 30):
        return "hold", "not enough data"

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # условия входа
    cond_adx = last["adx"] > ADX_THRESHOLD
    cond_di = last["plus_di"] > last["minus_di"]
    cond_price = last["close"] > last["ema100"]
    cond_vol = last["volume"] > last["vol_ma20"]
    cond_break = last["close"] > prev["high"]  # дополнительный триггер пробоя

    entry_ok = cond_adx and cond_di and cond_price and cond_vol and cond_break

    # условия выхода
    exit_cond = (last["close"] < last["ema100"]) or (last["plus_di"] < last["minus_di"]) or (last["adx"] < 20)

    # состав описания
    reason = (
        f"ADX={last['adx']:.2f} (+DI={last['plus_di']:.2f} -DI={last['minus_di']:.2f}), "
        f"close={last['close']:.2f}, ema100={last['ema100']:.2f}, vol={int(last['volume'])}, vol_ma={int(last['vol_ma20'])}"
    )

    if entry_ok:
        return "buy", "entry conditions met — " + reason
    if exit_cond:
        return "sell", "exit conditions met — " + reason
    return "hold", "no clear signal — " + reason

# === Main loop (one-shot or continuous) ===
def run_check_and_notify():
    try:
        df = fetch_hourly_candles(days=CANDLES_DAYS)
        if df.empty:
            logging.warning("No candles returned")
            return
        df = add_indicators(df)
        # use last CLOSED candle (some APIs return current forming candle as last — confirm by time)
        # We assume last candle is closed because we pulled up to now()
        signal, text = check_entry_exit(df)
        logging.info("Signal: %s — %s", signal, text)
        if signal == "buy":
            send_telegram(f"📈 BUY signal for SBER\n{text}")
        elif signal == "sell":
            send_telegram(f"📉 SELL signal for SBER\n{text}")
        else:
            logging.info("Hold — not sending Telegram message.")
    except Exception as e:
        logging.exception("Error in run_check_and_notify: %s", e)

if __name__ == "__main__":
    # одна итерация — удобно тестировать локально
    run_check_and_notify()

    # Если хочешь — можно запустить в loop:
    # while True:
    #     run_check_and_notify()
    #     time.sleep(CHECK_INTERVAL_MIN * 60)
