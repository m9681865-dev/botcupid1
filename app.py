import os
import threading
import logging
import time
from flask import Flask
from Kupidon import bot, dp
from aiogram.utils import executor

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    try:
        executor.start_polling(dp, skip_updates=True)
    except Exception as e:
        logging.error(f"Бот упал: {e}")
        time.sleep(5)
        run_bot()

if __name__ == "__main__":
    os.makedirs('sessions', exist_ok=True)
    os.makedirs('my_sessions', exist_ok=True)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)