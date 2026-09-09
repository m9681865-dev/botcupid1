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


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан. Добавь переменную окружения BOT_TOKEN."
    )

ADMIN_ID = 7806482040
OWNER_ID = 7806482040
CHANNEL_ID = -1004428565734

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(TOKEN)
dp = Dispatcher()


# ============================================================
# DATABASE
# ============================================================

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


# POSTS
cur.execute("""
CREATE TABLE IF NOT EXISTS posts(
    number INTEGER PRIMARY KEY,
    message_id_1 INTEGER,
    message_id_2 INTEGER,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    created_at TEXT
)
""")


# USERS
cur.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    role TEXT DEFAULT 'user'
)
""")


# POST ADMINS
cur.execute("""
CREATE TABLE IF NOT EXISTS post_admins(
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    added_at TEXT
)
""")


# MODERATORS
cur.execute("""
CREATE TABLE IF NOT EXISTS moderators(
    user_id INTEGER PRIMARY KEY,
    buy_date TEXT
)
""")


# VIP POSTS
cur.execute("""
CREATE TABLE IF NOT EXISTS vip_posts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_number INTEGER,
    vip_type TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    unpin_time TEXT
)
""")


# PROBIT HISTORY
cur.execute("""
CREATE TABLE IF NOT EXISTS probit_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    query TEXT,
    result TEXT,
    created_at TEXT
)
""")


# BANS
cur.execute("""
CREATE TABLE IF NOT EXISTS bans(
    user_id INTEGER PRIMARY KEY,
    ban_until TEXT,
    reason TEXT,
    banned_by INTEGER
)
""")


# APPEALS
cur.execute("""
CREATE TABLE IF NOT EXISTS appeals(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    question TEXT,
    answer TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT,
    answered_at TEXT
)
""")


# VIP USERS
cur.execute("""
CREATE TABLE IF NOT EXISTS vip_users(
    user_id INTEGER PRIMARY KEY,
    vip_type TEXT,
    expires_at TEXT,
    created_at TEXT
)
""")


# DELETE LOGS
cur.execute("""
CREATE TABLE IF NOT EXISTS delete_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_number INTEGER,
    user_id INTEGER,
    username TEXT,
    deleted_at TEXT,
    status TEXT
)
""")

db.commit()

logging.info(f"База данных: {DB_PATH}")


# ============================================================
# ROLES
# ============================================================

def get_role(user_id):
    cur.execute(
        "SELECT role FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    return row[0] if row else "user"


def set_role(user_id, role):
    cur.execute(
        """
        INSERT OR REPLACE INTO users(user_id, role)
        VALUES(?, ?)
        """,
        (user_id, role)
    )

    db.commit()


def is_admin(user_id):
    return user_id == ADMIN_ID or user_id == OWNER_ID


def is_post_admin(user_id):
    """
    Главный админ автоматически является пост-админом.
    """

    if is_admin(user_id):
        return True

    cur.execute(
        "SELECT user_id FROM post_admins WHERE user_id=?",
        (user_id,)
    )

    return cur.fetchone() is not None


def add_post_admin(user_id, added_by):
    cur.execute(
        """
        INSERT OR REPLACE INTO post_admins(
            user_id,
            added_by,
            added_at
        )
        VALUES(?, ?, ?)
        """,
        (
            user_id,
            added_by,
            datetime.now().isoformat()
        )
    )

    db.commit()


def remove_post_admin(user_id):
    cur.execute(
        "DELETE FROM post_admins WHERE user_id=?",
        (user_id,)
    )

    db.commit()


def get_post_admins():
    cur.execute(
        """
        SELECT user_id, added_by, added_at
        FROM post_admins
        ORDER BY added_at DESC
        """
    )

    return cur.fetchall()


# ============================================================
# BANS
# ============================================================

def ban_user(
    user_id,
    duration_seconds,
    reason="",
    banned_by=ADMIN_ID
):
    ban_until = (
        datetime.now() +
        timedelta(seconds=duration_seconds)
    ).isoformat()

    cur.execute(
        """
        INSERT OR REPLACE INTO bans(
            user_id,
            ban_until,
            reason,
            banned_by
        )
        VALUES(?, ?, ?, ?)
        """,
        (
            user_id,
            ban_until,
            reason,
            banned_by
        )
    )

    db.commit()

    return ban_until


def unban_user(user_id):
    cur.execute(
        "DELETE FROM bans WHERE user_id=?",
        (user_id,)
    )

    db.commit()


def is_banned(user_id):
    cur.execute(
        """
        SELECT ban_until, reason
        FROM bans
        WHERE user_id=?
        """,
        (user_id,)
    )

    row = cur.fetchone()

    if not row:
        return False, None, None

    ban_until_str, reason = row

    try:
        ban_until = datetime.fromisoformat(ban_until_str)
    except Exception:
        unban_user(user_id)
        return False, None, None

    if datetime.now() > ban_until:
        unban_user(user_id)
        return False, None, None

    return True, ban_until, reason


def get_all_bans():
    cur.execute(
        """
        SELECT user_id, ban_until, reason, banned_by
        FROM bans
        """
    )

    return cur.fetchall()


# ============================================================
# POSTS
# ============================================================

def save_post(
    message_id_1,
    message_id_2,
    user_id,
    username=None,
    first_name=None
):
    try:
        cur.execute(
            "SELECT MAX(number) FROM posts"
        )

        last = cur.fetchone()[0]

        number = 1 if last is None else last + 1

        cur.execute(
            """
            INSERT INTO posts(
                number,
                message_id_1,
                message_id_2,
                user_id,
                username,
                first_name,
                created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                number,
                message_id_1,
                message_id_2,
                user_id,
                username,
                first_name,
                datetime.now().isoformat()
            )
        )

        db.commit()

        logging.info(
            f"Пост №{number} сохранен в БД"
        )

        return number

    except Exception as e:
        logging.error(
            f"Ошибка сохранения поста: {e}"
        )

        return None


def get_post(number):
    try:
        cur.execute(
            """
            SELECT
                message_id_1,
                message_id_2,
                user_id,
                username,
                first_name,
                created_at
            FROM posts
            WHERE number=?
            """,
            (number,)
        )

        return cur.fetchone()

    except Exception as e:
        logging.error(
            f"Ошибка получения поста: {e}"
        )

        return None


def remove_post(number):
    try:
        cur.execute(
            "DELETE FROM posts WHERE number=?",
            (number,)
        )

        db.commit()

        return True

    except Exception as e:
        logging.error(
            f"Ошибка удаления поста: {e}"
        )

        db.rollback()

        return False


def get_all_posts():
    try:
        cur.execute(
            """
            SELECT
                number,
                user_id,
                username,
                first_name,
                created_at
            FROM posts
            ORDER BY number DESC
            """
        )

        return cur.fetchall()

    except Exception as e:
        logging.error(
            f"Ошибка получения постов: {e}"
        )

        return []


def get_user_posts(user_id):
    try:
        cur.execute(
            """
            SELECT
                number,
                message_id_1,
                message_id_2,
                created_at
            FROM posts
            WHERE user_id=?
            ORDER BY number DESC
            """,
            (user_id,)
        )

        return cur.fetchall()

    except Exception as e:
        logging.error(
            f"Ошибка получения постов пользователя: {e}"
        )

        return []


def log_delete(
    post_number,
    user_id,
    username,
    status
):
    try:
        cur.execute(
            """
            INSERT INTO delete_logs(
                post_number,
                user_id,
                username,
                deleted_at,
                status
            )
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                post_number,
                user_id,
                username,
                datetime.now().isoformat(),
                status
            )
        )

        db.commit()

    except Exception:
        pass


# ============================================================
# VIP
# ============================================================

def set_vip(user_id, vip_type, days=2):

    expires_at = (
        datetime.now() +
        timedelta(days=days)
    ).isoformat()

    cur.execute(
        """
        INSERT OR REPLACE INTO vip_users(
            user_id,
            vip_type,
            expires_at,
            created_at
        )
        VALUES(?, ?, ?, ?)
        """,
        (
            user_id,
            vip_type,
            expires_at,
            datetime.now().isoformat()
        )
    )

    db.commit()

    set_role(user_id, "vip")


def get_vip(user_id):

    cur.execute(
        """
        SELECT vip_type, expires_at
        FROM vip_users
        WHERE user_id=?
        """,
        (user_id,)
    )

    row = cur.fetchone()

    if not row:
        return None, None

    vip_type, expires_at_str = row

    try:
        expires_at = datetime.fromisoformat(
            expires_at_str
        )
    except Exception:
        return None, None

    if datetime.now() > expires_at:

        cur.execute(
            "DELETE FROM vip_users WHERE user_id=?",
            (user_id,)
        )

        db.commit()

        set_role(user_id, "user")

        return None, None

    return vip_type, expires_at


def check_and_clean_vips():

    cur.execute(
        "SELECT user_id, expires_at FROM vip_users"
    )

    rows = cur.fetchall()

    for user_id, expires_at_str in rows:

        try:
            expires_at = datetime.fromisoformat(
                expires_at_str
            )
        except Exception:
            continue

        if datetime.now() > expires_at:

            cur.execute(
                "DELETE FROM vip_users WHERE user_id=?",
                (user_id,)
            )

            db.commit()

            set_role(user_id, "user")


# ============================================================
# DATA
# ============================================================

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


# ============================================================
# MENUS
# ============================================================

def main_menu():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="💌 Створити пару"
                )
            ],
            [
                KeyboardButton(
                    text="💎 VIP послуги"
                )
            ],
            [
                KeyboardButton(
                    text="⭐ Послуги"
                )
            ],
            [
                KeyboardButton(
                    text="📜 Правила"
                )
            ],
            [
                KeyboardButton(
                    text="❓ Питання до адміна"
                )
            ]
        ],
        resize_keyboard=True
    )


def vip_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💎 Базовий VIP — 10 ⭐",
                    callback_data="vip_basic"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👑 Premium VIP — 25 ⭐",
                    callback_data="vip_premium"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back"
                )
            ]
        ]
    )


def services_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📌 Закріпити анкету — 5 ⭐",
                    callback_data="buy_pin"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Видалити пост — 5 ⭐",
                    callback_data="buy_delete"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back"
                )
            ]
        ]
    )


def admin_menu():

    status = (
        "🟢 УВІМКНЕНО"
        if auto_approve
        else
        "🔴 ВИМКНЕНО"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"⚙️ Автоматичне схвалення: {status}",
                    callback_data="auto_approve_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🟢 Увімкнути",
                    callback_data="auto_approve_on"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔴 Зупинити",
                    callback_data="auto_approve_off"
                )
            ]
        ]
    )


# ============================================================
# START
# ============================================================

@dp.message(Command("start"))
async def start(message: Message):

    banned, until, reason = is_banned(
        message.from_user.id
    )

    if banned:

        await message.answer(
            f"🚫 Ви забанені до "
            f"{until.strftime('%d.%m.%Y %H:%M')}"
        )

        return

    await message.answer(
        "💘 Ласкаво просимо в Купідон!\n\n"
        "Створюй пари та знаходь кохання ❤️",
        reply_markup=main_menu()
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================

@dp.message(Command("admin"))
async def admin_panel(message: Message):

    if not is_admin(message.from_user.id):
        await message.answer(
            "❌ Доступ заборонено."
        )
        return

    status = (
        "🟢 УВІМКНЕНО"
        if auto_approve
        else
        "🔴 ВИМКНЕНО"
    )

    await message.answer(
        f"👑 АДМІН-ПАНЕЛЬ\n\n"
        f"⚙️ Автоматичне схвалення: {status}",
        reply_markup=admin_menu()
    )


# ============================================================
# ADD POST ADMIN
# ============================================================

@dp.message(Command("add_post_admin"))
async def add_post_admin_cmd(message: Message):

    if message.from_user.id != OWNER_ID:

        await message.answer(
            "❌ Доступ заборонено.\n"
            "Тільки власник бота може добавлять пост-адмінів."
        )

        return

    args = message.text.split(
        maxsplit=1
    )

    if len(args) < 2:

        await message.answer(
            "❌ Использование:\n\n"
            "/add_post_admin <user_id>\n\n"
            "Пример:\n"
            "/add_post_admin 123456789"
        )

        return

    try:

        user_id = int(
            args[1].strip()
        )

    except ValueError:

        await message.answer(
            "❌ ID должен быть числом."
        )

        return

    if user_id == OWNER_ID or user_id == ADMIN_ID:

        await message.answer(
            "❌ Этот пользователь уже имеет "
            "полную админку."
        )

        return

    add_post_admin(
        user_id,
        message.from_user.id
    )

    try:

        user = await bot.get_chat(
            user_id
        )

        name = (
            user.first_name
            or
            "Без имени"
        )

        username = (
            f"@{user.username}"
            if user.username
            else
            "без username"
        )

        await bot.send_message(
            user_id,
            "👮 <b>Вам выдана роль "
            "администратора постов!</b>\n\n"
            "Ваши возможности:\n"
            "• 📋 Просмотр постов\n"
            "• 👤 Просмотр автора\n"
            "• 🆔 Просмотр Telegram ID\n"
            "• 🔗 Просмотр username\n"
            "• 🔍 Просмотр информации поста\n\n"
            "❌ Полной админки у вас нет.",
            parse_mode="HTML"
        )

    except Exception:

        name = "Пользователь не открыл бота"
        username = "неизвестно"

    await message.answer(
        "✅ <b>ПОСТ-АДМИН ДОБАВЛЕН</b>\n\n"
        f"👤 Имя: {name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        "🔐 Права:\n"
        "• просмотр постов — ✅\n"
        "• просмотр автора — ✅\n"
        "• Telegram ID — ✅\n"
        "• полная админка — ❌",
        parse_mode="HTML"
    )


# ============================================================
# REMOVE POST ADMIN
# ============================================================

@dp.message(Command("remove_post_admin"))
async def remove_post_admin_cmd(message: Message):

    if message.from_user.id != OWNER_ID:

        await message.answer(
            "❌ Доступ заборонено."
        )

        return

    args = message.text.split(
        maxsplit=1
    )

    if len(args) < 2:

        await message.answer(
            "❌ Использование:\n"
            "/remove_post_admin <user_id>"
        )

        return

    try:

        user_id = int(
            args[1].strip()
        )

    except ValueError:

        await message.answer(
            "❌ ID должен быть числом."
        )

        return

    cur.execute(
        "SELECT user_id FROM post_admins WHERE user_id=?",
        (user_id,)
    )

    if not cur.fetchone():

        await message.answer(
            "❌ Этот пользователь "
            "не является пост-админом."
        )

        return

    remove_post_admin(user_id)

    await message.answer(
        f"✅ Пост-админ "
        f"<code>{user_id}</code> удалён.",
        parse_mode="HTML"
    )

    try:

        await bot.send_message(
            user_id,
            "❌ Ваша роль администратора "
            "постов была снята."
        )

    except Exception:
        pass


# ============================================================
# POST ADMINS LIST
# ============================================================

@dp.message(Command("post_admins"))
async def post_admins_cmd(message: Message):

    if message.from_user.id != OWNER_ID:

        await message.answer(
            "❌ Доступ заборонено."
        )

        return

    admins = get_post_admins()

    if not admins:

        await message.answer(
            "📂 Пост-админов пока нет."
        )

        return

    text = "👮 <b>ПОСТ-АДМИНЫ</b>\n\n"

    for i, (
        user_id,
        added_by,
        added_at
    ) in enumerate(admins, 1):

        try:

            user = await bot.get_chat(
                user_id
            )

            name = (
                user.first_name
                or
                "Без имени"
            )

            username = (
                f"@{user.username}"
                if user.username
                else
                "без username"
            )

        except Exception:

            name = "Неизвестно"
            username = "недоступен"

        text += (
            f"{i}. 👤 {name}\n"
            f"├ 🆔 ID: <code>{user_id}</code>\n"
            f"├ 🔗 {username}\n"
            f"└ 📅 {added_at[:16]}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# ============================================================
# CHECK CHANNEL
# ============================================================

@dp.message(Command("check_channel"))
async def check_channel_cmd(message: Message):

    if not is_admin(message.from_user.id):

        await message.answer(
            "❌ Только админ!"
        )

        return

    try:

        me = await bot.get_me()

        member = await bot.get_chat_member(
            CHANNEL_ID,
            me.id
        )

        await message.answer(
            f"📊 <b>ПРАВА БОТА В КАНАЛЕ</b>\n\n"
            f"Статус: {member.status}\n"
            f"Удаление: "
            f"{'✅' if member.can_delete_messages else '❌'}\n"
            f"Закрепление: "
            f"{'✅' if member.can_pin_messages else '❌'}",
            parse_mode="HTML"
        )

    except Exception as e:

        await message.answer(
            f"❌ Ошибка: {e}"
        )


# ============================================================
# ALL POSTS
# ============================================================

@dp.message(Command("all_posts"))
async def all_posts_cmd(message: Message):

    if not is_post_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Доступ запрещен."
        )

        return

    posts = get_all_posts()

    if not posts:

        await message.answer(
            "📂 Постов нет"
        )

        return

    text = "📋 <b>ПОСТЫ</b>\n\n"

    for (
        number,
        user_id,
        username,
        first_name,
        created_at
    ) in posts[:50]:

        name = (
            first_name
            or
            "Без имени"
        )

        username_text = (
            f"@{username}"
            if username
            else
            "без username"
        )

        text += (
            f"💘 <b>Пост №{number}</b>\n"
            f"├ 👤 {name}\n"
            f"├ 🔗 {username_text}\n"
            f"├ 🆔 ID: <code>{user_id}</code>\n"
            f"└ 📅 {created_at[:16]}\n\n"
        )

    text += (
        f"📊 Всего постов: {len(posts)}"
    )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# ============================================================
# PROBIT POST
# ============================================================

@dp.message(Command("probit_post"))
async def probit_post_cmd(message: Message):

    if not is_post_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Доступ запрещен."
        )

        return

    args = message.text.split(
        maxsplit=1
    )

    if len(args) < 2:

        await message.answer(
            "❌ Использование:\n"
            "/probit_post <номер_поста>"
        )

        return

    try:

        post_number = int(
            args[1].strip()
        )

    except ValueError:

        await message.answer(
            "❌ Введите номер поста числом."
        )

        return

    post_data = get_post(
        post_number
    )

    if not post_data:

        await message.answer(
            f"❌ Пост №{post_number} не найден."
        )

        return

    (
        msg_id_1,
        msg_id_2,
        user_id,
        username,
        first_name,
        created_at
    ) = post_data

    text = (
        f"📌 <b>ПОСТ №{post_number}</b>\n\n"
        f"👤 Имя: {first_name or 'Неизвестно'}\n"
        f"🔗 Username: "
        f"{'@' + username if username else 'нет'}\n"
        f"🆔 Telegram ID: "
        f"<code>{user_id}</code>\n"
        f"📅 Создан: {created_at[:16]}\n\n"
        f"📨 Message ID 1: "
        f"<code>{msg_id_1}</code>\n"
        f"📨 Message ID 2: "
        f"<code>{msg_id_2}</code>"
    )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# ============================================================
# BAN
# ============================================================

@dp.message(Command("ban"))
async def ban_cmd(message: Message):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Доступ запрещен."
        )

        return

    args = message.text.split(
        maxsplit=3
    )

    if len(args) < 3:

        await message.answer(
            "❌ Использование:\n"
            "/ban <user_id> <время> [причина]\n\n"
            "Время:\n"
            "1h, 2h, 5h, 1d, 7d, forever"
        )

        return

    try:

        user_id = int(args[1])

    except ValueError:

        await message.answer(
            "❌ ID должен быть числом."
        )

        return

    duration_str = args[2].lower()

    reason = (
        args[3]
        if len(args) > 3
        else
        "Без причины"
    )

    duration_map = {
        "1h": 3600,
        "2h": 7200,
        "5h": 18000,
        "1d": 86400,
        "7d": 604800,
        "forever": 315360000
    }

    if duration_str not in duration_map:

        await message.answer(
            "❌ Неверный формат времени."
        )

        return

    if is_banned(user_id)[0]:

        await message.answer(
            "❌ Пользователь уже забанен."
        )

        return

    ban_until = ban_user(
        user_id,
        duration_map[duration_str],
        reason,
        message.from_user.id
    )

    ban_date = datetime.fromisoformat(
        ban_until
    )

    try:

        await bot.send_message(
            user_id,
            f"🚫 ВИ ЗАБАНЕНІ!\n\n"
            f"📅 До: "
            f"{ban_date.strftime('%d.%m.%Y %H:%M')}\n"
            f"📝 Причина: {reason}"
        )

    except Exception:
        pass

    await message.answer(
        f"✅ Пользователь забанен.\n\n"
        f"🆔 ID: {user_id}\n"
        f"📅 До: "
        f"{ban_date.strftime('%d.%m.%Y %H:%M')}\n"
        f"📝 Причина: {reason}"
    )


# ============================================================
# UNBAN
# ============================================================

@dp.message(Command("unban"))
async def unban_cmd(message: Message):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Доступ запрещен."
        )

        return

    args = message.text.split(
        maxsplit=1
    )

    if len(args) < 2:

        await message.answer(
            "❌ Использование:\n"
            "/unban <user_id>"
        )

        return

    try:

        user_id = int(
            args[1]
        )

    except ValueError:

        await message.answer(
            "❌ ID должен быть числом."
        )

        return

    if not is_banned(user_id)[0]:

        await message.answer(
            "❌ Пользователь не забанен."
        )

        return

    unban_user(user_id)

    try:

        await bot.send_message(
            user_id,
            "✅ Ви розблоковані!"
        )

    except Exception:
        pass

    await message.answer(
        f"✅ Пользователь {user_id} разблокирован."
    )


# ============================================================
# BANNED LIST
# ============================================================

@dp.message(Command("banned_list"))
async def banned_list_cmd(message: Message):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Доступ запрещен."
        )

        return

    bans = get_all_bans()

    if not bans:

        await message.answer(
            "📂 Забаненных пользователей нет."
        )

        return

    text = "🚫 <b>ЗАБАНЕННЫЕ:</b>\n\n"

    for (
        user_id,
        ban_until_str,
        reason,
        banned_by
    ) in bans[:20]:

        try:

            ban_until = datetime.fromisoformat(
                ban_until_str
            )

            date_text = ban_until.strftime(
                "%d.%m.%Y %H:%M"
            )

        except Exception:

            date_text = "неизвестно"

        text += (
            f"🆔 <code>{user_id}</code>\n"
            f"📅 До: {date_text}\n"
            f"📝 {reason or 'Без причины'}\n"
            f"👤 Забанил: {banned_by}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# ============================================================
# APPEALS
# ============================================================

@dp.message(Command("appeals"))
async def list_appeals(message: Message):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Доступ запрещен."
        )

        return

    cur.execute(
        """
        SELECT
            id,
            user_id,
            username,
            question,
            status,
            created_at
        FROM appeals
        ORDER BY id DESC
        LIMIT 20
        """
    )

    appeals = cur.fetchall()

    if not appeals:

        await message.answer(
            "📂 Немає звернень."
        )

        return

    text = "📩 <b>ЗВЕРНЕННЯ</b>\n\n"

    for appeal in appeals:

        (
            appeal_id,
            user_id,
            username,
            question,
            status,
            created_at
        ) = appeal

        status_text = (
            "🟢 Відкрите"
            if status == "open"
            else
            "🔒 Закрите"
        )

        text += (
            f"#{appeal_id} | {status_text}\n"
            f"👤 {username or user_id}\n"
            f"📝 {question[:60]}\n"
            f"📅 {created_at[:16]}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


@dp.message(Command("appeal"))
async def view_appeal(message: Message):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Доступ заборонено."
        )

        return

    args = message.text.split(
        maxsplit=1
    )

    if len(args) < 2:

        await message.answer(
            "❌ /appeal <id>"
        )

        return

    try:

        appeal_id = int(args[1])

    except ValueError:

        await message.answer(
            "❌ ID должен быть числом."
        )

        return

    cur.execute(
        """
        SELECT
            id,
            user_id,
            username,
            question,
            answer,
            status,
            created_at,
            answered_at
        FROM appeals
        WHERE id=?
        """,
        (appeal_id,)
    )

    appeal = cur.fetchone()

    if not appeal:

        await message.answer(
            "❌ Звернення не знайдено."
        )

        return

    (
        appeal_id,
        user_id,
        username,
        question,
        answer,
        status,
        created_at,
        answered_at
    ) = appeal

    text = (
        f"📩 <b>ЗВЕРНЕННЯ #{appeal_id}</b>\n\n"
        f"👤 {username or user_id}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📅 {created_at[:16]}\n"
        f"📝 {question}\n\n"
    )

    if answer:

        text += (
            f"💬 Відповідь:\n"
            f"{answer}\n\n"
        )

    text += (
        f"Статус: "
        f"{'🟢 Відкрите' if status == 'open' else '🔒 Закрите'}"
    )

    if status == "open":

        text += (
            f"\n\n"
            f"/answer {appeal_id} <текст>"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


@dp.message(Command("answer"))
async def answer_appeal(message: Message):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Доступ запрещен."
        )

        return

    args = message.text.split(
        maxsplit=2
    )

    if len(args) < 3:

        await message.answer(
            "❌ /answer <id> <текст>"
        )

        return

    try:

        appeal_id = int(args[1])

    except ValueError:

        await message.answer(
            "❌ ID должен быть числом."
        )

        return

    answer_text = args[2].strip()

    cur.execute(
        """
        SELECT user_id, question
        FROM appeals
        WHERE id=? AND status='open'
        """,
        (appeal_id,)
    )

    appeal = cur.fetchone()

    if not appeal:

        await message.answer(
            "❌ Звернення не знайдено "
            "або вже закрито."
        )

        return

    user_id, question = appeal

    cur.execute(
        """
        UPDATE appeals
        SET
            answer=?,
            status='closed',
            answered_at=?
        WHERE id=?
        """,
        (
            answer_text,
            datetime.now().isoformat(),
            appeal_id
        )
    )

    db.commit()

    try:

        await bot.send_message(
            user_id,
            f"📩 ВІДПОВІДЬ НА ВАШЕ ПИТАННЯ\n\n"
            f"🆔 Звернення: #{appeal_id}\n"
            f"📝 Ваше питання: {question}\n\n"
            f"💬 Відповідь:\n{answer_text}\n\n"
            f"✅ Звернення закрито."
        )

    except Exception:
        pass

    await message.answer(
        f"✅ Відповідь надіслано.\n\n"
        f"🆔 #{appeal_id}"
    )


# ============================================================
# VIP COMMANDS
# ============================================================

@dp.message(Command("vip_status"))
async def vip_status(message: Message):

    uid = message.from_user.id

    vip_type, expires_at = get_vip(uid)

    if vip_type:

        await message.answer(
            f"💎 ВАШ VIP\n\n"
            f"Тип: {vip_type.upper()}\n"
            f"Діє до: "
            f"{expires_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"Залишилось: "
            f"{(expires_at - datetime.now()).days} днів"
        )

    else:

        await message.answer(
            "❌ У вас немає активного VIP.\n\n"
            "Купити: /vip"
        )


@dp.message(Command("vip"))
async def vip_command(message: Message):

    await message.answer(
        "💎 <b>VIP ПОСЛУГИ</b>\n\n"
        "💎 Базовий VIP — 10 ⭐\n"
        "• VIP на 2 дні\n"
        "• Автопублікація\n"
        "• Позначка VIP\n\n"
        "👑 Premium VIP — 25 ⭐\n"
        "• VIP на 2 дні\n"
        "• Автопублікація\n"
        "• Пріоритет\n"
        "• Повторна публікація",
        reply_markup=vip_menu(),
        parse_mode="HTML"
    )


# ============================================================
# CANCEL
# ============================================================

@dp.message(Command("cancel"))
async def cancel_payment(message: Message):

    uid = message.from_user.id

    if uid in waiting_pin:

        waiting_pin.remove(uid)

        await message.answer(
            "❌ Операцію скасовано."
        )

    elif uid in waiting_delete:

        del waiting_delete[uid]

        await message.answer(
            "❌ Операцію скасовано."
        )

    else:

        await message.answer(
            "❌ Немає активних операцій."
        )


# ============================================================
# MY POSTS
# ============================================================

@dp.message(Command("my_posts"))
async def my_posts_cmd(message: Message):

    uid = message.from_user.id

    posts = get_user_posts(uid)

    if not posts:

        await message.answer(
            "📂 У вас немає постів."
        )

        return

    text = (
        f"📋 ВАШІ ПОСТИ "
        f"({len(posts)}):\n\n"
    )

    for (
        number,
        msg_id_1,
        msg_id_2,
        created_at
    ) in posts[:20]:

        text += (
            f"├ №{number}\n"
            f"└ {created_at[:16]}\n\n"
        )

    await message.answer(
        text
    )


# ============================================================
# USER MENU
# ============================================================

@dp.message(F.text == "💌 Створити пару")
async def create_pair(message: Message):

    banned, until, reason = is_banned(
        message.from_user.id
    )

    if banned:

        await message.answer(
            f"🚫 Ви забанені до "
            f"{until.strftime('%d.%m.%Y %H:%M')}"
        )

        return

    uid = message.from_user.id

    photos[uid] = []

    await message.answer(
        "📸 <b>Надішліть 2 фото:</b>\n\n"
        "1️⃣ Фото хлопця\n"
        "2️⃣ Фото дівчини ❤️\n\n"
        "Надішліть перше фото",
        parse_mode="HTML"
    )


@dp.message(F.text == "💎 VIP послуги")
async def vip_services_button(message: Message):

    banned, until, reason = is_banned(
        message.from_user.id
    )

    if banned:

        await message.answer(
            f"🚫 Ви забанені до "
            f"{until.strftime('%d.%m.%Y %H:%M')}"
        )

        return

    await message.answer(
        "💎 VIP ПОСЛУГИ",
        reply_markup=vip_menu()
    )


@dp.message(F.text == "⭐ Послуги")
async def services_button(message: Message):

    banned, until, reason = is_banned(
        message.from_user.id
    )

    if banned:

        await message.answer(
            f"🚫 Ви забанені до "
            f"{until.strftime('%d.%m.%Y %H:%M')}"
        )

        return

    await message.answer(
        "⭐ ПЛАТНІ ПОСЛУГИ",
        reply_markup=services_menu()
    )


@dp.message(F.text == "📜 Правила")
async def rules_button(message: Message):

    await message.answer(
        "📜 <b>ПРАВИЛА</b>\n\n"
        "🚫 Заборонено 18+\n"
        "🚫 Заборонено образи\n"
        "🚫 Заборонено спам\n"
        "❤️ Поважайте інших",
        parse_mode="HTML"
    )


@dp.message(F.text == "❓ Питання до адміна")
async def ask_admin(message: Message):

    banned, until, reason = is_banned(
        message.from_user.id
    )

    if banned:

        await message.answer(
            f"🚫 Ви забанені до "
            f"{until.strftime('%d.%m.%Y %H:%M')}"
        )

        return

    await message.answer(
        "❓ <b>Напишіть своє питання "
        "адміністратору.</b>\n\n"
        "Відповідь прийде в цей чат.",
        parse_mode="HTML"
    )

    waiting_question.add(
        message.from_user.id
    )


# ============================================================
# QUESTIONS
# ============================================================

@dp.message(F.text)
async def handle_question(message: Message):

    uid = message.from_user.id

    if uid in waiting_question:

        waiting_question.remove(uid)

        if len(message.text.strip()) < 5:

            await message.answer(
                "❌ Питання має бути довшим "
                "за 5 символів."
            )

            return

        cur.execute(
            """
            INSERT INTO appeals(
                user_id,
                username,
                question,
                created_at
            )
            VALUES(?, ?, ?, ?)
            """,
            (
                uid,
                message.from_user.username
                or "без ніка",
                message.text,
                datetime.now().isoformat()
            )
        )

        db.commit()

        appeal_id = cur.lastrowid

        await message.answer(
            f"✅ Ваше питання відправлено!\n"
            f"🆔 Звернення: #{appeal_id}\n"
            f"⏳ Очікуйте відповіді."
        )

        try:

            await bot.send_message(
                ADMIN_ID,
                f"📩 <b>НОВЕ ПИТАННЯ</b>\n\n"
                f"🆔 #{appeal_id}\n"
                f"👤 {message.from_user.first_name}\n"
                f"🔗 @{message.from_user.username or 'без ніка'}\n"
                f"🆔 ID: <code>{uid}</code>\n"
                f"📝 {message.text}\n\n"
                f"/answer {appeal_id} <текст>",
                parse_mode="HTML"
            )

        except Exception:
            pass

        return

    await message.answer(
        "💘 Використовуйте кнопки меню:",
        reply_markup=main_menu()
    )


# ============================================================
# PHOTOS
# ============================================================

@dp.message(F.photo)
async def get_photo(message: Message):

    banned, until, reason = is_banned(
        message.from_user.id
    )

    if banned:

        await message.answer(
            f"🚫 Ви забанені до "
            f"{until.strftime('%d.%m.%Y %H:%M')}"
        )

        return

    uid = message.from_user.id

    if uid not in photos:
        photos[uid] = []

    photos[uid].append(
        message.photo[-1].file_id
    )

    if len(photos[uid]) > 2:
        photos[uid] = photos[uid][:2]

    if len(photos[uid]) < 2:

        await message.answer(
            "✅ Перше фото отримано!\n"
            "Надішліть друге фото ❤️"
        )

        return

    p1, p2 = photos[uid]

    text = random.choice(wishes)

    vip_type, vip_expires = get_vip(uid)

    is_vip = vip_type is not None

    if is_vip:

        text += (
            f"\n\n💎 VIP: "
            f"{vip_type.upper()}"
        )

    pending[uid] = {
        "p1": p1,
        "p2": p2,
        "text": text
    }

    # ========================================================
    # AUTO APPROVE / VIP
    # ========================================================

    if auto_approve or is_vip:

        try:

            msg = await bot.send_media_group(
                CHANNEL_ID,
                media=[
                    InputMediaPhoto(
                        media=p1
                    ),
                    InputMediaPhoto(
                        media=p2,
                        caption=text
                    )
                ]
            )

            number = save_post(
                msg[0].message_id,
                msg[1].message_id,
                uid,
                message.from_user.username,
                message.from_user.first_name
            )

            if number:

                await bot.edit_message_caption(
                    chat_id=CHANNEL_ID,
                    message_id=msg[1].message_id,
                    caption=(
                        text +
                        f"\n\n🆔 Пост №{number}"
                    )
                )

            await message.answer(
                f"✅ Заявку автоматично схвалено!\n\n"
                f"🆔 Пост №{number}\n"
                f"❤️ Анкету опубліковано."
            )

            pending.pop(uid, None)
            photos.pop(uid, None)

            return

        except Exception:

            logging.exception(
                "Ошибка автоматического одобрения"
            )

            await message.answer(
                "❌ Не вдалося опублікувати."
            )

            photos.pop(uid, None)

            return

    # ========================================================
    # MODERATION
    # ========================================================

    try:

        await bot.send_message(
            ADMIN_ID,
            "👑 НОВА ЗАЯВКА НА ПАРУ"
        )

        await bot.send_media_group(
            ADMIN_ID,
            media=[
                InputMediaPhoto(
                    media=p1
                ),
                InputMediaPhoto(
                    media=p2,
                    caption=text
                )
            ]
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Схвалити",
                        callback_data=f"approve:{uid}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Відхилити",
                        callback_data=f"reject:{uid}"
                    )
                ]
            ]
        )

        await bot.send_message(
            ADMIN_ID,
            "Оберіть дію:",
            reply_markup=keyboard
        )

        await message.answer(
            "⏳ Заявку відправлено адміністратору.\n"
            "Очікуйте перевірки ❤️"
        )

    except Exception:

        logging.exception(
            "Ошибка отправки заявки"
        )

        await message.answer(
            "❌ Не вдалося відправити заявку."
        )

    photos.pop(uid, None)


# ============================================================
# APPROVE
# ============================================================

@dp.callback_query(
    lambda call:
    call.data.startswith("approve:")
)
async def approve(call: CallbackQuery):

    if not is_admin(
        call.from_user.id
    ):

        return

    try:

        uid = int(
            call.data.split(":")[1]
        )

    except ValueError:

        await call.answer(
            "❌ Помилка заявки",
            show_alert=True
        )

        return

    data = pending.get(uid)

    if not data:

        await call.answer(
            "❌ Заявка вже оброблена.",
            show_alert=True
        )

        return

    try:

        msg = await bot.send_media_group(
            CHANNEL_ID,
            media=[
                InputMediaPhoto(
                    media=data["p1"]
                ),
                InputMediaPhoto(
                    media=data["p2"],
                    caption=data["text"]
                )
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
            caption=(
                data["text"] +
                f"\n\n🆔 Пост №{number}"
            )
        )

        await call.message.edit_text(
            f"✅ ЗАЯВКА СХВАЛЕНА\n\n"
            f"🆔 Пост №{number}\n"
            f"📢 Опубліковано в канал."
        )

        pending.pop(uid, None)

        await call.answer(
            "Опубліковано ✅"
        )

    except Exception:

        logging.exception(
            "Ошибка одобрения"
        )

        await call.answer(
            "❌ Помилка публікації",
            show_alert=True
        )


# ============================================================
# REJECT
# ============================================================

@dp.callback_query(
    lambda call:
    call.data.startswith("reject:")
)
async def reject(call: CallbackQuery):

    if not is_admin(
        call.from_user.id
    ):

        return

    try:

        uid = int(
            call.data.split(":")[1]
        )

    except ValueError:

        return

    pending.pop(uid, None)

    await call.message.edit_text(
        "❌ ЗАЯВКУ ВІДХИЛЕНО"
    )

    await call.answer(
        "Заявку відхилено"
    )


# ============================================================
# BUY PIN
# ============================================================

@dp.callback_query(
    lambda call:
    call.data == "buy_pin"
)
async def buy_pin(call: CallbackQuery):

    try:

        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="📌 Закріплення поста",
            description="Закріплення вашого поста",
            payload="pin_post",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="Закріплення",
                    amount=5
                )
            ]
        )

    except Exception as e:

        await call.message.answer(
            f"❌ Помилка: {e}"
        )

    await call.answer()


# ============================================================
# BUY DELETE
# ============================================================

@dp.callback_query(
    lambda call:
    call.data == "buy_delete"
)
async def buy_delete(call: CallbackQuery):

    try:

        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="🗑 Видалення поста",
            description=(
                "Видалення поста "
                "з каналу за номером"
            ),
            payload="delete_post",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="Видалення",
                    amount=5
                )
            ]
        )

    except Exception as e:

        await call.message.answer(
            f"❌ Помилка: {e}"
        )

    await call.answer()


# ============================================================
# VIP PAYMENTS
# ============================================================

@dp.callback_query(
    lambda call:
    call.data == "vip_basic"
)
async def vip_basic(call: CallbackQuery):

    try:

        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="💎 Базовий VIP",
            description="VIP на 2 дні",
            payload="vip_basic",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="VIP Basic",
                    amount=10
                )
            ]
        )

    except Exception as e:

        await call.message.answer(
            f"❌ Помилка: {e}"
        )

    await call.answer()


@dp.callback_query(
    lambda call:
    call.data == "vip_premium"
)
async def vip_premium(call: CallbackQuery):

    try:

        await bot.send_invoice(
            chat_id=call.from_user.id,
            title="👑 Premium VIP",
            description="VIP Premium на 2 дні",
            payload="vip_premium",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="VIP Premium",
                    amount=25
                )
            ]
        )

    except Exception as e:

        await call.message.answer(
            f"❌ Помилка: {e}"
        )

    await call.answer()


# ============================================================
# BACK
# ============================================================

@dp.callback_query(
    lambda call:
    call.data == "back"
)
async def back_handler(call: CallbackQuery):

    try:

        await call.message.delete()

    except Exception:
        pass

    await call.message.answer(
        "💘 Головне меню:",
        reply_markup=main_menu()
    )

    await call.answer()


# ============================================================
# AUTO APPROVE
# ============================================================

@dp.callback_query(
    lambda call:
    call.data == "auto_approve_menu"
)
async def auto_approve_menu_handler(
    call: CallbackQuery
):

    if not is_admin(
        call.from_user.id
    ):

        return

    status = (
        "🟢 УВІМКНЕНО"
        if auto_approve
        else
        "🔴 ВИМКНЕНО"
    )

    await call.message.edit_text(
        f"⚙️ Налаштування\n\n"
        f"Статус: {status}",
        reply_markup=admin_menu()
    )

    await call.answer()


@dp.callback_query(
    lambda call:
    call.data == "auto_approve_on"
)
async def auto_approve_on(
    call: CallbackQuery
):

    global auto_approve

    if not is_admin(
        call.from_user.id
    ):

        return

    auto_approve = True

    await call.answer(
        "Увімкнено ✅"
    )

    await call.message.edit_text(
        "🟢 АВТОМАТИЧНЕ СХВАЛЕННЯ УВІМКНЕНО!",
        reply_markup=admin_menu()
    )


@dp.callback_query(
    lambda call:
    call.data == "auto_approve_off"
)
async def auto_approve_off(
    call: CallbackQuery
):

    global auto_approve

    if not is_admin(
        call.from_user.id
    ):

        return

    auto_approve = False

    await call.answer(
        "Зупинено 🔴"
    )

    await call.message.edit_text(
        "🔴 АВТОМАТИЧНЕ СХВАЛЕННЯ ЗУПИНЕНО!",
        reply_markup=admin_menu()
    )


# ============================================================
# PAYMENTS
# ============================================================

@dp.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery
):

    await bot.answer_pre_checkout_query(
        query.id,
        ok=True
    )


@dp.message(F.successful_payment)
async def success_payment(
    message: Message
):

    payload = (
        message.successful_payment
        .invoice_payload
    )

    uid = message.from_user.id

    # ========================================================
    # VIP BASIC
    # ========================================================

    if payload == "vip_basic":

        set_vip(
            uid,
            "basic",
            2
        )

        await message.answer(
            "💎 <b>VIP Базовий активовано!</b>\n\n"
            "⏱ Діє 2 дні\n"
            "✅ Автопублікація\n"
            "⭐ VIP позначка",
            parse_mode="HTML"
        )

    # ========================================================
    # VIP PREMIUM
    # ========================================================

    elif payload == "vip_premium":

        set_vip(
            uid,
            "premium",
            2
        )

        await message.answer(
            "👑 <b>Premium VIP активовано!</b>\n\n"
            "⏱ Діє 2 дні\n"
            "✅ Автопублікація\n"
            "🚀 Пріоритетна обробка",
            parse_mode="HTML"
        )

    # ========================================================
    # PIN
    # ========================================================

    elif payload == "pin_post":

        waiting_pin.add(uid)

        await message.answer(
            "📌 Введіть номер поста "
            "для закріплення."
        )

    # ========================================================
    # DELETE
    # ========================================================

    elif payload == "delete_post":

        waiting_delete[uid] = {
            "timestamp": datetime.now(),
            "status": "waiting"
        }

        await message.answer(
            "🗑 <b>Введіть номер поста "
            "для видалення.</b>\n\n"
            "Наприклад: <code>42</code>\n\n"
            "⏳ У вас є 5 хвилин.",
            parse_mode="HTML"
        )

        asyncio.create_task(
            auto_cancel_delete(uid)
        )

    else:

        await message.answer(
            "❌ Невідомий тип платежу."
        )


# ============================================================
# DELETE TIMER
# ============================================================

async def auto_cancel_delete(user_id: int):

    await asyncio.sleep(300)

    if user_id in waiting_delete:

        del waiting_delete[user_id]

        try:

            await bot.send_message(
                user_id,
                "⏰ Час вийшов. "
                "Операцію скасовано."
            )

        except Exception:
            pass


# ============================================================
# NUMBER HANDLER
# ============================================================

@dp.message(
    F.text.regexp(r"^\d+$")
)
async def number_handler(
    message: Message
):

    uid = message.from_user.id

    try:

        number = int(
            message.text
        )

    except ValueError:

        return

    # ========================================================
    # DELETE POST
    # ========================================================

    if uid in waiting_delete:

        del waiting_delete[uid]

        cur.execute(
            """
            SELECT
                message_id_1,
                message_id_2,
                user_id,
                username
            FROM posts
            WHERE number=?
            """,
            (number,)
        )

        row = cur.fetchone()

        if not row:

            await message.answer(
                f"❌ Пост №{number} "
                f"не найден в базе."
            )

            return

        msg1, msg2, post_user_id, username = row

        deleted = 0
        errors = []

        try:

            await bot.delete_message(
                chat_id=CHANNEL_ID,
                message_id=msg1
            )

            deleted += 1

        except Exception as e:

            errors.append(
                f"Фото 1: {e}"
            )

        try:

            await bot.delete_message(
                chat_id=CHANNEL_ID,
                message_id=msg2
            )

            deleted += 1

        except Exception as e:

            errors.append(
                f"Фото 2: {e}"
            )

        if deleted > 0:

            remove_post(number)

            log_delete(
                number,
                uid,
                message.from_user.username,
                f"deleted_{deleted}_of_2"
            )

        if deleted == 2:

            await message.answer(
                f"✅ <b>ПОСТ №{number} "
                f"ПОВНІСТЮ ВИДАЛЕНО!</b>",
                parse_mode="HTML"
            )

        elif deleted == 1:

            await message.answer(
                f"⚠️ <b>ПОСТ №{number} "
                f"ВИДАЛЕНО ЧАСТКОВО</b>\n\n"
                f"Видалено: 1/2\n\n"
                + "\n".join(errors),
                parse_mode="HTML"
            )

        else:

            await message.answer(
                f"❌ <b>ПОСТ №{number} "
                f"НЕ ВИДАЛЕНО</b>\n\n"
                + "\n".join(errors),
                parse_mode="HTML"
            )

        return

    # ========================================================
    # PIN POST
    # ========================================================

    if uid in waiting_pin:

        waiting_pin.remove(uid)

        data = get_post(number)

        if not data:

            await message.answer(
                "❌ Пост не знайдено."
            )

            return

        try:

            await bot.pin_chat_message(
                CHANNEL_ID,
                data[0]
            )

            await message.answer(
                f"📌 Пост №{number} закріплено!"
            )

        except Exception as e:

            await message.answer(
                f"❌ {e}"
            )

        return

    await message.answer(
        "❌ Немає активних операцій "
        "для цього номера."
    )


# ============================================================
# WEB SERVER
# ============================================================

async def health(
    _: web.Request
) -> web.Response:

    return web.json_response(
        {
            "status": "ok"
        }
    )


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/health",
        health
    )

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=port
    )

    await site.start()

    logging.info(
        f"Health server listening on {port}"
    )

    return runner


# ============================================================
# MAIN
# ============================================================

async def main():

    check_and_clean_vips()

    runner = await start_web_server()

    try:

        logging.info(
            "✅ Бот запущено"
        )

        await dp.start_polling(
            bot
        )

    finally:

        await runner.cleanup()

        await bot.session.close()

        db.close()


if __name__ == "__main__":

    asyncio.run(main())
