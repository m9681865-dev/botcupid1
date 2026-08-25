import os
import threading
import logging
import time
import asyncio
from flask import Flask
from Kupidon import bot, dp

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health_check():
    return "OK", 200

def run_flask():
    """Запускает Flask в отдельном потоке"""
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

async def run_bot():
    """Запускает бота в главном потоке"""
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logging.error(f"Бот упал: {e}")
        await asyncio.sleep(5)
        await run_bot()

if __name__ == "__main__":
    os.makedirs('sessions', exist_ok=True)
    os.makedirs('my_sessions', exist_ok=True)
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем бота в главном потоке
    asyncio.run(run_bot())
