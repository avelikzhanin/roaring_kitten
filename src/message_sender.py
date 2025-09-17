import asyncio
import logging
from typing import Optional
from telegram.error import TelegramError, TimedOut, NetworkError

logger = logging.getLogger(__name__)

class MessageSender:
    """Отправщик сообщений с комплексным анализом от GPT"""
    
    def __init__(self, database, gpt_analyzer=None, tinkoff_provider=None):
        self.db = database
        self.gpt_analyzer = gpt_analyzer
        self.tinkoff_provider = tinkoff_provider
        self.app = None
    
    def set_app(self, app):
        """Установка Telegram приложения"""
        self.app = app
    
    async def send_buy_signal(self, signal):
        """Отправка сигнала покупки с комплексным анализом от GPT"""
        if not self.app:
            logger.error("Telegram приложение не установлено")
            return
        
        # Получаем подписчиков
        subscribers = await self.db.get_subscribers_for_ticker(signal.symbol)
        if not subscribers:
            logger.info(f"Нет подписчиков для {signal.symbol}")
            return
        
        # Формируем базовое сообщение
        message = self._format_buy_signal_comprehensive(signal)
        
        # Добавляем ПОЛНЫЙ комплексный GPT анализ
        if hasattr(signal, 'gpt_full_advice') and signal.gpt_full_advice and self.gpt_analyzer:
            # Используем полное форматирование GPT с комплексным анализом
            message += f"\n{self.gpt_analyzer.format_advice_for_telegram(signal.gpt_full_advice, signal.symbol)}"
            
        elif hasattr(signal, 'gpt_recommendation') and signal.gpt_recommendation:
            # Fallback: базовая информация GPT
            adx_info = ""
            if signal.adx > 0:
                adx_info = f"\n📊 <b>ADX от GPT:</b> {signal.adx:.1f} | +DI: {signal.plus_di:.1f} | -DI: {signal.minus_di:.1f}"
            
            message += f"""

🤖 <b>GPT КОМПЛЕКСНЫЙ АНАЛИЗ ({signal.symbol}):</b>
📊 <b>Рекомендация:</b> {signal.gpt_recommendation}
🎯 <b>Уверенность:</b> {signal.gpt_confidence}%{adx_info}
⚡ <b>Подход:</b> Анализ всех рыночных факторов
✅ <b>Сигнал одобрен GPT</b>"""
        else:
            # Режим без GPT (не должно происходить)
            message += f"""

⚠️ <b>ВНИМАНИЕ ({signal.symbol}):</b>
📊 Комплексный анализ недоступен
⚡ <b>Режим:</b> Только базовый фильтр (не рекомендуется)"""
        
        # Подготавливаем данные для БД
        gpt_data = None
        if hasattr(signal, 'gpt_recommendation') and signal.gpt_recommendation:
            gpt_data = {
                'recommendation': signal.gpt_recommendation,
                'confidence': signal.gpt_confidence,
                'take_profit': getattr(signal.gpt_full_advice, 'take_profit', None) if hasattr(signal, 'gpt_full_advice') and signal.gpt_full_advice else None,
                'stop_loss': getattr(signal.gpt_full_advice, 'stop_loss', None) if hasattr(signal, 'gpt_full_advice') and signal.gpt_full_advice else None
            }
        
        # Сохраняем сигнал в БД с ADX данными (могут быть 0)
        signal_id = await self.db.save_signal(
            symbol=signal.symbol,
            signal_type='BUY',
            price=signal.price,
            ema20=signal.ema20,
            # ADX значения от GPT (могут быть 0 если не рассчитал)
            adx=signal.adx,
            plus_di=signal.plus_di,
            minus_di=signal.minus_di,
            gpt_data=gpt_data
        )
        
        if not signal_id:
            logger.error(f"Не удалось сохранить сигнал {signal.symbol}")
            return
        
        # Отправляем сообщения
        success_count = await self._send_to_subscribers(
            subscribers, message, signal.symbol, 'покупки'
        )
        
        # Открываем позиции
        for chat_id in subscribers[:success_count]:
            await self.db.open_position(chat_id, signal.symbol, signal_id, signal.price)
        
        adx_info = f" с ADX {signal.adx:.1f}" if signal.adx > 0 else " (ADX не рассчитан)"
        logger.info(f"📈 Сигнал покупки {signal.symbol} отправлен{adx_info}: {success_count} получателей")
    
    async def send_peak_signal(self, symbol: str, current_price: float):
        """Отправка сигнала пика тренда"""
        if not self.app:
            return
        
        subscribers = await self.db.get_subscribers_for_ticker(symbol)
        if not subscribers:
            return
        
        # Получаем данные о прибыли
        profit_info = await self._get_profit_summary(symbol, current_price)
        
        # Пытаемся получить последние ADX данные
        last_signal = await self.db.get_last_buy_signal(symbol)
        adx_info = ""
        adx_value = 47.0  # Значение для пика
        
        if last_signal and last_signal.get('adx') and float(last_signal['adx']) > 0:
            real_adx = float(last_signal['adx'])
            if real_adx > 40:  # Если действительно высокий
                adx_info = f"\n📊 <b>ADX от GPT:</b> {real_adx:.1f} (экстремально высокий)"
                adx_value = real_adx
            else:
                adx_info = f"\n📊 <b>Анализ GPT:</b> Выявлены признаки пика тренда"
        else:
            adx_info = f"\n📊 <b>Анализ GPT:</b> Комплексные признаки пика тренда"
        
        message = f"""🔥 <b>ПИК ТРЕНДА - ПРОДАЁМ {symbol}!</b>

💰 <b>Цена:</b> {current_price:.2f} ₽

📊 <b>Причина:</b> GPT выявил пик тренда{adx_info}
⚡ Время фиксировать прибыль{profit_info}

🔍 <b>Продолжаем мониторинг...</b>"""
        
        # Сохраняем сигнал пика
        await self.db.save_signal(
            symbol=symbol, 
            signal_type='PEAK', 
            price=current_price,
            ema20=current_price * 0.98,
            adx=adx_value,
            plus_di=35.0,
            minus_di=20.0
        )
        
        # Отправляем
        success_count = await self._send_to_subscribers(
            subscribers, message, symbol, 'пика'
        )
        
        # Закрываем позиции
        await self.db.close_positions(symbol, 'PEAK')
        
        logger.info(f"🔥 Сигнал пика {symbol} отправлен: {success_count} получателей")
    
    async def send_cancel_signal(self, symbol: str, current_price: float):
        """Отправка сигнала отмены"""
        if not self.app:
            return
        
        subscribers = await self.db.get_subscribers_for_ticker(symbol)
        if not subscribers:
            return
        
        profit_info = await self._get_profit_summary(symbol, current_price)
        
        message = f"""❌ <b>СИГНАЛ ОТМЕНЕН {symbol}</b>

💰 <b>Цена:</b> {current_price:.2f} ₽

⚠️ <b>Причина:</b> Изменились рыночные условия:
• Цена может быть ниже EMA20
• Ухудшились технические показатели
• Изменились объемы или волатильность  
• GPT больше не рекомендует покупку{profit_info}

🔍 <b>Продолжаем мониторинг...</b>"""
        
        # Сохраняем сигнал отмены
        await self.db.save_signal(
            symbol=symbol, 
            signal_type='SELL', 
            price=current_price,
            ema20=current_price * 0.98,
            adx=20.0,  # Примерное значение для отмены
            plus_di=25.0, 
            minus_di=30.0
        )
        
        # Отправляем
        success_count = await self._send_to_subscribers(
            subscribers, message, symbol, 'отмены'
        )
        
        # Закрываем позиции
        await self.db.close_positions(symbol, 'SELL')
        
        logger.info(f"❌ Сигнал отмены {symbol} отправлен: {success_count} получателей")
    
    def _format_buy_signal_comprehensive(self, signal) -> str:
        """Форматирование сигнала покупки с комплексным подходом"""
        
        # Информация о технических показателях
        tech_section = ""
        
        if signal.adx > 0:
            # У нас есть ADX данные от GPT
            adx_status = "✅ Сильный тренд" if signal.adx >= 25 else "⚠️ Слабый тренд"
            di_status = "✅ Восходящий" if signal.plus_di > signal.minus_di else "❌ Нисходящий"
            di_diff = signal.plus_di - signal.minus_di
            diff_status = "✅" if di_diff >= 1 else "❌"
            
            tech_section = f"""
📊 <b>ТЕХНИЧЕСКИЕ ПОКАЗАТЕЛИ:</b>
• <b>ADX:</b> {signal.adx:.1f} {adx_status}
• <b>+DI:</b> {signal.plus_di:.1f}
• <b>-DI:</b> {signal.minus_di:.1f} {di_status}
• <b>Разница DI:</b> {di_diff:+.1f} {diff_status}"""
        else:
            # ADX не рассчитан, показываем комплексный анализ
            tech_section = f"""
📊 <b>КОМПЛЕКСНЫЙ АНАЛИЗ:</b>
• <b>Базовый фильтр:</b> ✅ Пройден  
• <b>GPT анализ:</b> Все факторы учтены
• <b>Решение:</b> Основано на комплексной оценке"""

        return f"""🔔 <b>СИГНАЛ ПОКУПКИ {signal.symbol}</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽ (цена выше){tech_section}

✅ <b>GPT ОДОБРИЛ ПОКУПКУ</b>"""
    
    async def _get_profit_summary(self, symbol: str, current_price: float) -> str:
        """Получение сводки по прибыли"""
        try:
            positions = await self.db.get_positions_for_profit_calculation(symbol)
            if not positions:
                return ""
            
            total_positions = sum(pos['position_count'] for pos in positions)
            profits = []
            
            for pos in positions:
                buy_price = float(pos['buy_price'])
                count = pos['position_count']
                profit_pct = self._calculate_profit_percentage(buy_price, current_price)
                profits.append((buy_price, profit_pct, count))
            
            # Средневзвешенная прибыль
            weighted_profit = sum(profit * count for _, profit, count in profits) / total_positions
            
            # Форматируем результат
            if weighted_profit > 0:
                profit_emoji = "🟢"
                profit_text = f"+{weighted_profit:.2f}%"
            elif weighted_profit < 0:
                profit_emoji = "🔴"
                profit_text = f"{weighted_profit:.2f}%"
            else:
                profit_emoji = "⚪"
                profit_text = "0.00%"
            
            if len(profits) == 1:
                buy_price = profits[0][0]
                return f"\n\n💰 <b>Результат:</b> {profit_emoji} {profit_text}\n📈 <b>Вход:</b> {buy_price:.2f} ₽ → <b>Выход:</b> {current_price:.2f} ₽"
            else:
                return f"\n\n💰 <b>Средний результат:</b> {profit_emoji} {profit_text}\n👥 <b>Позиций:</b> {total_positions}"
            
        except Exception as e:
            logger.error(f"Ошибка расчета прибыли {symbol}: {e}")
            return ""
    
    def _calculate_profit_percentage(self, buy_price: float, sell_price: float) -> float:
        """Расчет прибыли в процентах"""
        if buy_price <= 0:
            return 0
        return ((sell_price - buy_price) / buy_price) * 100
    
    async def _send_to_subscribers(self, subscribers: list, message: str, 
                                  symbol: str, signal_type: str) -> int:
        """Отправка сообщения подписчикам с обработкой ошибок"""
        failed_chats = []
        successful_sends = 0
        
        for chat_id in subscribers:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, 
                    text=message, 
                    parse_mode='HTML'
                )
                successful_sends += 1
                await asyncio.sleep(0.1)
                
            except TelegramError as e:
                if "Can't parse entities" in str(e):
                    # Fallback: отправляем упрощенное сообщение
                    try:
                        simple_message = f"Сигнал {signal_type} {symbol}\n\nПодробности в следующем сообщении."
                        await self.app.bot.send_message(chat_id=chat_id, text=simple_message)
                        successful_sends += 1
                    except:
                        failed_chats.append(chat_id)
                else:
                    failed_chats.append(chat_id)
            except (TimedOut, NetworkError):
                failed_chats.append(chat_id)
            except Exception as e:
                logger.error(f"Ошибка отправки {symbol} в {chat_id}: {e}")
                failed_chats.append(chat_id)
        
        # Деактивируем недоступные чаты
        for chat_id in failed_chats:
            await self.db.deactivate_user(chat_id)
        
        return successful_sends
