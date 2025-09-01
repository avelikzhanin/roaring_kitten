# ИЗМЕНЕНИЯ В bot.py - добавить эти методы

    async def get_gpt_analysis(self, signal: TradingSignal, is_manual_check: bool = False) -> Optional[GPTAdvice]:
        """Получение GPT анализа для сигнала с историческими данными"""
        if not self.gpt_analyzer:
            return None
        
        # Получаем свечные данные для анализа уровней
        try:
            candles = await self.tinkoff_provider.get_candles(hours=120)  # 5 дней данных
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            
            # Преобразуем в формат для GPT
            candles_data = []
            if not df.empty:
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
            logger.warning(f"Не удалось получить данные свечей для GPT: {e}")
            candles_data = None
        
        signal_data = {
            'price': signal.price,
            'ema20': signal.ema20,
            'adx': signal.adx,
            'plus_di': signal.plus_di,
            'minus_di': signal.minus_di
        }
        
        return await self.gpt_analyzer.analyze_signal(signal_data, candles_data, is_manual_check)

    async def get_detailed_market_status(self) -> str:
        """Получение детального статуса рынка с расширенным GPT анализом"""
        try:
            candles = await self.tinkoff_provider.get_candles(hours=120)
            
            if len(candles) < 50:
                return "❌ <b>Недостаточно данных для анализа</b>\n\nПопробуйте позже."
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            
            if df.empty:
                return "❌ <b>Ошибка получения данных</b>"
            
            # Получаем текущие значения индикаторов
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            # Расчет индикаторов
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            # Последние значения
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            current_adx = adx_data['adx'][-1]
            current_plus_di = adx_data['plus_di'][-1]
            current_minus_di = adx_data['minus_di'][-1]
            
            # Проверяем условия
            price_above_ema = current_price > current_ema20 if not pd.isna(current_ema20) else False
            strong_trend = current_adx > 25 if not pd.isna(current_adx) else False
            positive_direction = current_plus_di > current_minus_di if not pd.isna(current_plus_di) and not pd.isna(current_minus_di) else False
            di_difference = (current_plus_di - current_minus_di) > 1 if not pd.isna(current_plus_di) and not pd.isna(current_minus_di) else False
            peak_trend = current_adx > 45 if not pd.isna(current_adx) else False
            
            all_conditions_met = all([price_above_ema, strong_trend, positive_direction, di_difference])
            
            peak_warning = ""
            if peak_trend and self.current_signal_active:
                peak_warning = "\n🔥 <b>ВНИМАНИЕ: ADX > 45 - пик тренда! Время продавать!</b>"
            elif peak_trend:
                peak_warning = "\n🔥 <b>ADX > 45 - пик тренда</b>"
            
            message = f"""📊 <b>ТЕКУЩЕЕ СОСТОЯНИЕ РЫНКА SBER</b>

💰 <b>Цена:</b> {current_price:.2f} ₽
📈 <b>EMA20:</b> {current_ema20:.2f} ₽ {'✅' if price_above_ema else '❌'}

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {current_adx:.1f} {'✅' if strong_trend else '❌'} (нужно >25)
• <b>+DI:</b> {current_plus_di:.1f}
• <b>-DI:</b> {current_minus_di:.1f} {'✅' if positive_direction else '❌'}
• <b>Разница DI:</b> {current_plus_di - current_minus_di:.1f} {'✅' if di_difference else '❌'} (нужно >1){peak_warning}

{'🔔 <b>Все условия выполнены - ожидайте сигнал!</b>' if all_conditions_met else '⏳ <b>Ожидаем улучшения показателей...</b>'}"""
            
            # Добавляем РАСШИРЕННЫЙ GPT анализ с историческими данными
            if self.gpt_analyzer:
                # Преобразуем данные свечей для GPT
                candles_data = []
                try:
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
                    logger.warning(f"Ошибка подготовки данных свечей: {e}")
                    candles_data = None
                
                signal_data = {
                    'price': current_price,
                    'ema20': current_ema20,
                    'adx': current_adx,
                    'plus_di': current_plus_di,
                    'minus_di': current_minus_di,
                    'conditions_met': all_conditions_met  # Передаем статус условий
                }
                
                gpt_advice = await self.gpt_analyzer.analyze_signal(signal_data, candles_data, is_manual_check=True)
                if gpt_advice:
                    message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice)}"
                else:
                    message += "\n\n🤖 <i>GPT анализ временно недоступен</i>"
            
            return message
                
        except Exception as e:
            logger.error(f"Ошибка в детальном анализе: {e}")
            return "❌ <b>Ошибка получения данных для анализа</b>\n\nПопробуйте позже."
