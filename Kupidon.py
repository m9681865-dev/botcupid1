import asyncio
import logging
import sqlite3
import os
from datetime import datetime, timedelta

from aiohttp import web

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
    KeyboardButton,
)


# =========================================================
# CONFIG
# =========================================================

TOKEN = "8982055607:AAEKKBdUejE8rwZVGldY-MUxWe6X1GOjkSI"

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан у змінних середовища")

ADMIN_ID = 7806482040
OWNER_ID = 7806482040
CHANNEL_ID = -1004428565734
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан у змінних середовища")

OWNER_ID = 7806482040
ADMIN_ID = 7806482040

CHANNEL_ID = -1004428565734

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(TOKEN)
dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "cupid.db")

# Проверяем возможность записи
try:
    test_file = os.path.join(BASE_DIR, "test_write.tmp")

    with open(test_file, "w", encoding="utf-8") as f:
        f.write("test")

    os.remove(test_file)

except Exception:
    DB_PATH = "/tmp/cupid.db"
    logging.warning(
        "Нет постоянной записи. Используется временная база: %s",
        DB_PATH
    )

db = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = db.cursor()


# ---------------------------------------------------------
# POSTS
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# USERS
# ---------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    role TEXT DEFAULT 'user'
)
""")


# ---------------------------------------------------------
# MODERATORS
# ---------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS moderators(
    user_id INTEGER PRIMARY KEY,
    buy_date TEXT
)
""")


# ---------------------------------------------------------
# POST ADMINS
# ---------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS post_admins(
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    added_at TEXT
)
""")


# ---------------------------------------------------------
# VIP POSTS
# ---------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS vip_posts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_number INTEGER,
    vip_type TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    unpin_time TEXT
)
""")


# ---------------------------------------------------------
# PROBIT HISTORY
# ---------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS probit_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    query TEXT,
    result TEXT,
    created_at TEXT
)
""")


# ---------------------------------------------------------
# BANS
# ---------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS bans(
    user_id INTEGER PRIMARY KEY,
    ban_until TEXT,
    reason TEXT,
    banned_by INTEGER
)
""")


# ---------------------------------------------------------
# APPEALS
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# VIP USERS
# ---------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS vip_users(
    user_id INTEGER PRIMARY KEY,
    vip_type TEXT,
    expires_at TEXT,
    created_at TEXT
)
""")


# ---------------------------------------------------------
# DELETE LOGS
# ---------------------------------------------------------

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


# =========================================================
# MEMORY
# =========================================================

photos = {}
pending = {}

waiting_delete = {}
waiting_pin = set()
waiting_question = set()

auto_approve = False


# =========================================================
# DATABASE HELPERS
# =========================================================

def get_role(user_id):
    cur.execute(
        "SELECT role FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    return row[0] if row else "user"


def set_role(user_id, role):
    cur.execute("""
        INSERT OR REPLACE INTO users(user_id, role)
        VALUES(?, ?)
    """, (user_id, role))

    db.commit()


def is_admin(user_id):
    return user_id == ADMIN_ID or user_id == OWNER_ID


def is_post_admin(user_id):
    if is_admin(user_id):
        return True

    cur.execute(
        "SELECT user_id FROM post_admins WHERE user_id=?",
        (user_id,)
    )

    return cur.fetchone() is not None


def add_post_admin(user_id, added_by):
    cur.execute("""
        INSERT OR REPLACE INTO post_admins(
            user_id,
            added_by,
            added_at
        )
        VALUES(?, ?, ?)
    """, (
        user_id,
        added_by,
        datetime.now().isoformat()
    ))

    db.commit()


def remove_post_admin(user_id):
    cur.execute(
        "DELETE FROM post_admins WHERE user_id=?",
        (user_id,)
    )

    db.commit()


def get_post_admins():
    cur.execute("""
        SELECT user_id, added_by, added_at
        FROM post_admins
        ORDER BY added_at DESC
    """)

    return cur.fetchall()


# =========================================================
# POSTS DATABASE
# =========================================================

def save_post(
    message_id_1,
    message_id_2,
    user_id,
    username=None,
    first_name=None
):
    """
    Номер поста сохраняется в SQLite.
    После перезапуска он НЕ начинается заново.
    """

    cur.execute("SELECT MAX(number) FROM posts")

    last = cur.fetchone()[0]

    if last is None:
        number = 1
    else:
        number = last + 1

    cur.execute("""
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
    """, (
        number,
        message_id_1,
        message_id_2,
        user_id,
        username,
        first_name,
        datetime.now().isoformat()
    ))

    db.commit()

    return number


def get_post(number):
    cur.execute("""
        SELECT
            message_id_1,
            message_id_2,
            user_id,
            username,
            first_name,
            created_at
        FROM posts
        WHERE number=?
    """, (number,))

    return cur.fetchone()


def remove_post(number):
    cur.execute(
        "DELETE FROM posts WHERE number=?",
        (number,)
    )

    db.commit()


def get_all_posts():
    cur.execute("""
        SELECT
            number,
            message_id_1,
            message_id_2,
            user_id,
            username,
            first_name,
            created_at
        FROM posts
        ORDER BY number DESC
    """)

    return cur.fetchall()


def log_delete(
    post_number,
    user_id,
    username,
    status
):
    cur.execute("""
        INSERT INTO delete_logs(
            post_number,
            user_id,
            username,
            deleted_at,
            status
        )
        VALUES(?, ?, ?, ?, ?)
    """, (
        post_number,
        user_id,
        username,
        datetime.now().isoformat(),
        status
    ))

    db.commit()


# =========================================================
# BAN SYSTEM
# =========================================================

def is_banned(user_id):
    cur.execute(
        "SELECT ban_until FROM bans WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    if not row:
        return False

    if row[0] is None:
        return True

    try:
        until = datetime.fromisoformat(row[0])

        if datetime.now() < until:
            return True

        cur.execute(
            "DELETE FROM bans WHERE user_id=?",
            (user_id,)
        )

        db.commit()

        return False

    except Exception:
        return False


def ban_user(user_id, reason="", until=None, banned_by=None):
    ban_until = until.isoformat() if until else None

    cur.execute("""
        INSERT OR REPLACE INTO bans(
            user_id,
            ban_until,
            reason,
            banned_by
        )
        VALUES(?, ?, ?, ?)
    """, (
        user_id,
        ban_until,
        reason,
        banned_by
    ))

    db.commit()


def unban_user(user_id):
    cur.execute(
        "DELETE FROM bans WHERE user_id=?",
        (user_id,)
    )

    db.commit()


# =========================================================
# VIP
# =========================================================

def set_vip(user_id, vip_type, days):
    expires = datetime.now() + timedelta(days=days)

    cur.execute("""
        INSERT OR REPLACE INTO vip_users(
            user_id,
            vip_type,
            expires_at,
            created_at
        )
        VALUES(?, ?, ?, ?)
    """, (
        user_id,
        vip_type,
        expires.isoformat(),
        datetime.now().isoformat()
    ))

    db.commit()


def get_vip(user_id):
    cur.execute("""
        SELECT vip_type, expires_at
        FROM vip_users
        WHERE user_id=?
    """, (user_id,))

    row = cur.fetchone()

    if not row:
        return None

    try:
        expires = datetime.fromisoformat(row[1])

        if datetime.now() >= expires:
            cur.execute(
                "DELETE FROM vip_users WHERE user_id=?",
                (user_id,)
            )

            db.commit()

            return None

    except Exception:
        return None

    return row


# =========================================================
# MENUS
# =========================================================

def main_menu():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="💌 Створити пару"),
            ],
            [
                KeyboardButton(text="💎 VIP послуги"),
                KeyboardButton(text="⭐ Послуги"),
            ],
            [
                KeyboardButton(text="📜 Правила"),
                KeyboardButton(text="❓ Питання до адміна"),
            ],
        ],
        resize_keyboard=True
    )


def services_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📌 Закріпити пост — 5 ⭐",
                    callback_data="buy_pin"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Видалити пост — 5 ⭐",
                    callback_data="buy_delete"
                )
            ],
        ]
    )


def vip_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💎 VIP Basic — 10 ⭐",
                    callback_data="vip_basic"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👑 VIP Premium — 25 ⭐",
                    callback_data="vip_premium"
                )
            ],
        ]
    )


def admin_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Всі пости",
                    callback_data="admin_posts"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👮 Пост-адміни",
                    callback_data="admin_post_admins"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Автоодобрення",
                    callback_data="admin_auto"
                )
            ],
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start_handler(message: Message):

    uid = message.from_user.id

    if is_banned(uid):
        await message.answer(
            "🚫 Ви заблоковані та не можете користуватися ботом."
        )
        return

    await message.answer(
        "💘 <b>Вітаємо у Купідоні!</b>\n\n"
        "Обирайте потрібну дію кнопками нижче.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================================================
# RULES
# =========================================================

@dp.message(F.text == "📜 Правила")
async def rules_handler(message: Message):

    await message.answer(
        "📜 <b>Правила</b>\n\n"
        "1. Заборонений 18+ контент.\n"
        "2. Заборонені образи та погрози.\n"
        "3. Заборонений спам.\n"
        "4. Не публікуйте персональні дані інших людей.\n"
        "5. Адміністрація має право відмовити у публікації.\n\n"
        "Перед використанням бота прочитайте правила.",
        parse_mode="HTML"
    )


# =========================================================
# SERVICES
# =========================================================

@dp.message(F.text == "⭐ Послуги")
async def services_handler(message: Message):

    await message.answer(
        "⭐ <b>ПЛАТНІ ПОСЛУГИ</b>\n\n"
        "📌 Закріплення поста — 5 ⭐\n"
        "🗑 Видалення поста — 5 ⭐",
        parse_mode="HTML",
        reply_markup=services_menu()
    )


# =========================================================
# VIP
# =========================================================

@dp.message(F.text == "💎 VIP послуги")
async def vip_handler(message: Message):

    await message.answer(
        "💎 <b>VIP ПОСЛУГИ</b>\n\n"
        "💎 Basic — 10 ⭐\n"
        "👑 Premium — 25 ⭐",
        parse_mode="HTML",
        reply_markup=vip_menu()
    )


# =========================================================
# BUY PIN
# =========================================================

@dp.callback_query(F.data == "buy_pin")
async def buy_pin_handler(callback: CallbackQuery):

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Закріплення поста",
        description="Закріплення вашого поста в каналі.",
        payload="pin_post",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Закріплення поста",
                amount=5
            )
        ]
    )

    await callback.answer()


# =========================================================
# BUY DELETE
# =========================================================

@dp.callback_query(F.data == "buy_delete")
async def buy_delete_handler(callback: CallbackQuery):

    uid = callback.from_user.id

    await bot.send_invoice(
        chat_id=uid,
        title="Видалення поста",
        description="Видалення одного поста з каналу.",
        payload="delete_post",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Видалення поста",
                amount=5
            )
        ]
    )

    await callback.answer()


# =========================================================
# VIP PAYMENTS
# =========================================================

@dp.callback_query(F.data == "vip_basic")
async def vip_basic_handler(callback: CallbackQuery):

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="VIP Basic",
        description="VIP Basic на 2 дні.",
        payload="vip_basic",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="VIP Basic",
                amount=10
            )
        ]
    )

    await callback.answer()


@dp.callback_query(F.data == "vip_premium")
async def vip_premium_handler(callback: CallbackQuery):

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="VIP Premium",
        description="VIP Premium на 7 днів.",
        payload="vip_premium",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="VIP Premium",
                amount=25
            )
        ]
    )

    await callback.answer()


# =========================================================
# PRE CHECKOUT
# =========================================================

@dp.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):

    await query.answer(ok=True)


# =========================================================
# PAYMENT SUCCESS
# =========================================================

@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):

    payment = message.successful_payment

    uid = message.from_user.id
    payload = payment.invoice_payload

    logging.info(
        "Payment: uid=%s payload=%s",
        uid,
        payload
    )

    # -----------------------------------------------------
    # VIP BASIC
    # -----------------------------------------------------

    if payload == "vip_basic":

        set_vip(
            uid,
            "basic",
            2
        )

        await message.answer(
            "💎 <b>VIP Basic активовано!</b>\n\n"
            "Термін: 2 дні.",
            parse_mode="HTML"
        )

        return

    # -----------------------------------------------------
    # VIP PREMIUM
    # -----------------------------------------------------

    if payload == "vip_premium":

        set_vip(
            uid,
            "premium",
            7
        )

        await message.answer(
            "👑 <b>VIP Premium активовано!</b>\n\n"
            "Термін: 7 днів.",
            parse_mode="HTML"
        )

        return

    # -----------------------------------------------------
    # PIN
    # -----------------------------------------------------

    if payload == "pin_post":

        waiting_pin.add(uid)

        await message.answer(
            "📌 <b>Введіть номер поста для закріплення.</b>\n\n"
            "Наприклад: <code>42</code>",
            parse_mode="HTML"
        )

        return

    # -----------------------------------------------------
    # DELETE
    # -----------------------------------------------------

    if payload == "delete_post":

        waiting_delete[uid] = {
            "timestamp": datetime.now(),
            "status": "waiting"
        }

        await message.answer(
            "🗑 <b>Введіть номер поста для видалення.</b>\n\n"
            "Наприклад: <code>42</code>\n\n"
            "⏳ У вас є 5 хвилин.",
            parse_mode="HTML"
        )

        asyncio.create_task(
            auto_cancel_delete(uid)
        )

        return


# =========================================================
# AUTO CANCEL DELETE
# =========================================================

async def auto_cancel_delete(uid):

    await asyncio.sleep(300)

    data = waiting_delete.get(uid)

    if not data:
        return

    waiting_delete.pop(uid, None)

    try:
        await bot.send_message(
            uid,
            "⌛ Час на введення номера поста закінчився."
        )
    except Exception:
        pass


# =========================================================
# NUMBER HANDLER
# =========================================================

@dp.message(F.text.regexp(r"^\d+$"))
async def number_handler(message: Message):

    uid = message.from_user.id

    try:
        number = int(message.text.strip())
    except ValueError:
        return

    # =====================================================
    # DELETE
    # =====================================================

    if uid in waiting_delete:

        waiting_delete.pop(uid, None)

        row = get_post(number)

        if not row:

            await message.answer(
                f"❌ Пост №{number} не знайдено в базі."
            )

            return

        (
            msg1,
            msg2,
            post_user_id,
            username,
            first_name,
            created_at
        ) = row

        deleted = 0
        errors = []

        # -------------------------------------------------
        # DELETE FIRST MESSAGE
        # -------------------------------------------------

        if msg1:

            try:

                await bot.delete_message(
                    CHANNEL_ID,
                    msg1
                )

                deleted += 1

            except Exception as e:

                logging.warning(
                    "Не удалось удалить сообщение %s: %s",
                    msg1,
                    e
                )

                errors.append(
                    f"Фото 1: {e}"
                )

        # -------------------------------------------------
        # DELETE SECOND MESSAGE
        # -------------------------------------------------

        if msg2:

            try:

                await bot.delete_message(
                    CHANNEL_ID,
                    msg2
                )

                deleted += 1

            except Exception as e:

                logging.warning(
                    "Не удалось удалить сообщение %s: %s",
                    msg2,
                    e
                )

                errors.append(
                    f"Фото 2: {e}"
                )

        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        if deleted == 2:

            remove_post(number)

            log_delete(
                number,
                uid,
                message.from_user.username,
                "deleted_2_of_2"
            )

            await message.answer(
                f"✅ <b>ПОСТ №{number} ПОВНІСТЮ ВИДАЛЕНО!</b>",
                parse_mode="HTML"
            )

            return

        # -------------------------------------------------
        # PARTIAL
        # -------------------------------------------------

        if deleted == 1:

            remove_post(number)

            log_delete(
                number,
                uid,
                message.from_user.username,
                "deleted_1_of_2"
            )

            await message.answer(
                f"⚠️ <b>ПОСТ №{number} ВИДАЛЕНО ЧАСТКОВО</b>\n\n"
                f"Видалено: 1/2\n\n"
                + "\n".join(errors),
                parse_mode="HTML"
            )

            return

        # -------------------------------------------------
        # FAILED
        # -------------------------------------------------

        log_delete(
            number,
            uid,
            message.from_user.username,
            "failed"
        )

        await message.answer(
            f"❌ <b>ПОСТ №{number} НЕ ВИДАЛЕНО</b>\n\n"
            + "\n".join(errors),
            parse_mode="HTML"
        )

        return

    # =====================================================
    # PIN
    # =====================================================

    if uid in waiting_pin:

        waiting_pin.remove(uid)

        data = get_post(number)

        if not data:

            await message.answer(
                f"❌ Пост №{number} не знайдено."
            )

            return

        msg1 = data[0]

        try:

            await bot.pin_chat_message(
                CHANNEL_ID,
                msg1,
                disable_notification=False
            )

            await message.answer(
                f"📌 Пост №{number} закріплено!"
            )

        except Exception as e:

            logging.exception(
                "Ошибка закрепления"
            )

            await message.answer(
                f"❌ Не вдалося закріпити пост.\n\n{e}"
            )

        return

    # =====================================================
    # NO OPERATION
    # =====================================================

    await message.answer(
        "❌ Немає активних операцій для цього номера."
    )


# =========================================================
# CREATE POST
# =========================================================

@dp.message(F.text == "💌 Створити пару")
async def create_pair(message: Message):

    uid = message.from_user.id

    if is_banned(uid):

        await message.answer(
            "🚫 Ви заблоковані."
        )

        return

    photos[uid] = []

    await message.answer(
        "💌 Надішліть <b>2 фотографії</b>.\n\n"
        "Після цього пост буде переданий на модерацію.",
        parse_mode="HTML"
    )


# =========================================================
# PHOTO RECEIVER
# =========================================================

@dp.message(F.photo)
async def photo_handler(message: Message):

    uid = message.from_user.id

    if is_banned(uid):
        return

    if uid not in photos:
        return

    photos[uid].append(
        message.photo[-1].file_id
    )

    count = len(photos[uid])

    if count == 1:

        await message.answer(
            "📸 Перше фото отримано.\n"
            "Надішліть друге."
        )

        return

    if count >= 2:

        photo_list = photos[uid][:2]

        pending[uid] = photo_list

        photos.pop(uid, None)

        # -------------------------------------------------
        # AUTO APPROVE
        # -------------------------------------------------

        if auto_approve:

            try:

                media = [
                    InputMediaPhoto(
                        media=photo_list[0]
                    ),
                    InputMediaPhoto(
                        media=photo_list[1]
                    )
                ]

                sent = await bot.send_media_group(
                    CHANNEL_ID,
                    media=media
                )

                msg1 = sent[0].message_id
                msg2 = sent[1].message_id

                number = save_post(
                    msg1,
                    msg2,
                    uid,
                    message.from_user.username,
                    message.from_user.first_name
                )

                await message.answer(
                    f"✅ Пост опубліковано!\n\n"
                    f"🔢 Номер поста: <b>#{number}</b>",
                    parse_mode="HTML"
                )

            except Exception as e:

                logging.exception(
                    "Ошибка автопубликации"
                )

                await message.answer(
                    f"❌ Помилка публікації:\n{e}"
                )

            return

        await message.answer(
            "✅ Обидва фото отримано.\n"
            "⏳ Пост відправлено на модерацію."
        )

        # -------------------------------------------------
        # SEND MODERATION TO ADMIN
        # -------------------------------------------------

        try:

            media = [
                InputMediaPhoto(
                    media=photo_list[0]
                ),
                InputMediaPhoto(
                    media=photo_list[1]
                )
            ]

            await bot.send_media_group(
                ADMIN_ID,
                media=media
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Опублікувати",
                            callback_data=f"approve:{uid}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Відхилити",
                            callback_data=f"decline:{uid}"
                        )
                    ]
                ]
            )

            await bot.send_message(
                ADMIN_ID,
                f"📝 <b>Новий пост на модерацію</b>\n\n"
                f"👤 User ID: <code>{uid}</code>\n"
                f"🔗 Username: @{message.from_user.username or 'немає'}\n"
                f"👤 Ім'я: {message.from_user.first_name or 'немає'}",
                parse_mode="HTML",
                reply_markup=keyboard
            )

        except Exception as e:

            logging.exception(
                "Ошибка отправки модерации"
            )


# =========================================================
# APPROVE
# =========================================================

@dp.callback_query(F.data.startswith("approve:"))
async def approve_handler(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        await callback.answer(
            "❌ Немає доступу.",
            show_alert=True
        )
        return

    try:

        uid = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Помилка."
        )

        return

    if uid not in pending:

        await callback.answer(
            "❌ Пост уже оброблено.",
            show_alert=True
        )

        return

    photo_list = pending.pop(uid)

    try:

        media = [
            InputMediaPhoto(
                media=photo_list[0]
            ),
            InputMediaPhoto(
                media=photo_list[1]
            )
        ]

        sent = await bot.send_media_group(
            CHANNEL_ID,
            media=media
        )

        msg1 = sent[0].message_id
        msg2 = sent[1].message_id

        # -------------------------------------------------
        # IMPORTANT:
        # NUMBER SAVED TO DB
        # -------------------------------------------------

        number = save_post(
            msg1,
            msg2,
            uid
        )

        await callback.message.edit_text(
            f"✅ <b>ПОСТ ОПУБЛІКОВАНО</b>\n\n"
            f"🔢 Номер: <b>#{number}</b>\n"
            f"👤 User ID: <code>{uid}</code>",
            parse_mode="HTML"
        )

        try:

            await bot.send_message(
                uid,
                f"✅ Ваш пост опубліковано!\n\n"
                f"🔢 Номер поста: <b>#{number}</b>",
                parse_mode="HTML"
            )

        except Exception:
            pass

    except Exception as e:

        logging.exception(
            "Ошибка публикации"
        )

        await callback.message.edit_text(
            f"❌ Помилка публікації:\n\n{e}"
        )

    await callback.answer()


# =========================================================
# DECLINE
# =========================================================

@dp.callback_query(F.data.startswith("decline:"))
async def decline_handler(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):

        await callback.answer(
            "❌ Немає доступу.",
            show_alert=True
        )

        return

    try:

        uid = int(
            callback.data.split(":")[1]
        )

    except Exception:

        await callback.answer(
            "Помилка."
        )

        return

    pending.pop(uid, None)

    try:

        await callback.message.edit_text(
            f"❌ <b>ПОСТ ВІДХИЛЕНО</b>\n\n"
            f"User ID: <code>{uid}</code>",
            parse_mode="HTML"
        )

    except Exception:
        pass

    try:

        await bot.send_message(
            uid,
            "❌ Ваш пост було відхилено модератором."
        )

    except Exception:
        pass

    await callback.answer()


# =========================================================
# QUESTION TO ADMIN
# =========================================================

@dp.message(F.text == "❓ Питання до адміна")
async def question_start(message: Message):

    uid = message.from_user.id

    waiting_question.add(uid)

    await message.answer(
        "❓ Напишіть ваше питання одним повідомленням."
    )


# =========================================================
# QUESTION HANDLER
# =========================================================

@dp.message(F.text)
async def handle_question(message: Message):

    uid = message.from_user.id

    # -----------------------------------------------------
    # ВАЖНО:
    # Если человек вводит номер во время удаления/закрепления,
    # generic handler НЕ должен отвечать меню.
    # -----------------------------------------------------

    if message.text and message.text.strip().isdigit():

        if uid in waiting_delete or uid in waiting_pin:
            return

    # -----------------------------------------------------
    # QUESTION
    # -----------------------------------------------------

    if uid in waiting_question:

        waiting_question.remove(uid)

        question = message.text

        cur.execute("""
            INSERT INTO appeals(
                user_id,
                username,
                question,
                created_at
            )
            VALUES(?, ?, ?, ?)
        """, (
            uid,
            message.from_user.username,
            question,
            datetime.now().isoformat()
        ))

        db.commit()

        await message.answer(
            "✅ Питання передано адміністратору."
        )

        try:

            await bot.send_message(
                ADMIN_ID,
                "❓ <b>НОВЕ ПИТАННЯ</b>\n\n"
                f"👤 ID: <code>{uid}</code>\n"
                f"🔗 Username: @{message.from_user.username or 'немає'}\n\n"
                f"💬 {question}",
                parse_mode="HTML"
            )

        except Exception:
            pass

        return

    # -----------------------------------------------------
    # DEFAULT
    # -----------------------------------------------------

    await message.answer(
        "💘 Використовуйте кнопки меню:",
        reply_markup=main_menu()
    )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):

    if not is_admin(message.from_user.id):

        await message.answer(
            "❌ Немає доступу."
        )

        return

    await message.answer(
        "🛠 <b>ПАНЕЛЬ АДМІНІСТРАТОРА</b>",
        parse_mode="HTML",
        reply_markup=admin_menu()
    )


# =========================================================
# CHECK CHANNEL
# =========================================================

@dp.message(Command("check_channel"))
async def check_channel(message: Message):

    if not is_admin(message.from_user.id):
        return

    try:

        chat = await bot.get_chat(
            CHANNEL_ID
        )

        await message.answer(
            "✅ Бот має доступ до каналу.\n\n"
            f"Назва: {chat.title}\n"
            f"ID: <code>{chat.id}</code>",
            parse_mode="HTML"
        )

    except Exception as e:

        await message.answer(
            f"❌ Немає доступу до каналу:\n\n{e}"
        )


# =========================================================
# ALL POSTS
# =========================================================

@dp.message(Command("all_posts"))
async def all_posts(message: Message):

    if not is_post_admin(message.from_user.id):

        await message.answer(
            "❌ Немає доступу."
        )

        return

    posts = get_all_posts()

    if not posts:

        await message.answer(
            "📭 Постів у базі немає."
        )

        return

    text = "📋 <b>ПОСТИ</b>\n\n"

    for post in posts[:50]:

        number = post[0]
        user_id = post[3]
        username = post[4]
        first_name = post[5]

        text += (
            f"#{number}\n"
            f"👤 {first_name or 'Без имени'}\n"
            f"🆔 <code>{user_id}</code>\n"
            f"🔗 @{username or 'немає'}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# POST INFO
# =========================================================

@dp.message(Command("post_info"))
async def post_info(message: Message):

    if not is_post_admin(message.from_user.id):

        await message.answer(
            "❌ Немає доступу."
        )

        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Використання:\n"
            "/post_info 42"
        )

        return

    try:

        number = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ Номер має бути числом."
        )

        return

    post = get_post(number)

    if not post:

        await message.answer(
            f"❌ Пост №{number} не знайдено."
        )

        return

    (
        msg1,
        msg2,
        user_id,
        username,
        first_name,
        created_at
    ) = post

    await message.answer(
        f"📋 <b>ПОСТ №{number}</b>\n\n"
        f"👤 Ім'я: {first_name or 'немає'}\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"🔗 Username: @{username or 'немає'}\n"
        f"💬 Message 1: <code>{msg1}</code>\n"
        f"💬 Message 2: <code>{msg2}</code>\n"
        f"📅 Створено: {created_at}",
        parse_mode="HTML"
    )


# =========================================================
# ADD POST ADMIN
# =========================================================

@dp.message(Command("add_post_admin"))
async def add_post_admin_command(message: Message):

    if message.from_user.id != OWNER_ID:

        await message.answer(
            "❌ Ця команда доступна тільки власнику."
        )

        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Використання:\n"
            "/add_post_admin USER_ID"
        )

        return

    try:

        user_id = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ User ID має бути числом."
        )

        return

    add_post_admin(
        user_id,
        message.from_user.id
    )

    await message.answer(
        f"✅ Пост-адміна додано.\n\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"Він може:\n"
        f"• дивитися пости\n"
        f"• дивитися ID автора\n"
        f"• дивитися username\n"
        f"• перевіряти інформацію про пост",
        parse_mode="HTML"
    )


# =========================================================
# REMOVE POST ADMIN
# =========================================================

@dp.message(Command("remove_post_admin"))
async def remove_post_admin_command(message: Message):

    if message.from_user.id != OWNER_ID:

        await message.answer(
            "❌ Ця команда доступна тільки власнику."
        )

        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Використання:\n"
            "/remove_post_admin USER_ID"
        )

        return

    try:

        user_id = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ User ID має бути числом."
        )

        return

    remove_post_admin(user_id)

    await message.answer(
        f"✅ Пост-адміна видалено.\n\n"
        f"🆔 ID: <code>{user_id}</code>",
        parse_mode="HTML"
    )


# =========================================================
# POST ADMINS LIST
# =========================================================

@dp.message(Command("post_admins"))
async def post_admins_command(message: Message):

    if message.from_user.id != OWNER_ID:

        await message.answer(
            "❌ Немає доступу."
        )

        return

    admins = get_post_admins()

    if not admins:

        await message.answer(
            "📭 Пост-адмінів немає."
        )

        return

    text = "👮 <b>ПОСТ-АДМІНИ</b>\n\n"

    for user_id, added_by, added_at in admins:

        text += (
            f"🆔 <code>{user_id}</code>\n"
            f"➕ Додав: <code>{added_by}</code>\n"
            f"📅 {added_at}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# BAN
# =========================================================

@dp.message(Command("ban"))
async def ban_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 2:

        await message.answer(
            "Використання:\n"
            "/ban USER_ID причина"
        )

        return

    try:

        user_id = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ Невірний ID."
        )

        return

    reason = parts[2] if len(parts) >= 3 else "Не вказано"

    ban_user(
        user_id,
        reason,
        banned_by=message.from_user.id
    )

    await message.answer(
        f"🚫 Користувача <code>{user_id}</code> заблоковано.\n"
        f"Причина: {reason}",
        parse_mode="HTML"
    )


# =========================================================
# UNBAN
# =========================================================

@dp.message(Command("unban"))
async def unban_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "/unban USER_ID"
        )

        return

    try:

        user_id = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ Невірний ID."
        )

        return

    unban_user(user_id)

    await message.answer(
        f"✅ Користувача <code>{user_id}</code> розблоковано.",
        parse_mode="HTML"
    )


# =========================================================
# BANNED LIST
# =========================================================

@dp.message(Command("banned_list"))
async def banned_list(message: Message):

    if not is_admin(message.from_user.id):
        return

    cur.execute("""
        SELECT user_id, ban_until, reason
        FROM bans
        ORDER BY user_id
    """)

    rows = cur.fetchall()

    if not rows:

        await message.answer(
            "📭 Заблокованих користувачів немає."
        )

        return

    text = "🚫 <b>ЗАБЛОКОВАНІ</b>\n\n"

    for user_id, until, reason in rows:

        text += (
            f"🆔 <code>{user_id}</code>\n"
            f"⏳ {until or 'назавжди'}\n"
            f"📄 {reason or 'без причини'}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# VIP STATUS
# =========================================================

@dp.message(Command("vip_status"))
async def vip_status(message: Message):

    vip = get_vip(
        message.from_user.id
    )

    if not vip:

        await message.answer(
            "ℹ️ У вас немає активного VIP."
        )

        return

    vip_type, expires = vip

    await message.answer(
        f"💎 <b>Ваш VIP</b>\n\n"
        f"Тип: {vip_type}\n"
        f"До: {expires}",
        parse_mode="HTML"
    )


# =========================================================
# MY POSTS
# =========================================================

@dp.message(Command("my_posts"))
async def my_posts(message: Message):

    uid = message.from_user.id

    cur.execute("""
        SELECT number, created_at
        FROM posts
        WHERE user_id=?
        ORDER BY number DESC
    """, (uid,))

    rows = cur.fetchall()

    if not rows:

        await message.answer(
            "📭 У вас немає опублікованих постів."
        )

        return

    text = "📋 <b>МОЇ ПОСТИ</b>\n\n"

    for number, created_at in rows:

        text += (
            f"🔢 #{number}\n"
            f"📅 {created_at}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# CANCEL
# =========================================================

@dp.message(Command("cancel"))
async def cancel_command(message: Message):

    uid = message.from_user.id

    waiting_delete.pop(uid, None)
    waiting_pin.discard(uid)
    waiting_question.discard(uid)

    photos.pop(uid, None)
    pending.pop(uid, None)

    await message.answer(
        "❌ Поточну операцію скасовано.",
        reply_markup=main_menu()
    )


# =========================================================
# APPEALS
# =========================================================

@dp.message(Command("appeals"))
async def appeals_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    cur.execute("""
        SELECT
            id,
            user_id,
            username,
            question,
            status,
            created_at
        FROM appeals
        WHERE status='open'
        ORDER BY id DESC
    """)

    rows = cur.fetchall()

    if not rows:

        await message.answer(
            "📭 Відкритих питань немає."
        )

        return

    text = "❓ <b>ПИТАННЯ</b>\n\n"

    for row in rows[:30]:

        appeal_id = row[0]
        user_id = row[1]
        username = row[2]
        question = row[3]
        created_at = row[5]

        text += (
            f"#{appeal_id}\n"
            f"👤 <code>{user_id}</code>\n"
            f"🔗 @{username or 'немає'}\n"
            f"💬 {question}\n"
            f"📅 {created_at}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# ANSWER APPEAL
# =========================================================

@dp.message(Command("answer"))
async def answer_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 3:

        await message.answer(
            "Використання:\n"
            "/answer ID відповідь"
        )

        return

    try:

        appeal_id = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ Невірний ID питання."
        )

        return

    answer = parts[2]

    cur.execute("""
        SELECT user_id
        FROM appeals
        WHERE id=? AND status='open'
    """, (appeal_id,))

    row = cur.fetchone()

    if not row:

        await message.answer(
            "❌ Питання не знайдено."
        )

        return

    user_id = row[0]

    cur.execute("""
        UPDATE appeals
        SET
            answer=?,
            status='answered',
            answered_at=?
        WHERE id=?
    """, (
        answer,
        datetime.now().isoformat(),
        appeal_id
    ))

    db.commit()

    try:

        await bot.send_message(
            user_id,
            f"📩 <b>Відповідь адміністратора:</b>\n\n"
            f"{answer}",
            parse_mode="HTML"
        )

    except Exception:
        pass

    await message.answer(
        "✅ Відповідь відправлено."
    )


# =========================================================
# ADMIN CALLBACK
# =========================================================

@dp.callback_query(F.data == "admin_posts")
async def admin_posts_callback(callback: CallbackQuery):

    if not is_post_admin(callback.from_user.id):

        await callback.answer(
            "❌ Немає доступу.",
            show_alert=True
        )

        return

    posts = get_all_posts()

    if not posts:

        await callback.message.answer(
            "📭 Постів немає."
        )

        await callback.answer()

        return

    text = "📋 <b>ОСТАННІ ПОСТИ</b>\n\n"

    for post in posts[:30]:

        number = post[0]
        user_id = post[3]
        username = post[4]

        text += (
            f"#{number} — "
            f"<code>{user_id}</code> — "
            f"@{username or 'немає'}\n"
        )

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN POST ADMINS
# =========================================================

@dp.callback_query(F.data == "admin_post_admins")
async def admin_post_admins_callback(callback: CallbackQuery):

    if callback.from_user.id != OWNER_ID:

        await callback.answer(
            "❌ Тільки власник.",
            show_alert=True
        )

        return

    admins = get_post_admins()

    if not admins:

        await callback.message.answer(
            "📭 Пост-адмінів немає."
        )

        await callback.answer()

        return

    text = "👮 <b>ПОСТ-АДМІНИ</b>\n\n"

    for user_id, added_by, added_at in admins:

        text += (
            f"🆔 <code>{user_id}</code>\n"
            f"➕ {added_by}\n"
            f"📅 {added_at}\n\n"
        )

    await callback.message.answer(
        text,
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# AUTO APPROVE
# =========================================================

@dp.callback_query(F.data == "admin_auto")
async def admin_auto_callback(callback: CallbackQuery):

    global auto_approve

    if not is_admin(callback.from_user.id):

        await callback.answer(
            "❌ Немає доступу.",
            show_alert=True
        )

        return

    auto_approve = not auto_approve

    status = "УВІМКНЕНО" if auto_approve else "ВИМКНЕНО"

    await callback.message.answer(
        f"⚙️ Автоодобрення: <b>{status}</b>",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# PROBIT POST
# =========================================================

@dp.message(Command("probit_post"))
async def probit_post(message: Message):

    # Пост-адмін має тільки перевіряти інформацію
    # самого поста, без надання йому повноважень
    # повного адміністратора.

    if not is_post_admin(message.from_user.id):

        await message.answer(
            "❌ Немає доступу."
        )

        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Використання:\n"
            "/probit_post 42"
        )

        return

    try:

        number = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ Номер поста має бути числом."
        )

        return

    post = get_post(number)

    if not post:

        await message.answer(
            "❌ Пост не знайдено."
        )

        return

    (
        msg1,
        msg2,
        user_id,
        username,
        first_name,
        created_at
    ) = post

    await message.answer(
        f"🔎 <b>ПЕРЕВІРКА ПОСТА №{number}</b>\n\n"
        f"👤 Ім'я: {first_name or 'немає'}\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"🔗 Username: @{username or 'немає'}\n"
        f"📅 Створено: {created_at}",
        parse_mode="HTML"
    )


# =========================================================
# HEALTH CHECK FOR RENDER
# =========================================================

async def health(request):

    return web.json_response({
        "status": "ok",
        "bot": "running"
    })


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
        "0.0.0.0",
        port
    )

    await site.start()

    logging.info(
        "Health server started on port %s",
        port
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    logging.info("Запуск бота...")

    await start_web_server()

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    logging.info(
        "Бот запущено. Telegram polling активний."
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logging.info(
            "Бот остановлен."
        )
