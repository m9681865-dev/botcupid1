import os
import threading
import logging
import time
import asyncio
from flask import Flask
from Kupidon import bot, dp  # Убедитесь, что эти объекты существуют в Kupidon.py

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health_check():
    """Эндпоинт для проверки работоспособности."""
    return "OK", 200

def run_bot():
    """Запускает бота с использованием aiogram 3.x."""
    try:
        # Создаем и запускаем новый цикл событий для этого потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем поллинг
        loop.run_until_complete(dp.start_polling(bot, skip_updates=True))
    except Exception as e:
        logging.error(f"Бот упал: {e}")
        # Попытка перезапуска через несколько секунд
        time.sleep(5)
        run_bot()

if __name__ == "__main__":
    # Создаем необходимые папки
    os.makedirs('sessions', exist_ok=True)
    os.makedirs('my_sessions', exist_ok=True)
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask-сервер, который будет держать хост активным
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
