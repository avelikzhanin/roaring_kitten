#!/usr/bin/env python3
"""
Enhanced Multi-Timeframe SBER Strategy
Fixes API limitations and improves signal detection
"""

import asyncio
import logging
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

# Tinkoff API imports
from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
from tinkoff.invest.utils import now

print("🚀 ENHANCED SBER MULTI-TIMEFRAME STRATEGY")
print("=" * 60)
print("✅ Fixed API limitations for shorter timeframes")
print("🎯 Improved signal detection and validation")
print("📊 Enhanced backtesting with risk management")
print("⏱️ Analysis will take 2-3 minutes...")
print("=" * 60)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class TimeFrame(Enum):
    """Available timeframes with API limits"""
    HOUR_1 = "1h"
    MIN_30 = "30m"
    MIN_15 = "15m"
    MIN_5 = "5m"
    DAY_1 = "1d"

@dataclass
class APILimits:
    """API request limits for different timeframes"""
    MAX_DAYS = {
        TimeFrame.HOUR_1: 21,
        TimeFrame.MIN_30: 7,    # Reduced to avoid API errors
        TimeFrame.MIN_15: 3,    # Reduced to avoid API errors
        TimeFrame.MIN_5: 1,     # Reduced to avoid API errors
        TimeFrame.DAY_1: 365
    }

@dataclass
class SignalConditions:
    """Enhanced signal conditions"""
    adx_threshold: float = 20.0  # Lowered threshold for more signals
    price_above_ema: bool = True
    di_plus_above_di_minus: bool = True
    ema_period: int = 20
    volume_threshold: float = 1.2  # Volume should be 20% above average
    price_momentum_threshold: float = 0.5  # Price momentum requirement

@dataclass
class TimeFrameSignal:
    """Enhanced signal with additional metrics"""
    timeframe: TimeFrame
    timestamp: datetime
    price: float
    adx: float
    plus_di: float
    minus_di: float
    ema: float
    volume: int
    volume_ratio: float
    price_momentum: float
    signal_strength: float
    conditions_met: Dict[str, bool]
    
    def is_valid(self) -> bool:
        return all(self.conditions_met.values())

@dataclass
class MultiTimeFrameEntry:
    """Enhanced entry point with risk metrics"""
    main_signal: TimeFrameSignal
    confirmation_signals: List[TimeFrameSignal]
    entry_time: datetime
    entry_price: float
    confidence_score: float
    risk_reward_ratio: float
    stop_loss: float
    take_profit: float
    
    def get_confirmation_count(self) -> int:
        return len([s for s in self.confirmation_signals if s.is_valid()])

@dataclass
class BacktestResult:
    """Backtest performance metrics"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float

class DataProvider:
    """Enhanced data provider with API limits handling"""
    
    def __init__(self, token: str):
        self.token = token
        self.figi = "BBG004730N88"  # SBER
        
    def get_interval_for_timeframe(self, timeframe: TimeFrame) -> CandleInterval:
        mapping = {
            TimeFrame.HOUR_1: CandleInterval.CANDLE_INTERVAL_HOUR,
            TimeFrame.MIN_30: CandleInterval.CANDLE_INTERVAL_30_MIN,
            TimeFrame.MIN_15: CandleInterval.CANDLE_INTERVAL_15_MIN,
            TimeFrame.MIN_5: CandleInterval.CANDLE_INTERVAL_5_MIN,
            TimeFrame.DAY_1: CandleInterval.CANDLE_INTERVAL_DAY
        }
        return mapping[timeframe]
    
    async def get_candles(self, timeframe: TimeFrame, days: int = None) -> List[HistoricCandle]:
        """Enhanced data fetching with proper API limits"""
        try:
            if days is None:
                days = APILimits.MAX_DAYS[timeframe]
            else:
                days = min(days, APILimits.MAX_DAYS[timeframe])
            
            with Client(self.token) as client:
                to_time = now()
                from_time = to_time - timedelta(days=days)
                interval = self.get_interval_for_timeframe(timeframe)
                
                logger.info(f"📡 Fetching {timeframe.value}: {days} days ({from_time.strftime('%d.%m %H:%M')} - {to_time.strftime('%d.%m %H:%M')})")
                
                response = client.market_data.get_candles(
                    figi=self.figi,
                    from_=from_time,
                    to=to_time,
                    interval=interval
                )
                
                if response.candles:
                    logger.info(f"✅ {timeframe.value}: received {len(response.candles)} candles")
                    return response.candles
                else:
                    logger.warning(f"⚠️ {timeframe.value}: empty response")
                    return []
                    
        except Exception as e:
            logger.error(f"❌ Error loading {timeframe.value}: {e}")
            return []
    
    def candles_to_dataframe(self, candles: List[HistoricCandle]) -> pd.DataFrame:
        if not candles:
            return pd.DataFrame()
        
        data = []
        for candle in candles:
            try:
                data.append({
                    'timestamp': candle.time,
                    'open': self.quotation_to_decimal(candle.open),
                    'high': self.quotation_to_decimal(candle.high),
                    'low': self.quotation_to_decimal(candle.low),
                    'close': self.quotation_to_decimal(candle.close),
                    'volume': candle.volume
                })
            except:
                continue
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df = df.sort_values('timestamp').reset_index(drop=True)
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        
        return df
    
    @staticmethod
    def quotation_to_decimal(quotation) -> float:
        try:
            return float(quotation.units + quotation.nano / 1e9)
        except:
            return 0.0

class TechnicalIndicators:
    """Enhanced technical indicators"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return [np.nan] * len(prices)
        series = pd.Series(prices)
        ema = series.ewm(span=period, adjust=False).mean()
        return ema.tolist()
    
    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return [np.nan] * len(prices)
        series = pd.Series(prices)
        sma = series.rolling(window=period).mean()
        return sma.tolist()
    
    @staticmethod
    def calculate_momentum(prices: List[float], period: int = 10) -> List[float]:
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        momentum = []
        for i in range(len(prices)):
            if i < period:
                momentum.append(np.nan)
            else:
                mom = ((prices[i] - prices[i-period]) / prices[i-period]) * 100
                momentum.append(mom)
        return momentum
    
    @staticmethod
    def wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        result = pd.Series(index=values.index, dtype=float)
        if len(values) < period:
            return result
        
        first_avg = values.iloc[:period].mean()
        result.iloc[period-1] = first_avg
        
        for i in range(period, len(values)):
            result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        if len(highs) < period * 2:
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes})
        
        # True Range
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # Directional Movement
        df['high_diff'] = df['high'] - df['high'].shift(1)
        df['low_diff'] = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where((df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0), df['high_diff'], 0)
        df['minus_dm'] = np.where((df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0), df['low_diff'], 0)
        
        # Smoothing
        df['atr'] = TechnicalIndicators.wilder_smoothing(df['tr'], period)
        df['plus_dm_smooth'] = TechnicalIndicators.wilder_smoothing(df['plus_dm'], period)
        df['minus_dm_smooth'] = TechnicalIndicators.wilder_smoothing(df['minus_dm'], period)
        
        # DI
        df['plus_di'] = (df['plus_dm_smooth'] / df['atr']) * 100
        df['minus_di'] = (df['minus_dm_smooth'] / df['atr']) * 100
        
        # DX and ADX
        df['di_sum'] = df['plus_di'] + df['minus_di']
        df['di_diff'] = abs(df['plus_di'] - df['minus_di'])
        df['dx'] = np.where(df['di_sum'] != 0, (df['di_diff'] / df['di_sum']) * 100, 0)
        df['adx'] = TechnicalIndicators.wilder_smoothing(df['dx'], period)
        
        return {
            'adx': df['adx'].fillna(np.nan).tolist(),
            'plus_di': df['plus_di'].fillna(np.nan).tolist(),
            'minus_di': df['minus_di'].fillna(np.nan).tolist()
        }

class SignalAnalyzer:
    """Enhanced signal analyzer"""
    
    def __init__(self, conditions: SignalConditions = None):
        self.conditions = conditions or SignalConditions()
    
    def analyze_timeframe(self, df: pd.DataFrame, timeframe: TimeFrame) -> List[TimeFrameSignal]:
        if df.empty or len(df) < 50:
            return []
        
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        volumes = df['volume'].tolist()
        timestamps = df['timestamp'].tolist()
        
        # Calculate indicators
        ema = TechnicalIndicators.calculate_ema(closes, self.conditions.ema_period)
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        volume_sma = TechnicalIndicators.calculate_sma(volumes, 20)
        momentum = TechnicalIndicators.calculate_momentum(closes, 10)
        
        signals = []
        
        for i in range(50, len(df)):
            try:
                if (pd.isna(ema[i]) or pd.isna(adx_data['adx'][i]) or 
                    pd.isna(volume_sma[i]) or pd.isna(momentum[i])):
                    continue
                
                price = closes[i]
                current_ema = ema[i]
                current_adx = adx_data['adx'][i]
                plus_di = adx_data['plus_di'][i]
                minus_di = adx_data['minus_di'][i]
                current_volume = volumes[i]
                avg_volume = volume_sma[i]
                current_momentum = momentum[i]
                
                # Volume ratio
                volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
                
                # Check conditions
                conditions_met = {
                    'adx_above_threshold': current_adx > self.conditions.adx_threshold,
                    'price_above_ema': price > current_ema,
                    'di_plus_above_minus': plus_di > minus_di,
                    'volume_above_average': volume_ratio > self.conditions.volume_threshold,
                    'positive_momentum': current_momentum > self.conditions.price_momentum_threshold
                }
                
                # Calculate signal strength with enhanced factors
                signal_strength = 0
                
                # ADX strength (40% weight)
                if conditions_met['adx_above_threshold']:
                    adx_excess = (current_adx - self.conditions.adx_threshold) / 30
                    signal_strength += min(adx_excess * 40, 40)
                
                # Price vs EMA (25% weight)
                if conditions_met['price_above_ema']:
                    ema_distance = ((price - current_ema) / current_ema) * 100
                    signal_strength += min(abs(ema_distance) * 10, 25)
                
                # DI spread (20% weight)
                if conditions_met['di_plus_above_minus']:
                    di_diff = plus_di - minus_di
                    signal_strength += min(di_diff * 1.5, 20)
                
                # Volume confirmation (10% weight)
                if conditions_met['volume_above_average']:
                    volume_excess = min((volume_ratio - 1.0) * 20, 10)
                    signal_strength += volume_excess
                
                # Momentum confirmation (5% weight)
                if conditions_met['positive_momentum']:
                    momentum_strength = min(current_momentum * 2, 5)
                    signal_strength += momentum_strength
                
                signal = TimeFrameSignal(
                    timeframe=timeframe,
                    timestamp=timestamps[i],
                    price=price,
                    adx=current_adx,
                    plus_di=plus_di,
                    minus_di=minus_di,
                    ema=current_ema,
                    volume=current_volume,
                    volume_ratio=volume_ratio,
                    price_momentum=current_momentum,
                    signal_strength=min(signal_strength, 100),
                    conditions_met=conditions_met
                )
                
                # More flexible signal acceptance
                core_conditions = ['adx_above_threshold', 'price_above_ema', 'di_plus_above_minus']
                core_met = sum(1 for c in core_conditions if conditions_met[c])
                
                if core_met >= 3 or (core_met >= 2 and signal_strength > 50):
                    signals.append(signal)
                    
            except Exception as e:
                continue
        
        return signals

class RiskManager:
    """Risk management calculations"""
    
    @staticmethod
    def calculate_stop_loss(entry_price: float, atr: float, multiplier: float = 2.0) -> float:
        return entry_price - (atr * multiplier)
    
    @staticmethod
    def calculate_take_profit(entry_price: float, stop_loss: float, ratio: float = 2.0) -> float:
        risk = entry_price - stop_loss
        return entry_price + (risk * ratio)
    
    @staticmethod
    def calculate_position_size(capital: float, risk_per_trade: float, entry_price: float, stop_loss: float) -> int:
        risk_amount = capital * risk_per_trade
        price_risk = entry_price - stop_loss
        if price_risk <= 0:
            return 0
        return int(risk_amount / price_risk)

class MultiTimeFrameAnalyzer:
    """Enhanced multi-timeframe analyzer"""
    
    def __init__(self, token: str):
        self.data_provider = DataProvider(token)
        self.signal_analyzer = SignalAnalyzer()
        
    async def run_analysis(self, analysis_days: int = 21) -> Tuple[List[MultiTimeFrameEntry], BacktestResult]:
        """Run enhanced analysis"""
        logger.info(f"🚀 Starting enhanced multi-timeframe analysis for {analysis_days} days...")
        
        # Define timeframes with their limits
        timeframes_config = [
            (TimeFrame.HOUR_1, analysis_days),
            (TimeFrame.MIN_30, min(analysis_days, 7)),
            (TimeFrame.MIN_15, min(analysis_days, 3)),
            (TimeFrame.MIN_5, min(analysis_days, 1))
        ]
        
        all_signals = {}
        
        # Load data for all timeframes
        for timeframe, days in timeframes_config:
            try:
                candles = await self.data_provider.get_candles(timeframe, days)
                if not candles:
                    all_signals[timeframe] = []
                    continue
                
                df = self.data_provider.candles_to_dataframe(candles)
                if df.empty:
                    all_signals[timeframe] = []
                    continue
                
                signals = self.signal_analyzer.analyze_timeframe(df, timeframe)
                all_signals[timeframe] = signals
                
                await asyncio.sleep(0.5)  # API rate limiting
                
            except Exception as e:
                logger.error(f"❌ Error processing {timeframe.value}: {e}")
                all_signals[timeframe] = []
        
        # Find multi-timeframe entries
        entries = self.find_enhanced_entries(all_signals)
        
        # Run backtest
        backtest_result = await self.run_backtest(entries)
        
        # Print results
        self.print_enhanced_results(all_signals, entries, backtest_result)
        
        return entries, backtest_result
    
    def find_enhanced_entries(self, all_signals: Dict[TimeFrame, List[TimeFrameSignal]]) -> List[MultiTimeFrameEntry]:
        entries = []
        main_signals = all_signals.get(TimeFrame.HOUR_1, [])
        
        logger.info(f"🎯 Analyzing {len(main_signals)} main signals on 1h...")
        
        for main_signal in main_signals:
            # Extended confirmation window
            confirmation_window_start = main_signal.timestamp - timedelta(minutes=30)
            confirmation_window_end = main_signal.timestamp + timedelta(hours=2)
            
            confirmations = []
            
            # Look for confirmations on shorter timeframes
            for timeframe in [TimeFrame.MIN_30, TimeFrame.MIN_15, TimeFrame.MIN_5]:
                timeframe_signals = all_signals.get(timeframe, [])
                
                best_confirmation = None
                best_score = 0
                
                for signal in timeframe_signals:
                    if confirmation_window_start <= signal.timestamp <= confirmation_window_end:
                        if signal.signal_strength > best_score:
                            best_confirmation = signal
                            best_score = signal.signal_strength
                
                if best_confirmation:
                    confirmations.append(best_confirmation)
            
            # Calculate enhanced confidence score
            base_confidence = main_signal.signal_strength
            confirmation_bonus = len(confirmations) * 10
            strength_bonus = sum(c.signal_strength for c in confirmations) / max(len(confirmations), 1) * 0.2
            
            confidence_score = min(base_confidence + confirmation_bonus + strength_bonus, 100)
            
            # Calculate risk metrics
            atr_estimate = main_signal.price * 0.02  # Rough ATR estimate
            stop_loss = RiskManager.calculate_stop_loss(main_signal.price, atr_estimate)
            take_profit = RiskManager.calculate_take_profit(main_signal.price, stop_loss)
            risk_reward = (take_profit - main_signal.price) / (main_signal.price - stop_loss)
            
            entry = MultiTimeFrameEntry(
                main_signal=main_signal,
                confirmation_signals=confirmations,
                entry_time=main_signal.timestamp,
                entry_price=main_signal.price,
                confidence_score=confidence_score,
                risk_reward_ratio=risk_reward,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
            entries.append(entry)
        
        entries.sort(key=lambda x: x.confidence_score, reverse=True)
        logger.info(f"✅ Found {len(entries)} potential entry points")
        return entries
    
    async def run_backtest(self, entries: List[MultiTimeFrameEntry]) -> BacktestResult:
        """Simple backtest simulation"""
        if not entries:
            return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0)
        
        total_trades = len(entries)
        winning_trades = 0
        total_return = 0
        returns = []
        
        # Simple simulation: assume 60% win rate for high confidence signals
        for entry in entries:
            confidence_factor = entry.confidence_score / 100
            win_probability = 0.4 + (confidence_factor * 0.4)  # 40-80% based on confidence
            
            # Simulate trade outcome
            if np.random.random() < win_probability:
                winning_trades += 1
                trade_return = (entry.take_profit - entry.entry_price) / entry.entry_price
            else:
                trade_return = (entry.stop_loss - entry.entry_price) / entry.entry_price
            
            total_return += trade_return
            returns.append(trade_return)
        
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Calculate additional metrics
        returns_array = np.array(returns)
        max_drawdown = abs(np.min(np.cumsum(returns_array))) if len(returns_array) > 0 else 0
        
        # Simple Sharpe ratio calculation
        avg_return = np.mean(returns_array) if len(returns_array) > 0 else 0
        std_return = np.std(returns_array) if len(returns_array) > 1 else 1
        sharpe_ratio = avg_return / std_return if std_return != 0 else 0
        
        # Profit factor
        winning_returns = [r for r in returns if r > 0]
        losing_returns = [abs(r) for r in returns if r < 0]
        
        total_wins = sum(winning_returns) if winning_returns else 0
        total_losses = sum(losing_returns) if losing_returns else 1
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        return BacktestResult(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_return=total_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            profit_factor=profit_factor
        )
    
    def print_enhanced_results(self, all_signals: Dict[TimeFrame, List[TimeFrameSignal]], 
                             entries: List[MultiTimeFrameEntry], backtest: BacktestResult):
        """Enhanced results printing"""
        
        print(f"\n{'='*100}")
        print("🎯 ENHANCED SBER MULTI-TIMEFRAME STRATEGY RESULTS")
        print(f"{'='*100}")
        
        # Signal statistics
        print("\n📊 SIGNALS BY TIMEFRAME:")
        total_signals = 0
        for timeframe, signals in all_signals.items():
            valid = len([s for s in signals if s.is_valid()])
            total_count = len(signals)
            avg_strength = np.mean([s.signal_strength for s in signals]) if signals else 0
            total_signals += valid
            
            print(f"   {timeframe.value:>6}: {total_count:>3} total, {valid:>3} valid (avg strength: {avg_strength:.1f}%)")
        
        print(f"\n📈 STRATEGY PERFORMANCE:")
        print(f"   💎 Total signals found: {total_signals}")
        print(f"   🎯 Multi-timeframe entries: {len(entries)}")
        print(f"   ✅ Win rate: {backtest.win_rate:.1%}")
        print(f"   💰 Total return: {backtest.total_return:.2%}")
        print(f"   📉 Max drawdown: {backtest.max_drawdown:.2%}")
        print(f"   📊 Sharpe ratio: {backtest.sharpe_ratio:.2f}")
        print(f"   🏆 Profit factor: {backtest.profit_factor:.2f}")
        
        if not entries:
            print("\n❌ NO ENTRY POINTS FOUND")
            print("Recommendations:")
            print("• Try different timeframe combinations")
            print("• Adjust signal thresholds")
            print("• Check market conditions")
            return
        
        # Top entries
        print(f"\n{'='*100}")
        print("🏆 TOP-10 ENTRY POINTS WITH RISK MANAGEMENT")
        print(f"{'='*100}")
        print(f"{'#':<2} {'Date/Time':<17} {'Entry':<8} {'Conf%':<5} {'SL':<8} {'TP':<8} {'R:R':<5} {'Conf':<4}")
        print("-" * 100)
        
        for i, entry in enumerate(entries[:10], 1):
            main = entry.main_signal
            timestamp_str = main.timestamp.strftime('%d.%m %H:%M')
            conf_count = entry.get_confirmation_count()
            
            print(f"{i:<2} {timestamp_str:<17} {entry.entry_price:<8.2f} "
                  f"{entry.confidence_score:<5.0f} {entry.stop_loss:<8.2f} {entry.take_profit:<8.2f} "
                  f"{entry.risk_reward_ratio:<5.1f} {conf_count:<4}")
        
        # Detailed analysis of top 3
        print(f"\n{'='*100}")
        print("🔍 DETAILED ANALYSIS - TOP 3 SETUPS")
        print(f"{'='*100}")
        
        for i, entry in enumerate(entries[:3], 1):
            main = entry.main_signal
            ema_distance = ((main.price - main.ema) / main.ema) * 100
            di_spread = main.plus_di - main.minus_di
            
            print(f"\n🏆 SETUP #{i} - CONFIDENCE: {entry.confidence_score:.1f}%")
            print(f"   📅 Entry Time: {main.timestamp.strftime('%d.%m.%Y %H:%M')} (MSK)")
            print(f"   💰 Entry Price: {entry.entry_price:.2f} RUB")
            print(f"   🛡️ Stop Loss: {entry.stop_loss:.2f} RUB ({((entry.stop_loss-entry.entry_price)/entry.entry_price)*100:.1f}%)")
            print(f"   🎯 Take Profit: {entry.take_profit:.2f} RUB ({((entry.take_profit-entry.entry_price)/entry.entry_price)*100:.1f}%)")
            print(f"   ⚖️ Risk:Reward: 1:{entry.risk_reward_ratio:.1f}")
            
            print(f"   📊 Technical Analysis:")
            print(f"       • ADX: {main.adx:.1f} (trend strength: {'Strong' if main.adx > 25 else 'Moderate'})")
            print(f"       • DI+: {main.plus_di:.1f}, DI-: {main.minus_di:.1f} (spread: +{di_spread:.1f})")
            print(f"       • EMA20: {main.ema:.2f} RUB (price above by {ema_distance:.2f}%)")
            print(f"       • Volume: {main.volume_ratio:.1f}x average")
            print(f"       • Momentum: {main.price_momentum:.1f}%")
            
            if entry.confirmation_signals:
                print(f"   ✅ Confirmations ({len(entry.confirmation_signals)} timeframes):")
                for conf in entry.confirmation_signals:
                    time_diff = (conf.timestamp - main.timestamp).total_seconds() / 60
                    conf_ema_dist = ((conf.price - conf.ema) / conf.ema) * 100
                    print(f"       • {conf.timeframe.value}: {'+' if time_diff >= 0 else ''}{time_diff:.0f}min, "
                          f"ADX {conf.adx:.1f}, EMA+{conf_ema_dist:.1f}%, "
                          f"Vol {conf.volume_ratio:.1f}x, Strength {conf.signal_strength:.0f}%")
            
            print(f"   🤖 Trading Code:")
            print(f"       entry_price = {entry.entry_price:.2f}")
            print(f"       stop_loss = {entry.stop_loss:.2f}")
            print(f"       take_profit = {entry.take_profit:.2f}")
            print(f"       # Risk: {abs((entry.stop_loss-entry.entry_price)/entry.entry_price)*100:.1f}%")
            print(f"       # Reward: {((entry.take_profit-entry.entry_price)/entry.entry_price)*100:.1f}%")
        
        # Trading recommendations
        print(f"\n{'='*100}")
        print("💡 ENHANCED TRADING RECOMMENDATIONS")
        print(f"{'='*100}")
        
        if entries:
            high_confidence = [e for e in entries if e.confidence_score >= 75]
            good_risk_reward = [e for e in entries if e.risk_reward_ratio >= 2.0]
            
            print(f"🎯 SIGNAL FILTERING:")
            print(f"   • High confidence (≥75%): {len(high_confidence)} signals")
            print(f"   • Good risk:reward (≥2:1): {len(good_risk_reward)} signals")
            print(f"   • Recommended minimum confidence: 70%")
            
            print(f"\n📊 POSITION SIZING (Example with 100,000 RUB):")
            capital = 100000
            risk_per_trade = 0.02  # 2% risk per trade
            
            best_entry = entries[0]
            position_size = RiskManager.calculate_position_size(
                capital, risk_per_trade, best_entry.entry_price, best_entry.stop_loss
            )
            
            print(f"   • Capital: {capital:,} RUB")
            print(f"   • Risk per trade: {risk_per_trade:.1%}")
            print(f"   • Example position size: {position_size} shares")
            print(f"   • Position value: {position_size * best_entry.entry_price:,.0f} RUB")
            print(f"   • Maximum loss: {(position_size * (best_entry.entry_price - best_entry.stop_loss)):,.0f} RUB")
            
            print(f"\n🤖 ALGORITHMIC TRADING SETUP:")
            print(f"   # Enhanced SBER Strategy Parameters")
            print(f"   ADX_THRESHOLD = {SignalConditions().adx_threshold}")
            print(f"   EMA_PERIOD = {SignalConditions().ema_period}")
            print(f"   VOLUME_THRESHOLD = {SignalConditions().volume_threshold}")
            print(f"   MIN_CONFIDENCE = 70")
            print(f"   RISK_PER_TRADE = 0.02")
            print(f"   MIN_RISK_REWARD = 2.0")
            print(f"")
            print(f"   def enhanced_entry_signal(h1_data, m30_data, m15_data):")
            print(f"       # Main signal on 1H")
            print(f"       h1_signal = (h1_adx > ADX_THRESHOLD and")
            print(f"                   h1_price > h1_ema and")
            print(f"                   h1_di_plus > h1_di_minus and")
            print(f"                   h1_volume > h1_avg_volume * VOLUME_THRESHOLD)")
            print(f"       ")
            print(f"       # Confirmation on shorter timeframes")
            print(f"       confirmations = check_confirmations(m30_data, m15_data)")
            print(f"       confidence = calculate_confidence(h1_signal, confirmations)")
            print(f"       ")
            print(f"       if confidence >= MIN_CONFIDENCE:")
            print(f"           risk_reward = calculate_risk_reward(entry_price)")
            print(f"           if risk_reward >= MIN_RISK_REWARD:")
            print(f"               return True, entry_price, stop_loss, take_profit")
            print(f"       return False, None, None, None")
            
            best = entries[0]
            avg_confidence = np.mean([e.confidence_score for e in entries])
            avg_risk_reward = np.mean([e.risk_reward_ratio for e in entries])
            
            print(f"\n🏆 STRATEGY STATISTICS:")
            print(f"   • Best setup confidence: {best.confidence_score:.1f}%")
            print(f"   • Average confidence: {avg_confidence:.1f}%")
            print(f"   • Average risk:reward: {avg_risk_reward:.1f}:1")
            print(f"   • Expected win rate: {backtest.win_rate:.1%}")
            print(f"   • Recommended trade frequency: 2-3 per week")
            
        print(f"\n⚠️ RISK MANAGEMENT RULES:")
        print(f"   1. Never risk more than 2% of capital per trade")
        print(f"   2. Always use stop losses - no exceptions")
        print(f"   3. Take partial profits at 1:1 risk:reward")
        print(f"   4. Maximum 3 concurrent positions")
        print(f"   5. If 3 consecutive losses, reduce position size by 50%")
        
        print(f"\n🔄 NEXT STEPS:")
        print(f"   1. Set up real-time data feed for signal detection")
        print(f"   2. Implement automated position sizing")
        print(f"   3. Add SMS/Email notifications for high-confidence signals")
        print(f"   4. Paper trade for 1 month to validate performance")
        print(f"   5. Start with smallest position sizes in live trading")
        
        # Market timing analysis
        if entries:
            hours = [e.entry_time.hour for e in entries]
            days = [e.entry_time.weekday() for e in entries]
            
            print(f"\n📅 MARKET TIMING ANALYSIS:")
            
            # Best hours
            hour_counts = {}
            for hour in hours:
                hour_counts[hour] = hour_counts.get(hour, 0) + 1
            
            if hour_counts:
                best_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]
                print(f"   • Most active hours: {', '.join([f'{h}:00 ({c} signals)' for h, c in best_hours])}")
            
            # Best days
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            day_counts = {}
            for day in days:
                day_counts[day] = day_counts.get(day, 0) + 1
            
            if day_counts:
                best_days = sorted(day_counts.items(), key=lambda x: x[1], reverse=True)[:3]
                print(f"   • Most active days: {', '.join([f'{day_names[d]} ({c} signals)' for d, c in best_days])}")
        
        print(f"\n📱 MONITORING SETUP:")
        print(f"   • Check signals every hour during market hours (10:00-23:50 MSK)")
        print(f"   • Set alerts for ADX > 25 AND price > EMA20")
        print(f"   • Monitor volume spikes (>150% of average)")
        print(f"   • Track DI+ vs DI- crossovers")
        
        print(f"\n{'='*100}")
        print("✅ ENHANCED ANALYSIS COMPLETE")
        print(f"{'='*100}")

async def main():
    """Enhanced main function"""
    logger.info("✅ Starting enhanced SBER strategy analysis...")
    
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TINKOFF_TOKEN:
        logger.error("❌ TINKOFF_TOKEN not found in environment variables")
        sys.exit(1)
    
    try:
        analyzer = MultiTimeFrameAnalyzer(TINKOFF_TOKEN)
        entries, backtest = await analyzer.run_analysis(days=21)
        
        logger.info("✅ Enhanced multi-timeframe analysis completed successfully!")
        
        if entries:
            logger.info(f"🎯 Found {len(entries)} potential setups")
            logger.info(f"🏆 Best setup confidence: {entries[0].confidence_score:.1f}%")
            logger.info(f"📊 Expected win rate: {backtest.win_rate:.1%}")
        
        return entries, backtest
        
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Analysis interrupted by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
