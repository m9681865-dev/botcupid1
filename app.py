import os
import threading
import logging
import time
from flask import Flask
from Kupidon import bot, dp  # Импорт вашего бота и диспетчера

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    """Запускает бота в асинхронном режиме для aiogram 3.x"""
    try:
        # В aiogram 3.x запуск через executor удален, используем async-запуск
        import asyncio
        from aiogram.types import BotCommand
        
        async def main():
            # Установка команд для бота (опционально)
            await bot.set_my_commands([
                BotCommand(command="/start", description="Запустить бота"),
                BotCommand(command="/help", description="Помощь")
            ])
            
            # Запуск поллинга
            await dp.start_polling(bot, skip_updates=True)
        
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Бот упал: {e}")
        time.sleep(5)
        run_bot()

if __name__ == "__main__":
    # Создаем необходимые папки
    os.makedirs('sessions', exist_ok=True)
    os.makedirs('my_sessions', exist_ok=True)
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask-сервер для поддержания работы на Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
