import logging
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn

from database import db
from config import SUPPORTED_STOCKS
from stock_service import StockService
from fear_greed_index import fear_greed

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Revushiy Kotenok Dashboard")

# Фильтр по пользователю
TARGET_USERNAME = 'matve1ch'

# Дата начала торговли
TRADING_START_DATE = datetime(2025, 10, 1)

# Сервис для получения данных акций
stock_service = StockService()

# Подключаем статические файлы и шаблоны
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    """Подключение к БД при старте"""
    await db.connect()
    logger.info("✅ Web Dashboard started")


@app.on_event("shutdown")
async def shutdown():
    """Отключение от БД при остановке"""
    await db.disconnect()
    logger.info("👋 Web Dashboard stopped")


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    year: Optional[int] = None, 
    month: Optional[int] = None,
    ticker_year: Optional[int] = None,
    ticker_month: Optional[int] = None,
    feed_type: Optional[str] = None
):
    """Главная страница дашборда"""
    
    if year is None or month is None:
        now = datetime.now()
        year = now.year
        month = now.month
    
    try:
        # Получаем общую статистику за месяц
        monthly_stats_all = await db.get_global_monthly_statistics(year, month, username=TARGET_USERNAME)
        
        open_positions = await db.get_all_open_positions_web(username=TARGET_USERNAME)
        
        # Статистика по акциям с фильтром по месяцу
        if ticker_year and ticker_month:
            ticker_stats_all = await db.get_statistics_by_ticker_filtered(
                username=TARGET_USERNAME, 
                year=ticker_year, 
                month=ticker_month
            )
            ticker_filter_label = datetime(ticker_year, ticker_month, 1).strftime("%B %Y")
            
            chart_data_response = await db.get_cumulative_profit_data(
                username=TARGET_USERNAME,
                year=ticker_year,
                month=ticker_month
            )
        else:
            ticker_stats_all = await db.get_statistics_by_ticker(username=TARGET_USERNAME)
            ticker_filter_label = "за всё время"
            
            chart_data_response = await db.get_cumulative_profit_data(username=TARGET_USERNAME)
        
        chart_data_raw = chart_data_response.get('data', {})
        start_date = chart_data_response.get('start_date')
        
        # Лента сделок
        if feed_type and feed_type != 'all':
            closed_positions = await db.get_all_closed_positions_web(
                limit=50, username=TARGET_USERNAME, position_type=feed_type
            )
        else:
            closed_positions = await db.get_all_closed_positions_web(
                limit=50, username=TARGET_USERNAME
            )
        
        # Раздел "Дополнительно"
        best_trade = None
        worst_trade = None
        avg_duration_str = "Н/Д"
        
        try:
            async with db.pool.acquire() as conn:
                best_row = await conn.fetchrow("""
                    SELECT ticker, position_type, profit_percent, exit_time
                    FROM positions
                    WHERE is_open = FALSE
                    ORDER BY profit_percent DESC
                    LIMIT 1
                """)
                if best_row:
                    best_trade = dict(best_row)
        except Exception as e:
            logger.error(f"Error getting best trade: {e}")
        
        try:
            async with db.pool.acquire() as conn:
                worst_row = await conn.fetchrow("""
                    SELECT ticker, position_type, profit_percent, exit_time
                    FROM positions
                    WHERE is_open = FALSE
                    ORDER BY profit_percent ASC
                    LIMIT 1
                """)
                if worst_row:
                    worst_trade = dict(worst_row)
        except Exception as e:
            logger.error(f"Error getting worst trade: {e}")
        
        try:
            async with db.pool.acquire() as conn:
                avg_hours = await conn.fetchval("""
                    SELECT AVG(EXTRACT(EPOCH FROM (exit_time - entry_time)) / 3600)
                    FROM positions
                    WHERE is_open = FALSE
                """)
                if avg_hours:
                    if avg_hours < 24:
                        avg_duration_str = f"{avg_hours:.1f} часов"
                    else:
                        avg_duration_str = f"{avg_hours / 24:.1f} дней"
        except Exception as e:
            logger.error(f"Error getting avg duration: {e}")
        
        # Добавляем имена и эмодзи к акциям
        for pos in open_positions:
            ticker = pos['ticker']
            pos['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            pos['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
            
            try:
                stock_data = await stock_service.get_stock_data(ticker)
                if stock_data:
                    pos['current_price'] = stock_data.price.current_price
                    entry_price = float(pos['entry_price'])
                    position_type = pos['position_type']
                    
                    if position_type == 'LONG':
                        current_profit = ((pos['current_price'] - entry_price) / entry_price) * 100
                    else:
                        current_profit = ((entry_price - pos['current_price']) / entry_price) * 100
                    
                    pos['current_profit'] = current_profit
                else:
                    pos['current_price'] = None
                    pos['current_profit'] = None
            except Exception as e:
                logger.error(f"Error getting current price for {ticker}: {e}")
                pos['current_price'] = None
                pos['current_profit'] = None
        
        for pos in closed_positions:
            ticker = pos['ticker']
            pos['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            pos['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
            duration = pos['exit_time'] - pos['entry_time']
            duration_hours = duration.total_seconds() / 3600
            if duration_hours < 24:
                pos['duration_str'] = f"{duration_hours:.1f}ч"
            else:
                pos['duration_str'] = f"{duration_hours / 24:.1f}д"
        
        for stat in ticker_stats_all:
            ticker = stat['ticker']
            stat['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            stat['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        if best_trade:
            ticker = best_trade['ticker']
            best_trade['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            best_trade['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        if worst_trade:
            ticker = worst_trade['ticker']
            worst_trade['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            worst_trade['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        # Формируем список месяцев
        months_list = []
        current_date = datetime.now()
        temp_date = datetime(current_date.year, current_date.month, 1)
        
        while temp_date >= TRADING_START_DATE:
            months_list.append({
                'year': temp_date.year,
                'month': temp_date.month,
                'label': temp_date.strftime("%B %Y")
            })
            
            if temp_date.month == 1:
                temp_date = datetime(temp_date.year - 1, 12, 1)
            else:
                temp_date = datetime(temp_date.year, temp_date.month - 1, 1)
        
        # Формируем данные для графика прибыли
        chart_data = {}
        for ticker in SUPPORTED_STOCKS.keys():
            chart_data[ticker] = {
                'label': f"{SUPPORTED_STOCKS[ticker]['emoji']} {ticker}",
                'data': []
            }
        
        for ticker, points in chart_data_raw.items():
            if ticker in chart_data:
                chart_data[ticker]['data'] = [
                    {
                        'x': point['date'].strftime('%Y-%m-%d %H:%M:%S'),
                        'y': round(point['cumulative_profit'], 2)
                    }
                    for point in points
                ]
        
        chart_data_json = json.dumps(chart_data)
        
        # Fear & Greed Index
        fg_latest = await db.get_fear_greed_latest()
        fg_history = await db.get_fear_greed_history(days=90)
        
        fg_chart_data = json.dumps([
            {'date': row['date'].strftime('%Y-%m-%d'), 'value': row['value']}
            for row in fg_history
        ])
        
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "year": year,
                "month": month,
                "month_name": datetime(year, month, 1).strftime("%B %Y"),
                "months_list": months_list,
                "monthly_stats_all": monthly_stats_all,
                "open_positions": open_positions,
                "closed_positions": closed_positions,
                "ticker_stats_all": ticker_stats_all,
                "ticker_filter_label": ticker_filter_label,
                "ticker_year": ticker_year,
                "ticker_month": ticker_month,
                "feed_type": feed_type or 'all',
                "best_trade": best_trade,
                "worst_trade": worst_trade,
                "avg_duration_str": avg_duration_str,
                "chart_data_json": chart_data_json,
                "fg_latest": fg_latest,
                "fg_chart_data": fg_chart_data,
            }
        )
    
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}", exc_info=True)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "error": str(e)
            }
        )


@app.post("/api/fear-greed/refresh")
async def refresh_fear_greed():
    """Пересчитать индекс страха и жадности прямо сейчас"""
    try:
        result = await fear_greed.calculate()
        if result:
            await db.save_fear_greed(result)
            logger.info(f"✅ Fear & Greed Index refreshed: {result['value']} ({result['label']})")
        else:
            logger.warning("⚠️ Failed to calculate Fear & Greed Index on refresh")
    except Exception as e:
        logger.error(f"❌ Error refreshing Fear & Greed Index: {e}", exc_info=True)
    
    return RedirectResponse(url="/", status_code=303)


@app.get("/health")
async def health_check():
    """Health check endpoint для Railway"""
    return {"status": "ok"}


@app.get("/top-trades", response_class=HTMLResponse)
async def top_trades(request: Request, type: str = "best", position_type: str = None):
    """Страница топ-10 лучших или худших сделок"""
    try:
        is_best = type == "best"
        trades = await db.get_top_trades(username=TARGET_USERNAME, limit=10, best=is_best, position_type=position_type)
        
        for trade in trades:
            ticker = trade['ticker']
            trade['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            trade['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        if position_type == 'LONG':
            title_suffix = " (LONG)"
        elif position_type == 'SHORT':
            title_suffix = " (SHORT)"
        else:
            title_suffix = ""
        
        title = f"🏆 Топ-10 лучших сделок{title_suffix}" if is_best else f"📉 Топ-10 худших сделок{title_suffix}"
        
        return templates.TemplateResponse(
            "top_trades.html",
            {
                "request": request,
                "title": title,
                "trades": trades,
                "is_best": is_best
            }
        )
    
    except Exception as e:
        logger.error(f"Error loading top trades: {e}", exc_info=True)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "error": str(e)
            }
        )


if __name__ == "__main__":
    uvicorn.run(
        "web_dashboard:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )
