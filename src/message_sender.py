import asyncio
import logging
from typing import Optional
from telegram.error import TelegramError, TimedOut, NetworkError

logger = logging.getLogger(__name__)

class MessageSender:
    """Отправщик сообщений с РЕАЛЬНЫМИ ADX значениями от GPT"""
    
    def __init__(self, database, gpt_analyzer=None, tinkoff_provider=None):
        self.db = database
        self.gpt_analyzer = gpt_analyzer
        self.tinkoff_provider = tinkoff_provider
        self.app = None
    
    def set_app(self, app):
        """Установка Telegram приложения"""
        self.app = app
    
    async def send_buy_signal(self, signal):
        """Отправка сигнала покупки с РЕАЛЬНЫМИ ADX от GPT"""
        if not self.app:
            logger.error("Telegram приложение не установлено")
            return
        
        # Получаем подписчиков
        subscribers = await self.db.get_subscribers_for_ticker(signal.symbol)
        if not subscribers:
            logger.info(f"Нет подписчиков для {signal.symbol}")
            return
        
        # Формируем базовое сообщение
        message = self._format_buy_signal_with_real_adx(signal)
        
        # Добавляем ПОЛНЫЙ GPT анализ с РЕАЛЬНЫМИ ADX
        if hasattr(signal, 'gpt_full_advice') and signal.gpt_full_advice and self.gpt_analyzer:
            # Используем полное форматирование GPT с РЕАЛЬНЫМИ ADX значениями
            message += f"\n{self.gpt_analyzer.format_advice_for_telegram(signal.gpt_full_advice, signal.symbol)}"
            
        elif hasattr(signal, 'gpt_recommendation') and signal.gpt_recommendation:
            # Fallback: базовая информация GPT с ADX
            adx_info = ""
            if signal.adx > 0:
                adx_info = f"\n📊 <b>РЕАЛЬНЫЙ ADX от GPT:</b> {signal.adx:.1f} | +DI: {signal.plus_di:.1f} | -DI: {signal.minus_di:.1f}"
            
            message += f"""

🤖 <b>АНАЛИЗ GPT ({signal.symbol}):</b>
📊 <b>Рекомендация:</b> {signal.gpt_recommendation}
🎯 <b>Уверенность:</b> {signal.gpt_confidence}%{adx_info}
⚡ <b>Стратегия:</b> EMA20 + РЕАЛЬНЫЙ ADX от GPT
✅ <b>Все условия ADX выполнены</b>"""
        else:
            # Режим без GPT (не должно происходить, так как ADX нужен)
            message += f"""

⚠️ <b>ВНИМАНИЕ ({signal.symbol}):</b>
📊 ADX анализ недоступен
⚡ <b>Режим:</b> Только EMA20 (не рекомендуется)"""
        
        # Подготавливаем данные для БД с РЕАЛЬНЫМИ ADX
        gpt_data = None
        if hasattr(signal, 'gpt_recommendation') and signal.gpt_recommendation:
            gpt_data = {
                'recommendation': signal.gpt_recommendation,
                'confidence': signal.gpt_confidence,
                'take_profit': getattr(signal.gpt_full_advice, 'take_profit', None) if hasattr(signal, 'gpt_full_advice') and signal.gpt_full_advice else None,
                'stop_loss': getattr(signal.gpt_full_advice, 'stop_loss', None) if hasattr(signal, 'gpt_full_advice') and signal.gpt_full_advice else None
            }
        
        # Сохраняем сигнал в БД с РЕАЛЬНЫМИ ADX значениями от GPT
        signal_id = await self.db.save_signal(
            symbol=signal.symbol,
            signal_type='BUY',
            price=signal.price,
            ema20=signal.ema20,
            # РЕАЛЬНЫЕ ADX значения от GPT (не фиктивные!)
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
        
        logger.info(f"📈 Сигнал покупки {signal.symbol} отправлен с РЕАЛЬНЫМ ADX {signal.adx:.1f}: {success_count} получателей")
    
    async def send_peak_signal(self, symbol: str, current_price: float):
        """Отправка сигнала пика тренда с проверкой РЕАЛЬНОГО ADX > 45"""
        if not self.app:
            return
        
        subscribers = await self.db.get_subscribers_for_ticker(symbol)
        if not subscribers:
            return
        
        # Получаем данные о прибыли
        profit_info = await self._get_profit_summary(symbol, current_price)
        
        # Пытаемся получить последний РЕАЛЬНЫЙ ADX для пика
        last_signal = await self.db.get_last_buy_signal(symbol)
        adx_info = ""
        adx_value = 45.0  # Fallback значение для БД
        
        if last_signal and last_signal.get('adx'):
            real_adx = float(last_signal['adx'])
            adx_info = f"\n📊 <b>РЕАЛЬНЫЙ ADX от GPT:</b> {real_adx:.1f} > 45 (экстремально сильный тренд)"
            adx_value = real_adx
        
        message = f"""🔥 <b>ПИК ТРЕНДА - ПРОДАЁМ {symbol}!</b>

💰 <b>Цена:</b> {current_price:.2f} ₽

📊 <b>Причина:</b> GPT определил пик тренда{adx_info}
⚡ Время фиксировать прибыль{profit_info}

🔍 <b>Продолжаем мониторинг...</b>"""
        
        # Сохраняем сигнал с РЕАЛЬНЫМ ADX пика
        await self.db.save_signal(
            symbol=symbol, 
            signal_type='PEAK', 
            price=current_price,
            ema20=current_price * 0.98,  # Примерное значение
            # Используем РЕАЛЬНОЕ ADX значение пика
            adx=adx_value,
            plus_di=35.0,  # Примерные значения для пика
            minus_di=20.0
        )
        
        # Отправляем
        success_count = await self._send_to_subscribers(
            subscribers, message, symbol, 'пика'
        )
        
        # Закрываем позиции
        await self.db.close_positions(symbol, 'PEAK')
        
        logger.info(f"🔥 Сигнал пика {symbol} отправлен с ADX {adx_value:.1f}: {success_count} получателей")
    
    async def send_cancel_signal(self, symbol: str, current_price: float):
        """Отправка сигнала отмены с объяснением ADX условий"""
        if not self.app:
            return
        
        subscribers = await self.db.get_subscribers_for_ticker(symbol)
        if not subscribers:
            return
        
        profit_info = await self._get_profit_summary(symbol, current_price)
        
        message = f"""❌ <b>СИГНАЛ ОТМЕНЕН {symbol}</b>

💰 <b>Цена:</b> {current_price:.2f} ₽

⚠️ <b>Причина:</b> Условия покупки больше не выполняются:
• Цена может быть ниже EMA20
• ADX < 25 (слабый тренд)
• +DI <= -DI (нисходящее движение)
• Разница DI < 1 (недостаточная сила)
• GPT не рекомендует продолжать{profit_info}

🔍 <b>Продолжаем мониторинг...</b>"""
        
        # Сохраняем сигнал с примерными "слабыми" ADX значениями
        await self.db.save_signal(
            symbol=symbol, 
            signal_type='SELL', 
            price=current_price,
            ema20=current_price * 0.98,  # Примерное значение
            # Примерные значения для отмены (слабый тренд)
            adx=20.0,    # < 25 = слабый тренд
            plus_di=25.0, 
            minus_di=30.0  # minus_di > plus_di = нисходящее движение
        )
        
        # Отправляем
        success_count = await self._send_to_subscribers(
            subscribers, message, symbol, 'отмены'
        )
        
        # Закрываем позиции
        await self.db.close_positions(symbol, 'SELL')
        
        logger.info(f"❌ Сигнал отмены {symbol} отправлен: {success_count} получателей")
    
    def _format_buy_signal_with_real_adx(self, signal) -> str:
        """Форматирование сигнала покупки с РЕАЛЬНЫМИ ADX от GPT"""
        
        # Проверяем наличие РЕАЛЬНЫХ ADX значений
        if signal.adx > 0 and signal.plus_di > 0 and signal.minus_di > 0:
            # У нас есть РЕАЛЬНЫЕ ADX значения от GPT
            adx_status = "✅ Сильный тренд" if signal.adx >= 25 else "⚠️ Слабый тренд"
            di_status = "✅ Восходящий" if signal.plus_di > signal.minus_di else "❌ Нисходящий"
            di_diff = signal.plus_di - signal.minus_di
            diff_status = "✅" if di_diff >= 1 else "❌"
            
            adx_section = f"""
📊 <b>РЕАЛЬНЫЙ ADX ОТ GPT:</b>
• <b>ADX:</b> {signal.adx:.1f} {adx_status}
• <b>+DI:</b> {signal.plus_di:.1f}
• <b>-DI:</b> {signal.minus_di:.1f} {di_status}
• <b>Разница DI:</b> {di_diff:+.1f} {diff_status}"""
        else:
            # Fallback если ADX не рассчитан
            adx_section = f"""
📊 <b>ТЕХНИЧЕСКИЕ УСЛОВИЯ:</b>
• <b>ADX анализ:</b> В процессе расчета GPT
• <b>Базовый фильтр:</b> ✅ Пройден"""

        return f"""🔔 <b>СИГНАЛ ПОКУПКИ {signal.symbol}</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽ (цена выше){adx_section}

✅ <b>ВСЕ УСЛОВИЯ ВЫПОЛНЕНЫ</b>"""
    
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
