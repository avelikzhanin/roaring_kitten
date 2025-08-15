import os
import logging
import pandas as pd
from datetime import timedelta
import asyncio

from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================
# Конфиг
# =========================
BOT_VERSION = "v0.25 — сигналы на покупку + выход"
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"  # SBER
TF = CandleInterval.CANDLE_INTERVAL_HOUR
LOOKBACK_HOURS = 200
CHECK_INTERVAL = 15 * 60  # 15 минут
TRAIL_PCT = 0.015
ADX_THRESHOLD = 23

CHAT_ID_FILE = "chat_id.txt"

# =========================
# Глобальное состояние позиции
# =========================
position_type = None   # "long" / None
entry_price = None
best_price = None
trailing_stop = None

# =========================
# Логирование
# =========================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sber-bot")

# =========================
# Работа с chat_id
# =========================
def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
    log.info(f"Chat ID сохранён: {chat_id}")

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    return None

# =========================
# Индикаторы
# =========================
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()

    plus_dm[plus_dm < 0] = 0

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()

    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)

    dx = (plus_di / plus_di) * 100  # будет корректно для одного DI
    adx_val = dx.rolling(window=period).mean()

    return adx_val, plus_di, minus_dm  # минус DI пока не нужен

# =========================
# Данные
# =========================
def get_candles() -> pd.DataFrame:
    with Client(TINKOFF_API_TOKEN) as client:
        now = pd.Timestamp.now(tz="Europe/Moscow")
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=now - pd.Timedelta(hours=LOOKBACK_HOURS),
            to=now,
            interval=TF
        ).candles

    df = pd.DataFrame([{
        "time": c.time,
        "open": c.open.units + c.open.nano / 1e9,
        "high": c.high.units + c.high.nano / 1e9,
        "low":  c.low.units  + c.low.nano  / 1e9,
        "close":c.close.units+ c.close.nano / 1e9,
        "volume": c.volume
    } for c in candles])
    return df

# =========================
# Оценка сигналов
# =========================
def evaluate_signal(df: pd.DataFrame):
    df = df.copy()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], _ = adx(df["high"], df["low"], df["close"], period=14)
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    last = df.iloc[-1]

    adx_cond = last["ADX"] > ADX_THRESHOLD
    vol_cond = last["volume"] > last["vol_ma20"]
    di_buy = last["+DI"] > 0
    ema_buy = last["close"] > last["ema100"]

    buy_ok = adx_cond and di_buy and vol_cond and ema_buy

    signal = "BUY" if buy_ok else None

    return last, {
        "adx_cond": adx_cond,
        "vol_cond": vol_cond,
        "di_buy": di_buy,
        "ema_buy": ema_buy,
        "signal": signal,
        "vol_ma20": last["vol_ma20"]
    }, df

# =========================
# Трейлинг
# =========================
def update_trailing(curr_price: float):
    global trailing_stop, best_price
    if position_type == "long":
        best_price = max(best_price or curr_price, curr_price)
        trailing_stop = best_price * (1 - TRAIL_PCT)

# =========================
# Сообщения
# =========================
def emoji(ok: bool) -> str:
    return "✅" if ok else "❌"

def build_message(last: pd.Series, conds: dict) -> str:
    price = last["close"]
    adx = last["ADX"]
    plus_di = last["+DI"]
    ema100 = last["ema100"]
    vol = last["volume"]
    vol_ma20 = conds["vol_ma20"]

    lines = []
    lines.append("📊 Параметры стратегии:")
    lines.append(f"ADX: {adx:.2f} | BUY: {emoji(conds['adx_cond'])}")
    lines.append(f"Объём: {int(vol)} | BUY: {emoji(conds['vol_cond'])} (MA20={int(vol_ma20)})")
    lines.append(f"EMA100: {ema100:.2f} | BUY: {emoji(conds['ema_buy'])}")
    lines.append(f"+DI: {plus_di:.2f} | BUY: {emoji(conds['di_buy'])}")

    if conds["signal"]:
        lines.append(f"\n📢 Сигнал стратегии: {conds['signal']}")
    else:
        lines.append("\n❌ Сигналов по стратегии нет")

    if position_type and entry_price:
        pnl = (price - entry_price) / entry_price * 100
        ts_text = f"{trailing_stop:.2f}" if trailing_stop else "-"
        lines.append(f"\nТекущая цена: {price:.2f}")
        lines.append(f"Цена входа: {entry_price:.2f}")
        lines.append(f"Трейлинг-стоп: {ts_text}")
        lines.append(f"Текущая прибыль: {pnl:.2f}%")
    else:
        lines.append(f"\nТекущая цена: {price:.2f}")
        lines.append("Цена входа: -")
        lines.append("Трейлинг-стоп: -")
        lines.append("Текущая прибыль: -")

    return "\n".join(lines)

# =========================
# Telegram Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text="😺 Ревущий котёнок на связи! Буду присылать сигналы по SBER"
    )

async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        df = get_candles()
        last, conds, _ = evaluate_signal(df)
        msg = build_message(last, conds)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
    except Exception as e:
        log.exception("Ошибка в /signal")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Ошибка: {e}")

# =========================
# Авто-проверка сигналов
# =========================
async def auto_check(app):
    global position_type, entry_price, best_price, trailing_stop
    while True:
        try:
            df = get_candles()
            last, conds, _ = evaluate_signal(df)
            current_signal = conds["signal"]
            price = last["close"]
            chat_id = load_chat_id()

            exit_pos = False

            # Обновляем трейлинг
            if position_type:
                update_trailing(price)
                if price <= trailing_stop:
                    exit_pos = True
                    reason = "трейлинг-стоп"
                    pnl = (price - entry_price)/entry_price*100
                    if chat_id:
                        msg = f"❌ Закрытие позиции LONG! ({reason})\nЦена: {price:.2f}\nПрибыль: {pnl:.2f}%"
                        await app.bot.send_message(chat_id=chat_id, text=msg)
                    position_type = None
                    entry_price = None
                    best_price = None
                    trailing_stop = None
                else:
                    # Регулярный апдейт
                    if chat_id:
                        pnl = (price - entry_price)/entry_price*100
                        ts_text = f"{trailing_stop:.2f}" if trailing_stop else "-"
                        msg = (
                            f"📈 Обновление позиции LONG\n"
                            f"Текущая цена: {price:.2f}\n"
                            f"Цена входа: {entry_price:.2f}\n"
                            f"Трейлинг-стоп: {ts_text}\n"
                            f"Текущая прибыль: {pnl:.2f}%"
                        )
                        await app.bot.send_message(chat_id=chat_id, text=msg)

            # Новый сигнал — открываем позицию
            if current_signal and not position_type:
                position_type = "long"
                entry_price = price
                best_price = price
                trailing_stop = price*(1-TRAIL_PCT)
                if chat_id:
                    msg = build_message(last, conds)
                    await app.bot.send_message(chat_id=chat_id, text=msg)

        except Exception:
            log.exception("Ошибка в авто-проверке сигналов")

        await asyncio.sleep(CHECK_INTERVAL)

# =========================
# Main
# =========================
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_cmd))

    # Запуск авто-проверки
    asyncio.create_task(auto_check(app))

    # Запуск бота
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()  # держим процесс живым

# =========================
# Запуск
# =========================
try:
    loop = asyncio.get_running_loop()
    loop.create_task(main())
except RuntimeError:
    asyncio.run(main())
