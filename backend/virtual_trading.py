from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pandas as pd
from models import (VirtualAccount, VirtualTrade, StrategySettings, StrategyLog, 
                   StrategySignal, get_db_session)
from strategy import FinancialPotentialStrategy
import json

class VirtualTradingEngine:
    """Движок виртуальной торговли с отдельными счетами для каждого символа"""
    
    def __init__(self, symbols: List[str] = None):
        if symbols is None:
            symbols = ["SBER", "GAZP", "LKOH", "VTBR"]
        self.symbols = symbols
        self.commission_rate = 0.0005  # 0.05% комиссия
        
    def get_account(self, symbol: str) -> VirtualAccount:
        """Получение виртуального счета для конкретного символа"""
        db = get_db_session()
        try:
            account = db.query(VirtualAccount).filter(VirtualAccount.symbol == symbol).first()
            if not account:
                # Создаем новый счет для символа
                account = VirtualAccount(
                    symbol=symbol,
                    initial_balance=100000.0,
                    current_balance=100000.0,
                    max_balance=100000.0
                )
                db.add(account)
                db.commit()
                db.refresh(account)
            return account
        finally:
            db.close()
    
    def get_all_accounts(self) -> Dict[str, VirtualAccount]:
        """Получение всех виртуальных счетов"""
        accounts = {}
        for symbol in self.symbols:
            accounts[symbol] = self.get_account(symbol)
        return accounts
    
    def update_drawdown(self, symbol: str):
        """Обновление информации о просадке для конкретного счета"""
        db = get_db_session()
        try:
            account = self.get_account(symbol)
            
            if account.current_balance > account.max_balance:
                account.max_balance = account.current_balance
            
            if account.max_balance > account.initial_balance:
                account.current_drawdown = (account.max_balance - account.current_balance) / account.max_balance * 100.0
            else:
                account.current_drawdown = (account.initial_balance - account.current_balance) / account.initial_balance * 100.0
            
            # Проверяем блокировку торговли
            max_drawdown = 25.0  # Можно сделать настраиваемым
            if account.current_drawdown >= max_drawdown:
                if not account.trading_blocked:
                    account.trading_blocked = True
                    self.log_event("TRADING_BLOCKED", f"Достигнута максимальная просадка {account.current_drawdown:.2f}%", symbol)
            
            account.updated_at = datetime.utcnow()
            db.commit()
            
        finally:
            db.close()
    
    def place_virtual_order(self, signal: StrategySignal) -> Optional[VirtualTrade]:
        """Размещение виртуального ордера для конкретного символа"""
        if signal.direction == "NONE":
            return None
            
        account = self.get_account(signal.symbol)
        if account.trading_blocked:
            self.log_event("ORDER_REJECTED", "Торговля заблокирована из-за просадки", signal.symbol)
            return None
        
        db = get_db_session()
        try:
            # Проверяем, есть ли уже открытые позиции по этому символу
            existing_trades = db.query(VirtualTrade).filter(
                VirtualTrade.symbol == signal.symbol,
                VirtualTrade.status.in_(["PENDING", "OPEN"])
            ).count()
            
            if existing_trades > 0:
                self.log_event("ORDER_REJECTED", "Уже есть открытые позиции по символу", signal.symbol)
                return None
            
            # Создаем виртуальную сделку, связанную с конкретным счетом
            trade = VirtualTrade(
                account_id=account.id,
                symbol=signal.symbol,
                direction=signal.direction,
                entry_price=signal.entry_price,
                lot_size=signal.lot_size,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                status="PENDING",
                h_fin=signal.h_fin,
                rsi=signal.rsi,
                v_level=signal.v_level,
                v_trend=signal.v_trend,
                v_rsi=signal.v_rsi,
                v_total=signal.v_total,
                comment=f"FP_v2_{signal.direction}_confidence_{signal.confidence:.2f}"
            )
            
            db.add(trade)
            db.commit()
            db.refresh(trade)
            
            self.log_event("ORDER_PLACED", 
                          f"{signal.direction} {signal.lot_size} lots at {signal.entry_price:.4f}", 
                          signal.symbol,
                          json.dumps({
                              "trade_id": trade.id,
                              "sl": signal.stop_loss,
                              "tp": signal.take_profit,
                              "confidence": signal.confidence,
                              "v_total": signal.v_total
                          }))
            
            return trade
            
        finally:
            db.close()
    
    def update_trades(self, market_data: Dict[str, Dict]) -> List[Dict]:
        """Обновление состояния виртуальных сделок для всех символов"""
        db = get_db_session()
        results = []
        
        try:
            # Получаем все активные сделки для всех символов
            pending_trades = db.query(VirtualTrade).filter(
                VirtualTrade.status == "PENDING"
            ).all()
            
            open_trades = db.query(VirtualTrade).filter(
                VirtualTrade.status == "OPEN"
            ).all()
            
            # Обновляем pending ордера
            for trade in pending_trades:
                if trade.symbol in market_data:
                    current_price = market_data[trade.symbol].get('current_price')
                    if current_price and self._check_order_trigger(trade, current_price):
                        trade.status = "OPEN"
                        trade.opened_at = datetime.utcnow()
                        self.log_event("ORDER_FILLED", 
                                     f"{trade.direction} order filled at {current_price:.4f}", 
                                     trade.symbol)
                        results.append({
                            "action": "ORDER_FILLED",
                            "trade_id": trade.id,
                            "symbol": trade.symbol,
                            "price": current_price
                        })
            
            # Обновляем открытые сделки
            for trade in open_trades:
                if trade.symbol in market_data:
                    current_price = market_data[trade.symbol].get('current_price')
                    if current_price and self._check_exit_conditions(trade, current_price):
                        self._close_trade(trade, current_price, db)
                        results.append({
                            "action": "TRADE_CLOSED",
                            "trade_id": trade.id,
                            "symbol": trade.symbol,
                            "exit_price": current_price,
                            "profit": trade.profit_loss
                        })
            
            db.commit()
            
            # Обновляем просадку для всех счетов
            for symbol in self.symbols:
                self.update_drawdown(symbol)
            
            return results
            
        finally:
            db.close()
    
    def _close_trade(self, trade: VirtualTrade, exit_price: float, db):
        """Закрытие сделки"""
        trade.exit_price = exit_price
        trade.closed_at = datetime.utcnow()
        trade.status = "CLOSED"
        
        # Расчет прибыли/убытка
        if trade.direction == "BUY":
            price_diff = exit_price - trade.entry_price
        else:  # SELL
            price_diff = trade.entry_price - exit_price
        
        # Упрощенный расчет P&L (в реальности нужно знать стоимость пункта)
        trade.profit_loss = price_diff * trade.lot_size * 100  # Предполагаем 100 рублей за пункт
        
        # Комиссия
        trade.commission = abs(trade.entry_price * trade.lot_size * self.commission_rate * 2)  # Вход + выход
        trade.profit_loss -= trade.commission
        
        # Обновляем баланс соответствующего счета
        account = db.query(VirtualAccount).filter(VirtualAccount.id == trade.account_id).first()
        if account:
            account.current_balance += trade.profit_loss
            account.updated_at = datetime.utcnow()
        
        # Логируем
        result_type = "PROFIT" if trade.profit_loss > 0 else "LOSS"
        self.log_event("TRADE_CLOSED", 
                      f"{trade.direction} closed at {exit_price:.4f}, P&L: {trade.profit_loss:.2f}",
                      trade.symbol,
                      json.dumps({
                          "trade_id": trade.id,
                          "entry_price": trade.entry_price,
                          "exit_price": exit_price,
                          "profit_loss": trade.profit_loss,
                          "commission": trade.commission,
                          "result": result_type
                      }))
    
    def get_account_statistics(self, symbol: str = None) -> Dict:
        """Получение статистики счета для конкретного символа или всех символов"""
        if symbol:
            return self._get_single_account_statistics(symbol)
        else:
            return self._get_all_accounts_statistics()
    
    def _get_single_account_statistics(self, symbol: str) -> Dict:
        """Статистика для одного символа"""
        db = get_db_session()
        try:
            account = self.get_account(symbol)
            
            # Статистика сделок
            closed_trades = db.query(VirtualTrade).filter(
                VirtualTrade.symbol == symbol,
                VirtualTrade.status == "CLOSED"
            ).all()
            
            total_trades = len(closed_trades)
            profitable_trades = len([t for t in closed_trades if t.profit_loss > 0])
            losing_trades = len([t for t in closed_trades if t.profit_loss < 0])
            
            total_profit = sum([t.profit_loss for t in closed_trades if t.profit_loss > 0])
            total_loss = sum([t.profit_loss for t in closed_trades if t.profit_loss < 0])
            net_profit = sum([t.profit_loss for t in closed_trades])
            
            # Открытые позиции
            open_positions = db.query(VirtualTrade).filter(
                VirtualTrade.symbol == symbol,
                VirtualTrade.status.in_(["PENDING", "OPEN"])
            ).count()
            
            return {
                "account": {
                    "symbol": account.symbol,
                    "initial_balance": account.initial_balance,
                    "current_balance": account.current_balance,
                    "max_balance": account.max_balance,
                    "current_drawdown": account.current_drawdown,
                    "trading_blocked": account.trading_blocked,
                    "total_return": ((account.current_balance - account.initial_balance) / account.initial_balance * 100)
                },
                "trading": {
                    "total_trades": total_trades,
                    "profitable_trades": profitable_trades,
                    "losing_trades": losing_trades,
                    "win_rate": (profitable_trades / total_trades * 100) if total_trades > 0 else 0,
                    "total_profit": total_profit,
                    "total_loss": total_loss,
                    "net_profit": net_profit,
                    "open_positions": open_positions,
                    "avg_profit": (total_profit / profitable_trades) if profitable_trades > 0 else 0,
                    "avg_loss": (total_loss / losing_trades) if losing_trades > 0 else 0
                }
            }
            
        finally:
            db.close()
    
    def _get_all_accounts_statistics(self) -> Dict:
        """Статистика для всех символов"""
        accounts_stats = {}
        total_balance = 0
        total_initial = 0
        
        for symbol in self.symbols:
            stats = self._get_single_account_statistics(symbol)
            accounts_stats[symbol] = stats
            total_balance += stats["account"]["current_balance"]
            total_initial += stats["account"]["initial_balance"]
        
        total_return = ((total_balance - total_initial) / total_initial * 100) if total_initial > 0 else 0
        
        return {
            "accounts": accounts_stats,
            "summary": {
                "total_balance": total_balance,
                "total_initial": total_initial,
                "total_return": total_return,
                "symbols": self.symbols
            }
        }
    
    def reset_account(self, symbol: str = None):
        """Сброс виртуального счета для символа или всех символов"""
        db = get_db_session()
        try:
            symbols_to_reset = [symbol] if symbol else self.symbols
            
            for sym in symbols_to_reset:
                # Закрываем все открытые сделки
                open_trades = db.query(VirtualTrade).filter(
                    VirtualTrade.symbol == sym,
                    VirtualTrade.status.in_(["PENDING", "OPEN"])
                ).all()
                
                for trade in open_trades:
                    trade.status = "CANCELLED"
                    trade.closed_at = datetime.utcnow()
                
                # Сбрасываем счет
                account = self.get_account(sym)
                account.current_balance = account.initial_balance
                account.max_balance = account.initial_balance
                account.current_drawdown = 0.0
                account.trading_blocked = False
                account.updated_at = datetime.utcnow()
                
                self.log_event("ACCOUNT_RESET", f"Виртуальный счет сброшен", sym)
            
            db.commit()
            
        finally:
            db.close()

    def _check_order_trigger(self, trade: VirtualTrade, current_price: float) -> bool:
        """Проверка срабатывания pending ордера"""
        if trade.direction == "BUY":
            # Лимитный ордер на покупку срабатывает, когда цена опускается до уровня или ниже
            # Стоп ордер на покупку срабатывает, когда цена поднимается до уровня или выше
            # Для упрощения считаем, что это лимитный ордер
            return current_price <= trade.entry_price
        else:  # SELL
            # Лимитный ордер на продажу срабатывает, когда цена поднимается до уровня или выше
            return current_price >= trade.entry_price
    
    def _check_exit_conditions(self, trade: VirtualTrade, current_price: float) -> bool:
        """Проверка условий закрытия сделки"""
        if trade.direction == "BUY":
            # Закрываем по стоп-лоссу или тейк-профиту
            return (current_price <= trade.stop_loss or 
                   current_price >= trade.take_profit)
        else:  # SELL
            return (current_price >= trade.stop_loss or 
                   current_price <= trade.take_profit)
    
    def get_trade_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Получение истории сделок для символа или всех символов"""
        db = get_db_session()
        try:
            query = db.query(VirtualTrade)
            
            if symbol:
                query = query.filter(VirtualTrade.symbol == symbol)
            
            trades = query.order_by(VirtualTrade.created_at.desc()).limit(limit).all()
            
            return [{
                "id": trade.id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "lot_size": trade.lot_size,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
                "status": trade.status,
                "profit_loss": trade.profit_loss,
                "commission": trade.commission,
                "created_at": trade.created_at.isoformat() if trade.created_at else None,
                "opened_at": trade.opened_at.isoformat() if trade.opened_at else None,
                "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
                "comment": trade.comment,
                "indicators": {
                    "h_fin": trade.h_fin,
                    "rsi": trade.rsi,
                    "v_level": trade.v_level,
                    "v_trend": trade.v_trend,
                    "v_rsi": trade.v_rsi,
                    "v_total": trade.v_total
                }
            } for trade in trades]
            
        finally:
            db.close()
    
    def log_event(self, event_type: str, message: str, symbol: str = "", data: str = None):
        """Логирование событий"""
        db = get_db_session()
        try:
            log_entry = StrategyLog(
                symbol=symbol,
                event_type=event_type,
                message=message,
                data=data
            )
            db.add(log_entry)
            db.commit()
        finally:
            db.close()

# Менеджер стратегий для всех символов с отдельными счетами
class StrategyManager:
    """Менеджер стратегий для всех торгуемых символов с отдельными счетами"""
    
    def __init__(self):
        self.symbols = ["SBER", "GAZP", "LKOH", "VTBR"]
        self.trading_engine = VirtualTradingEngine(self.symbols)
        self.strategies: Dict[str, FinancialPotentialStrategy] = {}
        self._load_strategies()
    
    def _load_strategies(self):
        """Загрузка настроек стратегий для всех символов"""
        db = get_db_session()
        try:
            for symbol in self.symbols:
                settings = db.query(StrategySettings).filter(
                    StrategySettings.symbol == symbol
                ).first()
                
                if not settings:
                    # Создаем настройки по умолчанию
                    settings = StrategySettings(symbol=symbol)
                    db.add(settings)
                    db.commit()
                    db.refresh(settings)
                
                self.strategies[symbol] = FinancialPotentialStrategy(settings)
                
        finally:
            db.close()
    
    def analyze_market(self, market_data: Dict[str, Dict]) -> List[StrategySignal]:
        """Анализ рынка и генерация сигналов"""
        signals = []
        
        for symbol in self.symbols:
            if symbol in market_data and symbol in self.strategies:
                data = market_data[symbol]
                if not data.get('candles', pd.DataFrame()).empty and data.get('current_price'):
                    
                    strategy = self.strategies[symbol]
                    signal = strategy.generate_signal(
                        data['candles'], 
                        data['current_price']
                    )
                    
                    if signal.direction != "NONE":
                        signals.append(signal)
        
        return signals
    
    def process_signals(self, signals: List[StrategySignal]) -> List[Dict]:
        """Обработка сигналов и размещение ордеров"""
        results = []
        
        for signal in signals:
            trade = self.trading_engine.place_virtual_order(signal)
            if trade:
                results.append({
                    "action": "ORDER_PLACED",
                    "trade_id": trade.id,
                    "symbol": signal.symbol,
                    "direction": signal.direction,
                    "confidence": signal.confidence
                })
        
        return results

# Тестирование
if __name__ == "__main__":
    from models import create_database
    
    # Создаем базу данных
    create_database()
    
    # Тестируем виртуальную торговлю
    engine = VirtualTradingEngine()
    
    # Получаем статистику
    stats = engine.get_account_statistics()
    print("Статистика счета:", stats)
    
    # Создаем тестовый сигнал
    test_signal = StrategySignal(
        symbol="SBER",
        direction="BUY",
        confidence=0.8,
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=105.0,
        lot_size=1.0,
        h_fin=0.5,
        rsi=35.0,
        v_level=-1.2,
        v_trend=0.1,
        v_rsi=-15.0,
        v_total=-1.1,
        timestamp=datetime.now()
    )
    
    # Размещаем ордер
    trade = engine.place_virtual_order(test_signal)
    if trade:
        print(f"Размещен ордер ID: {trade.id}")
    
    # Получаем историю
    history = engine.get_trade_history(limit=10)
    print(f"История сделок: {len(history)} записей")
