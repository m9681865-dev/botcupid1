import asyncio
import random
import logging
import sqlite3
import re
import requests
import json
import os

from aiohttp import web

from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    LabeledPrice,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    KeyboardButton
)


TOKEN = "8982055607:AAEKKBdUejE8rwZVGldY-MUxWe6X1GOjkSI"
ADMIN_ID = 7806482040
OWNER_ID = 7806482040
CHANNEL_ID = -1004428565734

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

bot = Bot(TOKEN)
dp = Dispatcher()

# ===================== НАСТРОЙКА БАЗЫ ДАННЫХ =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "cupid.db")

try:
    test_file = os.path.join(BASE_DIR, "test_write.tmp")
    with open(test_file, "w") as f:
        f.write("test")
    os.remove(test_file)
except Exception:
    DB_PATH = "/tmp/cupid.db"
    logging.warning(f"Использую временную базу: {DB_PATH}")

db = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = db.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS posts(
    number INTEGER PRIMARY KEY,
    message_id_1 INTEGER,
    message_id_2 INTEGER,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    created_at TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    role TEXT DEFAULT 'user'
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS moderators(
    user_id INTEGER PRIMARY KEY,
    buy_date TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS vip_posts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_number INTEGER,
    vip_type TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    unpin_time TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS probit_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    query TEXT,
    result TEXT,
    created_at TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS bans(
    user_id INTEGER PRIMARY KEY,
    ban_until TEXT,
    reason TEXT,
    banned_by INTEGER
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS appeals(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    question TEXT,
    answer TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT,
    answered_at TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS vip_users(
    user_id INTEGER PRIMARY KEY,
    vip_type TEXT,
    expires_at TEXT,
    created_at TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS delete_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_number INTEGER,
    user_id INTEGER,
    username TEXT,
    deleted_at TEXT,
    status TEXT
)""")

db.commit()
logging.info(f"База данных: {DB_PATH}")


def get_role(user_id):
    cur.execute("SELECT role FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else "user"


def set_role(user_id, role):
    cur.execute("INSERT OR REPLACE INTO users(user_id, role) VALUES(?, ?)", (user_id, role))
    db.commit()


def is_admin(user_id):
    return user_id == ADMIN_ID or user_id == OWNER_ID


def ban_user(user_id, duration_seconds, reason="", banned_by=ADMIN_ID):
    ban_until = (datetime.now() + timedelta(seconds=duration_seconds)).isoformat()
    cur.execute("INSERT OR REPLACE INTO bans(user_id, ban_until, reason, banned_by) VALUES(?, ?, ?, ?)",
                (user_id, ban_until, reason, banned_by))
    db.commit()
    return ban_until


def unban_user(user_id):
    cur.execute("DELETE FROM bans WHERE user_id=?", (user_id,))
    db.commit()


def is_banned(user_id):
    cur.execute("SELECT ban_until, reason FROM bans WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        return False, None, None
    ban_until_str, reason = row
    ban_until = datetime.fromisoformat(ban_until_str)
    if datetime.now() > ban_until:
        unban_user(user_id)
        return False, None, None
    return True, ban_until, reason


def get_all_bans():
    cur.execute("SELECT user_id, ban_until, reason, banned_by FROM bans")
    return cur.fetchall()


def save_post(message_id_1, message_id_2, user_id, username=None, first_name=None):
    try:
        cur.execute("SELECT MAX(number) FROM posts")
        last = cur.fetchone()[0]
        number = 1 if last is None else last + 1
        
        cur.execute("""INSERT INTO posts(number, message_id_1, message_id_2, user_id, username, first_name, created_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?)""",
                    (number, message_id_1, message_id_2, user_id, username, first_name, datetime.now().isoformat()))
        db.commit()
        logging.info(f"✅ Пост №{number} сохранен в БД")
        return number
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения поста: {e}")
        return None


def get_post(number):
    try:
        cur.execute("SELECT message_id_1, message_id_2, user_id, username, first_name, created_at FROM posts WHERE number=?",
                    (number,))
        return cur.fetchone()
    except Exception as e:
        logging.error(f"❌ Ошибка получения поста: {e}")
        return None


def remove_post(number):
    try:
        cur.execute("DELETE FROM posts WHERE number=?", (number,))
        db.commit()
        logging.info(f"✅ Пост №{number} удален из БД")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка удаления поста из БД: {e}")
        db.rollback()
        return False


def get_all_posts():
    try:
        cur.execute("SELECT number, user_id, username, first_name, created_at FROM posts ORDER BY number DESC")
        return cur.fetchall()
    except Exception as e:
        logging.error(f"❌ Ошибка получения всех постов: {e}")
        return []


def get_user_posts(user_id):
    try:
        cur.execute("SELECT number, message_id_1, message_id_2, created_at FROM posts WHERE user_id=? ORDER BY number DESC",
                    (user_id,))
        return cur.fetchall()
    except Exception as e:
        logging.error(f"❌ Ошибка получения постов пользователя: {e}")
        return []


def log_delete(post_number, user_id, username, status):
    try:
        cur.execute("""INSERT INTO delete_logs(post_number, user_id, username, deleted_at, status)
                       VALUES(?, ?, ?, ?, ?)""",
                    (post_number, user_id, username, datetime.now().isoformat(), status))
        db.commit()
    except:
        pass


# ============= VIP ФУНКЦИИ =============
def set_vip(user_id, vip_type, days=2):
    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    cur.execute("""INSERT OR REPLACE INTO vip_users(user_id, vip_type, expires_at, created_at)
                   VALUES(?, ?, ?, ?)""",
                (user_id, vip_type, expires_at, datetime.now().isoformat()))
    db.commit()
    set_role(user_id, "vip")


def get_vip(user_id):
    cur.execute("SELECT vip_type, expires_at FROM vip_users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        return None, None
    vip_type, expires_at_str = row
    expires_at = datetime.fromisoformat(expires_at_str)
    if datetime.now() > expires_at:
        cur.execute("DELETE FROM vip_users WHERE user_id=?", (user_id,))
        db.commit()
        set_role(user_id, "user")
        return None, None
    return vip_type, expires_at


def check_and_clean_vips():
    cur.execute("SELECT user_id, expires_at FROM vip_users")
    rows = cur.fetchall()
    for user_id, expires_at_str in rows:
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now() > expires_at:
            cur.execute("DELETE FROM vip_users WHERE user_id=?", (user_id,))
            db.commit()
            set_role(user_id, "user")


# ============= ДАННЫЕ =============
wishes = [
    "🔥 Нехай цей вечір запам'ятається надовго!",
    "❤️ Сподіваюся, ви знайдете спільну мову!",
    "💀 Готуйтеся до найцікавішого!",
    "🎉 Удачі вам обом!",
    "💎 Ви — як преміум-підписка: всі хочуть, але не всі готові платити",
    "🤝 Ці двоє точно знайдуть спільну мову!",
    "🍺 Нехай ваше знайомство буде міцним, як хороша кава!",
    "🔥 Сподіваюся, ви не пошкодуєте про свій вибір!",
    "💘 Нехай цей день стане початком чогось більшого!",
    "🤡 Або просто початком нового мему...",
    "🎯 Ви потрапили в саме серце цього чату!",
    "⚡ Ваша зустріч — це як спалах блискавки!",
    "💩 Я бажаю вам не посваритися в перший же вечір..."
]

photos = {}
pending = {}
waiting_delete = {}
waiting_pin = set()
waiting_question = set()
auto_approve = False


# ============= ПРОБИТ ФУНКЦИИ =============
def save_probit_history(user_id, query, result):
    cur.execute("""INSERT INTO probit_history(user_id, query, result, created_at)
                   VALUES(?, ?, ?, ?)""",
                (user_id, query, json.dumps(result, ensure_ascii=False), datetime.now().isoformat()))
    db.commit()


def get_probit_history(user_id, limit=20):
    cur.execute("SELECT query, result, created_at FROM probit_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit))
    return cur.fetchall()


async def collect_info(query):
    result = {
        'query': query, 'type': 'unknown', 'tg_id': None, 'username': None,
        'first_name': None, 'last_name': None, 'bio': None,
        'premium': False, 'verified': False, 'scam': False, 'restricted': False,
        'breaches': [], 'location': {}, 'social': {}
    }

    if query.startswith('@'):
        result['type'] = 'username'
        result['username'] = query[1:]
    elif query.startswith('https://t.me/'):
        result['type'] = 'link'
        result['username'] = query.split('/')[-1]
    elif re.match(r'^\+?\d{10,15}$', query.replace(' ', '')):
        result['type'] = 'phone'
        result['phone'] = query.replace(' ', '')
    else:
        result['type'] = 'username'
        result['username'] = query

    if result.get('username'):
        try:
            resp = requests.get(f'https://t.me/{result["username"]}', timeout=10,
                                headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                html = resp.text
                name_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                if name_match:
                    result['first_name'] = name_match.group(1)
                bio_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
                if bio_match:
                    result['bio'] = bio_match.group(1)[:200]
                if 'premium' in html.lower():
                    result['premium'] = True
                if 'verified' in html.lower():
                    result['verified'] = True
        except:
            pass

    if result.get('phone'):
        try:
            resp = requests.get(f'https://haveibeenpwned.com/api/v3/breachedaccount/{result["phone"]}', timeout=10)
            if resp.status_code == 200:
                result['breaches'] = [b.get('Name', 'Unknown') for b in resp.json()]
        except:
            pass

    if result.get('phone'):
        try:
            resp = requests.get(f'http://ip-api.com/json/{result["phone"]}', timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'success':
                    result['location'] = {
                        'country': data.get('country'), 'city': data.get('city'),
                        'region': data.get('regionName'), 'isp': data.get('isp'),
                        'lat': data.get('lat'), 'lon': data.get('lon')
                    }
        except:
            pass

    if result.get('username'):
        social_platforms = {
            'Telegram': f'https://t.me/{result["username"]}',
            'Instagram': f'https://www.instagram.com/{result["username"]}',
            'GitHub': f'https://github.com/{result["username"]}',
            'Twitter': f'https://twitter.com/{result["username"]}',
            'VK': f'https://vk.com/{result["username"]}',
            'YouTube': f'https://www.youtube.com/@{result["username"]}',
            'Reddit': f'https://www.reddit.com/user/{result["username"]}',
            'LinkedIn': f'https://www.linkedin.com/in/{result["username"]}'
        }
        for platform, url in social_platforms.items():
            try:
                resp = requests.head(url, timeout=5)
                if resp.status_code == 200:
                    result['social'][platform] = url
            except:
                pass

    save_probit_history(ADMIN_ID, query, result)
    return result


def format_probit_report(data):
    output = f"🔍 <b>ПРОБИВ:</b> {data['query']}\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    output += "🎯 <b>ОСНОВНАЯ ИНФОРМАЦИЯ:</b>\n"
    if data.get('type'):
        output += f"├ Тип: {data['type']}\n"
    if data.get('tg_id'):
        output += f"├ Telegram ID: <code>{data['tg_id']}</code>\n"
    if data.get('first_name'):
        output += f"├ Имя: {data['first_name']}\n"
    if data.get('last_name'):
        output += f"├ Фамилия: {data['last_name']}\n"
    if data.get('username'):
        output += f"├ Username: @{data['username']}\n"
    if data.get('phone'):
        output += f"├ Номер: <code>{data['phone']}</code>\n"
    if data.get('bio'):
        output += f"├ Bio: {data['bio'][:100]}...\n"
    output += f"├ Premium: {'✅ Да' if data.get('premium') else '❌ Нет'}\n"
    output += f"├ Верифицирован: {'✅ Да' if data.get('verified') else '❌ Нет'}\n"
    output += f"├ Scam: {'⚠️ ДА' if data.get('scam') else '✅ Нет'}\n"
    output += f"└ Ограничен: {'⚠️ ДА' if data.get('restricted') else '✅ Нет'}\n\n"
    if data.get('breaches'):
        output += "⚠️ <b>УТЕЧКИ ДАННЫХ:</b>\n"
        for b in data['breaches'][:5]:
            output += f"├ {b}\n"
        output += "\n"
    if data.get('location'):
        loc = data['location']
        output += "🌍 <b>ГЕОЛОКАЦИЯ:</b>\n"
        if loc.get('country'):
            output += f"├ Страна: {loc['country']}\n"
        if loc.get('city'):
            output += f"├ Город: {loc['city']}\n"
        if loc.get('region'):
            output += f"├ Регион: {loc['region']}\n"
        if loc.get('isp'):
            output += f"├ Провайдер: {loc['isp']}\n"
        if loc.get('lat') and loc.get('lon'):
            output += f"└ Координаты: {loc['lat']}, {loc['lon']}\n"
        output += "\n"
    if data.get('social'):
        output += "🔗 <b>СОЦИАЛЬНЫЕ СЕТИ:</b>\n"
        for platform, url in data['social'].items():
            output += f"├ {platform}: {url}\n"
        output += "\n"
    output += "📊 <b>ВЕРДИКТ:</b>\n"
    output += "⚠️ <b>АККАУНТ ПОДОЗРИТЕЛЬНЫЙ</b>" if data.get('scam') or data.get('restricted') else "✅ Аккаунт чистый"
    return output


# ============= МЕНЮ =============
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💌 Створити пару")],
            [KeyboardButton(text="💎 VIP послуги")],
            [KeyboardButton(text="⭐ Послуги")],
            [KeyboardButton(text="📜 Правила")],
            [KeyboardButton(text="❓ Питання до адміна")]
        ],
        resize_keyboard=True
    )


def vip_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Базовий VIP — 10 ⭐", callback_data="vip_basic")],
            [InlineKeyboardButton(text="👑 Premium VIP — 25 ⭐", callback_data="vip_premium")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
        ]
    )


def services_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📌 Закріпити анкету — 5 ⭐", callback_data="buy_pin")],
            [InlineKeyboardButton(text="🗑 Видалити пост — 5 ⭐", callback_data="buy_delete")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")]
        ]
    )


def admin_menu():
    status = "🟢 УВІМКНЕНО" if auto_approve else "🔴 ВИМКНЕНО"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⚙️ Автоматичне схвалення: {status}", callback_data="auto_approve_menu")],
            [InlineKeyboardButton(text="🟢 Увімкнути", callback_data="auto_approve_on")],
            [InlineKeyboardButton(text="🔴 Зупинити", callback_data="auto_approve_off")]
        ]
    )


# ============= КОМАНДЫ =============
@dp.message(Command("start"))
async def start(message: Message):
    banned, until, reason = is_banned(message.from_user.id)
    if banned:
        await message.answer(f"🚫 Ви забанені до {until.strftime('%d.%m.%Y %H:%M')}")
        return
    await message.answer(
        "💘 Ласкаво просимо в Купідон!\n\nСтворюй пари та знаходь кохання ❤️",
        reply_markup=main_menu()
    )


@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    status = "🟢 УВІМКНЕНО" if auto_approve else "🔴 ВИМКНЕНО"
    await message.answer(f"👑 АДМІН-ПАНЕЛЬ\n\n⚙️ Автоматичне схвалення: {status}", reply_markup=admin_menu())


@dp.message(Command("check_channel"))
async def check_channel_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Только админ!")
        return
    
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(CHANNEL_ID, me.id)
        
        await message.answer(
            f"📊 **ПРАВА БОТА В КАНАЛЕ**\n\n"
            f"Статус: {member.status}\n"
            f"Удаление: {'✅' if member.can_delete_messages else '❌ НЕТ!'}\n"
            f"Закрепление: {'✅' if member.can_pin_messages else '❌ НЕТ!'}\n\n"
            f"Если удаление НЕТ - добавьте бота в админы!"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("probit"))
async def probit_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ запрещен. Только для администратора.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /probit <номер или @username>")
        return
    query = args[1].strip()
    status_msg = await message.answer(f"⏳ Ищу информацию по {query}...")
    try:
        data = await collect_info(query)
        report = format_probit_report(data)
        if len(report) > 4096:
            for part in [report[i:i+4000] for i in range(0, len(report), 4000)]:
                await message.answer(part, parse_mode='HTML')
        else:
            await status_msg.edit_text(report, parse_mode='HTML')
    except Exception as e:
        await status_msg.edit_text(f'❌ Ошибка: {str(e)}')


@dp.message(Command("probit_post"))
async def probit_post_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ запрещен. Только для администратора.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /probit_post <номер_поста>")
        return
    try:
        post_number = int(args[1].strip())
    except ValueError:
        await message.answer("❌ Введите номер поста (число)")
        return
    status_msg = await message.answer(f"⏳ Ищу пост №{post_number}...")
    try:
        post_data = get_post(post_number)
        if not post_data:
            await status_msg.edit_text(f"❌ Пост №{post_number} не найден")
            return
        msg_id_1, msg_id_2, user_id, username, first_name, created_at = post_data
        query = f"@{username}" if username else str(user_id)
        data = await collect_info(query)
        data['post_number'] = post_number
        data['post_created_at'] = created_at
        report = f"📌 <b>ПОСТ №{post_number}</b>\n📅 Создан: {created_at[:16]}\n"
        report += f"👤 Автор: {first_name or 'Неизвестно'}\n"
        if username:
            report += f"├ Username: @{username}\n"
        report += f"├ User ID: <code>{user_id}</code>\n\n" + "=" * 30 + "\n\n" + format_probit_report(data)
        if len(report) > 4096:
            for part in [report[i:i+4000] for i in range(0, len(report), 4000)]:
                await message.answer(part, parse_mode='HTML')
        else:
            await status_msg.edit_text(report, parse_mode='HTML')
    except Exception as e:
        await status_msg.edit_text(f'❌ Ошибка: {str(e)}')


@dp.message(Command("all_posts"))
async def all_posts_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ запрещен")
        return
    posts = get_all_posts()
    if not posts:
        await message.answer("📂 Постов нет")
        return
    text = "📋 <b>ВСЕ ПОСТЫ:</b>\n\n"
    for number, user_id, username, first_name, created_at in posts[:50]:
        name = first_name or username or str(user_id)
        text += f"├ №{number} — {name} ({created_at[:10]})\n"
    text += f"\nВсего: {len(posts)} постов"
    await message.answer(text, parse_mode='HTML')


@dp.message(Command("history"))
async def history_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ запрещен")
        return
    history = get_probit_history(ADMIN_ID, 20)
    if not history:
        await message.answer("📂 История пробивов пуста")
        return
    text = "📋 <b>ИСТОРИЯ ПРОБИВОВ (последние 20):</b>\n\n"
    for i, (query, result, created_at) in enumerate(history, 1):
        try:
            data = json.loads(result) if result else {}
            username = data.get('username', data.get('query', query))
            text += f"{i}. <code>{username}</code> — {created_at[:16]}\n"
        except:
            text += f"{i}. <code>{query}</code> — {created_at[:16]}\n"
    await message.answer(text, parse_mode='HTML')


@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен. Только для администратора.")
        return
    args = message.text.split(maxsplit=3)
    if len(args) < 3:
        await message.answer(
            "❌ Использование:\n/ban <user_id> <время> [причина]\n\n"
            "Время: 1h, 2h, 5h, 1d, 7d, forever\n\nПример:\n/ban 123456789 1h Спам"
        )
        return
    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя")
        return
    duration_str = args[2].lower()
    reason = args[3] if len(args) > 3 else "Без причины"
    duration_map = {"1h": 3600, "2h": 7200, "5h": 18000, "1d": 86400, "7d": 604800, "forever": 315360000}
    if duration_str not in duration_map:
        await message.answer("❌ Неверный формат времени. Доступно: 1h, 2h, 5h, 1d, 7d, forever")
        return
    banned, until, _ = is_banned(user_id)
    if banned:
        await message.answer(f"❌ Пользователь {user_id} уже забанен до {until.strftime('%d.%m.%Y %H:%M')}")
        return
    ban_until = ban_user(user_id, duration_map[duration_str], reason, message.from_user.id)
    ban_date = datetime.fromisoformat(ban_until)
    try:
        await bot.send_message(user_id,
                               f"🚫 **ВИ ЗАБАНЕНІ!**\n\n📅 До: {ban_date.strftime('%d.%m.%Y %H:%M')}\n📝 Причина: {reason}\n👤 Забанив: {message.from_user.first_name}")
    except:
        pass
    await message.answer(
        f"✅ **ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН!**\n\n🆔 ID: {user_id}\n📅 До: {ban_date.strftime('%d.%m.%Y %H:%M')}\n📝 Причина: {reason}")


@dp.message(Command("unban"))
async def unban_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен. Только для администратора.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /unban <user_id>")
        return
    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя")
        return
    if not is_banned(user_id)[0]:
        await message.answer(f"❌ Пользователь {user_id} не забанен.")
        return
    unban_user(user_id)
    try:
        await bot.send_message(user_id, "✅ **ВИ РОЗБЛОКОВАНІ!** Тепер ви знову можете користуватися ботом.")
    except:
        pass
    await message.answer(f"✅ **ПОЛЬЗОВАТЕЛЬ {user_id} РОЗБЛОКОВАНИЙ!**")


@dp.message(Command("banned_list"))
async def banned_list_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен. Только для администратора.")
        return
    bans = get_all_bans()
    if not bans:
        await message.answer("📂 Забаненных пользователей нет.")
        return
    text = "🚫 **СПИСОК ЗАБАНЕННЫХ:**\n\n"
    for user_id, ban_until_str, reason, banned_by in bans[:20]:
        ban_until = datetime.fromisoformat(ban_until_str)
        text += f"├ 🆔 {user_id}\n├ 📅 До: {ban_until.strftime('%d.%m.%Y %H:%M')}\n├ 📝 {reason[:30]}\n└ 👤 Забанил: {banned_by}\n\n"
    text += f"Всего: {len(bans)} пользователей"
    await message.answer(text)


@dp.message(Command("appeals"))
async def list_appeals(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заборонено. Тільки для адміністратора.")
        return
    cur.execute("""
        SELECT id, user_id, username, question, status, created_at
        FROM appeals
        ORDER BY id DESC
        LIMIT 20
    """)
    appeals = cur.fetchall()
    if not appeals:
        await message.answer("📂 Немає звернень.")
        return
    text = "📩 **СПИСОК ЗВЕРНЕНЬ (останні 20):**\n\n"
    for appeal in appeals:
        appeal_id, user_id, username, question, status, created_at = appeal
        status_emoji = "🟢 Відкрите" if status == "open" else "🔒 Закрите"
        text += f"#{appeal_id} | {status_emoji}\n"
        text += f"├ 👤 {username or user_id}\n"
        text += f"├ 📝 {question[:50]}...\n"
        text += f"└ 📅 {created_at[:16]}\n\n"
    await message.answer(text)


@dp.message(Command("appeal"))
async def view_appeal(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заборонено. Тільки для адміністратора.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Використання: /appeal <id_звернення>")
        return
    try:
        appeal_id = int(args[1])
    except ValueError:
        await message.answer("❌ Введіть правильний ID (число).")
        return
    cur.execute("""
        SELECT id, user_id, username, question, answer, status, created_at, answered_at
        FROM appeals
        WHERE id=?
    """, (appeal_id,))
    appeal = cur.fetchone()
    if not appeal:
        await message.answer("❌ Звернення не знайдено.")
        return
    appeal_id, user_id, username, question, answer, status, created_at, answered_at = appeal
    text = f"📩 **ЗВЕРНЕННЯ #{appeal_id}**\n\n"
    text += f"👤 Користувач: {username or user_id}\n"
    text += f"🆔 ID: {user_id}\n"
    text += f"📅 Створено: {created_at[:16]}\n"
    text += f"📝 Питання: {question}\n"
    if status == "closed":
        text += f"💬 Відповідь: {answer}\n"
        text += f"📅 Відповідь: {answered_at[:16] if answered_at else 'невідомо'}\n"
    text += f"\nСтатус: {'🟢 Відкрите' if status == 'open' else '🔒 Закрите'}"
    if status == "open":
        text += f"\n\nЩоб відповісти: /answer {appeal_id} <текст>"
    await message.answer(text)


@dp.message(Command("answer"))
async def answer_appeal(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заборонено. Тільки для адміністратора.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ Використання: /answer <id_звернення> <відповідь>\n\n"
            "Приклад: /answer 5 Дякую за питання, ми виправимо цю помилку!"
        )
        return
    try:
        appeal_id = int(args[1])
    except ValueError:
        await message.answer("❌ Введіть правильний ID звернення (число).")
        return
    answer_text = args[2].strip()
    cur.execute("SELECT user_id, question FROM appeals WHERE id=? AND status='open'", (appeal_id,))
    appeal = cur.fetchone()
    if not appeal:
        await message.answer("❌ Звернення не знайдено або вже закрите.")
        return
    user_id, question = appeal
    cur.execute("""
        UPDATE appeals 
        SET answer=?, status='closed', answered_at=?
        WHERE id=?
    """, (answer_text, datetime.now().isoformat(), appeal_id))
    db.commit()
    try:
        await bot.send_message(
            user_id,
            f"📩 **ВІДПОВІДЬ НА ВАШЕ ПИТАННЯ**\n\n"
            f"🆔 Звернення: #{appeal_id}\n"
            f"📝 Ваше питання: {question}\n\n"
            f"💬 Відповідь адміна:\n{answer_text}\n\n"
            f"✅ Звернення закрито."
        )
    except:
        pass
    await message.answer(
        f"✅ **ВІДПОВІДЬ НАДІСЛАНО!**\n\n"
        f"🆔 Звернення: #{appeal_id}\n"
        f"📝 Відповідь: {answer_text}\n\n"
        f"Статус: 🔒 Закрито"
    )


@dp.message(Command("vip_status"))
async def vip_status(message: Message):
    uid = message.from_user.id
    vip_type, expires_at = get_vip(uid)
    if vip_type:
        await message.answer(
            f"💎 **ВАШ VIP СТАТУС:**\n\n"
            f"Тип: {vip_type.upper()}\n"
            f"Діє до: {expires_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"Залишилось: {(expires_at - datetime.now()).days} днів"
        )
    else:
        await message.answer(
            "❌ У вас немає активного VIP.\n\n"
            "Купити VIP: /vip"
        )


@dp.message(Command("vip"))
async def vip_command(message: Message):
    await message.answer(
        "💎 **VIP ПОСЛУГИ:**\n\n"
        "💎 Базовий VIP — 10 ⭐\n"
        "   • VIP на 2 дні\n"
        "   • Автопублікація без модерації\n"
        "   • Позначка VIP\n\n"
        "👑 Premium VIP — 25 ⭐\n"
        "   • Все що в базовому\n"
        "   • Пріоритетна обробка\n"
        "   • Повторна публікація\n\n"
        "Натисніть кнопку нижче для покупки:",
        reply_markup=vip_menu()
    )


@dp.message(Command("cancel"))
async def cancel_payment(message: Message):
    uid = message.from_user.id
    if uid in waiting_pin:
        waiting_pin.remove(uid)
        await message.answer("❌ Операцію скасовано.")
    elif uid in waiting_delete:
        del waiting_delete[uid]
        await message.answer("❌ Операцію скасовано.")
    else:
        await message.answer("❌ Немає активних операцій для скасування.")


@dp.message(Command("my_posts"))
async def my_posts_cmd(message: Message):
    uid = message.from_user.id
    posts = get_user_posts(uid)
    
    if not posts:
        await message.answer("📂 У вас немає постів.")
        return
    
    text = f"📋 **ВАШІ ПОСТИ ({len(posts)}):**\n\n"
    for number, msg_id_1, msg_id_2, created_at in posts[:20]:
        text += f"├ №{number} — {created_at[:16]}\n"
    
    text += f"\n💡 Щоб видалити пост - купіть послугу 'Видалити пост'"
    await message.answer(text)


# ============= КНОПКИ МЕНЮ =============
@dp.message(F.text == "💌 Створити пару")
async def create_pair(message: Message):
    banned, until, reason = is_banned(message.from_user.id)
    if banned:
        await message.answer(f"🚫 Ви забанені до {until.strftime('%d.%m.%Y %H:%M')}")
        return
    uid = message.from_user.id
    photos[uid] = []
    await message.answer("📸 **Надішліть 2 фото:**\n\n1️⃣ Фото хлопця\n2️⃣ Фото дівчини ❤️\n\nНадішліть перше фото")


@dp.message(F.text == "💎 VIP послуги")
async def vip_services_button(message: Message):
    banned, until, reason = is_banned(message.from_user.id)
    if banned:
        await message.answer(f"🚫 Ви забанені до {until.strftime('%d.%m.%Y %H:%M')}")
        return
    await message.answer("💎 **VIP ПОСЛУГИ:**\n\n💎 Базовий VIP — 10 ⭐\n👑 Premium VIP — 25 ⭐\n\nНатисніть кнопку нижче:",
                         reply_markup=vip_menu())


@dp.message(F.text == "⭐ Послуги")
async def services_button(message: Message):
    banned, until, reason = is_banned(message.from_user.id)
    if banned:
        await message.answer(f"🚫 Ви забанені до {until.strftime('%d.%m.%Y %H:%M')}")
        return
    await message.answer("⭐ **ПЛАТНІ ПОСЛУГИ:**\n\n📌 Закріпити анкету — 5 ⭐\n🗑 Видалити пост — 5 ⭐\n\nНатисніть кнопку нижче:",
                         reply_markup=services_menu())


@dp.message(F.text == "📜 Правила")
async def rules_button(message: Message):
    await message.answer("📜 **ПРАВИЛА:**\n\n🚫 Заборонено 18+\n🚫 Заборонено образи\n🚫 Заборонено спам\n❤️ Поважайте інших")


@dp.message(F.text == "❓ Питання до адміна")
async def ask_admin(message: Message):
    banned, until, reason = is_banned(message.from_user.id)
    if banned:
        await message.answer(f"🚫 Ви забанені до {until.strftime('%d.%m.%Y %H:%M')}")
        return
    await message.answer(
        "❓ **Напишіть своє питання адміністратору.**\n\n"
        "Відповідь прийде в цей чат, коли адмін її напише.\n"
        "Можна писати будь-які питання щодо роботи бота."
    )
    waiting_question.add(message.from_user.id)


@dp.message(F.text)
async def handle_question(message: Message):
    uid = message.from_user.id
    if uid in waiting_question:
        waiting_question.remove(uid)
        if len(message.text.strip()) < 5:
            await message.answer("❌ Питання має бути довшим за 5 символів.")
            return
        cur.execute("""
            INSERT INTO appeals(user_id, username, question, created_at)
            VALUES(?, ?, ?, ?)
        """, (uid, message.from_user.username or "без ніка", message.text, datetime.now().isoformat()))
        db.commit()
        appeal_id = cur.lastrowid
        await message.answer(
            f"✅ Ваше питання відправлено адміністратору!\n"
            f"🆔 Номер звернення: #{appeal_id}\n"
            f"⏳ Очікуйте відповіді."
        )
        await bot.send_message(
            ADMIN_ID,
            f"📩 **НОВЕ ПИТАННЯ!**\n\n"
            f"🆔 Звернення: #{appeal_id}\n"
            f"👤 Користувач: {message.from_user.first_name} (@{message.from_user.username or 'без ніка'})\n"
            f"🆔 ID: {uid}\n"
            f"📝 Питання: {message.text}\n\n"
            f"Відповісти: /answer {appeal_id} <текст>"
        )
        return
    await message.answer("💘 Використовуйте кнопки меню:", reply_markup=main_menu())


# ============= ОБРАБОТКА ФОТО =============
@dp.message(F.photo)
async def get_photo(message: Message):
    banned, until, reason = is_banned(message.from_user.id)
    if banned:
        await message.answer(f"🚫 Ви забанені до {until.strftime('%d.%m.%Y %H:%M')}")
        return

    uid = message.from_user.id
    if uid not in photos:
        photos[uid] = []
    photos[uid].append(message.photo[-1].file_id)
    if len(photos[uid]) > 2:
        photos[uid] = photos[uid][:2]
    if len(photos[uid]) < 2:
        await message.answer("✅ Перше фото отримано!\nНадішліть друге фото ❤️")
        return

    p1, p2 = photos[uid][0], photos[uid][1]
    text = random.choice(wishes)
    
    vip_type, vip_expires = get_vip(uid)
    is_vip = vip_type is not None
    
    if is_vip:
        text += f"\n\n💎 VIP: {vip_type.upper()}"
    
    pending[uid] = {"p1": p1, "p2": p2, "text": text}

    if auto_approve or is_vip:
        try:
            msg = await bot.send_media_group(
                CHANNEL_ID,
                media=[
                    InputMediaPhoto(media=p1),
                    InputMediaPhoto(media=p2, caption=text)
                ]
            )
            number = save_post(
                msg[0].message_id,
                msg[1].message_id,
                uid,
                message.from_user.username,
                message.from_user.first_name
            )
            await bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=msg[1].message_id,
                caption=text + f"\n\n🆔 Пост №{number}"
            )
            await message.answer(
                f"✅ Заявку автоматично схвалено!{' (VIP)' if is_vip else ''}\n\n"
                f"🆔 Пост №{number}\n"
                "❤️ Анкету опубліковано."
            )
            pending.pop(uid, None)
            photos.pop(uid, None)
            return
        except Exception as e:
            logging.exception("Помилка автоматичного схвалення")
            await message.answer("❌ Не вдалося автоматично опублікувати заявку.")
            photos.pop(uid, None)
            return

    try:
        await bot.send_message(ADMIN_ID, "👑 НОВА ЗАЯВКА НА ПАРУ")
        await bot.send_media_group(
            ADMIN_ID,
            media=[
                InputMediaPhoto(media=p1),
                InputMediaPhoto(media=p2, caption=text)
            ]
        )
        await bot.send_message(
            ADMIN_ID,
            f"Оберіть дію:\n{'💎 VIP пользователь' if is_vip else ''}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Схвалити", callback_data=f"approve:{uid}"),
                        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject:{uid}")
                    ]
                ]
            )
        )
        await message.answer("⏳ Заявку відправлено адміністратору.\nОчікуйте перевірки ❤️")
    except Exception:
        logging.exception("Помилка відправки заявки адміну")
        await message.answer("❌ Не вдалося відправити заявку.")
    photos.pop(uid, None)


# ============= КОЛБЭКИ =============
@dp.callback_query(lambda call: call.data.startswith("approve:"))
async def approve(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(call.data.split(":")[1])
    except ValueError:
        await call.answer("❌ Помилка заявки", show_alert=True)
        return
    data = pending.get(uid)
    if not data:
        await call.answer("❌ Заявка вже оброблена", show_alert=True)
        return
    try:
        msg = await bot.send_media_group(
            CHANNEL_ID,
            media=[
                InputMediaPhoto(media=data["p1"]),
                InputMediaPhoto(media=data["p2"], caption=data["text"])
            ]
        )
        user = await bot.get_chat(uid)
        number = save_post(
            msg[0].message_id,
            msg[1].message_id,
            uid,
            user.username,
            user.first_name
        )
        await bot.edit_message_caption(
            chat_id=CHANNEL_ID,
            message_id=msg[1].message_id,
            caption=data["text"] + f"\n\n🆔 Пост №{number}"
        )
        await call.message.edit_text(f"✅ ЗАЯВКА СХВАЛЕНА\n\n🆔 Пост №{number}\n📢 Опубліковано в канал.")
        pending.pop(uid, None)
    except Exception as e:
        logging.exception("Помилка схвалення заявки")
        await call.answer("❌ Помилка публікації", show_alert=True)


@dp.callback_query(lambda call: call.data.startswith("reject:"))
async def reject(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(call.data.split(":")[1])
    except ValueError:
        return
    pending.pop(uid, None)
    await call.message.edit_text("❌ ЗАЯВКУ ВІДХИЛЕНО")
    await call.answer("Заявку відхилено")


@dp.callback_query(lambda call: call.data == "buy_pin")
async def buy_pin(call: CallbackQuery):
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="📌 Закріплення поста",
            description="Закріплення вашого поста в каналі на 2 дні",
            payload="pin_post",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Закріплення", amount=5)]
        )
    except Exception as e:
        await call.message.answer(f"❌ Помилка: {str(e)}")
    await call.answer()


@dp.callback_query(lambda call: call.data == "buy_delete")
async def buy_delete(call: CallbackQuery):
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="🗑 Видалення поста",
            description="Видалення будь-якого поста з каналу за номером",
            payload="delete_post",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Видалення", amount=5)]
        )
    except Exception as e:
        await call.message.answer(f"❌ Помилка: {str(e)}")
    await call.answer()


@dp.callback_query(lambda call: call.data == "vip_basic")
async def vip_basic(call: CallbackQuery):
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="💎 Базовий VIP",
            description="VIP на 2 дні + автопублікація + позначка VIP",
            payload="vip_basic",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="VIP Basic", amount=10)]
        )
    except Exception as e:
        await call.message.answer(f"❌ Помилка: {str(e)}")
    await call.answer()


@dp.callback_query(lambda call: call.data == "vip_premium")
async def vip_premium(call: CallbackQuery):
    try:
        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="👑 Premium VIP",
            description="VIP Premium: 2 дні + пріоритет + повторна публікація",
            payload="vip_premium",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="VIP Premium", amount=25)]
        )
    except Exception as e:
        await call.message.answer(f"❌ Помилка: {str(e)}")
    await call.answer()


@dp.callback_query(lambda call: call.data == "back")
async def back_handler(call: CallbackQuery):
    await call.message.delete()
    await call.message.answer("💘 Головне меню:", reply_markup=main_menu())
    await call.answer()


@dp.callback_query(lambda call: call.data == "auto_approve_menu")
async def auto_approve_menu_handler(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    status = "🟢 УВІМКНЕНО" if auto_approve else "🔴 ВИМКНЕНО"
    await call.message.edit_text(f"⚙️ Налаштування\n\nСтатус: {status}", reply_markup=admin_menu())
    await call.answer()


@dp.callback_query(lambda call: call.data == "auto_approve_on")
async def auto_approve_on(call: CallbackQuery):
    global auto_approve
    if call.from_user.id != ADMIN_ID:
        return
    auto_approve = True
    await call.answer("Увімкнено ✅")
    await call.message.edit_text("🟢 АВТОМАТИЧНЕ СХВАЛЕННЯ УВІМКНЕНО!", reply_markup=admin_menu())


@dp.callback_query(lambda call: call.data == "auto_approve_off")
async def auto_approve_off(call: CallbackQuery):
    global auto_approve
    if call.from_user.id != ADMIN_ID:
        return
    auto_approve = False
    await call.answer("Зупинено 🔴")
    await call.message.edit_text("🔴 АВТОМАТИЧНЕ СХВАЛЕННЯ ЗУПИНЕНО!", reply_markup=admin_menu())


# ============= ПЛАТЕЖИ =============
@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)


@dp.message(F.successful_payment)
async def success_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    uid = message.from_user.id
    
    if payload == "vip_basic":
        existing_vip, _ = get_vip(uid)
        if existing_vip:
            await message.answer("❌ У вас уже есть VIP! Он будет продлен.")
        set_vip(uid, "basic", 2)
        await message.answer(
            f"💎 **VIP Базовий активовано на 2 дні!**\n\n"
            f"✅ Автопублікація увімкнена\n"
            f"⭐ Позначка VIP в профілі\n"
            f"📅 Діє до: {(datetime.now() + timedelta(days=2)).strftime('%d.%m.%Y %H:%M')}"
        )
        
    elif payload == "vip_premium":
        existing_vip, _ = get_vip(uid)
        if existing_vip:
            await message.answer("❌ У вас уже есть VIP! Он будет продлен.")
        set_vip(uid, "premium", 2)
        await message.answer(
            f"👑 **Premium VIP активовано на 2 дні!**\n\n"
            f"✅ Автопублікація увімкнена\n"
            f"⭐ Позначка VIP в профілі\n"
            f"🚀 Пріоритетна обробка заявок\n"
            f"📅 Діє до: {(datetime.now() + timedelta(days=2)).strftime('%d.%m.%Y %H:%M')}"
        )
        
    elif payload == "pin_post":
        waiting_pin.add(uid)
        await message.answer("📌 Введіть номер поста для закріплення.")
        
    elif payload == "delete_post":
        waiting_delete[uid] = {
            "timestamp": datetime.now(),
            "status": "waiting_for_number"
        }
        await message.answer(
            "🗑 **Введіть номер поста для видалення.**\n\n"
            "Номер поста можна знайти в каналі під фото.\n"
            "Приклад: 42\n\n"
            "⏳ У вас є 5 хвилин для введення номера."
        )
        asyncio.create_task(auto_cancel_delete(uid))
        
    else:
        await message.answer("❌ Невідомий тип платежу.")


async def auto_cancel_delete(user_id: int):
    await asyncio.sleep(60 * 5)
    if user_id in waiting_delete:
        del waiting_delete[user_id]
        try:
            await bot.send_message(user_id, "⏰ Час вийшов. Операцію скасовано.")
        except:
            pass


# ============= ОБРАБОТКА ЧИСЕЛ (УДАЛЕНИЕ ЛЮБОГО ПОСТА) =============
@dp.message(F.text.regexp(r"^\d+$"))
async def number_handler(message: Message):
    uid = message.from_user.id
    try:
        number = int(message.text)
    except ValueError:
        return
    
    # ========== ВИДАЛЕННЯ ПОСТА (ЛЮБОГО) ==========
    if uid in waiting_delete:
        del waiting_delete[uid]
        
        # ПРЯМОЙ ЗАПРОС В БАЗУ
        try:
            cur.execute("SELECT message_id_1, message_id_2, user_id, username, first_name, created_at FROM posts WHERE number=?", (number,))
            post_data = cur.fetchone()
        except Exception as e:
            await message.answer(f"❌ Ошибка БД: {e}")
            return
        
        if not post_data:
            await message.answer(
                f"❌ **Пост №{number} не знайдено в базі даних.**\n\n"
                f"Перевірте номер. Доступні пости:\n"
                f"/all_posts"
            )
            return
        
        msg_id_1 = post_data[0]
        msg_id_2 = post_data[1]
        post_user_id = post_data[2]
        username = post_data[3]
        first_name = post_data[4]
        
        await message.answer(f"⏳ Видаляю пост №{number}...")
        
        deleted_count = 0
        errors = []
        
        # УДАЛЯЕМ ПЕРВОЕ СООБЩЕНИЕ
        try:
            await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id_1)
            deleted_count += 1
            await message.answer(f"✅ Удалено сообщение 1 (ID: {msg_id_1})")
        except Exception as e:
            errors.append(f"Сообщение 1: {str(e)}")
            await message.answer(f"❌ Ошибка удаления 1: {str(e)}")
        
        # УДАЛЯЕМ ВТОРОЕ СООБЩЕНИЕ
        try:
            await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id_2)
            deleted_count += 1
            await message.answer(f"✅ Удалено сообщение 2 (ID: {msg_id_2})")
        except Exception as e:
            errors.append(f"Сообщение 2: {str(e)}")
            await message.answer(f"❌ Ошибка удаления 2: {str(e)}")
        
        # УДАЛЯЕМ ИЗ БАЗЫ
        try:
            cur.execute("DELETE FROM posts WHERE number=?", (number,))
            db.commit()
            await message.answer("✅ Пост удален из базы данных")
        except Exception as e:
            errors.append(f"База данных: {str(e)}")
            await message.answer(f"❌ Ошибка удаления из БД: {str(e)}")
        
        # ЛОГИРУЕМ
        try:
            cur.execute("""INSERT INTO delete_logs(post_number, user_id, username, deleted_at, status)
                           VALUES(?, ?, ?, ?, ?)""",
                        (number, uid, message.from_user.username or "без ніка", 
                         datetime.now().isoformat(), "deleted" if deleted_count == 2 else "partial"))
            db.commit()
        except:
            pass
        
        # ИТОГ
        if deleted_count == 2:
            await message.answer(
                f"✅ **ПОСТ №{number} ПОВНІСТЮ ВИДАЛЕНО!**\n\n"
                f"🗑 З каналу: 2/2\n"
                f"🗄 З бази: ✅\n\n"
                f"❤️ Дякуємо!"
            )
        elif deleted_count == 1:
            await message.answer(
                f"⚠️ **ПОСТ №{number} ВИДАЛЕНО ЧАСТКОВО**\n\n"
                f"🗑 З каналу: 1/2\n"
                f"🗄 З бази: ✅\n\n"
                f"❌ Помилка: {errors[0] if errors else 'Неизвестно'}"
            )
        else:
            await message.answer(
                f"❌ **ПОСТ №{number} НЕ ВИДАЛЕНО**\n\n"
                f"Помилки:\n" + "\n".join(errors) + "\n\n"
                f"🔧 Проверьте права бота в канале через /check_channel"
            )
        return
    
    # ========== ЗАКРІПЛЕННЯ ==========
    if uid in waiting_pin:
        waiting_pin.remove(uid)
        data = get_post(number)
        if not data:
            await message.answer("❌ Пост не знайдено.")
            return
        try:
            await bot.pin_chat_message(CHANNEL_ID, data[0])
            await message.answer(f"📌 Пост №{number} закріплено!")
        except Exception as e:
            await message.answer(f"❌ {e}")
        return
    
    await message.answer("❌ Немає активних операцій для цього номера.")


# ============= WEB СЕРВЕР =============
async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/health", health)
    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info("Health server listening on port %s", port)
    return runner


# ============= MAIN =============
async def main() -> None:
    check_and_clean_vips()
    runner = await start_web_server()
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
