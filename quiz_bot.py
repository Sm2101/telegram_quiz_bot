# --- Telegram PDF Quiz Bot ---
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import os, pdfplumber, random

# Telegram Token
TOKEN = os.getenv("BOT_TOKEN")

# --- Mini Flask server (for Render) ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# --- Memory ---
user_quizzes = {}

# --- Extract quiz questions from PDF text ---
def extract_quiz_from_pdf(file_path):
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""

    # Split into possible questions (very simple logic)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    questions = []
    for line in lines:
        if "?" in line and len(line.split()) > 3:
            # Make fake options for now
            correct = random.choice(["A", "B", "C", "D"])
            questions.append({
                "question": line,
                "options": ["A", "B", "C", "D"],
                "answer": correct
            })
    return questions[:5]  # Limit to 5 for demo

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Send me a PDF and I’ll make quiz questions from it!")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_path = "uploaded.pdf"
    await file.download_to_drive(file_path)
    await update.message.reply_text("📖 Reading your PDF, please wait...")

    quiz = extract_quiz_from_pdf(file_path)
    if not quiz:
        await update.message.reply_text("⚠️ Sorry, I couldn’t find any questions in that PDF.")
        return

    user_quizzes[update.effective_chat.id] = {"quiz": quiz, "index": 0, "score": 0}
    await send_question(update, context)

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    quiz_data = user_quizzes.get(chat_id)

    if not quiz_data or quiz_data["index"] >= len(quiz_data["quiz"]):
        await context.bot.send_message(chat_id, f"✅ Quiz finished! Your score: {quiz_data['score']} / {len(quiz_data['quiz'])}")
        return

    q = quiz_data["quiz"][quiz_data["index"]]
    buttons = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in q["options"]]
    await context.bot.send_message(chat_id, q["question"], reply_markup=InlineKeyboardMarkup(buttons))

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_data = user_quizzes.get(chat_id)
    if not user_data:
        return

    q = user_data["quiz"][user_data["index"]]
    user_choice = query.data
    if user_choice == q["answer"]:
        user_data["score"] += 1
        await query.edit_message_text(f"✅ Correct! ({user_choice})")
    else:
        await query.edit_message_text(f"❌ Wrong! Correct answer: {q['answer']}")

    user_data["index"] += 1
    await send_question(update, context)

# --- Start bot ---
def main():
    Thread(target=run_flask).start()
    app_tg = ApplicationBuilder().token(TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app_tg.add_handler(CallbackQueryHandler(handle_answer))
    app_tg.run_polling()

if __name__ == "__main__":
    main()
