from models import StockData
from config import ADX_STRONG_TREND_THRESHOLD, SUPPORTED_STOCKS


class MessageFormatter:
    """Класс для форматирования сообщений"""
    
    @staticmethod
    def format_stock_message(data: StockData) -> str:
        """Форматирование сообщения с данными акции"""
        
        adx_strength = "Сильный тренд" if data.technical.adx > ADX_STRONG_TREND_THRESHOLD else "Слабый тренд"
        
        message = f"""{data.info.emoji} <b>{data.info.ticker} - {data.info.name}</b>

💰 <b>Цена:</b> {data.price.current_price:.2f} ₽
📊 <b>EMA20:</b> {data.technical.ema20:.2f} ₽

📈 <b>ADX:</b> {data.technical.adx:.2f} ({adx_strength})
<b>DI+:</b> {data.technical.di_plus:.2f} | <b>DI-:</b> {data.technical.di_minus:.2f}"""
        
        return message
    
    @staticmethod
    def format_welcome_message() -> str:
        """Приветственное сообщение"""
        return """👋 Привет! Я Ревущий котёнок, буду присылать тебе сигналы о трендовых движениях рынка акций 🐱

📊 <b>Доступные команды:</b>
/stocks - Выбрать акцию для анализа"""
    
    @staticmethod
    def format_stocks_selection() -> str:
        """Сообщение для выбора акции"""
        return "📈 Выберите акцию для анализа:"
    
    @staticmethod
    def format_error_message(error_type: str = "general") -> str:
        """Сообщения об ошибках"""
        error_messages = {
            "no_data": "❌ Не удалось получить данные. Попробуйте позже.",
            "insufficient_data": "❌ Недостаточно данных для расчета индикаторов. Попробуйте позже.",
            "general": "❌ Произошла ошибка при получении данных."
        }
        return error_messages.get(error_type, error_messages["general"])
    
    @staticmethod
    def format_loading_message(ticker: str = None) -> str:
        """Сообщение загрузки"""
        if ticker:
            return f"⏳ Получаю данные {ticker}..."
        return "⏳ Получаю данные..."
