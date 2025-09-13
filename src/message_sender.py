import asyncio
import logging
from typing import Optional
from telegram.error import TelegramError, TimedOut, NetworkError

logger = logging.getLogger(__name__)

class MessageSender:
    """Отправщик сообщений подписчикам"""
    
    def __init__(self, database, gpt_analyzer=None, tinkoff_provider=None):
        self.db = database
        self.gpt_analyzer = gpt_analyzer
        self.tinkoff_provider = tinkoff_provider
        self.app = None
    
    def set_app(self, app):
        """Установка Telegram приложения"""
        self.app = app
    
    async def send_buy_signal(self, signal):
        """Отправка сигнала покупки"""
        if not self.app:
            logger.error("Telegram приложение не установлено")
            return
        
        # Получаем подписчиков
        subscribers = await self.db.get_subscribers_for_ticker(signal.symbol)
        if not subscribers:
            logger.info(f"Нет подписчиков для {signal.symbol}")
            return
        
        # Формируем сообщение
        message = self._format_buy_signal(signal)
        
        # Получаем GPT анализ
        gpt_data = await self._get_gpt_analysis(signal)
        if gpt_data:
            message += f"\n{gpt_data['formatted_message']}"
        
        # Сохраняем сигнал в БД
        signal_id = await self.db.save_signal(
            symbol=signal.symbol,
            signal_type='BUY',
            price=signal.price,
            ema20=signal.ema20,
            adx=signal.adx,
            plus_di=signal.plus_di,
            minus_di=signal.minus_di,
            gpt_data=gpt_data['db_data'] if gpt_data else None
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
        
        logger.info(f"📈 Сигнал покупки {signal.symbol} отправлен: {success_count} получателей")
    
    async def send_peak_signal(self, symbol: str, current_price: float):
        """Отправка сигнала пика тренда"""
        if not self.app:
            return
        
        subscribers = await self.db.get_subscribers_for_ticker(symbol)
        if not subscribers:
            return
        
        # Получаем данные о прибыли
        profit_info = await self._get_profit_summary(symbol, current_price)
        
        message = f"""🔥 <b>ПИК ТРЕНДА - ПРОДАЁМ {symbol}!</b>

💰 <b>Цена:</b> {current_price:.2f} ₽

📊 ADX > 45 - пик тренда!
Время фиксировать прибыль.{profit_info}

🔍 <b>Продолжаем мониторинг...</b>"""
        
        # Сохраняем сигнал
        await self.db.save_signal(
            symbol=symbol, signal_type='PEAK', price=current_price,
            ema20=current_price * 0.98, adx=47, plus_di=35, minus_di=20
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

⚠️ <b>Причина:</b> Условия больше не выполняются{profit_info}

🔍 <b>Продолжаем мониторинг...</b>"""
        
        # Сохраняем сигнал
        await self.db.save_signal(
            symbol=symbol, signal_type='SELL', price=current_price,
            ema20=current_price * 0.98, adx=20, plus_di=25, minus_di=30
        )
        
        # Отправляем
        success_count = await self._send_to_subscribers(
            subscribers, message, symbol, 'отмены'
        )
        
        # Закрываем позиции
        await self.db.close_positions(symbol, 'SELL')
        
        logger.info(f"❌ Сигнал отмены {symbol} отправлен: {success_count} получателей")
    
    def _format_buy_signal(self, signal) -> str:
        """Форматирование сигнала покупки"""
        return f"""🔔 <b>СИГНАЛ ПОКУПКИ {signal.symbol}</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽ (цена выше)

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {signal.adx:.1f} (сильный тренд >25)
• <b>+DI:</b> {signal.plus_di:.1f}
• <b>-DI:</b> {signal.minus_di:.1f}
• <b>Разница DI:</b> {signal.plus_di - signal.minus_di:.1f}"""
    
    async def _get_gpt_analysis(self, signal) -> Optional[dict]:
        """Получение GPT анализа для сигнала"""
        if not self.gpt_analyzer:
            return None
        
        try:
            # Получаем свечные данные для GPT
            ticker_info = await self.db.get_ticker_info(signal.symbol)
            candles_data = None
            
            if ticker_info and self.tinkoff_provider:
                try:
                    candles = await self.tinkoff_provider.get_candles_for_ticker(
                        ticker_info['figi'], hours=100
                    )
                    df = self.tinkoff_provider.candles_to_dataframe(candles)
                    
                    if not df.empty:
                        candles_data = []
                        for _, row in df.iterrows():
                            candles_data.append({
                                'timestamp': row['timestamp'],
                                'open': float(row['open']),
                                'high': float(row['high']),
                                'low': float(row['low']),
                                'close': float(row['close']),
                                'volume': int(row['volume'])
                            })
                except Exception as e:
                    logger.warning(f"Не удалось получить свечи для GPT {signal.symbol}: {e}")
            
            signal_data = {
                'price': signal.price,
                'ema20': signal.ema20,
                'adx': signal.adx,
                'plus_di': signal.plus_di,
                'minus_di': signal.minus_di
            }
            
            gpt_advice = await self.gpt_analyzer.analyze_signal(
                signal_data, candles_data, is_manual_check=False, symbol=signal.symbol
            )
            
            if gpt_advice:
                formatted_message = self.gpt_analyzer.format_advice_for_telegram(gpt_advice, signal.symbol)
                
                # Добавляем предупреждения
                if gpt_advice.recommendation == 'AVOID':
                    formatted_message += "\n\n⚠️ <b>ВНИМАНИЕ:</b> GPT не рекомендует покупку!"
                elif gpt_advice.recommendation == 'WEAK_BUY':
                    formatted_message += "\n\n⚡ <b>Осторожно:</b> GPT рекомендует минимальный риск"
                
                return {
                    'formatted_message': formatted_message,
                    'db_data': {
                        'recommendation': gpt_advice.recommendation,
                        'confidence': gpt_advice.confidence,
                        'take_profit': gpt_advice.take_profit,
                        'stop_loss': gpt_advice.stop_loss
                    }
                }
            
        except Exception as e:
            logger.error(f"Ошибка GPT анализа для {signal.symbol}: {e}")
        
        return None
    
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
