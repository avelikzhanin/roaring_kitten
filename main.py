import os
import asyncio
from datetime import datetime, timedelta, timezone
import logging

import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.utils import quotation_to_decimal, now

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
TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
SBER_FIGI = 'BBG004730N88'  # FIGI для Сбербанка

if not TELEGRAM_TOKEN or not TINKOFF_TOKEN:
    raise ValueError("Missing required environment variables")


async def get_sber_data():
    """Получение данных SBER и расчет технических индикаторов"""
    try:
        with Client(TINKOFF_TOKEN) as client:
            # Берем данные за 7 дней (с запасом для получения 50+ часовых свечей)
            to_date = now()
            from_date = to_date - timedelta(days=7)  # Уменьшил с 60 дней до 7
            
            # Получаем свечи
            candles_data = []
            for candle in client.get_all_candles(
                figi=SBER_FIGI,
                from_=from_date,
                interval=CandleInterval.CANDLE_INTERVAL_HOUR
            ):
                candles_data.append({
                    'high': float(quotation_to_decimal(candle.high)),
                    'low': float(quotation_to_decimal(candle.low)),
                    'close': float(quotation_to_decimal(candle.close)),
                    'volume': candle.volume,
                    'time': candle.time
                })
            
            # Ограничиваем до последних 50 свечей
            if len(candles_data) > 50:
                candles_data = candles_data[-50:]  # Берем последние 50
            
            logger.info(f"Получено {len(candles_data)} часовых свечей для анализа")  # Логируем количество
            
            if not candles_data:
                logger.error("No candles data received")
                return None
            
            # Преобразуем в DataFrame
            df = pd.DataFrame(candles_data)
            df = df.sort_values('time').reset_index(drop=True)
            
            if df.empty or len(df) < 30:  # Минимум 30 свечей (было 50)
                logger.error(f"Insufficient data for calculations: {len(df)} candles")
                return None
            
            logger.info(f"Используем {len(df)} свечей для расчета индикаторов")
            
            # Расчет технических индикаторов - ТЕСТИРУЕМ 4 ВАРИАНТА ADX
            # EMA20
            df['ema20'] = ta.ema(df['close'], length=20)
            
            # ADX с 4 разными методами сглаживания
            adx_period = 14
            
            # Вариант 1: RMA (Relative MA) - классический Wilder's ADX
            adx_rma = ta.adx(df['high'], df['low'], df['close'], length=adx_period, mamode='rma')
            
            # Вариант 2: EMA (Exponential MA) - используется в MT4, TradingView
            adx_ema = ta.adx(df['high'], df['low'], df['close'], length=adx_period, mamode='ema')
            
            # Вариант 3: SMA (Simple MA) - простые платформы
            adx_sma = ta.adx(df['high'], df['low'], df['close'], length=adx_period, mamode='sma')
            
            # Вариант 4: WMA (Weighted MA) - специализированные платформы
            adx_wma = ta.adx(df['high'], df['low'], df['close'], length=adx_period, mamode='wma')
            
            # Используем RMA как основной (можно поменять)
            df['adx'] = adx_rma[f'ADX_{adx_period}']
            df['di_plus'] = adx_rma[f'DMP_{adx_period}'] 
            df['di_minus'] = adx_rma[f'DMN_{adx_period}']
            
            # Берем последние значения
            last_row = df.iloc[-1]
            
            # Логируем ВСЕ 4 варианта для сравнения с графиком
            logger.info("=== 🔍 СРАВНЕНИЕ 4-Х МЕТОДОВ ADX ===")
            logger.info(f"📊 График показывает: ADX=25.47, DI+=29.84, DI-=15.18")
            logger.info(f"1️⃣ RMA (Wilder): ADX={adx_rma[f'ADX_{adx_period}'].iloc[-1]:.2f}, DI+={adx_rma[f'DMP_{adx_period}'].iloc[-1]:.2f}, DI-={adx_rma[f'DMN_{adx_period}'].iloc[-1]:.2f}")
            logger.info(f"2️⃣ EMA (MT4/TV): ADX={adx_ema[f'ADX_{adx_period}'].iloc[-1]:.2f}, DI+={adx_ema[f'DMP_{adx_period}'].iloc[-1]:.2f}, DI-={adx_ema[f'DMN_{adx_period}'].iloc[-1]:.2f}")
            logger.info(f"3️⃣ SMA (простой): ADX={adx_sma[f'ADX_{adx_period}'].iloc[-1]:.2f}, DI+={adx_sma[f'DMP_{adx_period}'].iloc[-1]:.2f}, DI-={adx_sma[f'DMN_{adx_period}'].iloc[-1]:.2f}")
            logger.info(f"4️⃣ WMA (взвешен): ADX={adx_wma[f'ADX_{adx_period}'].iloc[-1]:.2f}, DI+={adx_wma[f'DMP_{adx_period}'].iloc[-1]:.2f}, DI-={adx_wma[f'DMN_{adx_period}'].iloc[-1]:.2f}")
            logger.info(f"🎯 Используем RMA: ADX={last_row['adx']:.2f}, DI+={last_row['di_plus']:.2f}, DI-={last_row['di_minus']:.2f}")
            logger.info("=== Какой ближе к графику? ===")
            
            return {
                'current_price': last_row['close'],
                'ema20': last_row['ema20'],
                'adx': last_row['adx'],
                'di_plus': last_row['di_plus'],
                'di_minus': last_row['di_minus']
            }
            
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

<i>Бот предоставляет информацию о цене, EMA20, ADX, DI+ и DI-</i>"""
    
    await update.message.reply_text(welcome_message, parse_mode='HTML')


async def sber_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /sber"""
    # Отправляем сообщение о загрузке
    loading_message = await update.message.reply_text('⏳ Получаю данные по SBER...')
    
    try:
        # Получаем данные
        sber_data = await get_sber_data()
        
        if not sber_data:
            await loading_message.edit_text('❌ Не удалось получить данные по SBER. Попробуйте позже.')
            return
        
        # Проверяем на NaN значения
        if (pd.isna(sber_data['ema20']) or 
            pd.isna(sber_data['adx']) or 
            pd.isna(sber_data['di_plus']) or 
            pd.isna(sber_data['di_minus'])):
            await loading_message.edit_text('❌ Недостаточно данных для расчета индикаторов. Попробуйте позже.')
            return
        
        # Форматируем и отправляем результат
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
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("sber", sber_command))
    
    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("🤖 SBER Telegram Bot started...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
