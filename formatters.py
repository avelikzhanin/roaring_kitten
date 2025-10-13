from typing import List, Dict, Any
from datetime import datetime

from models import StockData, Signal, SignalType
from config import ADX_THRESHOLD, SUPPORTED_STOCKS


class MessageFormatter:
    """Класс для форматирования сообщений"""
    
    @staticmethod
    def format_stock_message(data: StockData, is_subscribed: bool = False) -> str:
        """Форматирование сообщения с данными акции"""
        
        adx_strength = "Сильный тренд" if data.technical.adx > ADX_THRESHOLD else "Слабый тренд"
        
        # Определяем текущий сигнал
        signal_emoji = ""
        signal_text = ""
        if data.technical.adx > ADX_THRESHOLD and data.technical.di_plus > ADX_THRESHOLD:
            signal_emoji = "🟢"
            signal_text = "BUY сигнал"
        elif data.technical.adx <= ADX_THRESHOLD or data.technical.di_plus <= ADX_THRESHOLD:
            signal_emoji = "🔴"
            signal_text = "SELL сигнал"
        
        subscription_status = "✅ Подписка активна" if is_subscribed else ""
        
        message = f"""{data.info.emoji} <b>{data.info.ticker} - {data.info.name}</b>

💰 <b>Цена:</b> {data.price.current_price:.2f} ₽
📊 <b>EMA20:</b> {data.technical.ema20:.2f} ₽

📈 <b>ADX:</b> {data.technical.adx:.2f} ({adx_strength})
<b>DI+:</b> {data.technical.di_plus:.2f} | <b>DI-:</b> {data.technical.di_minus:.2f}

{signal_emoji} <b>{signal_text}</b>
{subscription_status}"""
        
        return message
    
    @staticmethod
    def format_buy_signal_notification(signal: Signal, stock_name: str, stock_emoji: str) -> str:
        """Уведомление о сигнале на покупку"""
        return f"""🟢 <b>СИГНАЛ НА ПОКУПКУ!</b>

{stock_emoji} <b>{signal.ticker} - {stock_name}</b>

💰 <b>Цена входа:</b> {signal.price:.2f} ₽

📈 <b>Индикаторы:</b>
• ADX: {signal.adx:.2f}
• DI+: {signal.di_plus:.2f}
• DI-: {signal.di_minus:.2f}

✅ Позиция открыта! Ждём сигнала на продажу."""
    
    @staticmethod
    def format_sell_signal_notification(
        signal: Signal, 
        stock_name: str, 
        stock_emoji: str,
        entry_price: float,
        profit_percent: float
    ) -> str:
        """Уведомление о сигнале на продажу"""
        profit_emoji = "📈" if profit_percent > 0 else "📉"
        profit_sign = "+" if profit_percent > 0 else ""
        
        return f"""🔴 <b>СИГНАЛ НА ПРОДАЖУ!</b>

{stock_emoji} <b>{signal.ticker} - {stock_name}</b>

💰 <b>Цена выхода:</b> {signal.price:.2f} ₽
💵 <b>Цена входа:</b> {entry_price:.2f} ₽

{profit_emoji} <b>Прибыль:</b> {profit_sign}{profit_percent:.2f}%

📈 <b>Индикаторы:</b>
• ADX: {signal.adx:.2f}
• DI+: {signal.di_plus:.2f}
• DI-: {signal.di_minus:.2f}

✅ Позиция закрыта!"""
    
    @staticmethod
    def format_welcome_message() -> str:
        """Приветственное сообщение"""
        return """👋 Привет! Я Ревущий котёнок, буду присылать тебе сигналы о трендовых движениях рынка акций 🐱

💡 <b>Как это работает:</b>
• Выбери акции для анализа
• Подпишись на уведомления о сигналах
• Получай BUY/SELL сигналы автоматически
• Отслеживай прибыль по сделкам

🟢 <b>BUY сигнал:</b> ADX > 25 AND DI+ > 25
🔴 <b>SELL сигнал:</b> ADX ≤ 25 OR DI+ ≤ 25

Выбери действие из меню ниже 👇"""
    
    @staticmethod
    def format_stocks_selection() -> str:
        """Сообщение для выбора акции"""
        return "📈 Выберите акцию для анализа:\n\n🔔 - подписка активна"
    
    @staticmethod
    def format_subscriptions_list(subscriptions: List[str]) -> str:
        """Список подписок пользователя"""
        if not subscriptions:
            return """📭 У вас нет активных подписок.

Используйте /stocks для подписки на акции."""
        
        message = "🔔 <b>Ваши подписки:</b>\n\n"
        for ticker in subscriptions:
            stock_info = SUPPORTED_STOCKS.get(ticker, {})
            emoji = stock_info.get('emoji', '📊')
            name = stock_info.get('name', ticker)
            message += f"{emoji} <b>{ticker}</b> - {name}\n"
        
        message += "\n💡 Нажмите на акцию в /stocks чтобы отписаться"
        return message
    
    @staticmethod
    def format_positions_list(
        open_positions: List[Dict[str, Any]], 
        closed_positions: List[Dict[str, Any]],
        current_prices: Dict[str, float] = None
    ) -> str:
        """Список позиций пользователя"""
        
        if not open_positions and not closed_positions:
            return """📊 У вас нет позиций.

Подпишитесь на акции через /stocks и получайте сигналы для открытия позиций!"""
        
        message = ""
        
        # Открытые позиции
        if open_positions:
            message += "🟢 <b>Открытые позиции:</b>\n\n"
            for pos in open_positions:
                ticker = pos['ticker']
                stock_info = SUPPORTED_STOCKS.get(ticker, {})
                emoji = stock_info.get('emoji', '📊')
                name = stock_info.get('name', ticker)
                
                entry_price = float(pos['entry_price'])
                current_price = current_prices.get(ticker) if current_prices else None
                
                profit_text = ""
                if current_price:
                    profit = ((current_price - entry_price) / entry_price) * 100
                    profit_emoji = "📈" if profit > 0 else "📉"
                    profit_sign = "+" if profit > 0 else ""
                    profit_text = f"\n  💰 Текущая: {current_price:.2f} ₽ ({profit_emoji} {profit_sign}{profit:.2f}%)"
                
                entry_time = pos['entry_time'].strftime("%d.%m.%Y %H:%M")
                
                message += f"{emoji} <b>{ticker}</b> - {name}\n"
                message += f"  📅 {entry_time}\n"
                message += f"  💵 Вход: {entry_price:.2f} ₽{profit_text}\n\n"
        
        # Закрытые позиции
        if closed_positions:
            message += "\n🔴 <b>Последние закрытые позиции:</b>\n\n"
            for pos in closed_positions:
                ticker = pos['ticker']
                stock_info = SUPPORTED_STOCKS.get(ticker, {})
                emoji = stock_info.get('emoji', '📊')
                name = stock_info.get('name', ticker)
                
                entry_price = float(pos['entry_price'])
                exit_price = float(pos['exit_price'])
                profit_percent = float(pos['profit_percent'])
                
                profit_emoji = "📈" if profit_percent > 0 else "📉"
                profit_sign = "+" if profit_percent > 0 else ""
                
                exit_time = pos['exit_time'].strftime("%d.%m.%Y %H:%M")
                
                message += f"{emoji} <b>{ticker}</b> - {name}\n"
                message += f"  📅 {exit_time}\n"
                message += f"  💵 {entry_price:.2f} ₽ → {exit_price:.2f} ₽\n"
                message += f"  {profit_emoji} <b>{profit_sign}{profit_percent:.2f}%</b>\n\n"
        
        return message
    
    @staticmethod
    def format_subscription_added(ticker: str) -> str:
        """Сообщение о добавлении подписки"""
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        emoji = stock_info.get('emoji', '📊')
        name = stock_info.get('name', ticker)
        return f"✅ Вы подписались на {emoji} <b>{ticker} - {name}</b>\n\nВы будете получать уведомления о сигналах!"
    
    @staticmethod
    def format_subscription_removed(ticker: str) -> str:
        """Сообщение об удалении подписки"""
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        emoji = stock_info.get('emoji', '📊')
        name = stock_info.get('name', ticker)
        return f"🔕 Вы отписались от {emoji} <b>{ticker} - {name}</b>"
    
    @staticmethod
    def format_error_message(error_type: str = "general") -> str:
        """Сообщения об ошибках"""
        error_messages = {
            "no_data": "❌ Не удалось получить данные. Попробуйте позже.",
            "insufficient_data": "❌ Недостаточно данных для расчета индикаторов. Попробуйте позже.",
            "general": "❌ Произошла ошибка при получении данных.",
            "already_subscribed": "ℹ️ Вы уже подписаны на эту акцию.",
            "not_subscribed": "ℹ️ Вы не подписаны на эту акцию."
        }
        return error_messages.get(error_type, error_messages["general"])
    
    @staticmethod
    def format_loading_message(ticker: str = None) -> str:
        """Сообщение загрузки"""
        if ticker:
            return f"⏳ Получаю данные {ticker}..."
        return "⏳ Получаю данные..."
