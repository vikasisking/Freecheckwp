import os
import re
import logging
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configuration
TOKEN = os.getenv("BOT_TOKEN", "7784541637:AAFLIOZltZslKEjEuiYj_O33OpoOZ2lE7EE")  # Set your bot token in environment variables
GROUP_ID = -1002990279188 # Set your 
NUMBER_BOT_ID = os.getenv("NUMBER_BOT_ID", "8361669889")  # Set the Telegram user ID of the number-sending bot
NUMBER_PATTERN = r'^\d{8,13}$'  # Regex for 8-13 digit numbers
DB_FILE = "group_numbers.db"  # SQLite database for storing group numbers

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("CREATE TABLE IF NOT EXISTS group_numbers (number TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

# Normalize number (remove whitespace, ensure string)
def normalize_number(num):
    return str(num).strip()

# Add a number to the database
def add_group_number(num):
    num = normalize_number(num)
    if not re.match(NUMBER_PATTERN, num):
        logger.warning(f"Invalid number format: {num}")
        return
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("INSERT OR IGNORE INTO group_numbers (number) VALUES (?)", (num,))
        conn.commit()
        logger.info(f"Added number to database: {num}")
    except Exception as e:
        logger.error(f"Error adding number to database: {e}")
    finally:
        conn.close()

# Load group numbers from the database
def load_group_numbers():
    conn = sqlite3.connect(DB_FILE)
    try:
        cursor = conn.execute("SELECT number FROM group_numbers")
        numbers = {normalize_number(row[0]) for row in cursor.fetchall()}
        logger.info(f"Loaded {len(numbers)} numbers from database: {numbers}")
        return numbers
    except Exception as e:
        logger.error(f"Error loading group numbers: {e}")
        return set()
    finally:
        conn.close()

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        return
    await update.message.reply_text(
        "Welcome! I'm an admin bot in a private group. Send me a .txt file containing numbers "
        "(one per line, 8-13 digits). I'll compare them with numbers sent by the designated bot "
        "in the group and return the unmatched ones (in your file but not in the group)."
    )

# Debug command to show database contents (for private chat)
async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        return
    numbers = load_group_numbers()
    if not numbers:
        await update.message.reply_text("No numbers in the database.")
        return
    output = f"Current numbers in database ({len(numbers)}):\n\n" + "\n".join(sorted(numbers))
    if len(output) < 4096:
        await update.message.reply_text(output)
    else:
        with open("debug_numbers.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(numbers)))
        await update.message.reply_document(document="debug_numbers.txt", caption="Database numbers")
        os.remove("debug_numbers.txt")

# Handler for messages in the group (only process numbers from NUMBER_BOT_ID)
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != int(GROUP_ID):
        return
    # Check if the message is from the designated number-sending bot
    if not update.message.from_user or str(update.message.from_user.id) != NUMBER_BOT_ID:
        logger.debug(f"Ignored message from user ID {update.message.from_user.id if update.message.from_user else 'unknown'}")
        return
    text = normalize_number(update.message.text)
    if re.match(NUMBER_PATTERN, text):
        logger.info(f"Received valid number from number bot: {text}")
        add_group_number(text)
    else:
        logger.debug(f"Ignored invalid number from number bot: {text}")

# Handler for .txt files sent in private chat
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        return
    document = update.message.document
    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("Please send a .txt file only.")
        return

    # Download the file
    file = await document.get_file()
    file_path = await file.download_to_drive(custom_path=document.file_name)

    # Read numbers from the file
    file_numbers = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                num = normalize_number(line)
                if re.match(NUMBER_PATTERN, num):
                    file_numbers.add(num)
                else:
                    logger.warning(f"Ignored invalid number in file: {num}")
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        await update.message.reply_text("Error reading the file. Please ensure it's a valid .txt file.")
        os.remove(file_path)
        return

    os.remove(file_path)  # Clean up

    if not file_numbers:
        await update.message.reply_text("No valid numbers (8-13 digits) found in the file.")
        return

    logger.info(f"File contains {len(file_numbers)} numbers: {file_numbers}")

    # Load group numbers from database
    group_numbers = load_group_numbers()

    # Find unmatched numbers (in file but not in group)
    unmatched = file_numbers - group_numbers

    logger.info(f"Comparison result - File numbers: {len(file_numbers)}, Group numbers: {len(group_numbers)}, Unmatched: {len(unmatched)}")
    logger.debug(f"Unmatched numbers: {unmatched}")

    if not unmatched:
        await update.message.reply_text("All numbers from the file are already in the group.")
        return

    # Prepare output
    output_text = "Unmatched numbers (in file but not in group):\n\n" + "\n".join(sorted(unmatched))

    # Send as text if short, else as file
    if len(output_text) < 4096:  # Telegram message limit
        await update.message.reply_text(output_text)
    else:
        output_file = "unmatched_numbers.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(unmatched)))
        await update.message.reply_document(document=output_file, caption="Unmatched numbers")
        os.remove(output_file)

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.message and update.message.chat.type == 'private':
        await update.message.reply_text("An error occurred. Please try again later.")

def main():
    # Initialize the database
    init_db()

    # Validate configuration
    if not TOKEN or not GROUP_ID or not NUMBER_BOT_ID:
        logger.error("Missing required environment variables: BOT_TOKEN, GROUP_ID, or NUMBER_BOT_ID")
        return

    # Initialize the application
    application = Application.builder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("debug", debug))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Chat(int(GROUP_ID)), handle_group_message))
    application.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, handle_document))
    application.add_error_handler(error_handler)

    # Start polling
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
