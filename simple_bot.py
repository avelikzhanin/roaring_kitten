#!/usr/bin/env python3
# simple_bot.py - Минимальный бот для тестирования Railway

print("=" * 50, flush=True)
print("SIMPLE BOT STARTING", flush=True)
print("=" * 50, flush=True)

import sys
print(f"Python version: {sys.version}", flush=True)

try:
    import os
    print("✅ os imported", flush=True)
    
    import asyncio
    print("✅ asyncio imported", flush=True)
    
    from telegram import Update
    print("✅ telegram.Update imported", flush=True)
    
    from telegram.ext import Application, CommandHandler, ContextTypes
    print("✅ telegram.ext imported", flush=True)
    
except ImportError as e:
    print(f"❌ Import error: {e}", flush=True)
    sys.exit(1)

# Проверяем переменные окружения
print("\n📋 Checking environment variables:", flush=True)
telegram_token = os.getenv("TELEGRAM_TOKEN")
print(f"TELEGRAM_TOKEN: {'✅ Found' if telegram_token else '❌ Not found'}", flush=True)

database_url = os.getenv("DATABASE_URL")
print(f"DATABASE_URL: {'✅ Found' if database_url else '❌ Not found'}", flush=True)

tinkoff_token = os.getenv("TINKOFF_TOKEN")
print(f"TINKOFF_TOKEN: {'✅ Found' if tinkoff_token else '❌ Not found'}", flush=True)

if not telegram_token:
    print("❌ Cannot start without TELEGRAM_TOKEN", flush=True)
    sys.exit(1)

# Простейшие обработчики
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    print(f"📥 Received /start from user {update.effective_user.id}", flush=True)
    await update.message.reply_text("✅ Bot is working! Database integration disabled for testing.")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /test"""
    print(f"📥 Received /test from user {update.effective_user.id}", flush=True)
    await update.message.reply_text("🔧 Test successful!")

async def main():
    """Основная функция"""
    print("\n🚀 Starting main function...", flush=True)
    
    try:
        # Создаем приложение
        print("📱 Creating application...", flush=True)
        application = Application.builder().token(telegram_token).build()
        print("✅ Application created", flush=True)
        
        # Добавляем обработчики
        print("🎯 Adding handlers...", flush=True)
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("test", test))
        print("✅ Handlers added", flush=True)
        
        # Инициализация
        print("🔄 Initializing bot...", flush=True)
        await application.initialize()
        print("✅ Bot initialized", flush=True)
        
        # Запуск
        print("▶️ Starting bot...", flush=True)
        await application.start()
        print("✅ Bot started", flush=True)
        
        # Polling
        print("👂 Starting polling...", flush=True)
        await application.updater.start_polling(drop_pending_updates=True)
        print("✅ Polling started", flush=True)
        
        print("\n" + "=" * 50, flush=True)
        print("🎉 BOT IS RUNNING!", flush=True)
        print("Try sending /start or /test to your bot", flush=True)
        print("=" * 50 + "\n", flush=True)
        
        # Держим бота живым
        while True:
            await asyncio.sleep(60)
            print("💓 Bot is alive...", flush=True)
            
    except Exception as e:
        print(f"❌ Error in main: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    print("📌 Starting from __main__", flush=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user", flush=True)
    except Exception as e:
        print(f"💥 Fatal error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
