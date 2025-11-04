import os
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import pdfplumber

# --- Load environment ---
TOKEN = os.getenv("BOT_TOKEN")
APP_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}"
PORT = int(os.environ.get("PORT", 5000))

# --- Create app and bot ---
app = Flask(__name__)
application = Application.builder().token(TOKEN).build()


# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Send me a PDF, and I’ll create quiz questions from it!")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles uploaded PDF and extracts text"""
    if not update.message.document:
        await update.message.reply_text("Please send a valid PDF file 📄")
        return

    file = await update.message.document.get_file()
    file_path = "/tmp/temp.pdf"
    await file.download_to_drive(custom_path=file_path)

    try:
        # Extract text from PDF (simple placeholder)
        with pdfplumber.open(file_path) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""

        # Basic response
        await update.message.reply_text("✅ Got your PDF! Generating quiz...")
        if len(text.strip()) > 50:
            await update.message.reply_text("📚 Example extract:\n\n" + text[:500] + "...")
        else:
            await update.message.reply_text("⚠️ Couldn't extract much text from your PDF.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error reading PDF: {e}")


# --- Register handlers ---
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))


# --- Flask Routes ---
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """Telegram webhook endpoint"""
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "OK", 200

@app.route("/")
def index():
    return "🤖 Bot is alive!", 200


# --- Start bot via webhook ---
if __name__ == "__main__":
    print("🚀 Starting bot on Render (webhook mode)...")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{APP_URL}/{TOKEN}"
    )
    app.run(host="0.0.0.0", port=PORT)
