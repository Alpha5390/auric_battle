# battle.py
import re
import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.markdown import quote_html
from aiogram.utils import executor
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)

# ==== Sozlamalar ====
BOT_TOKEN = "8373707159:AAGNYsoM0Ivh22aT45ZZ7e2e4FFzFPA0HvQ"  # o'zingizniki bilan almashtiring
CHANNEL_ID = "@auric_stars"  # kanal ID (yoki "@kanalusername")
BOOST_LINK = "https://t.me/boost/auric_stars"
ADMIN_IDS = [6510338337,7399225804]  # admin ID(lar)

# === Bot va DB ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
DB = "users.db"

USERNAME_REGEX = re.compile(r'^@[A-Za-z0-9_]{5,}$')

WELCOME_TEXT = """Username Battle:
👋 Salom {name}!

📝 Iltimos, faqat o‘z @usernamengizni yuboring.
📋 Masalan: @mening_username

ℹ️ Username kamida 5 ta belgidan iborat bo‘lishi kerak.
"""

INVALID_FORMAT = """Username Battle:
❗ Noto‘g‘ri username formati!

✅ To‘g‘ri format: @username
📏 Kamida 5 ta belgi
🔤 Faqat harf, raqam va _ belgisi ishlatiladi

📋 Masalan: @user123
"""

NOT_YOUR_USERNAME = """Username Battle:
❌ Bu sizning usernamengiz emas!

💡 Sizning usernamengiz: {real}
ℹ️ Iltimos, faqat o‘z username'ingizni yuboring.
"""

SUCCESS_REPLY = """Username Battle:
✅ Username muvaffaqiyatli ro'yxatga olindi!
📊 Sizning raqamingiz: {number}
📢 Xabar {channel} kanaliga yuborildi.
"""

DEFAULT_CHANNEL_TEMPLATE = """📢 #{num} — Yangi ishtirokchi!

👤 Foydalanuvchi: {username}
⭐ Yulduzlar: {stars}
💬 Reaksiya: {reaction}
🚀 Boost: {boost}
🔗 Boost linki: {boost_link}
"""

# === DATABASE INIT ===
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            username TEXT UNIQUE,
            created_at TEXT
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        # default settings
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("battle_status", "on"))
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("template", DEFAULT_CHANNEL_TEMPLATE))
        # force_channel may be set by admin later
        await db.commit()

async def get_setting(key):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def set_setting(key, value):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def register_user(tg_id: int, username: str):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT id FROM users WHERE username = ?", (username,)) as cur:
            row = await cur.fetchone()
            if row:
                return row[0]
        now = datetime.utcnow().isoformat()
        await db.execute("INSERT INTO users (telegram_id, username, created_at) VALUES (?, ?, ?)",
                         (tg_id, username, now))
        await db.commit()
        async with db.execute("SELECT id FROM users WHERE username = ?", (username,)) as cur2:
            row2 = await cur2.fetchone()
            return row2[0] if row2 else None

# === Admin modes flags ===
admin_template_mode = {}       # admin_id -> True/False
admin_force_channel_mode = {}  # admin_id -> True/False

# === KEYBOARDS ===
def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🚀 Start Battle"), KeyboardButton("⏸ Stop Battle"))
    kb.add(KeyboardButton("📝 Set Template"), KeyboardButton("➕ Majburiy kanal qo‘shish"))
    return kb

# === COMMANDS ===
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        await message.reply("Admin panel:", reply_markup=admin_keyboard())
    else:
        text = WELCOME_TEXT.format(name=quote_html(message.from_user.first_name or "👤"))
        await message.reply(text, parse_mode=ParseMode.HTML)

@dp.message_handler(lambda m: m.from_user.id in ADMIN_IDS and m.text == "🚀 Start Battle")
async def start_battle(message: types.Message):
    await set_setting("battle_status", "on")
    await message.reply("✅ Battle boshlandi!")

@dp.message_handler(lambda m: m.from_user.id in ADMIN_IDS and m.text == "⏸ Stop Battle")
async def stop_battle(message: types.Message):
    await set_setting("battle_status", "off")
    await message.reply("⏸ Battle to‘xtatildi!")

@dp.message_handler(lambda m: m.from_user.id in ADMIN_IDS and m.text == "📝 Set Template")
async def ask_template(message: types.Message):
    admin_template_mode[message.from_user.id] = True
    await message.reply(
        "📝 Yangi kanal xabar shablonini yuboring.\n\n"
        "Parametrlar: {num}, {username}, {stars}, {reaction}, {boost}, {boost_link}\n\n"
        "Masalan:\n📢 #{num} — Yangi ishtirokchi!\n👤 Foydalanuvchi: {username}"
    )

@dp.message_handler(lambda m: m.from_user.id in ADMIN_IDS and m.text == "➕ Majburiy kanal qo‘shish")
async def ask_force_channel(message: types.Message):
    admin_force_channel_mode[message.from_user.id] = True
    await message.reply("📢 Majburiy kanalni yuboring (username bilan: @kanalname yoki kanal numeric ID: -1001234567890).")

# === HANDLE ADMIN INPUTS (template or force channel) ===
@dp.message_handler(lambda m: m.from_user.id in ADMIN_IDS)
async def admin_message_handler(message: types.Message):
    admin_id = message.from_user.id
    text = message.text.strip()
    if admin_template_mode.get(admin_id):
        await set_setting("template", text)
        admin_template_mode[admin_id] = False
        await message.reply("✅ Shablon yangilandi!")
    elif admin_force_channel_mode.get(admin_id):
        # Save exact value as given (e.g. @channel or -100...)
        await set_setting("force_channel", text)
        admin_force_channel_mode[admin_id] = False
        await message.reply(f"✅ Majburiy kanal saqlandi: {text}")
    else:
        # other admin messages not handled here
        await message.reply("❗ Bu buyruq tanilmadi. Admin menyudagi tugmalardan foydalaning.")

# === USERNAME HANDLER ===
@dp.message_handler()
async def handle_username(message: types.Message):
    # Check battle on/off
    status = await get_setting("battle_status")
    if status != "on":
        await message.reply("⏸ Hozircha battle yopiq.")
        return

    text = message.text.strip()
    user = message.from_user

    # Validate format
    if not USERNAME_REGEX.match(text):
        await message.reply(INVALID_FORMAT)
        return

    # Ensure user has a Telegram username set
    if not user.username:
        await message.reply("Sizning Telegram akkauntingizda username mavjud emas. Avval @username qo‘shing.")
        return

    provided = text
    expected = "@" + user.username
    if provided.lower() != expected.lower():
        await message.reply(NOT_YOUR_USERNAME.format(real=quote_html(expected)), parse_mode=ParseMode.HTML)
        return

    # Check forced channel subscription if set
    force_channel = await get_setting("force_channel")  # might be None or "@chan" or "-100..."
    if force_channel:
        # try to check membership
        try:
            # aiogram's get_chat_member accepts either username (with @) or numeric id (as int)
            chat_arg = force_channel
            if force_channel.startswith("-"):
                # numeric id stored as string - convert to int
                try:
                    chat_arg = int(force_channel)
                except Exception:
                    chat_arg = force_channel  # fallback
            member = await bot.get_chat_member(chat_arg, user.id)
            # valid statuses for being subscribed: member, administrator, creator
            if member.status not in ("member", "administrator", "creator"):
                # not a member
                if isinstance(force_channel, str) and force_channel.startswith("@"):
                    invite_link = f"https://t.me/{force_channel.lstrip('@')}"
                else:
                    invite_link = force_channel  # show raw id if no username
                await message.reply(
                    f"📢 Battle’da qatnashish uchun avval quyidagi kanalga a'zo bo'ling:\n{invite_link}"
                )
                return
        except Exception as e:
            logging.warning(f"Force channel check error: {e}")
            # if get_chat_member errors (bot not admin or channel private), inform user/admin
            await message.reply(
                "⚠️ Majburiy kanalga obuna tekshiruvida xato yuz berdi.\n"
                "Iltimos, admin bilan bog'laning."
            )
            return

    # register
    number = await register_user(user.id, provided.lower())
    if not number:
        await message.reply("Ro'yxatga olishda xatolik yuz berdi.")
        return

    # prepare channel message (escape HTML)
    stars = 5
    reaction = 1
    boost = 15
    template = await get_setting("template") or DEFAULT_CHANNEL_TEMPLATE

    try:
        channel_msg = template.format(
            num=quote_html(str(number)),
            username=quote_html(provided),
            stars=quote_html(str(stars)),
            reaction=quote_html(str(reaction)),
            boost=quote_html(str(boost)),
            boost_link=quote_html(BOOST_LINK)
        )
        await bot.send_message(CHANNEL_ID, channel_msg, parse_mode=ParseMode.HTML)
    except Exception:
        logging.exception("Channel post failed")
        await message.reply("✅ Username ro'yxatga olindi, lekin kanalga yuborilmadi.")
        return

    await message.reply(SUCCESS_REPLY.format(number=number, channel=CHANNEL_ID))

# === RUN ===
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True)
