# --- Simple Telegram Quiz Bot for Render ---
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import requests, os

# Telegram Bot Token from Render Environment
TOKEN = os.getenv("BOT_TOKEN")

# --- Flask mini server (keeps Render alive) ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Send me a PDF and I’ll make quiz questions from it!")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_path = "file.pdf"
    await file.download_to_drive(file_path)
    await update.message.reply_text("✅ Got your PDF! (Quiz generation coming soon...)")

# --- Start Everything ---
def main():
    Thread(target=run_flask).start()  # Start mini web server
    app_tg = ApplicationBuilder().token(TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app_tg.run_polling()

if __name__ == "__main__":
    main()
