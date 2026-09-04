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
    PreCheckoutQuery
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

# Проверяем, можем ли писать в папку
try:
    test_file = os.path.join(BASE_DIR, "test_write.tmp")
    with open(test_file, "w") as f:
        f.write("test")
    os.remove(test_file)
except Exception:
    # Если не можем — используем /tmp
    DB_PATH = "/tmp/cupid.db"
    logging.warning(f"Использую временную базу: {DB_PATH}")

db = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = db.cursor()

# Проверяем, существует ли база
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='posts'")
table_exists = cur.fetchone()

# Создаем таблицы
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

db.commit()
logging.info(f"База данных: {DB_PATH}")
# ================================================================


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
    cur.execute("SELECT MAX(number) FROM posts")
    last = cur.fetchone()[0]
    number = 1 if last is None else last + 1
    cur.execute("""INSERT INTO posts(number, message_id_1, message_id_2, user_id, username, first_name, created_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (number, message_id_1, message_id_2, user_id, username, first_name, datetime.now().isoformat()))
    db.commit()
    return number


def get_post(number):
    cur.execute("SELECT message_id_1, message_id_2, user_id, username, first_name, created_at FROM posts WHERE number=?",
                (number,))
    return cur.fetchone()


def remove_post(number):
    cur.execute("DELETE FROM posts WHERE number=?", (number,))
    db.commit()


def get_all_posts():
    cur.execute("SELECT number, user_id, username, first_name, created_at FROM posts ORDER BY number DESC")
    return cur.fetchall()


phrases = [
    "💘 Судьба свела двух незнакомцев... или это просто глюк телеги?"
]

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
waiting_delete = set()
waiting_pin = set()
waiting_question = set()
auto_approve = False
vip_users = {}


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


def main_menu():
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
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
            [InlineKeyboardButton(text="💎 Базовий VIP", callback_data="vip_basic")],
            [InlineKeyboardButton(text="👑 Premium VIP", callback_data="vip_premium")],
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
    banned, until, reason = is
