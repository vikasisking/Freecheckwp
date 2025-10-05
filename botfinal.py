import os
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient

# ==== MongoDB Setup ====
MONGO_URI = "mongodb+srv://number25:number25@cluster0.kdeklci.mongodb.net/"
DB_NAME = "otp_database"
COLLECTION_NAME = "numbers"

# ==== Telegram Bot Token ====
BOT_TOKEN = "7784541637:AAGPk4zNAryYKrk_EIdyNfdmpE6fqWQMcMA"

# ==== MongoDB Client ====
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📁 Send me a .txt file containing numbers to compare with MongoDB.")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_path = f"{file.file_unique_id}.txt"
    await file.download_to_drive(file_path)

    # Read numbers from file
    with open(file_path, "r") as f:
        file_numbers = [line.strip() for line in f if line.strip().isdigit()]

    # Fetch MongoDB numbers
    mongo_numbers = {doc["number"] for doc in collection.find({}, {"number": 1})}

    # Compare
    unmatched = [num for num in file_numbers if num not in mongo_numbers]
    matched = [num for num in file_numbers if num in mongo_numbers]

    # Stats
    total = len(file_numbers)
    unmatched_count = len(unmatched)
    matched_count = len(matched)

    # Create unmatched.txt
    unmatched_file = "unmatched_numbers.txt"
    with open(unmatched_file, "w") as f:
        f.write("\n".join(unmatched) if unmatched else "All numbers matched with MongoDB ✅")

    # Send stats
    summary = (
        f"📊 **Comparison Report**\n\n"
        f"📁 Total Numbers in File: `{total}`\n"
        f"❌ Unmatched Numbers: `{unmatched_count}`\n"
        f"✅ Matched Numbers: `{matched_count}`"
    )

    await update.message.reply_text(summary, parse_mode="Markdown")

    # Send unmatched file
    await update.message.reply_document(InputFile(unmatched_file))

    # Cleanup
    os.remove(file_path)
    os.remove(unmatched_file)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.FILE_EXTENSION("txt"), handle_file))
    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
