import os
import logging
import threading
from flask import Flask, Response
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from datetime import datetime

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Flask App ---
app = Flask(__name__)

@app.route('/health')
def health():
    return Response("OK", status=200)

@app.route("/")
def root():
    logger.info("Root endpoint requested")
    return Response("OK", status=200)

# --- MongoDB Config ---
MONGO_URI = "mongodb+srv://number25:number25@cluster0.kdeklci.mongodb.net/"
DB_NAME = "otp_database"
COLLECTION_NAME = "numbers"
USERS_COLLECTION = "users"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
numbers_collection = db[COLLECTION_NAME]
users_collection = db[USERS_COLLECTION]

# --- Bot Config ---
BOT_TOKEN = "7784541637:AAGPk4zNAryYKrk_EIdyNfdmpE6fqWQMcMA"
ADMIN_IDS = [8093935563]  # Replace with Telegram user IDs who are admins

# --- Utility Functions ---
def save_user(user_id, username):
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"username": username, "last_seen": datetime.now()}},
        upsert=True
    )

def get_mongo_numbers():
    return {doc["number"] for doc in numbers_collection.find({}, {"number": 1})}

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user.id, update.effective_user.username)
    keyboard = [
        [InlineKeyboardButton("☘ Owner ", url="https://t.me/hiden_25")],
        [InlineKeyboardButton("📌 Channel", url="https://t.me/freeotpss")],
        [InlineKeyboardButton("📌 0tp Group", url="https://t.me/+1R-r0OSZJuVmOWZl")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 Welcome! Send me a .txt file or numbers to check.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "feature1":
        await query.edit_message_text("Feature 1 coming soon 🚀")
    elif query.data == "feature2":
        await query.edit_message_text("Feature 2 under development 🔧")

# --- File Upload Handler ---
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user.id, update.effective_user.username)
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name

    if not file_name.endswith(".txt"):
        await update.message.reply_text("❌ Only .txt files are supported.")
        return

    file_path = f"/tmp/{file.file_unique_id}.txt"
    await file.download_to_drive(file_path)

    with open(file_path, "r") as f:
        file_numbers = [line.strip() for line in f if line.strip().isdigit()]

    mongo_numbers = get_mongo_numbers()
    matched = [num for num in file_numbers if num in mongo_numbers]
    unmatched = [num for num in file_numbers if num not in mongo_numbers]

    summary_lines = [
        "📊 Comparison Report",
        "",
        f"📁 Total Numbers in File: {len(file_numbers)}",
        f"✅ Registered Numbers: {len(matched)}",
        f"❌ Not Registered Numbers: {len(unmatched)}"
    ]

    if unmatched:
        summary_lines.append("\n📌 Unmatched Numbers:")
        unmatched_text = "\n".join(unmatched)
        if len(unmatched_text) > 3500:
            unmatched_text = unmatched_text[:3500] + "\n…and more"
        summary_lines.append(unmatched_text)

    summary = "\n".join(summary_lines)
    await update.message.reply_text(summary)
    os.remove(file_path)

# --- Search Numbers Handler ---
async def search_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user.id, update.effective_user.username)
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Send one or more numbers separated by comma or newline.")
        return

    file_numbers = [num.strip() for num in text.replace(",", "\n").split("\n") if num.strip().isdigit()]
    mongo_numbers = get_mongo_numbers()
    matched = [num for num in file_numbers if num in mongo_numbers]
    unmatched = [num for num in file_numbers if num not in mongo_numbers]

    summary_lines = [
        "📊 Search Report",
        "",
        f"📁 Total Numbers Sent: {len(file_numbers)}",
        f"✅ Registered Numbers: {len(matched)}",
        f"❌ Not Registered Numbers: {len(unmatched)}"
    ]
    if unmatched:
        summary_lines.append("\n📌 Unmatched Numbers:")
        unmatched_text = "\n".join(unmatched)
        if len(unmatched_text) > 3500:
            unmatched_text = unmatched_text[:3500] + "\n…and more"
        summary_lines.append(unmatched_text)

    summary = "\n".join(summary_lines)
    await update.message.reply_text(summary)

# --- Admin Commands ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not admin.")
        return

    total_numbers = numbers_collection.count_documents({})
    total_users = users_collection.count_documents({})
    await update.message.reply_text(
        f"📊 Bot Stats\n\nTotal Numbers in DB: {total_numbers}\nTotal Users: {total_users}"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not admin.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast Your message here")
        return

    message_text = " ".join(context.args)
    users = users_collection.find({}, {"user_id": 1})
    count = 0
    for u in users:
        try:
            await context.bot.send_message(u["user_id"], message_text)
            count += 1
        except:
            continue
    await update.message.reply_text(f"✅ Broadcast sent to {count} users")

# --- Bot Starter ---
def start_telegram_bot():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_number))
    app_bot.add_handler(CommandHandler("stats", stats))
    app_bot.add_handler(CommandHandler("broadcast", broadcast))
    print("🤖 Telegram Bot running...")
    app_bot.run_polling()

# --- Main ---
if __name__ == "__main__":
    # Flask thread for Render health check
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080), daemon=True)
    flask_thread.start()

    # Telegram Bot main thread
    start_telegram_bot()

