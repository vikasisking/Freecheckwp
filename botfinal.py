import re
import json
import asyncio
import os
import tempfile
from pathlib import Path
from threading import Thread
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from flask import Flask

# ---------------- Configuration ----------------
TOKEN = "7784541637:AAHoWGZ51eqZv-KW1wfsHZIrzcX4o9Kz57A"
GROUP_ID = -1002990279188
OWNER_ID = 7761576669
STORE_FILE = Path("numbers_only.json")
USERS_FILE = Path("users.json")
DEV_URL = "https://t.me/hiden_25"
CHANNEL_URL = "https://t.me/freeotpss"

group_numbers: set[str] = set()
users: set[int] = set()
save_lock = asyncio.Lock()

# ---------------- Healthcheck Server ----------------
flask_app = Flask("healthcheck")

@flask_app.route("/")
def home():
    return "Bot is running ✅"

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

Thread(target=run_flask).start()

# ---------------- Helper Functions ----------------
def normalize_number(num: str, strip_country_code: bool = True) -> str:
    digits = re.sub(r"\D", "", str(num))
    if strip_country_code and len(digits) > 10:
        return digits[-10:]
    if len(digits) >= 8:
        return digits
    return ""

def load_store():
    if STORE_FILE.exists():
        try:
            data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                group_numbers.update(data)
        except Exception as e:
            print(f"Error loading numbers_only.json: {e}")
    if USERS_FILE.exists():
        try:
            data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                users.update(data)
        except Exception as e:
            print(f"Error loading users.json: {e}")

async def save_store():
    async with save_lock:
        STORE_FILE.write_text(
            json.dumps(sorted(group_numbers), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        USERS_FILE.write_text(
            json.dumps(sorted(users), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

# ---------------- Bot Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.add(user_id)
    await save_store()

    text = (
        "👋 Welcome!\n\n"
        "📂 Send me a TXT file (one number per line). I will compare it with "
        "the group numbers and return unmatched numbers as text.\n\n"
        "⚡ Features:\n"
        "• Compare numbers quickly\n"
        "• Get unmatched numbers in text"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👨‍💻 Developer", url=DEV_URL)],
            [InlineKeyboardButton("📢 Main Channel", url=CHANNEL_URL)],
        ]
    )

    await update.message.reply_text(text, reply_markup=keyboard)

async def group_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == GROUP_ID:
        text = (update.message.text or "").strip()
        n = normalize_number(text, strip_country_code=True)
        if n and n not in group_numbers:
            group_numbers.add(n)
            print(f"Added to group_numbers: {n}")
            await save_store()

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Please send a valid TXT file.")
        return

    try:
        f = await doc.get_file()
        with tempfile.TemporaryDirectory() as tmp_dir:
            local = Path(tmp_dir) / "input.txt"
            await f.download_to_drive(local)
            print(f"Downloaded file to: {local}")
            user_numbers = set()
            invalid_numbers = []
            with open(local, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    n = normalize_number(line, strip_country_code=True)
                    if n:
                        user_numbers.add(n)
                    else:
                        invalid_numbers.append(line.strip())

            print(f"User numbers: {user_numbers}")
            print(f"Invalid numbers: {invalid_numbers}")
            print(f"Group numbers before matching: {group_numbers}")

            # Matching
            matched = user_numbers & group_numbers
            unmatched = user_numbers - group_numbers

            # Automatically add valid user_numbers to group_numbers
            for n in user_numbers:
                if n not in group_numbers:
                    group_numbers.add(n)
            await save_store()

            total_numbers = len(user_numbers)
            matched_count = len(matched)
            unmatched_count = len(unmatched)

            print(f"Matched numbers: {matched}")
            print(f"Unmatched numbers: {unmatched}")
            print(f"Group numbers after update: {group_numbers}")

            unmatched_text = "Unmatched numbers:\n" + "\n".join(sorted(unmatched)) if unmatched else "Unmatched numbers: None"
            await update.message.reply_text(unmatched_text)

            summary = (
                f"✅ Found {unmatched_count} unmatched numbers.\n"
                f"📊 Total numbers in file: {total_numbers}\n"
                f"✅ Registered numbers: {matched_count}\n"
                f"🚫 Not registered numbers: {unmatched_count}"
            )
            if invalid_numbers:
                summary += f"\n⚠️ Ignored {len(invalid_numbers)} invalid numbers."
            await update.message.reply_text(summary)

    except Exception as e:
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    msg = " ".join(context.args)
    sent = 0
    for uid in users.copy():
        try:
            await context.bot.send_message(chat_id=uid, text=msg)
            sent += 1
        except:
            users.discard(uid)

    await save_store()
    await update.message.reply_text(f"📢 Broadcast sent to {sent} users.")

async def export_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        if USERS_FILE.exists():
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = f.read()
            await update.message.reply_text(f"📄 users.json:\n{data}")
        else:
            await update.message.reply_text("❌ users.json not found.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def export_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    try:
        if STORE_FILE.exists():
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                data = f.read()
            await update.message.reply_text(f"📄 numbers_only.json:\n{data}")
        else:
            await update.message.reply_text("❌ numbers_only.json not found.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def connect_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /connect <file_path>")
        return

    file_path = context.args[0]
    try:
        if not Path(file_path).exists():
            await update.message.reply_text(f"❌ File not found: {file_path}")
            return

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                added = 0
                for n in data:
                    n_norm = normalize_number(str(n))
                    if n_norm and n_norm not in group_numbers:
                        group_numbers.add(n_norm)
                        added += 1
                await save_store()
                await update.message.reply_text(f"✅ Added {added} numbers from {file_path}.")
            else:
                await update.message.reply_text("❌ Invalid JSON format (expected a list).")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def connect_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /connect_id <file_path>")
        return

    file_path = context.args[0]
    try:
        if not Path(file_path).exists():
            await update.message.reply_text(f"❌ File not found: {file_path}")
            return

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                added = 0
                for uid in data:
                    if isinstance(uid, int) and uid not in users:
                        users.add(uid)
                        added += 1
                await save_store()
                await update.message.reply_text(f"✅ Added {added} user IDs from {file_path}.")
            else:
                await update.message.reply_text("❌ Invalid JSON format (expected a list).")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ---------------- Main ----------------
def main():
    load_store()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export_id", export_ids))
    app.add_handler(CommandHandler("export_num", export_numbers))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("connect", connect_numbers))
    app.add_handler(CommandHandler("connect_id", connect_ids))
    app.add_handler(MessageHandler(filters.Document.MimeType("text/plain"), handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_number_handler))

    print("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()

