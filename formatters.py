from models import StockData
from config import ADX_STRONG_TREND_THRESHOLD


class MessageFormatter:
    """Класс для форматирования сообщений"""
    
    @staticmethod
    def format_stock_message(data: StockData) -> str:
        """Форматирование сообщения с данными акции - показываем ДВА варианта ADX"""
        
        # Определяем силу тренда для двух вариантов
        adx_standard_strength = "Сильный тренд" if data.technical.adx_standard > ADX_STRONG_TREND_THRESHOLD else "Слабый тренд"
        adx_pine_strength = "Сильный тренд" if data.technical.adx_pinescript > ADX_STRONG_TREND_THRESHOLD else "Слабый тренд"
        
        message = f"""{data.info.emoji} <b>{data.info.ticker} - {data.info.name}</b>

💰 <b>Цена:</b> {data.price.current_price:.2f} ₽
📊 <b>EMA20:</b> {data.technical.ema20:.2f} ₽

🔧 <b>ADX — pandas-ta (RMA):</b>
- <b>ADX:</b> {data.technical.adx_standard:.2f} ({adx_standard_strength})
- <b>DI+:</b> {data.technical.di_plus_standard:.2f} | <b>DI-:</b> {data.technical.di_minus_standard:.2f}

📈 <b>ADX — Pine Script (sma):</b>
- <b>ADX:</b> {data.technical.adx_pinescript:.2f} ({adx_pine_strength})
- <b>DI+:</b> {data.technical.di_plus_pinescript:.2f} | <b>DI-:</b> {data.technical.di_minus_pinescript:.2f}"""
        
        return message
    
    @staticmethod
    def format_welcome_message() -> str:
        """Приветственное сообщение"""
        return """👋 Привет! Я бот для мониторинга акций SBER.

📊 <b>Доступные команды:</b>
/sber - Получить актуальные данные по Сбербанку

<i>Данные получаются напрямую с Московской биржи через MOEX API</i>"""
    
    @staticmethod
    def format_error_message(error_type: str = "general") -> str:
        """Сообщения об ошибках"""
        error_messages = {
            "no_data": "❌ Не удалось получить данные с MOEX API. Попробуйте позже.",
            "insufficient_data": "❌ Недостаточно данных для расчета индикаторов. Попробуйте позже.",
            "general": "❌ Произошла ошибка при получении данных."
        }
        return error_messages.get(error_type, error_messages["general"])
    
    @staticmethod
    def format_loading_message() -> str:
        """Сообщение загрузки"""
        return "⏳ Получаю данные с MOEX..."
