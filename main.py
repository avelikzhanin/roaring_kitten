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


async def get_sber_data():
    """Получение данных SBER через MOEX API и расчет технических индикаторов"""
    try:
        # Получаем данные за последние 7 дней
        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)
        
        # MOEX API для получения часовых свечей SBER
        url = "https://iss.moex.com/iss/engines/stock/markets/shares/securities/SBER/candles.json"
        params = {
            'from': from_date.strftime('%Y-%m-%d'),
            'till': to_date.strftime('%Y-%m-%d'),
            'interval': '60'  # 60 минут = часовые свечи
        }
        
        logger.info(f"Запрашиваем данные MOEX API с {from_date.strftime('%Y-%m-%d')} по {to_date.strftime('%Y-%m-%d')}")
        
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
        
        # Показываем временной диапазон
        if candles_data:
            first_time = candles_data[0]['time']
            last_time = candles_data[-1]['time']
            logger.info(f"Диапазон времени (МСК): {first_time} → {last_time}")
            logger.info(f"Цена: {candles_data[-1]['close']:.2f} ₽")
        
        if len(candles_data) < 30:
            logger.error(f"Insufficient data: {len(candles_data)} candles")
            return None
        
        # Преобразуем в DataFrame
        df = pd.DataFrame(candles_data)
        
        # Расчет технических индикаторов (стандартные настройки)
        df['ema20'] = ta.ema(df['close'], length=20)
        adx_data = ta.adx(df['high'], df['low'], df['close'], length=14, mamode='rma')
        df['adx'] = adx_data['ADX_14']
        df['di_plus'] = adx_data['DMP_14'] 
        df['di_minus'] = adx_data['DMN_14']
        
        # Берем последние значения
        last_row = df.iloc[-1]
        
        logger.info(f"MOEX результат: ADX={last_row['adx']:.2f}, DI+={last_row['di_plus']:.2f}, DI-={last_row['di_minus']:.2f}")
        
        return {
            'current_price': last_row['close'],
            'ema20': last_row['ema20'],
            'adx': last_row['adx'],
            'di_plus': last_row['di_plus'],
            'di_minus': last_row['di_minus']
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
