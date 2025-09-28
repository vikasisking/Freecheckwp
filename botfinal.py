import os
import re
import logging
import sqlite3
import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from pyrogram import Client as PyroClient, filters as pyro_filters
from pyrogram.types import Message as PyroMessage

# ========== CONFIG ==========
# Telegram Bot (admin bot)
TOKEN = os.getenv("BOT_TOKEN", "7784541637:AAFyQ9jx1am7DA0LL2eOcfPPIzkmgqW3dmA")
GROUP_ID = -1002990279188
NUMBER_BOT_ID = os.getenv("NUMBER_BOT_ID", "8361669889")
NUMBER_PATTERN = r'^\d{8,13}$'
DB_FILE = "groupnumbers.db"

# Pyrogram UserBot
API_ID = int(os.getenv("API_ID", "22922489"))        # your API ID
API_HASH = os.getenv("API_HASH", "c9188fc0a202b2b3941d02dc9cc0cc84")  # your API HASH
SESSION_STRING = os.getenv("SESSION_STRING", "BQFdxPkAurkRwLKnKBh_9EJh50vgSI8lT_FF5PYRLr_ShgpUkrxGobpUMEYTiCE0-ZybiEzErd5d2mqY3-zcig5hj50DN-f3Nt0pSzGnDvZSEDutEyGEgQdfePST5F4qJjYda782z3RmtrCZTX7JmMW1qPzpCyW7eJGgzwyHohvzmik0uANJt_A8z5hPABJwkAKtFIk8Eat6autjSPCJUIZNGGOwZPRzahkw4Ftx3wQKBaoezKwVoPWrP36PDEFtGfw38mqpduu9A6xV87Y8rTtRlmKk_gUBuKsksf-9fQlznNnfap3rZfHpuTq8N2rl049SElb2CPzy1NI5KTcD2wl-bQDClwAAAAHib6fLAA")
ALLOWED_CHATS = []  # empty = all groups
# =============================

# Setup logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ========== DATABASE ==========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("CREATE TABLE IF NOT EXISTS group_numbers (number TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

def normalize_number(num):
    return str(num).strip()

def add_group_number(num):
    num = normalize_number(num)
    if not re.match(NUMBER_PATTERN, num):
        return
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR IGNORE INTO group_numbers (number) VALUES (?)", (num,))
    conn.commit()
    conn.close()

def load_group_numbers():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute("SELECT number FROM group_numbers")
    numbers = {normalize_number(row[0]) for row in cursor.fetchall()}
    conn.close()
    return numbers

# ========== ADMIN BOT (python-telegram-bot) ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        return
    await update.message.reply_text(
        "Welcome! Send me a .txt file of numbers. "
        "I'll compare with group numbers and return unmatched."
    )

async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        return
    numbers = load_group_numbers()
    if not numbers:
        await update.message.reply_text("No numbers in database.")
        return
    output = f"Numbers ({len(numbers)}):\n" + "\n".join(sorted(numbers))
    await update.message.reply_text(output[:4000])

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != int(GROUP_ID):
        return
    if not update.message.from_user or str(update.message.from_user.id) != NUMBER_BOT_ID:
        return
    text = normalize_number(update.message.text)
    if re.match(NUMBER_PATTERN, text):
        add_group_number(text)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        return
    document = update.message.document
    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("Send a .txt file only.")
        return
    file = await document.get_file()
    path = await file.download_to_drive(custom_path=document.file_name)

    file_numbers = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            num = normalize_number(line)
            if re.match(NUMBER_PATTERN, num):
                file_numbers.add(num)
    os.remove(path)

    group_numbers = load_group_numbers()
    unmatched = file_numbers - group_numbers
    if not unmatched:
        await update.message.reply_text("All numbers from file are already in group.")
        return
    text = "Unmatched:\n" + "\n".join(sorted(unmatched))
    await update.message.reply_text(text[:4000])

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

def build_admin_bot():
    init_db()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("debug", debug))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Chat(int(GROUP_ID)), handle_group_message))
    application.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, handle_document))
    application.add_error_handler(error_handler)
    return application

# ========== USERBOT (Pyrogram) ==========
pyro = PyroClient(SESSION_STRING, api_id=API_ID, api_hash=API_HASH)

def chat_allowed(chat_id, chat_username=None):
    if not ALLOWED_CHATS:
        return True
    if str(chat_id) in [str(x) for x in ALLOWED_CHATS]:
        return True
    if chat_username and chat_username in ALLOWED_CHATS:
        return True
    return False

@pyro.on_message(pyro_filters.group & ~pyro_filters.me)
async def echo_handler(client: PyroClient, message: PyroMessage):
    try:
        if message.service:
            return
        chat = message.chat
        if not chat_allowed(chat.id, getattr(chat, "username", None)):
            return
        await message.copy(chat.id)
        logger.info(f"Echoed in {chat.id}")
    except Exception as e:
        logger.error(f"Userbot error: {e}")

# ========== RUN BOTH TOGETHER ==========
async def main():
    admin_bot = build_admin_bot()
    # Run both applications concurrently
    await asyncio.gather(
        admin_bot.initialize(),
        pyro.start(),
    )
    # Start polling in parallel
    await asyncio.gather(
        admin_bot.start(),
        pyro.idle(),
    )

if __name__ == "__main__":
    asyncio.run(main())
