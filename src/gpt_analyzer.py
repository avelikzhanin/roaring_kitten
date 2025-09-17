# src/gpt_analyzer.py - Комплексный анализ всех факторов
import logging
import aiohttp
import json
import asyncio
import numpy as np
import pandas as pd
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class GPTAdvice:
    """Комплексный совет от GPT с анализом всех факторов"""
    recommendation: str  # "BUY", "AVOID", "WEAK_BUY", "WAIT"
    confidence: int      # 0-100%
    reasoning: str       # Детальное объяснение
    risk_warning: str    # Предупреждение о рисках
    
    # ADX как один из факторов (может быть None)
    calculated_adx: Optional[float] = None        
    calculated_plus_di: Optional[float] = None   
    calculated_minus_di: Optional[float] = None   
    
    # Дополнительные поля
    take_profit: Optional[str] = None
    stop_loss: Optional[str] = None
    expected_levels: Optional[str] = None
    timeframe: Optional[str] = None
    key_factors: Optional[str] = None  # Ключевые факторы решения

class GPTMarketAnalyzer:
    """GPT анализатор с комплексным подходом ко всем факторам"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        # НОВЫЙ комплексный системный промпт
        self.base_system_prompt = """Ты профессиональный трейдер российского рынка с 15-летним опытом торговли голубыми фишками и комплексного технического анализа.

ТВОЯ РОЛЬ: Провести КОМПЛЕКСНЫЙ анализ всех доступных факторов и принять взвешенное торговое решение для {symbol}.

АНАЛИЗИРУЙ ВСЕ ФАКТОРЫ:

1. 📊 ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ:
   - EMA20 (основной тренд-фильтр)
   - ADX/DI (сила и направление тренда) - РАССЧИТАЙ из свечей
   - Поддержка/сопротивление
   - Позиция в диапазоне

2. 📈 ЦЕНОВАЯ ДИНАМИКА:
   - Краткосрочные изменения (1ч, 4ч, 1д)
   - Волатильность
   - Свечные паттерны
   - Пробои уровней

3. 🔊 ОБЪЕМЫ:
   - Текущий vs средний
   - Тренд объемов  
   - Всплески активности
   - Качество движения

4. ⏰ ВРЕМЕННОЙ КОНТЕКСТ:
   - Торговая сессия (main/evening/weekend)
   - Качество времени (premium/normal/низкое)
   - Ликвидность

5. 🎯 РЫНОЧНАЯ СИТУАЦИЯ:
   - Положение относительно диапазона
   - Близость к ключевым уровням
   - Общий настрой рынка

{ticker_specific_context}

ПРИНЦИПЫ РЕШЕНИЯ:
- BUY: Большинство факторов позитивны, риски контролируемы
- WEAK_BUY: Смешанные сигналы, но больше позитива  
- WAIT: Неопределенность, лучше подождать улучшения
- AVOID: Преобладают негативные факторы или высокие риски

ФОРМАТ ОТВЕТА - СТРОГО JSON:
{{
  "calculated_adx": число_или_null (если удалось рассчитать),
  "calculated_plus_di": число_или_null,
  "calculated_minus_di": число_или_null,
  "recommendation": "BUY/WEAK_BUY/WAIT/AVOID",
  "confidence": число_от_0_до_100,
  "reasoning": "детальный анализ всех факторов",
  "key_factors": "3-4 главных фактора решения",
  "take_profit": "уровень или null",
  "stop_loss": "уровень или null", 
  "expected_levels": "что ждать или null",
  "timeframe": "горизонт сделки",
  "risk_warning": "основные риски"
}}

ВАЖНО: Анализируй ВСЕ факторы комплексно. ADX - важен, но не единственный критерий!"""

        # Обновленные контексты для комплексного анализа
        self.ticker_contexts = {
            'SBER': """
КОНТЕКСТ SBER:
- Ценовой диапазон: 280-330₽, типичная волатильность 2-5%
- Лучшее время: 11:00-16:00 МСК (высокая ликвидность)
- Ключевые драйверы: ЦБ РФ, санкции, нефть, дивиденды
- Техуровни: поддержка ~275-285₽, сопротивление ~320-340₽
- Объемы: норма 1-3М/час, всплески 5М+ на новостях
- Особенности: лидер сектора, высокая корреляция с рублем""",

            'GAZP': """
КОНТЕКСТ GAZP:
- Ценовой диапазон: 120-180₽, высокая волатильность 3-7%
- Лучшее время: 11:00-16:00 МСК  
- Ключевые драйверы: газ в Европе, санкции, геополитика, сезон
- Техуровни: поддержка ~125-135₽, сопротивление ~170-185₽
- Объемы: средняя ликвидность, резкие всплески
- Особенности: сильная внешняя зависимость""",

            'LKOH': """
КОНТЕКСТ LKOH:
- Ценовой диапазон: 6000-8000₽, умеренная волатильность 2-6%
- Лучшее время: 11:00-16:00 МСК
- Ключевые драйверы: нефть Brent, санкции, рубль, дивиденды  
- Техуровни: поддержка ~6000-6200₽, сопротивление ~7500-8000₽
- Объемы: ниже чем у SBER, широкие спреды
- Особенности: нефтяная зависимость, экспортер""",

            'DEFAULT': """
ОБЩИЕ ПРИНЦИПЫ:
- Учитывай макроэкономику и настрой рынка
- Анализируй исторические паттерны из данных
- Премиум-время: 11:00-16:00 МСК"""
        }

    def get_system_prompt(self, symbol: str) -> str:
        """Получение системного промпта для комплексного анализа"""
        context = self.ticker_contexts.get(symbol, self.ticker_contexts['DEFAULT'])
        return self.base_system_prompt.format(
            symbol=symbol,
            ticker_specific_context=context
        )

    async def analyze_signal(self, signal_data: Dict, candles_data: Optional[List] = None, 
                           is_manual_check: bool = False, symbol: str = 'SBER') -> Optional[GPTAdvice]:
        """Комплексный анализ всех факторов через GPT"""
        try:
            # Получаем системный промпт
            system_prompt = self.get_system_prompt(symbol)
            
            # Создаем комплексный промпт с ВСЕМИ факторами
            prompt = self._create_comprehensive_prompt(signal_data, candles_data, is_manual_check, symbol)
            
            response = await self._call_openai_api(prompt, system_prompt)
            
            if response:
                return self._parse_comprehensive_advice(response)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка комплексного GPT анализа для {symbol}: {e}")
            return None
    
    def _create_comprehensive_prompt(self, signal_data: Dict, candles_data: Optional[List], 
                                   is_manual_check: bool, symbol: str = 'SBER') -> str:
        """Создание комплексного промпта с ВСЕМИ факторами"""
        
        # Ограничиваем свечи до 50 максимум
        if candles_data and len(candles_data) > 50:
            candles_data = candles_data[-50:]
            logger.info(f"🔢 Ограничили данные до 50 свечей для {symbol}")
        
        # Проверяем минимум данных
        if not candles_data or len(candles_data) < 20:
            return f"""НЕДОСТАТОЧНО ДАННЫХ для комплексного анализа {symbol}:
Получено свечей: {len(candles_data) if candles_data else 0}
Требуется минимум: 20

{{
  "calculated_adx": null,
  "calculated_plus_di": null, 
  "calculated_minus_di": null,
  "recommendation": "WAIT",
  "confidence": 20,
  "reasoning": "Недостаточно данных для полноценного анализа",
  "key_factors": "Мало исторических данных",
  "risk_warning": "Невозможно оценить все факторы"
}}"""

        # Формируем КОМПАКТНУЮ таблицу свечей (максимум 50)
        candles_table = "№ | ВРЕМЯ   | OPEN   | HIGH   | LOW    | CLOSE  | VOLUME\n"
        candles_table += "--|---------|--------|--------|--------|--------|---------\n"
        
        for i, candle in enumerate(candles_data):
            timestamp = candle.get('timestamp', datetime.now())
            if hasattr(timestamp, 'strftime'):
                time_str = timestamp.strftime('%d.%m %H:%M')
            else:
                time_str = str(timestamp)[:11]
            
            candles_table += f"{i+1:2d}|{time_str}|{candle['open']:7.2f}|{candle['high']:7.2f}|{candle['low']:7.2f}|{candle['close']:7.2f}|{candle['volume']:8,}\n"
        
        # Получаем все доступные данные
        current_price = signal_data.get('price', 0)
        current_ema20 = signal_data.get('ema20', 0)
        session = signal_data.get('trading_session', 'unknown')
        time_quality = signal_data.get('time_quality', 'unknown')
        
        # Объемы
        volume_info = ""
        if 'volume_analysis' in signal_data:
            vol = signal_data['volume_analysis']
            volume_info = f"""
🔊 ОБЪЕМЫ:
• Текущий: {vol.get('current_volume', 0):,}
• Отношение к среднему: {vol.get('volume_ratio', 1.0):.1f}x
• Тренд: {vol.get('volume_trend', 'unknown')}"""

        # Ценовая динамика
        movement_info = ""
        changes = []
        for key in ['change_1h', 'change_4h', 'change_1d']:
            if key in signal_data:
                period = key.replace('change_', '').upper()
                changes.append(f"{period}: {signal_data[key]:+.1f}%")
        
        if 'volatility_5d' in signal_data:
            changes.append(f"Vol5д: {signal_data['volatility_5d']:.1f}%")
        
        if changes:
            movement_info = f"\n📈 ДИНАМИКА: " + " | ".join(changes)

        # Уровни поддержки/сопротивления
        levels_info = ""
        if 'price_levels' in signal_data and signal_data['price_levels']:
            levels = signal_data['price_levels']
            resistance = levels.get('nearest_resistance')
            support = levels.get('nearest_support')
            if resistance or support:
                levels_info = f"""
📊 УРОВНИ:
• Сопротивление: {resistance:.2f}₽ ({((resistance/current_price-1)*100):+.1f}%)" if resistance else "нет"}
• Поддержка: {support:.2f}₽ ({((support/current_price-1)*100):+.1f}%)" if support else "нет"}
• Диапазон: {levels.get('recent_low', 0):.2f} - {levels.get('recent_high', 0):.2f}₽"""

        signal_type = "Ручная проверка" if is_manual_check else "Автоматический мониторинг"
        check_peak = signal_data.get('check_peak', False)
        task_description = "ПРОВЕРИТЬ пик тренда" if check_peak else "КОМПЛЕКСНЫЙ анализ для торгового решения"

        # Формируем итоговый промпт
        prompt = f"""КОМПЛЕКСНЫЙ АНАЛИЗ {symbol} - ВСЕ ФАКТОРЫ:

💰 ТЕКУЩЕЕ СОСТОЯНИЕ:
• Цена: {current_price:.2f}₽
• EMA20: {current_ema20:.2f}₽ ({'✅выше' if current_price > current_ema20 else '❌ниже'})
• Пробой EMA20: {((current_price/current_ema20-1)*100):+.2f}%{levels_info}{volume_info}{movement_info}

⏰ КОНТЕКСТ:
• Время: {datetime.now().strftime('%H:%M МСК')}
• Сессия: {session} (качество: {time_quality})
• Анализ: {signal_type}

📊 СВЕЧНЫЕ ДАННЫЕ ({len(candles_data)} свечей):
{candles_table}

🎯 ЗАДАЧА: {task_description}

ПРОАНАЛИЗИРУЙ ВСЕ ФАКТОРЫ:
1. 📊 Рассчитай ADX/DI из свечей (если возможно)
2. 📈 Оцени ценовую динамику и паттерны  
3. 🔊 Проанализируй объемы и их качество
4. ⏰ Учти временной контекст и ликвидность
5. 🎯 Оцени близость к ключевым уровням
6. 💡 Дай взвешенную рекомендацию

НЕ ОГРАНИЧИВАЙСЯ только ADX - это лишь один из факторов!"""

        return prompt
    
    def _parse_comprehensive_advice(self, response: str) -> Optional[GPTAdvice]:
        """Парсинг комплексного ответа GPT"""
        try:
            data = json.loads(response.strip())
            
            # Валидация обязательных полей
            recommendation = data.get('recommendation', 'AVOID').upper()
            if recommendation not in ['BUY', 'WEAK_BUY', 'WAIT', 'AVOID']:
                recommendation = 'AVOID'
            
            confidence = data.get('confidence', 50)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                confidence = 50
            
            reasoning = str(data.get('reasoning', 'Анализ недоступен'))[:1000]  # Увеличен лимит
            risk_warning = str(data.get('risk_warning', ''))[:300]
            
            # ADX данные (могут быть None)
            calculated_adx = data.get('calculated_adx')
            calculated_plus_di = data.get('calculated_plus_di') 
            calculated_minus_di = data.get('calculated_minus_di')
            
            # Валидация ADX если есть
            if calculated_adx is not None:
                try:
                    calculated_adx = float(calculated_adx)
                    if calculated_adx < 0 or calculated_adx > 100:
                        calculated_adx = None
                except (ValueError, TypeError):
                    calculated_adx = None
            
            if calculated_plus_di is not None:
                try:
                    calculated_plus_di = float(calculated_plus_di)
                    if calculated_plus_di < 0 or calculated_plus_di > 100:
                        calculated_plus_di = None
                except (ValueError, TypeError):
                    calculated_plus_di = None
                    
            if calculated_minus_di is not None:
                try:
                    calculated_minus_di = float(calculated_minus_di)
                    if calculated_minus_di < 0 or calculated_minus_di > 100:
                        calculated_minus_di = None
                except (ValueError, TypeError):
                    calculated_minus_di = None
            
            # Дополнительные поля
            key_factors = str(data.get('key_factors', ''))[:200] if data.get('key_factors') else None
            
            # TP/SL только для покупок
            take_profit = None
            stop_loss = None
            if recommendation in ['BUY', 'WEAK_BUY']:
                take_profit = str(data.get('take_profit', ''))[:100] if data.get('take_profit') else None
                stop_loss = str(data.get('stop_loss', ''))[:100] if data.get('stop_loss') else None
            
            # Expected levels для ожидания
            expected_levels = None
            if recommendation in ['WAIT', 'AVOID']:
                expected_levels = str(data.get('expected_levels', ''))[:300] if data.get('expected_levels') else None
            
            timeframe = str(data.get('timeframe', ''))[:150] if data.get('timeframe') else None
            
            advice = GPTAdvice(
                recommendation=recommendation,
                confidence=int(confidence),
                reasoning=reasoning,
                risk_warning=risk_warning,
                # ADX данные (могут быть None)
                calculated_adx=calculated_adx,
                calculated_plus_di=calculated_plus_di,
                calculated_minus_di=calculated_minus_di,
                # Дополнительные поля
                key_factors=key_factors,
                take_profit=take_profit,
                stop_loss=stop_loss,
                expected_levels=expected_levels,
                timeframe=timeframe
            )
            
            # Логируем результат
            adx_info = ""
            if calculated_adx is not None:
                adx_info = f", ADX: {calculated_adx:.1f}"
            
            logger.info(f"🎯 GPT комплексный анализ: {recommendation} ({confidence}%){adx_info}")
            
            return advice
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Некорректный JSON от GPT: {e}")
            logger.error(f"Ответ GPT: {response[:200]}...")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка парсинга комплексного анализа: {e}")
            return None
    
    async def _call_openai_api(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """Вызов OpenAI API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        if system_prompt is None:
            system_prompt = self.get_system_prompt('SBER')
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,  # Немного повысили для творческого анализа
            "max_tokens": 1500,
            "response_format": {"type": "json_object"}
        }
        
        timeout = aiohttp.ClientTimeout(total=30)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        logger.info("✅ GPT комплексный анализ получен")
                        return content
                    elif response.status == 429:
                        logger.warning("⚠️ Rate limit OpenAI API")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ OpenAI API ошибка {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.warning("⏰ Таймаут запроса к OpenAI")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка OpenAI API: {e}")
            return None
    
    def format_advice_for_telegram(self, advice: GPTAdvice, symbol: str = 'SBER') -> str:
        """Форматирование комплексного совета GPT для Telegram"""
        
        # Эмодзи для рекомендаций
        rec_emoji = {
            'BUY': '🚀',
            'WEAK_BUY': '⚡',
            'WAIT': '⏳', 
            'AVOID': '⛔'
        }
        
        # Оценка уверенности
        if advice.confidence >= 80:
            confidence_text = "высокая уверенность"
            confidence_emoji = '🟢'
        elif advice.confidence >= 60:
            confidence_text = "средняя уверенность"  
            confidence_emoji = '🟡'
        else:
            confidence_text = "низкая уверенность"
            confidence_emoji = '🔴'
        
        result = f"""
🤖 <b>GPT КОМПЛЕКСНЫЙ АНАЛИЗ {symbol}:</b>
{rec_emoji.get(advice.recommendation, '❓')} <b>{advice.recommendation}</b> | {confidence_emoji} {confidence_text} ({advice.confidence}%)"""

        # Ключевые факторы решения
        if advice.key_factors:
            result += f"""

🎯 <b>Ключевые факторы:</b> {advice.key_factors}"""

        # ADX данные если есть (не обязательно)
        if advice.calculated_adx is not None:
            adx_status = "🟢" if advice.calculated_adx > 25 else "🔴"
            di_status = "🟢" if (advice.calculated_plus_di or 0) > (advice.calculated_minus_di or 0) else "🔴"
            
            result += f"""

📊 <b>ADX анализ:</b>
• <b>ADX:</b> {advice.calculated_adx:.1f} {adx_status}
• <b>+DI:</b> {advice.calculated_plus_di:.1f} | <b>-DI:</b> {advice.calculated_minus_di:.1f} {di_status}"""

        result += f"""

💡 <b>Анализ:</b> {advice.reasoning}"""
        
        # TP/SL для покупок
        if advice.recommendation in ['BUY', 'WEAK_BUY']:
            if advice.take_profit:
                result += f"\n🎯 <b>Take Profit:</b> {advice.take_profit}"
            if advice.stop_loss:
                result += f"\n🛑 <b>Stop Loss:</b> {advice.stop_loss}"
            if advice.timeframe:
                result += f"\n⏰ <b>Горизонт:</b> {advice.timeframe}"
        
        # Уровни ожидания
        elif advice.recommendation in ['WAIT', 'AVOID'] and advice.expected_levels:
            result += f"\n📊 <b>Ждать:</b> {advice.expected_levels}"
        
        # Предупреждение о рисках
        if advice.risk_warning:
            result += f"\n\n⚠️ <b>Риски:</b> {advice.risk_warning}"
        
        return result
