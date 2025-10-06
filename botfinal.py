import os
import logging
import threading
import uuid
from datetime import datetime, timedelta
from flask import Flask, Response
from pymongo import MongoClient
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------
# Flask Health Check
# -------------------------
app = Flask(__name__)

@app.route('/health')
def health():
    return Response("OK", status=200)

@app.route('/')
def root():
    return Response("Bot active ✅", status=200)

# -------------------------
# MongoDB Config
# -------------------------
MONGO_URI = "mongodb+srv://number25:number25@cluster0.kdeklci.mongodb.net/"
DB_NAME = "otp_database"
COLLECTION_NAME = "numbers"
USERS_COLLECTION = "users"

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
numbers_collection = db[COLLECTION_NAME]
users_collection = db[USERS_COLLECTION]

# -------------------------
# Bot Config
# -------------------------
BOT_TOKEN = "7784541637:AAGPk4zNAryYKrk_EIdyNfdmpE6fqWQMcMA"
ADMIN_IDS = [8093935563]   # Replace with your admin Telegram ID
PER_PAGE = 50
SESSION_EXPIRY = timedelta(hours=1)

# -------------------------
# Session Cache
# -------------------------
sessions = {}

# -------------------------
# Utilities
# -------------------------
def save_user(user_id, username):
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"username": username or "", "last_seen": datetime.utcnow()}},
        upsert=True
    )

def get_mongo_numbers():
    return {doc["number"] for doc in numbers_collection.find({}, {"number": 1}) if "number" in doc}

def make_pagination_keyboard(session_id, page, total_pages):
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page:{session_id}:{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"page:{session_id}:{page+1}"))
    return InlineKeyboardMarkup([buttons]) if buttons else None

def format_page_text(page_items, page, total_pages, total_count, matched_count):
    head = (
        f"📊 Comparison Report\n\n"
        f"📁 Total Numbers in File: {total_count}\n"
        f"✅ Registered Numbers: {matched_count}\n"
        f"❌ Not Registered Numbers: {total_count - matched_count}\n\n"
        f"📄 Page {page}/{total_pages}\n\n"
    )
    body = "\n".join(page_items) if page_items else "(No unmatched numbers on this page)"
    return head + body

def cleanup_old_sessions():
    now = datetime.utcnow()
    expired = [sid for sid, s in sessions.items() if now - s["created_at"] > SESSION_EXPIRY]
    for sid in expired:
        del sessions[sid]

# -------------------------
# Handlers
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username)

    keyboard = [[InlineKeyboardButton("📢 Join Channel", url="https://t.me/freeotpss")]]
    await update.message.reply_text(
        "👋 *Welcome!*\n\n"
        "Send me a `.txt` file containing numbers or type them directly.\n"
        "I'll check which are registered in the database.\n\n"
        "🧩 Features:\n"
        "• File Upload Comparison\n"
        "• Single/Multi Number Search\n"
        "• Admin Tools: /add, /remove, /stats, /broadcast, /exportdb",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username)

    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Only .txt files are supported.")
        return

    file_obj = await doc.get_file()
    path = f"/tmp/{uuid.uuid4().hex}.txt"
    await file_obj.download_to_drive(path)

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        numbers = [line.strip() for line in f if line.strip().isdigit()]

    total = len(numbers)
    mongo_numbers = get_mongo_numbers()
    matched = [n for n in numbers if n in mongo_numbers]
    unmatched = [n for n in numbers if n not in mongo_numbers]

    if not unmatched:
        await update.message.reply_text("✅ All numbers matched.")
        os.remove(path)
        return

    session_id = uuid.uuid4().hex
    sessions[session_id] = {
        "unmatched": unmatched,
        "created_at": datetime.utcnow(),
        "total": total,
        "matched": len(matched)
    }

    total_pages = (len(unmatched) + PER_PAGE - 1) // PER_PAGE
    first_page = unmatched[:PER_PAGE]

    text = format_page_text(first_page, 1, total_pages, total, len(matched))
    keyboard = make_pagination_keyboard(session_id, 1, total_pages)

    await update.message.reply_text(text, reply_markup=keyboard)
    os.remove(path)

async def paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3:
        return

    _, session_id, page_str = parts
    if session_id not in sessions:
        await query.edit_message_text("⚠️ Session expired.")
        return

    try:
        page = int(page_str)
    except ValueError:
        return

    s = sessions[session_id]
    unmatched = s["unmatched"]
    total = s["total"]
    matched = s["matched"]
    total_pages = (len(unmatched) + PER_PAGE - 1) // PER_PAGE
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    items = unmatched[start:end]
    text = format_page_text(items, page, total_pages, total, matched)
    keyboard = make_pagination_keyboard(session_id, page, total_pages)
    await query.edit_message_text(text, reply_markup=keyboard)

async def search_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username)
    text = update.message.text.strip()

    nums = [n for n in text.replace(",", "\n").split("\n") if n.strip().isdigit()]
    if not nums:
        await update.message.reply_text("❌ Please send valid numbers.")
        return

    mongo_numbers = get_mongo_numbers()
    matched = [n for n in nums if n in mongo_numbers]
    unmatched = [n for n in nums if n not in mongo_numbers]

    msg = (
        f"📊 Search Report\n\n"
        f"📁 Total: {len(nums)}\n"
        f"✅ Registered: {len(matched)}\n"
        f"❌ Not Registered: {len(unmatched)}\n\n"
    )

    if unmatched:
        txt = "\n".join(unmatched[:50])
        if len(unmatched) > 50:
            txt += f"\n...and {len(unmatched)-50} more"
        msg += txt

    await update.message.reply_text(msg)

# -------------------------
# Admin Commands
# -------------------------
async def add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Unauthorized")
    if not context.args:
        return await update.message.reply_text("Usage: /add <number>")
    num = context.args[0]
    numbers_collection.insert_one({"number": num})
    await update.message.reply_text(f"✅ Added number: {num}")

async def remove_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Unauthorized")
    if not context.args:
        return await update.message.reply_text("Usage: /remove <number>")
    num = context.args[0]
    res = numbers_collection.delete_one({"number": num})
    msg = "🗑️ Removed successfully" if res.deleted_count else "❌ Not found"
    await update.message.reply_text(msg)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Unauthorized")
    total_numbers = numbers_collection.count_documents({})
    total_users = users_collection.count_documents({})
    await update.message.reply_text(f"📊 Stats\n\n👥 Users: {total_users}\n📞 Numbers: {total_numbers}")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Unauthorized")
    msg = " ".join(context.args)
    if not msg:
        return await update.message.reply_text("Usage: /broadcast <message>")
    users = users_collection.find()
    sent = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u["user_id"], text=msg)
            sent += 1
        except Exception:
            continue
    await update.message.reply_text(f"📢 Sent to {sent} users")

async def exportdb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Unauthorized")
    nums = [doc["number"] for doc in numbers_collection.find({}, {"number": 1})]
    path = "/tmp/export_numbers.txt"
    with open(path, "w") as f:
        f.write("\n".join(nums))
    await update.message.reply_document(InputFile(path, filename="numbers.txt"), caption=f"📤 Exported {len(nums)} numbers")
    os.remove(path)

# -------------------------
# Bot Starter
# -------------------------
def start_bot():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("add", add_number))
    app_bot.add_handler(CommandHandler("remove", remove_number))
    app_bot.add_handler(CommandHandler("stats", stats_cmd))
    app_bot.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app_bot.add_handler(CommandHandler("exportdb", exportdb))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_number))
    app_bot.add_handler(CallbackQueryHandler(paginate, pattern=r"^page:"))

    logger.info("🤖 Bot Running...")
    app_bot.run_polling()


if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080), daemon=True).start()
    start_bot()
