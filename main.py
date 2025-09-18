import os
import asyncio
from datetime import datetime, timedelta
import logging

import pandas as pd
import pandas_ta as ta
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Переменные окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN environment variable")


def calculate_adx_tradingview_style(df, period=14):
    """
    Расчет ADX точно по формуле TradingView:
    ADX = (Prior ADX × 13) + Current DX) / 14
    """
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    
    # Расчет True Range
    tr = []
    dm_plus = []
    dm_minus = []
    
    for i in range(1, len(high)):
        # True Range
        tr1 = high[i] - low[i]
        tr2 = abs(high[i] - close[i-1])
        tr3 = abs(low[i] - close[i-1])
        tr.append(max(tr1, tr2, tr3))
        
        # Directional Movement (как в TradingView)
        dm_p = max(high[i] - high[i-1], 0) if high[i] - high[i-1] > low[i-1] - low[i] else 0
        dm_m = max(low[i-1] - low[i], 0) if low[i-1] - low[i] > high[i] - high[i-1] else 0
        
        dm_plus.append(dm_p)
        dm_minus.append(dm_m)
    
    # Сглаживание Wilder's для ATR, DM+, DM-
    def wilders_smoothing(data, period):
        smoothed = []
        sma = sum(data[:period]) / period
        smoothed.append(sma)
        
        for i in range(period, len(data)):
            smoothed_val = (smoothed[-1] * (period - 1) + data[i]) / period
            smoothed.append(smoothed_val)
        return smoothed
    
    # Сглаженные значения
    atr = wilders_smoothing(tr, period)
    smoothed_dm_plus = wilders_smoothing(dm_plus, period)
    smoothed_dm_minus = wilders_smoothing(dm_minus, period)
    
    # DI+ и DI-
    di_plus = [(smoothed_dm_plus[i] / atr[i]) * 100 for i in range(len(atr))]
    di_minus = [(smoothed_dm_minus[i] / atr[i]) * 100 for i in range(len(atr))]
    
    # DX
    dx = [abs(di_plus[i] - di_minus[i]) / (di_plus[i] + di_minus[i]) * 100 
          if (di_plus[i] + di_minus[i]) > 0 else 0 for i in range(len(di_plus))]
    
    # ADX по формуле TradingView: ADX = (Prior ADX × 13) + Current DX) / 14
    adx = []
    if dx:
        # Первое значение ADX = среднее первых 14 DX
        first_adx = sum(dx[:period]) / period if len(dx) >= period else sum(dx) / len(dx)
        adx.append(first_adx)
        
        # Остальные значения по формуле TradingView
        for i in range(1, len(dx) - period + 1):
            current_dx = dx[period - 1 + i]
            prior_adx = adx[-1]
            new_adx = (prior_adx * 13 + current_dx) / 14  # ← Формула TradingView!
            adx.append(new_adx)
    
    return {
        'adx': adx[-1] if adx else 0,
        'di_plus': di_plus[-1] if di_plus else 0,
        'di_minus': di_minus[-1] if di_minus else 0
    }


async def get_sber_data():
    """Получение данных SBER через MOEX API и расчет технических индикаторов"""
    try:
        # Получаем данные за последние 7 дней
        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)
        
        # MOEX API для получения часовых свечей SBER (как TradingView)
        url = "https://iss.moex.com/iss/engines/stock/markets/shares/securities/SBER/candles.json"
        params = {
            'from': from_date.strftime('%Y-%m-%d'),
            'till': to_date.strftime('%Y-%m-%d'),
            'interval': '60'  # 60 минут = часовые свечи (как TradingView)
        }
        
        logger.info(f"Запрашиваем данные MOEX API с {from_date.strftime('%Y-%m-%d')} по {to_date.strftime('%Y-%m-%d')} (часовой таймфрейм)")
        
        # Делаем запрос к MOEX API с httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
        
        # Извлекаем данные свечей
        if 'candles' not in data or not data['candles']['data']:
            logger.error("No candle data received from MOEX API")
            return None
        
        columns = data['candles']['columns']
        candles_raw = data['candles']['data']
        
        # Преобразуем в удобный формат для pandas
        candles_data = []
        for candle in candles_raw:
            # columns: ["open", "close", "high", "low", "value", "volume", "begin", "end"]
            candles_data.append({
                'open': float(candle[0]),
                'close': float(candle[1]),
                'high': float(candle[2]),
                'low': float(candle[3]),
                'volume': int(candle[5]),
                'time': candle[6]  # время начала свечи
            })
        
        # Ограничиваем до последних 50 свечей
        if len(candles_data) > 50:
            candles_data = candles_data[-50:]
        
        logger.info(f"Получено {len(candles_data)} часовых свечей с MOEX")
        
        # ДИАГНОСТИКА: показываем последние несколько свечей
        if candles_data:
            logger.info("🔍 ПОСЛЕДНИЕ 3 СВЕЧИ (для диагностики):")
            for i, candle in enumerate(candles_data[-3:]):
                logger.info(f"   {i+1}. {candle['time']} | O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}")
            
            first_time = candles_data[0]['time']
            last_time = candles_data[-1]['time']
            logger.info(f"Диапазон времени (МСК): {first_time} → {last_time}")
            logger.info(f"Цена: {candles_data[-1]['close']:.2f} ₽")
        
        if len(candles_data) < 30:
            logger.error(f"Insufficient data: {len(candles_data)} candles")
            return None
        
        # Преобразуем в DataFrame
        df = pd.DataFrame(candles_data)
        
        # Расчет EMA20
        df['ema20'] = ta.ema(df['close'], length=20)
        
        # ADX по стандартной формуле pandas-ta
        adx_data_standard = ta.adx(df['high'], df['low'], df['close'], length=14, mamode='rma')
        
        # ADX по формуле TradingView
        adx_tradingview = calculate_adx_tradingview_style(df, period=14)
        
        # Берем последние значения
        last_row = df.iloc[-1]
        
        # Сравниваем результаты
        logger.info("📊 СРАВНЕНИЕ ФОРМУЛ ADX:")
        logger.info(f"   🔧 pandas-ta (стандарт): ADX={adx_data_standard['ADX_14'].iloc[-1]:.2f}")
        logger.info(f"   📈 TradingView формула: ADX={adx_tradingview['adx']:.2f}")
        logger.info(f"   🎯 DI+ TradingView: {adx_tradingview['di_plus']:.2f}")
        logger.info(f"   🎯 DI- TradingView: {adx_tradingview['di_minus']:.2f}")
        logger.info("=== Используем TradingView формулу ===")
        
        return {
            'current_price': last_row['close'],
            'ema20': last_row['ema20'],
            'adx': adx_tradingview['adx'],
            'di_plus': adx_tradingview['di_plus'],
            'di_minus': adx_tradingview['di_minus']
        }
        
    except httpx.HTTPError as e:
        logger.error(f"MOEX API request error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching SBER data: {e}")
        return None


def format_sber_message(data):
    """Форматирование сообщения с данными SBER"""
    adx_strength = "Сильный тренд" if data['adx'] > 25 else "Слабый тренд"
    
    message = f"""🏦 <b>SBER - Сбербанк</b>

💰 <b>Цена:</b> {data['current_price']:.2f} ₽
📊 <b>EMA20:</b> {data['ema20']:.2f} ₽

📈 <b>Технические индикаторы:</b>
• <b>ADX:</b> {data['adx']:.2f} ({adx_strength})
• <b>DI+:</b> {data['di_plus']:.2f}
• <b>DI-:</b> {data['di_minus']:.2f}"""
    
    return message


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_message = """👋 Привет! Я бот для мониторинга акций SBER.

📊 <b>Доступные команды:</b>
/sber - Получить актуальные данные по Сбербанку

<i>Данные получаются напрямую с Московской биржи через MOEX API</i>"""
    
    await update.message.reply_text(welcome_message, parse_mode='HTML')


async def sber_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /sber"""
    loading_message = await update.message.reply_text('⏳ Получаю данные с MOEX...')
    
    try:
        sber_data = await get_sber_data()
        
        if not sber_data:
            await loading_message.edit_text('❌ Не удалось получить данные с MOEX API. Попробуйте позже.')
            return
        
        # Проверяем на NaN значения
        if (pd.isna(sber_data['ema20']) or 
            pd.isna(sber_data['adx']) or 
            pd.isna(sber_data['di_plus']) or 
            pd.isna(sber_data['di_minus'])):
            await loading_message.edit_text('❌ Недостаточно данных для расчета индикаторов. Попробуйте позже.')
            return
        
        message = format_sber_message(sber_data)
        await loading_message.edit_text(message, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in sber_command: {e}")
        await loading_message.edit_text('❌ Произошла ошибка при получении данных.')


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Основная функция запуска бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("sber", sber_command))
    
    application.add_error_handler(error_handler)
    
    logger.info("🤖 SBER Telegram Bot started with MOEX API...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
