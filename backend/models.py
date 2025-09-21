from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List
import json

Base = declarative_base()

# SQLAlchemy модели
class StrategySettings(Base):
    """Настройки стратегии"""
    __tablename__ = "strategy_settings"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False)
    
    # Индикаторы
    atr_period = Column(Integer, default=14)
    rsi_period = Column(Integer, default=14)
    ema_period = Column(Integer, default=20)
    
    # Уровни и потенциалы
    threshold_level = Column(Float, default=0.4)
    level_radius_factor = Column(Float, default=4.5)
    min_potential_strength = Column(Float, default=0.6)
    
    # Управление рисками
    risk_percent = Column(Float, default=0.7)
    dynamic_lot = Column(Boolean, default=True)
    base_lot = Column(Float, default=0.03)
    min_lot = Column(Float, default=0.01)
    
    # Защита от просадки
    max_drawdown_percent = Column(Float, default=25.0)
    reduce_risk_on_drawdown = Column(Boolean, default=True)
    drawdown_risk_reduction = Column(Float, default=0.5)
    
    # SL/TP
    stop_loss_atr = Column(Float, default=2.5)
    take_profit_atr = Column(Float, default=3.5)
    enable_ladder = Column(Boolean, default=False)
    ladder_count = Column(Integer, default=2)
    ladder_step_atr = Column(Float, default=0.4)
    
    # Сигналы
    buy_rsi_threshold = Column(Float, default=40.0)
    sell_rsi_threshold = Column(Float, default=60.0)
    buy_threshold_multiplier = Column(Float, default=1.0)
    sell_threshold_multiplier = Column(Float, default=1.3)
    
    # Фильтры
    use_volatility_filter = Column(Boolean, default=True)
    max_atr_multiplier = Column(Float, default=2.2)
    use_volume_filter = Column(Boolean, default=True)
    min_volume_ratio = Column(Float, default=1.2)
    
    # Режимы
    mode = Column(String(20), default="LIMIT")  # LIMIT или BREAKOUT
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class VirtualAccount(Base):
    """Виртуальный торговый счет"""
    __tablename__ = "virtual_account"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False, unique=True)  # Уникальный счет для каждого символа
    initial_balance = Column(Float, default=100000.0)
    current_balance = Column(Float, default=100000.0)
    max_balance = Column(Float, default=100000.0)
    current_drawdown = Column(Float, default=0.0)
    trading_blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class VirtualTrade(Base):
    """Виртуальная сделка"""
    __tablename__ = "virtual_trades"
    
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("virtual_account.id"))
    symbol = Column(String(10), nullable=False)
    
    # Параметры сделки
    direction = Column(String(10), nullable=False)  # BUY, SELL
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    lot_size = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    
    # Статус
    status = Column(String(20), default="PENDING")  # PENDING, OPEN, CLOSED, CANCELLED
    
    # Результат
    profit_loss = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    
    # Данные стратегии
    h_fin = Column(Float, nullable=True)
    rsi = Column(Float, nullable=True)
    v_level = Column(Float, nullable=True)
    v_trend = Column(Float, nullable=True)
    v_rsi = Column(Float, nullable=True)
    v_total = Column(Float, nullable=True)
    
    # Временные метки
    created_at = Column(DateTime, default=datetime.utcnow)
    opened_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    
    # Комментарий
    comment = Column(Text, nullable=True)
    
    account = relationship("VirtualAccount")

class StrategyLog(Base):
    """Лог событий стратегии"""
    __tablename__ = "strategy_logs"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    symbol = Column(String(10), nullable=False)
    event_type = Column(String(50), nullable=False)  # SIGNAL, TRADE, ERROR, INFO
    message = Column(Text, nullable=False)
    data = Column(Text, nullable=True)  # JSON данные

class MarketLevel(Base):
    """Уровни поддержки/сопротивления"""
    __tablename__ = "market_levels"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False)
    price = Column(Float, nullable=False)
    strength = Column(Float, nullable=False)
    is_resistance = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    level_time = Column(DateTime, nullable=False)

# Pydantic модели для API
class StrategySettingsRequest(BaseModel):
    symbol: str
    # Индикаторы
    atr_period: int = 14
    rsi_period: int = 14
    ema_period: int = 20
    
    # Уровни и потенциалы
    threshold_level: float = 0.4
    level_radius_factor: float = 4.5
    min_potential_strength: float = 0.6
    
    # Управление рисками
    risk_percent: float = 0.7
    dynamic_lot: bool = True
    base_lot: float = 0.03
    min_lot: float = 0.01
    
    # Защита от просадки
    max_drawdown_percent: float = 25.0
    reduce_risk_on_drawdown: bool = True
    drawdown_risk_reduction: float = 0.5
    
    # Защита от волатильности
    use_volatility_filter: bool = True
    max_atr_multiplier: float = 2.2
    atr_period_for_avg: int = 50
    
    # SL/TP
    stop_loss_atr: float = 2.5
    take_profit_atr: float = 3.5
    enable_ladder: bool = False
    ladder_count: int = 2
    ladder_step_atr: float = 0.4
    
    # Сигналы
    buy_rsi_threshold: float = 40.0
    sell_rsi_threshold: float = 60.0
    buy_threshold_multiplier: float = 1.0
    sell_threshold_multiplier: float = 1.3
    
    # Фильтры
    use_volume_filter: bool = True
    min_volume_ratio: float = 1.2
    volume_period: int = 20
    
    # Режимы
    mode: str = "LIMIT"

class StrategySettingsResponse(BaseModel):
    id: int
    symbol: str
    atr_period: int
    rsi_period: int
    ema_period: int
    threshold_level: float
    level_radius_factor: float
    min_potential_strength: float
    risk_percent: float
    dynamic_lot: bool
    base_lot: float
    min_lot: float
    max_drawdown_percent: float
    reduce_risk_on_drawdown: bool
    drawdown_risk_reduction: float
    stop_loss_atr: float
    take_profit_atr: float
    enable_ladder: bool
    ladder_count: int
    ladder_step_atr: float
    buy_rsi_threshold: float
    sell_rsi_threshold: float
    buy_threshold_multiplier: float
    sell_threshold_multiplier: float
    use_volatility_filter: bool
    max_atr_multiplier: float
    use_volume_filter: bool
    min_volume_ratio: float
    mode: str
    created_at: datetime
    updated_at: datetime

class VirtualTradeResponse(BaseModel):
    id: int
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    lot_size: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    status: str
    profit_loss: float
    commission: float
    h_fin: Optional[float]
    rsi: Optional[float]
    v_level: Optional[float]
    v_trend: Optional[float]
    v_rsi: Optional[float]
    v_total: Optional[float]
    created_at: datetime
    opened_at: Optional[datetime]
    closed_at: Optional[datetime]
    comment: Optional[str]

class AccountResponse(BaseModel):
    id: int
    symbol: str
    initial_balance: float
    current_balance: float
    max_balance: float
    current_drawdown: float
    trading_blocked: bool
    created_at: datetime
    updated_at: datetime

class AccountsStatisticsResponse(BaseModel):
    accounts: Dict[str, AccountResponse]
    trading_statistics: Dict[str, Dict]
    total_balance: float
    total_return: float

class MarketDataResponse(BaseModel):
    symbol: str
    current_price: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    volume: Optional[float]
    last_update: str

class StrategySignal(BaseModel):
    symbol: str
    direction: str  # BUY, SELL, NONE
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    h_fin: float
    rsi: float
    v_level: float
    v_trend: float
    v_rsi: float
    v_total: float
    timestamp: datetime

# Создание базы данных
def create_database():
    """Создание базы данных и таблиц"""
    import os
    
    # Проверяем переменную окружения DATABASE_URL от Railway
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # PostgreSQL на Railway
        print("🐘 Используется PostgreSQL (Railway)")
        engine = create_engine(database_url)
    else:
        # SQLite для локальной разработки
        print("🗄️ Используется SQLite (локально)")
        engine = create_engine("sqlite:///fp_strategy.db")
    
    Base.metadata.create_all(engine)
    return engine

def get_db_session():
    """Получение сессии базы данных"""
    import os
    
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        engine = create_engine(database_url)
    else:
        engine = create_engine("sqlite:///fp_strategy.db")
        
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()

if __name__ == "__main__":
    # Создание базы данных
    create_database()
    print("База данных создана успешно!")
