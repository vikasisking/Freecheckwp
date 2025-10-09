import os
import logging
import threading
import uuid
from flask import Flask, Response
from pymongo import MongoClient
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from datetime import datetime

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

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
numbers_collection = db[COLLECTION_NAME]
users_collection = db[USERS_COLLECTION]

# -------------------------
# Bot Config
# -------------------------
BOT_TOKEN = "7784541637:AAGPk4zNAryYKrk_EIdyNfdmpE6fqWQMcMA"   # <-- replace
ADMIN_IDS = [8093935563]            
sessions = {}
PER_PAGE = 50

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

    # Arrange in one row
    keyboard = InlineKeyboardMarkup([buttons])
    return keyboard

def format_page_text(page_items, page: int, total_pages: int, total_count: int, matched_count: int):
    header = [
        "📊 Comparison Report",
        "",
        f"📁 Total Numbers in File: {total_count}",
        f"✅ Registered Numbers: {matched_count}",
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
    keyboard = [
        [InlineKeyboardButton("☘ Channel", url="https://t.me/freeotpss")],
        [InlineKeyboardButton("🧑‍💻 Owner", url="https://t.me/hiden_25")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
    "🤖 Welcome! Send me a .txt file containing numbers. "
    "If you include one or more two-digit numbers, it will be checked. "
    "The bot will tell you which numbers are not registered.\n\n"
    "Only files sent in this channel will work; the bot will not work in other channels.\n"
    "@freeotpss",
    reply_markup=reply_markup
)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "feature1":
        await query.edit_message_text("Feature 1 coming soon 🚀")
    elif data == "feature2":
        await query.edit_message_text("Feature 2 under development 🔧")
    else:
        # For any other (should be handled elsewhere)
        await query.answer()

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username)

    if not update.message.document:
        await update.message.reply_text("❌ Please send a .txt file.")
        return

    doc = update.message.document
    file_name = doc.file_name or ""
    if not file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Only .txt files are supported.")
        return

    # download file
    file_obj = await doc.get_file()
    tmp_path = f"/tmp/{doc.file_unique_id}.txt"
    await file_obj.download_to_drive(tmp_path)

    # Read numbers (simple normalization: take only digits)
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

    # build initial summary and (if unmatched) first page
    summary_lines = [
        "📊 Comparison Report",
        "",
        f"📁 Total Numbers in File: {total_count}",
        f"✅ Registered Numbers: {matched_count}",
        f"❌ Not Registered Numbers: {unmatched_count}",
        ""
    ]

    if unmatched_count == 0:
        await update.message.reply_text("\n".join(summary_lines))
        os.remove(tmp_path)
        return

    # create session
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

    # prepare first page
    total_pages = (unmatched_count + PER_PAGE - 1) // PER_PAGE
    page = 1
    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    page_items = unmatched[start_idx:end_idx]

    text = format_page_text(page_items, page, total_pages, total_count, matched_count)
    keyboard = make_pagination_keyboard(session_id, page, total_pages)

    # send combined message (summary + page)
    await update.message.reply_text(text, reply_markup=keyboard)

    # cleanup temp file
    try:
        os.remove(tmp_path)
    except Exception:
        pass

async def callback_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    # callback formats:
    # page:<session_id>:<page>
    # back:<session_id>
    # noop:<session_id>
    parts = data.split(":")
    action = parts[0] if parts else ""
    if len(parts) >= 2:
        session_id = parts[1]
    else:
        await query.answer()
        return

    session = sessions.get(session_id)
    if not session:
        await query.edit_message_text("Session expired or not found. Please upload file again.")
        return

    if action == "noop":
        # do nothing (disabled button)
        await query.answer()
        return
        
    if action == "page":
        # expected third part is page number
        if len(parts) < 3:
            await query.answer()
            return
        try:
            page = int(parts[2])
        except ValueError:
            await query.answer()
            return

        unmatched = session["unmatched"]
        total_count = session.get("total_count", len(unmatched))
        matched_count = session.get("matched_count", 0)
        total_pages = (len(unmatched) + PER_PAGE - 1) // PER_PAGE
        # clamp page
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages

        start_idx = (page - 1) * PER_PAGE
        end_idx = start_idx + PER_PAGE
        page_items = unmatched[start_idx:end_idx]

        text = format_page_text(page_items, page, total_pages, total_count, matched_count)
        keyboard = make_pagination_keyboard(session_id, page, total_pages)

        # edit the same message with new page content
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    # fallback
    await query.answer()

# -------------------------
# Search single/multiple numbers via plain text message
# -------------------------
async def search_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username)
    text = update.message.text or ""
    # allow comma or newline separated numbers; normalize digits only
    parts = [p.strip() for p in text.replace(",", "\n").split("\n") if p.strip()]
    nums = []
    for p in parts:
        n = "".join(ch for ch in p if ch.isdigit())
        if n:
            nums.append(n)
    if not nums:
        await update.message.reply_text("Send one or more numbers (comma or newline separated).")
        return

    mongo_numbers = get_mongo_numbers()
    matched = [n for n in nums if n in mongo_numbers]
    unmatched = [n for n in nums if n not in mongo_numbers]

    lines = [
        "📊 Search Report",
        "",
        f"📁 Total Numbers Sent: {len(nums)}",
        f"✅ Registered Numbers: {len(matched)}",
        f"❌ Not Registered Numbers: {len(unmatched)}",
        ""
    ]
    if unmatched:
        # show all (if many, truncate)
        txt = "\n".join(unmatched)
        if len(txt) > 3500:
            txt = txt[:3500] + "\n…and more"
        lines.append(txt)

    await update.message.reply_text("\n".join(lines))

# -------------------------
# Admin: stats & broadcast
# -------------------------
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not admin.")
        return
    total_numbers = numbers_collection.count_documents({})
    total_users = users_collection.count_documents({})
    await update.message.reply_text(
        f"📊 Bot Stats\n\nTotal Numbers in DB: {total_numbers}\nTotal Users: {total_users}"
    )

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

def start_telegram_bot():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler, pattern="^(feature1|feature2)$"))
    app_bot.add_handler(CallbackQueryHandler(callback_pagination, pattern="^(page|back|noop):"))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_number))
    app_bot.add_handler(CommandHandler("stats", stats_cmd))
    app_bot.add_handler(CommandHandler("broadcast", broadcast_cmd))
    logger.info("🤖 Telegram Bot running...")
    app_bot.run_polling()

if __name__ == "__main__":
    # run flask in background for Render health checks
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080))), daemon=True)
    flask_thread.start()

    start_telegram_bot()
