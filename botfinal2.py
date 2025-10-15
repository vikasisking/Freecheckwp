import os
import logging
import threading
import uuid
from flask import Flask, Response
from pymongo import MongoClient
from telegram import (
    Update, InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, InlineQueryHandler, filters
)
from datetime import datetime, timedelta

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------
# Flask for health check
# -------------------------
app = Flask(__name__)

@app.route('/health')
def health():
    return Response("OK", status=200)

@app.route('/')
def root():
    logger.info("Root endpoint requested")
    return Response("OK", status=200)

# -------------------------
# MongoDB Config
# -------------------------
MONGO_URI = "mongodb+srv://number25:number25@cluster0.kdeklci.mongodb.net/"
DB_NAME = "otp_database"
COLLECTION_NAME = "numbers"
USERS_COLLECTION = "users"
FORCE_JOIN = "TEAM56RJ" 
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
numbers_collection = db[COLLECTION_NAME]
users_collection = db[USERS_COLLECTION]

# -------------------------
# Bot Config
# -------------------------
BOT_TOKEN = "8207135806:AAFF8bbZWy3m5H1wu5aS8N1EEU5mcIdDZ24"
ADMIN_IDS = [8093935563]
sessions = {}
PER_PAGE = 50
active_usernames = set()

# -------------------------
# Helper Functions
# -------------------------
def save_user(user_id, username):
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"username": username or "", "last_seen": datetime.utcnow()}},
            upsert=True
        )
    except Exception as e:
        logger.exception("save_user error: %s", e)

def get_mongo_numbers():
    try:
        return {doc["number"] for doc in numbers_collection.find({}, {"number": 1}) if "number" in doc}
    except Exception as e:
        logger.exception("get_mongo_numbers error: %s", e)
        return set()

def make_pagination_keyboard(session_id: str, page: int, total_pages: int):
    buttons = []
    # Previous
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"page:{session_id}:{page-1}"))
    else:
        buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"noop:{session_id}"))  # noop for disabled
    # Next
    if page < total_pages:
        buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"page:{session_id}:{page+1}"))
    else:
        buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"noop:{session_id}"))
    return InlineKeyboardMarkup([buttons])

def format_page_text(page_items, page: int, total_pages: int, total_count: int, matched_count: int):
    header = [
        "📊 Comparison Report",
        "",
        f"📁 Total Numbers in File: {total_count}",
        f"✅ Registered Numbers: {matched_count}\n",
        f"❌ Not Registered Numbers: {total_count - matched_count}",
        "",
        f"📌 Showing page {page} / {total_pages}",
        f"Not Registered Number List Below: {total_count - matched_count}",
        ""
    ]
    body = "\n".join(page_items) if page_items else "(No unmatched numbers on this page)"
    return "\n".join(header) + "\n" + body

# -------------------------
# Bot Handlers
# -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username)

    # Admin notification
    ADMIN_ID = 8093935563  # change if your admin ID is different
    if user.id != ADMIN_ID:
        try:
            msg = (
               msg = f"ID: `{user.id}`"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

    # Main keyboard
    keyboard = [
        [
            InlineKeyboardButton("📢 Main Channel", url="https://t.me/TEAM56RJ"),
            InlineKeyboardButton("🆕 Backup Channel", url="https://t.me/RishiOfficial56")
        ],
        [InlineKeyboardButton("👨‍💻 Bot Developer", url="https://t.me/hiden_25")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # User welcome message
    await update.message.reply_text(
        "🤖 Welcome!\n\n"
        "Send me a `.txt` file containing numbers. I’ll check which ones are not registered.\n\n"
        "📌 Only files sent this bot @Rishifreeotp5bot.\n"
        "This bot only work number bot v0.2.0 File other file not work.",
        reply_markup=reply_markup
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    save_user(user.id, user.username)
    active_usernames.add(f"@{user.username}" if user.username else str(user.id))
    log_file_upload(user.id, user.username)

    if not update.message.document:
        await update.message.reply_text("❌ Please send a .txt file.")
        return

    doc = update.message.document
    if not (doc.file_name or "").lower().endswith(".txt"):
        await update.message.reply_text("❌ Only .txt files are supported.")
        return

    tmp_path = f"/tmp/{doc.file_unique_id}.txt"
    file_obj = await doc.get_file()
    await file_obj.download_to_drive(tmp_path)

    file_numbers = []
    with open(tmp_path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            num = "".join(ch for ch in line.strip() if ch.isdigit())
            if num:
                file_numbers.append(num)

    total_count = len(file_numbers)
    mongo_numbers = get_mongo_numbers()
    matched = [n for n in file_numbers if n in mongo_numbers]
    unmatched = [n for n in file_numbers if n not in mongo_numbers]

    matched_count = len(matched)
    unmatched_count = len(unmatched)

    if unmatched_count == 0:
        await update.message.reply_text(
            "📊 *Comparison Report*\n\n"
            f"📁 Total Numbers in File: `{total_count}`\n"
            f"✅ Registered Numbers: `{matched_count}`\n"
            f"❌ Not Registered Numbers: `{unmatched_count}`\n\n"
            "🎉 All numbers are registered!",
            parse_mode="Markdown"
        )
        os.remove(tmp_path)
        return

    # Pagination
    session_id = uuid.uuid4().hex
    sessions[session_id] = {
        "chat_id": update.effective_chat.id,
        "user_id": user.id,
        "unmatched": unmatched,
        "per_page": PER_PAGE,
        "created_at": datetime.utcnow(),
        "total_count": total_count,
        "matched_count": matched_count
    }

    # first page
    total_pages = (len(unmatched) + PER_PAGE - 1) // PER_PAGE
    page_items = unmatched[:PER_PAGE]

    text = format_page_text(page_items, 1, total_pages, total_count, matched_count)
    keyboard = make_pagination_keyboard(session_id, 1, total_pages)
    await update.message.reply_text(text, reply_markup=keyboard)

    os.remove(tmp_path)

async def callback_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split(":")
    action = parts[0] if parts else ""
    if len(parts) >= 2:
        session_id = parts[1]
    else:
        return

    session = sessions.get(session_id)
    if not session:
        await query.edit_message_text("Session expired or not found. Please upload file again.")
        return

    if action == "noop":
        return

    if action == "page" and len(parts) >= 3:
        try:
            page = int(parts[2])
        except ValueError:
            return

        unmatched = session["unmatched"]
        per_page = session.get("per_page", PER_PAGE)
        total_pages = (len(unmatched) + per_page - 1) // per_page

        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_items = unmatched[start_idx:end_idx]

        text = format_page_text(page_items, page, total_pages, session["total_count"], session["matched_count"])
        keyboard = make_pagination_keyboard(session_id, page, total_pages)
        await query.edit_message_text(text, reply_markup=keyboard)

# -------------------------
# Usage Tracking
# -------------------------
def log_file_upload(user_id, username):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    collection = db["usage_logs"]
    collection.update_one(
        {"user_id": user_id, "date": today},
        {"$inc": {"uploads": 1}, "$set": {"username": username}},
        upsert=True
    )

def get_today_usage():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    collection = db["usage_logs"]
    result = list(collection.aggregate([
        {"$match": {"date": today}},
        {"$group": {"_id": None, "total_uploads": {"$sum": "$uploads"}}}
    ]))
    return result

def get_top_users(limit=10):
    collection = db["usage_logs"]
    pipeline = [
        {"$group": {"_id": "$user_id", "username": {"$first": "$username"}, "uploads": {"$sum": "$uploads"}}},
        {"$sort": {"uploads": -1}},
        {"$limit": limit}
    ]
    return list(collection.aggregate(pipeline))

# -------------------------
# Search Handlers
# -------------------------
async def search_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username)
    active_usernames.add(f"@{user.username}" if user.username else str(user.id))

    text = update.message.text or ""
    parts = [p.strip() for p in text.replace(",", "\n").split("\n") if p.strip()]
    nums = ["".join(ch for ch in p if ch.isdigit()) for p in parts if any(ch.isdigit() for ch in p)]
    if not nums:
        await update.message.reply_text("Send one or more numbers (comma or newline separated).")
        return

    mongo_numbers = get_mongo_numbers()
    matched = [n for n in nums if n in mongo_numbers]
    unmatched = [n for n in nums if n not in mongo_numbers]

    total_count = len(nums)
    matched_count = len(matched)
    unmatched_count = len(unmatched)

    lines = [
        "📊 *Search Report*",
        "",
        f"📁 *Total Numbers Sent:* `{total_count}`",
        f"✅ *Registered Numbers:* `{matched_count}`",
        f"❌ *Not Registered Numbers:* `{unmatched_count}`",
        "",
        "🗂️ *Not Registered Number List Below:*"
    ]

    if unmatched:
        txt = "\n".join(unmatched)
        if len(txt) > 3500:
            txt = txt[:3500] + "\n…and more"
        lines.append(f"```{txt}```")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def inline_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query:
        return
    number_found = db["numbers"].find_one({"number": query})
    text = f"✅ {query} is registered." if number_found else f"❌ {query} not found in database."
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="Check number",
            description=text,
            input_message_content=InputTextMessageContent(text)
        )
    ]
    await update.inline_query.answer(results, cache_time=0)

# -------------------------
# Admin Handlers
# -------------------------
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not admin.")
        return
    total_numbers = numbers_collection.count_documents({})
    total_users = users_collection.count_documents({})
    await update.message.reply_text(f"📊 Bot Stats\n\nTotal Numbers in DB: {total_numbers}\nTotal Users: {total_users}")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not admin.")
        return
    text = " ".join(context.args or [])
    if not text:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    users = users_collection.find({}, {"user_id": 1})
    sent = 0
    for u in users:
        try:
            await context.bot.send_message(u["user_id"], text)
            sent += 1
        except Exception:
            continue
    await update.message.reply_text(f"✅ Broadcast sent to {sent} users")

async def usage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("🚫 Admin only.")
    result = get_today_usage()
    total = result[0]['total_uploads'] if result else 0
    await update.message.reply_text(f"📊 Files processed today: {total}")

async def topusers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("🚫 Admin only.")
    top_users = get_top_users()
    if not top_users:
        await update.message.reply_text("No usage data yet.")
        return
    msg = "🏆 Top Users:\n\n"
    for i, user in enumerate(top_users, start=1):
        msg += f"{i}. @{user['username']} — {user['uploads']} files\n"
    await update.message.reply_text(msg)

# -------------------------
# Run Bot
# -------------------------
def start_telegram_bot():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("usage", usage_cmd))
    app_bot.add_handler(CommandHandler("topusers", topusers_cmd))
    app_bot.add_handler(CommandHandler("stats", stats_cmd))
    app_bot.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app_bot.add_handler(CallbackQueryHandler(callback_pagination, pattern="^(page|back|noop):"))
    app_bot.add_handler(InlineQueryHandler(inline_search))  # moved above text handler
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_number))
    logger.info("🤖 Telegram Bot running with Force Join...")
    app_bot.run_polling()

if __name__ == "__main__":
    # run flask in background for health checks
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080))), daemon=True)
    flask_thread.start()
    start_telegram_bot()

