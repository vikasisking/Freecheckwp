import os
import logging
from flask import Flask, Response
import threading
from pymongo import MongoClient
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Flask app ---
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

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

# --- Telegram Bot ---
BOT_TOKEN = "7784541637:AAGPk4zNAryYKrk_EIdyNfdmpE6fqWQMcMA"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📁 Send me a .txt file containing numbers to compare with MongoDB."
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name

    if not file_name.endswith(".txt"):
        await update.message.reply_text("❌ Only .txt files are supported.")
        return

    file_path = f"/tmp/{file.file_unique_id}.txt"
    await file.download_to_drive(file_path)

    # --- Read numbers from file ---
    with open(file_path, "r") as f:
        file_numbers = [line.strip() for line in f if line.strip().isdigit()]

    # --- Read numbers from MongoDB ---
    mongo_numbers = {doc["number"] for doc in collection.find({}, {"number": 1})}

    matched = [num for num in file_numbers if num in mongo_numbers]
    unmatched = [num for num in file_numbers if num not in mongo_numbers]

    # --- Prepare summary ---
    summary_lines = [
        "📊 **Comparison Report**",
        "",
        f"📁 Total Numbers in File: `{len(file_numbers)}`",
        f"✅ Registered Numbers: `{len(matched)}`",
        f"❌ Not Registered Numbers: `{len(unmatched)}`"
    ]

    if unmatched:
        summary_lines.append("\n📌 Unmatched Numbers:")
        # Limit Telegram message size to ~4000 chars
        unmatched_text = "\n".join(unmatched)
        if len(unmatched_text) > 3500:
            unmatched_text = unmatched_text[:3500] + "\n…and more"
        summary_lines.append(f"<code>{unmatched_text}</code>")

    summary = "\n".join(summary_lines)

    await update.message.reply_text(summary, parse_mode="HTML")

    # --- Cleanup ---
    os.remove(file_path)

def start_telegram_bot():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    print("🤖 Telegram Bot running...")
    app_bot.run_polling()

if __name__ == "__main__":
    # Flask thread
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080), daemon=True)
    flask_thread.start()

    # Telegram bot main thread
    start_telegram_bot()



