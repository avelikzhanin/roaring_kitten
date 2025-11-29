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
        
        # Определяем направление тренда по EMA
        price_vs_ema = data.price.current_price - data.technical.ema20
        price_vs_ema_percent = (price_vs_ema / data.technical.ema20) * 100
        
        if data.price.current_price > data.technical.ema20:
            trend_emoji = "📈"
            trend_text = f"Цена выше EMA20 ({price_vs_ema_percent:+.2f}%)"
        else:
            trend_emoji = "📉"
            trend_text = f"Цена ниже EMA20 ({price_vs_ema_percent:+.2f}%)"
        
        # Проверяем условия для входа и выхода LONG
        long_entry_conditions = data.technical.adx > ADX_THRESHOLD and data.technical.di_minus > ADX_THRESHOLD
        long_exit_conditions = data.technical.adx > ADX_THRESHOLD and data.technical.di_plus > ADX_THRESHOLD
        
        signal_text = ""
        if long_entry_conditions:
            signal_text += f"✅ ВХОД LONG: ADX > {ADX_THRESHOLD} AND DI- > {ADX_THRESHOLD}\n"
        else:
            signal_text += f"❌ ВХОД LONG: Условия не выполнены\n"
        
        if long_exit_conditions:
            signal_text += f"✅ ВЫХОД LONG: ADX > {ADX_THRESHOLD} AND DI+ > {ADX_THRESHOLD}\n"
        else:
            signal_text += f"❌ ВЫХОД LONG: Условия не выполнены\n"
        
        signal_text += "\nПри подписке получите уведомление"
        
        subscription_status = "⭐ Подписка активна" if is_subscribed else ""
        
        message = f"""{data.info.emoji} <b>{data.info.ticker} - {data.info.name}</b>

💰 <b>Цена:</b> {data.price.current_price:.2f} ₽
📊 <b>EMA20:</b> {data.technical.ema20:.2f} ₽
{trend_emoji} {trend_text}

📈 <b>Индикаторы:</b>
• ADX: {data.technical.adx:.2f} ({adx_strength})
• DI+: {data.technical.di_plus:.2f} | DI-: {data.technical.di_minus:.2f}

{signal_text}

{subscription_status}"""
        
        return message
    
    @staticmethod
    def format_long_buy_signal_notification(signal: Signal, stock_name: str, stock_emoji: str, gpt_analysis: str = None) -> str:
        """Уведомление о сигнале на покупку (LONG)"""
        message = f"""🔥 <b>СИГНАЛ НА ПОКУПКУ (LONG)!</b>

{stock_emoji} <b>{signal.ticker} - {stock_name}</b>

💰 <b>Цена входа:</b> {signal.price:.2f} ₽

📈 <b>Индикаторы:</b>
• ADX: {signal.adx:.2f}
• DI+: {signal.di_plus:.2f}
• DI-: {signal.di_minus:.2f}"""

        if gpt_analysis:
            import html
            gpt_analysis_escaped = html.escape(gpt_analysis)
            message += f"\n\n🤖 <b>GPT АНАЛИЗ:</b>\n{gpt_analysis_escaped}"
        
        message += "\n\n✅ LONG позиция открыта! Ждём сигнала на продажу."
        
        return message
    
    @staticmethod
    def format_long_sell_signal_notification(
        signal: Signal, 
        stock_name: str, 
        stock_emoji: str,
        entry_price: float,
        profit_percent: float,
        gpt_analysis: str = None
    ) -> str:
        """Уведомление о сигнале на продажу (закрытие LONG)"""
        profit_emoji = "📈" if profit_percent > 0 else "📉"
        profit_sign = "+" if profit_percent > 0 else ""
        
        message = f"""🔴 <b>СИГНАЛ НА ПРОДАЖУ (LONG)!</b>

{stock_emoji} <b>{signal.ticker} - {stock_name}</b>

💰 <b>Цена выхода:</b> {signal.price:.2f} ₽
💵 <b>Цена входа:</b> {entry_price:.2f} ₽

{profit_emoji} <b>Прибыль:</b> {profit_sign}{profit_percent:.2f}%

📈 <b>Индикаторы:</b>
• ADX: {signal.adx:.2f}
• DI+: {signal.di_plus:.2f}
• DI-: {signal.di_minus:.2f}"""

        if gpt_analysis:
            import html
            gpt_analysis_escaped = html.escape(gpt_analysis)
            message += f"\n\n🤖 <b>GPT АНАЛИЗ:</b>\n{gpt_analysis_escaped}"
        
        message += "\n\n✅ LONG позиция закрыта!"
        
        return message
    
    @staticmethod
    def format_stop_loss_notification(
        signal: Signal,
        stock_name: str,
        stock_emoji: str,
        entry_price: float,
        profit_percent: float,
        stop_loss_price: float
    ) -> str:
        """Уведомление о срабатывании Stop Loss"""
        message = f"""🛑 <b>STOP LOSS!</b>

{stock_emoji} <b>{signal.ticker} - {stock_name}</b>

💰 <b>Цена выхода:</b> {signal.price:.2f} ₽
💵 <b>Цена входа:</b> {entry_price:.2f} ₽
🛑 <b>Stop Loss:</b> {stop_loss_price:.2f} ₽

📉 <b>Убыток:</b> {profit_percent:.2f}%

📈 <b>Индикаторы:</b>
• ADX: {signal.adx:.2f}
• DI+: {signal.di_plus:.2f}
• DI-: {signal.di_minus:.2f}

⚠️ LONG позиция закрыта по Stop Loss</message>
        
        return message
    
    @staticmethod
    def format_welcome_message() -> str:
        """Приветственное сообщение"""
        return """👋 Привет! Я Ревущий котёнок, буду присылать тебе сигналы о трендовых движениях рынка акций 🐱

💡 <b>Как это работает:</b>
• Выбери акции для анализа
• Подпишись на уведомления (⭐)
• Получай автоматические сигналы на вход/выход (LONG)
• Отслеживай прибыль по сделкам

Выбери действие из меню ниже 👇"""
    
    @staticmethod
    def format_stocks_selection() -> str:
        """Сообщение для выбора акции"""
        return "📈 Выберите акцию для анализа:\n\n⭐ - подписка активна"
    
    @staticmethod
    def format_positions_list(
        open_positions: List[Dict[str, Any]], 
        closed_positions: List[Dict[str, Any]],
        current_prices: Dict[str, float] = None
    ) -> str:
        """Список позиций пользователя"""
        
        if not open_positions and not closed_positions:
            return "📊 У вас нет позиций."
        
        message = ""
        
        # Открытые позиции
        if open_positions:
            message += "🟢 <b>Открытые позиции:</b>\n\n"
            for pos in open_positions:
                ticker = pos['ticker']
                position_type = pos['position_type']
                stock_info = SUPPORTED_STOCKS.get(ticker, {})
                emoji = stock_info.get('emoji', '📊')
                name = stock_info.get('name', ticker)
                
                # Определяем эмодзи типа позиции
                type_emoji = "↗️" if position_type == 'LONG' else "↘️"
                
                entry_price = float(pos['entry_price'])
                current_price = current_prices.get(ticker) if current_prices else None
                
                profit_text = ""
                if current_price:
                    if position_type == 'LONG':
                        profit = ((current_price - entry_price) / entry_price) * 100
                    else:  # SHORT
                        profit = ((entry_price - current_price) / entry_price) * 100
                    
                    profit_emoji = "📈" if profit > 0 else "📉"
                    profit_sign = "+" if profit > 0 else ""
                    profit_text = f"\n  💰 Текущая: {current_price:.2f} ₽ ({profit_emoji} {profit_sign}{profit:.2f}%)"
                
                entry_time = pos['entry_time'].strftime("%d.%m.%Y %H:%M")
                
                message += f"{emoji} <b>{ticker}</b> - {name}\n"
                message += f"  {type_emoji} <b>{position_type}</b>\n"
                message += f"  📅 {entry_time}\n"
                message += f"  💵 Вход: {entry_price:.2f} ₽{profit_text}\n\n"
        
        # Закрытые позиции
        if closed_positions:
            message += "\n🔴 <b>Последние закрытые позиции:</b>\n\n"
            for pos in closed_positions:
                ticker = pos['ticker']
                position_type = pos['position_type']
                stock_info = SUPPORTED_STOCKS.get(ticker, {})
                emoji = stock_info.get('emoji', '📊')
                name = stock_info.get('name', ticker)
                
                # Определяем эмодзи типа позиции
                type_emoji = "↗️" if position_type == 'LONG' else "↘️"
                
                entry_price = float(pos['entry_price'])
                exit_price = float(pos['exit_price'])
                profit_percent = float(pos['profit_percent'])
                
                profit_emoji = "📈" if profit_percent > 0 else "📉"
                profit_sign = "+" if profit_percent > 0 else ""
                
                exit_time = pos['exit_time'].strftime("%d.%m.%Y %H:%M")
                
                message += f"{emoji} <b>{ticker}</b> - {name}\n"
                message += f"  {type_emoji} <b>{position_type}</b>\n"
                message += f"  📅 {exit_time}\n"
                message += f"  💵 {entry_price:.2f} ₽ → {exit_price:.2f} ₽\n"
                message += f"  {profit_emoji} <b>{profit_sign}{profit_percent:.2f}%</b>\n\n"
        
        return message
    
    @staticmethod
    def format_monthly_statistics(stats: Dict[str, Any], year: int, month: int) -> str:
        """Форматирование статистики за месяц"""
        # Название месяца на русском
        month_names = {
            1: "январь", 2: "февраль", 3: "март", 4: "апрель",
            5: "май", 6: "июнь", 7: "июль", 8: "август",
            9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"
        }
        month_name = month_names.get(month, "").capitalize()
        
        if stats['total_trades'] == 0:
            return f"📊 <b>СТАТИСТИКА</b>\n\nПока нет сделок за {month_name} {year}"
        
        # Процент прибыльных
        profitable_percent = (stats['profitable'] / stats['total_trades']) * 100 if stats['total_trades'] > 0 else 0
        unprofitable_percent = (stats['unprofitable'] / stats['total_trades']) * 100 if stats['total_trades'] > 0 else 0
        
        # Эмодзи для общего результата
        result_emoji = "📈" if stats['total_profit'] > 0 else "📉"
        result_sign = "+" if stats['total_profit'] > 0 else ""
        
        message = f"""📊 <b>СТАТИСТИКА ЗА {month_name.upper()} {year}:</b>

• Закрыто сделок: {stats['total_trades']}
• Прибыльных: {stats['profitable']} ({profitable_percent:.1f}%)
• Убыточных: {stats['unprofitable']} ({unprofitable_percent:.1f}%)
• Общий результат: {result_emoji} <b>{result_sign}{stats['total_profit']:.2f}%</b>"""
        
        return message
    
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
    
    @staticmethod
    def format_gpt_analysis_message(stock_data: StockData, gpt_analysis: str) -> str:
        """Форматирование сообщения с GPT анализом"""
        # Экранируем HTML спецсимволы в GPT ответе
        import html
        gpt_analysis_escaped = html.escape(gpt_analysis)
        
        return f"""🤖 <b>GPT АНАЛИЗ</b>

{stock_data.info.emoji} <b>{stock_data.info.ticker} - {stock_data.info.name}</b>

💰 <b>Цена:</b> {stock_data.price.current_price:.2f} ₽
📊 <b>EMA20:</b> {stock_data.technical.ema20:.2f} ₽

📈 <b>Индикаторы:</b>
• ADX: {stock_data.technical.adx:.2f}
• DI+: {stock_data.technical.di_plus:.2f}
• DI-: {stock_data.technical.di_minus:.2f}

━━━━━━━━━━━━━━━━

{gpt_analysis_escaped}"""
