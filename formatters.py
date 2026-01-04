# -*- coding: utf-8 -*-
from typing import List, Dict, Any
from datetime import datetime

from models import StockData, Signal
from config import SUPPORTED_STOCKS


class MessageFormatter:
    """Форматирование сообщений для пользователей"""
    
    @staticmethod
    def format_stock_message(stock_data: StockData) -> str:
        """Форматирование информации об акции"""
        stock_info = SUPPORTED_STOCKS.get(stock_data.info.ticker, {})
        stock_name = stock_info.get('name', stock_data.info.ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        long_signal = stock_data.signals.get('LONG')
        
        signal_emoji = {
            'BUY': '🟢',
            'SELL': '🔴',
            'NONE': '⚪'
        }
        
        long_emoji = signal_emoji.get(long_signal.signal_type.value, '⚪')
        long_text = long_signal.signal_type.value
        
        message = (
            f"{stock_emoji} <b>{stock_data.info.ticker} - {stock_name}</b>\n\n"
            f"💰 <b>Цена:</b> {stock_data.price.current_price:.2f} ₽\n\n"
            f"📈 <b>Индикаторы:</b>\n"
            f"• ADX: {stock_data.technical.adx:.2f}\n"
            f"• DI+: {stock_data.technical.di_plus:.2f}\n"
            f"• DI-: {stock_data.technical.di_minus:.2f}\n\n"
            f"🎯 <b>Сигнал LONG:</b> {long_emoji} {long_text}\n\n"
            f"📋 <b>Условия LONG:</b>\n"
            f"✅ ВХОД LONG: ADX > 25 AND DI- > 25\n"
            f"✅ ВЫХОД LONG: ADX > 25 AND DI+ > 25\n"
            f"🛑 STOP LOSS: -5% от цены входа\n"
            f"📊 ДОЛИВКИ: -2% и -4% от цены входа"
        )
        
        return message
    
    @staticmethod
    def format_long_buy_signal_notification(
        signal: Signal,
        stock_name: str,
        stock_emoji: str,
        lots: int,
        gpt_analysis: str = None
    ) -> str:
        """Уведомление о сигнале на покупку (открытие LONG)"""
        message = (
            f"🟢 <b>СИГНАЛ НА ПОКУПКУ (LONG)!</b>\n\n"
            f"{stock_emoji} <b>{signal.ticker} - {stock_name}</b>\n\n"
            f"💰 <b>Цена входа:</b> {signal.price:.2f} ₽\n"
            f"📦 <b>Лотов:</b> {lots:,}\n\n"
            f"📈 <b>Индикаторы:</b>\n"
            f"• ADX: {signal.adx:.2f}\n"
            f"• DI+: {signal.di_plus:.2f}\n"
            f"• DI-: {signal.di_minus:.2f}"
        )
        
        if gpt_analysis:
            import html
            gpt_analysis_escaped = html.escape(gpt_analysis)
            message += f"\n\n🤖 <b>GPT АНАЛИЗ:</b>\n{gpt_analysis_escaped}"
        
        message += "\n\n✅ Рекомендуется открыть LONG позицию!"
        
        return message
    
    @staticmethod
    def format_long_sell_signal_notification(
        signal: Signal, 
        stock_name: str, 
        stock_emoji: str,
        entry_price: float,
        average_price: float,
        profit_percent: float,
        lots: int,
        averaging_count: int,
        gpt_analysis: str = None
    ) -> str:
        """Уведомление о сигнале на продажу (закрытие LONG)"""
        profit_emoji = "📈" if profit_percent > 0 else "📉"
        profit_sign = "+" if profit_percent > 0 else ""
        
        message = (
            f"🔴 <b>СИГНАЛ НА ПРОДАЖУ (LONG)!</b>\n\n"
            f"{stock_emoji} <b>{signal.ticker} - {stock_name}</b>\n\n"
            f"💰 <b>Цена выхода:</b> {signal.price:.2f} ₽\n"
            f"💵 <b>Цена входа:</b> {entry_price:.2f} ₽\n"
            f"📊 <b>Средняя цена:</b> {average_price:.2f} ₽\n"
            f"📦 <b>Лотов:</b> {lots:,}\n"
        )
        
        if averaging_count > 0:
            message += f"🔄 <b>Доливок:</b> {averaging_count}\n"
        
        message += (
            f"\n{profit_emoji} <b>Прибыль:</b> {profit_sign}{profit_percent:.2f}%\n\n"
            f"📈 <b>Индикаторы:</b>\n"
            f"• ADX: {signal.adx:.2f}\n"
            f"• DI+: {signal.di_plus:.2f}\n"
            f"• DI-: {signal.di_minus:.2f}"
        )

        if gpt_analysis:
            import html
            gpt_analysis_escaped = html.escape(gpt_analysis)
            message += f"\n\n🤖 <b>GPT АНАЛИЗ:</b>\n{gpt_analysis_escaped}"
        
        message += "\n\n✅ LONG позиция закрыта!"
        
        return message
    
    @staticmethod
    def format_averaging_notification(
        signal: Signal,
        stock_name: str,
        stock_emoji: str,
        entry_price: float,
        current_price: float,
        add_lots: int,
        total_lots: int,
        new_average_price: float,
        averaging_number: int,
        gpt_analysis: str = None
    ) -> str:
        """Уведомление о доливке позиции"""
        drop_percent = ((current_price - entry_price) / entry_price) * 100
        
        message = (
            f"🔄 <b>ДОЛИВКА #{averaging_number}!</b>\n\n"
            f"{stock_emoji} <b>{signal.ticker} - {stock_name}</b>\n\n"
            f"💰 <b>Цена доливки:</b> {current_price:.2f} ₽\n"
            f"💵 <b>Цена входа:</b> {entry_price:.2f} ₽\n"
            f"📉 <b>Просадка:</b> {drop_percent:.2f}%\n\n"
            f"📦 <b>Добавлено лотов:</b> {add_lots:,}\n"
            f"📦 <b>Всего лотов:</b> {total_lots:,}\n"
            f"📊 <b>Новая средняя цена:</b> {new_average_price:.2f} ₽\n\n"
            f"📈 <b>Индикаторы:</b>\n"
            f"• ADX: {signal.adx:.2f}\n"
            f"• DI+: {signal.di_plus:.2f}\n"
            f"• DI-: {signal.di_minus:.2f}"
        )
        
        if gpt_analysis:
            import html
            gpt_analysis_escaped = html.escape(gpt_analysis)
            message += f"\n\n🤖 <b>GPT АНАЛИЗ:</b>\n{gpt_analysis_escaped}"
        
        message += "\n\n✅ Позиция увеличена (усреднение)!"
        
        return message
    
    @staticmethod
    def format_stop_loss_notification(
        signal: Signal,
        stock_name: str,
        stock_emoji: str,
        entry_price: float,
        average_price: float,
        profit_percent: float,
        stop_loss_price: float,
        lots: int,
        averaging_count: int
    ) -> str:
        """Уведомление о срабатывании Stop Loss"""
        message = (
            f"🛑 <b>STOP LOSS!</b>\n\n"
            f"{stock_emoji} <b>{signal.ticker} - {stock_name}</b>\n\n"
            f"💰 <b>Цена выхода:</b> {signal.price:.2f} ₽\n"
            f"💵 <b>Цена входа:</b> {entry_price:.2f} ₽\n"
            f"📊 <b>Средняя цена:</b> {average_price:.2f} ₽\n"
            f"🛑 <b>Stop Loss:</b> {stop_loss_price:.2f} ₽\n"
            f"📦 <b>Лотов:</b> {lots:,}\n"
        )
        
        if averaging_count > 0:
            message += f"🔄 <b>Доливок было:</b> {averaging_count}\n"
        
        message += (
            f"\n📉 <b>Убыток:</b> {profit_percent:.2f}%\n\n"
            f"📈 <b>Индикаторы:</b>\n"
            f"• ADX: {signal.adx:.2f}\n"
            f"• DI+: {signal.di_plus:.2f}\n"
            f"• DI-: {signal.di_minus:.2f}\n\n"
            f"⚠️ LONG позиция закрыта по Stop Loss"
        )
        
        return message
    
    @staticmethod
    def format_welcome_message() -> str:
        """Приветственное сообщение"""
        message = (
            "👋 Привет! Я Ревущий котёнок, буду присылать тебе сигналы о трендовых движениях рынка акций 🐱\n\n"
            "💡 <b>Как это работает:</b>\n"
            "• Выбери акции для анализа\n"
            "• Подпишись на уведомления (⭐)\n"
            "• Получай автоматические сигналы на вход/выход (LONG)\n"
            "• Отслеживай прибыль по сделкам\n\n"
            "💰 <b>Мани-менеджмент:</b>\n"
            "• Риск на сделку: 5% от депозита\n"
            "• Stop Loss: -5% от цены входа\n"
            "• Доливки: -2% и -4% от цены входа\n\n"
            "Выбери действие из меню ниже 👇"
        )
        return message
    
    @staticmethod
    def format_stocks_selection() -> str:
        """Сообщение для выбора акции"""
        return "📈 Выберите акцию для анализа:\n\n⭐ - подписка активна"
    
    @staticmethod
    def format_loading_message() -> str:
        """Сообщение о загрузке данных"""
        return "⏳ Загружаю данные..."
    
    @staticmethod
    def format_positions_list(
        open_positions: List[Dict[str, Any]], 
        closed_positions: List[Dict[str, Any]],
        current_prices: Dict[str, float] = None
    ) -> str:
        """Список позиций пользователя"""
        if not open_positions and not closed_positions:
            return "📭 У вас пока нет открытых или закрытых позиций"
        
        message = ""
        
        if open_positions:
            message += "📊 <b>Открытые позиции:</b>\n\n"
            for pos in open_positions:
                ticker = pos['ticker']
                position_type = pos['position_type']
                entry_price = float(pos['entry_price'])
                # Если average_price None (старая позиция), используем entry_price
                average_price = float(pos['average_price']) if pos['average_price'] is not None else entry_price
                entry_time = pos['entry_time']
                lots = pos.get('lots', 0)
                averaging_count = pos.get('averaging_count', 0)
                
                stock_info = SUPPORTED_STOCKS.get(ticker, {})
                stock_name = stock_info.get('name', ticker)
                stock_emoji = stock_info.get('emoji', '📊')
                
                current_price = None
                profit_percent = 0.0
                
                if current_prices and ticker in current_prices:
                    current_price = current_prices[ticker]
                    if position_type == 'LONG':
                        profit_percent = ((current_price - average_price) / average_price) * 100
                    elif position_type == 'SHORT':
                        profit_percent = ((average_price - current_price) / average_price) * 100
                
                profit_emoji = "📈" if profit_percent > 0 else "📉"
                profit_sign = "+" if profit_percent > 0 else ""
                
                type_emoji = "🟢" if position_type == 'LONG' else "🔴"
                
                message += (
                    f"{stock_emoji} <b>{ticker} - {stock_name}</b> {type_emoji}\n"
                    f"💵 Вход: {entry_price:.2f} ₽\n"
                    f"📊 Средняя: {average_price:.2f} ₽\n"
                    f"📦 Лотов: {lots:,}\n"
                )
                
                if averaging_count > 0:
                    message += f"🔄 Доливок: {averaging_count}\n"
                
                if current_price:
                    message += (
                        f"💰 Сейчас: {current_price:.2f} ₽\n"
                        f"{profit_emoji} P&L: {profit_sign}{profit_percent:.2f}%\n"
                    )
                
                if isinstance(entry_time, str):
                    entry_time = datetime.fromisoformat(entry_time)
                message += f"🕐 Открыто: {entry_time.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        if closed_positions:
            message += "\n📜 <b>Последние закрытые позиции:</b>\n\n"
            for pos in closed_positions[:10]:
                ticker = pos['ticker']
                position_type = pos['position_type']
                entry_price = float(pos['entry_price'])
                # Если average_price None (старая позиция), используем entry_price
                average_price = float(pos['average_price']) if pos['average_price'] is not None else entry_price
                exit_price = float(pos['exit_price'])
                profit_percent = float(pos['profit_percent'])
                exit_time = pos['exit_time']
                lots = pos.get('lots', 0)
                averaging_count = pos.get('averaging_count', 0)
                
                stock_info = SUPPORTED_STOCKS.get(ticker, {})
                stock_name = stock_info.get('name', ticker)
                stock_emoji = stock_info.get('emoji', '📊')
                
                profit_emoji = "📈" if profit_percent > 0 else "📉"
                profit_sign = "+" if profit_percent > 0 else ""
                
                type_emoji = "🟢" if position_type == 'LONG' else "🔴"
                
                message += (
                    f"{stock_emoji} <b>{ticker} - {stock_name}</b> {type_emoji}\n"
                    f"💵 Вход: {entry_price:.2f} ₽ → Выход: {exit_price:.2f} ₽\n"
                    f"📊 Средняя: {average_price:.2f} ₽\n"
                    f"📦 Лотов: {lots:,}\n"
                )
                
                if averaging_count > 0:
                    message += f"🔄 Доливок: {averaging_count}\n"
                
                message += f"{profit_emoji} P&L: {profit_sign}{profit_percent:.2f}%\n"
                
                if isinstance(exit_time, str):
                    exit_time = datetime.fromisoformat(exit_time)
                message += f"🕐 Закрыто: {exit_time.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        return message
    
    @staticmethod
    def format_subscription_status(ticker: str, is_subscribed: bool) -> str:
        """Статус подписки на акцию"""
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        stock_name = stock_info.get('name', ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        if is_subscribed:
            return f"✅ Вы подписались на уведомления {stock_emoji} <b>{ticker} - {stock_name}</b>"
        else:
            return f"❌ Вы отписались от уведомлений {stock_emoji} <b>{ticker} - {stock_name}</b>"
    
    @staticmethod
    def format_error_message(error_text: str) -> str:
        """Сообщение об ошибке"""
        return f"❌ <b>Ошибка:</b> {error_text}"
    
    @staticmethod
    def format_help_message() -> str:
        """Справочное сообщение"""
        message = (
            "📚 <b>Справка по боту</b>\n\n"
            "🤖 <b>Команды:</b>\n"
            "/start - Главное меню\n"
            "/positions - Мои позиции\n"
            "/help - Эта справка\n\n"
            "📊 <b>Логика сигналов LONG:</b>\n"
            "✅ ВХОД LONG: ADX > 25 AND DI- > 25\n"
            "   (входим при сильной коррекции вниз)\n\n"
            "✅ ВЫХОД LONG: ADX > 25 AND DI+ > 25\n"
            "   (выходим при развороте вверх)\n\n"
            "🛑 STOP LOSS: -5% от цены входа\n"
            "   (защита от больших убытков)\n\n"
            "🔄 ДОЛИВКИ:\n"
            "   • Первая доливка: -2% от цены входа\n"
            "   • Вторая доливка: -4% от цены входа\n"
            "   • Объем доливки = объему первоначальной позиции\n\n"
            "💰 <b>Мани-менеджмент:</b>\n"
            "   • Депозит: 10,000,000 ₽\n"
            "   • Риск на сделку: 5% (500,000 ₽)\n"
            "   • Размер позиции рассчитывается так,\n"
            "     чтобы при Stop Loss потеря = 500,000 ₽\n\n"
            "📈 <b>Доступные акции:</b>\n"
            "🏦 SBER - Сбербанк (лот = 10 акций)\n"
            "🛢️ GAZP - Газпром (лот = 10 акций)\n"
            "⛽ LKOH - ЛУКОЙЛ (лот = 1 акция)\n"
            "🏛️ VTBR - ВТБ (лот = 100 акций)\n"
            "🧑‍💼 HEAD - Headhunter (лот = 1 акция)\n\n"
            "💡 <b>Как использовать:</b>\n"
            "1. Подпишитесь на интересующие акции\n"
            "2. Получайте автоматические уведомления о сигналах\n"
            "3. Торгуйте по сигналам или используйте их как подсказки\n"
            "4. Отслеживайте прибыль в разделе 'Мои позиции'\n\n"
            "⚠️ <b>Важно:</b> Это не инвестиционная рекомендация. "
            "Торговля акциями связана с рисками."
        )
        return message
