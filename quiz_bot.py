# quiz_bot.py
# All-in-one advanced PDF->MCQ quiz bot for Telegram (works on Render)
import os
import re
import csv
import io
import sys
import random
import tempfile
from threading import Thread
from flask import Flask
from PIL import Image
import pdfplumber
import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# -------------------------
# Config / Token
# -------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

# -------------------------
# Mini-web server (for Render)
# -------------------------
app = Flask(__name__)
@app.route("/")
def index():
    return "Quiz Bot is running."

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# Duplicate-instance check
# -------------------------
def check_existing_instance(token):
    try:
        res = requests.post(f"https://api.telegram.org/bot{token}/getUpdates", timeout=5)
        if res.status_code == 409:
            print("⚠️ Another instance is running. Exiting.")
            sys.exit(0)
    except Exception as e:
        print(f"⚠️ Could not check existing instance: {e}")

check_existing_instance(BOT_TOKEN)

# -------------------------
# PDF parsing utilities
# -------------------------
OPTION_LINE_RE = re.compile(r'^\s*([A-Da-d])[\)\.\-]?\s*(.+)')
INLINE_OPTION_SPLIT_RE = re.compile(r'([A-Da-d])[\)\.\-]\s*')

def extract_text_and_images_from_pdf(pdf_path):
    pages_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            lines = [ln.rstrip() for ln in page_text.split("\n") if ln.strip()]
            images = []
            try:
                pi = page.to_image(resolution=150)
                for img in page.images:
                    bbox = (img.get("x0"), img.get("top"), img.get("x1"), img.get("bottom"))
                    crop = pi.crop(bbox).original
                    images.append({"bbox": bbox, "pil": crop})
            except Exception:
                images = []
            pages_data.append({"lines": lines, "images": images})
    return pages_data

def group_questions_from_lines(lines):
    qlist = []
    cur = None
    for line in lines:
        # numeric question start (e.g., "1. What is...")
        m = re.match(r'^\s*(?:Q|q)?\s*(\d+)[\).:-]\s*(.+)', line)
        if m:
            if cur:
                qlist.append(cur)
            cur = {"question": m.group(2).strip(), "options": [], "raw": [line]}
            continue
        # standalone question line
        if "?" in line and len(line.split()) > 3 and (cur is None or len(cur.get("options", []))==0):
            if cur:
                qlist.append(cur)
            cur = {"question": line.strip(), "options": [], "raw": [line]}
            continue
        # option line
        om = OPTION_LINE_RE.match(line)
        if om and cur:
            cur["options"].append(om.group(2).strip())
            cur["raw"].append(line)
            continue
        # inline options in a single line e.g., "A) apple B) banana C) cat D) dog"
        if INLINE_OPTION_SPLIT_RE.search(line) and cur:
            parts = re.split(r'([A-Da-d])[\)\.\-]\s*', line)
            # build list after letter markers
            assembled = []
            for idx in range(1, len(parts), 2):
                textp = parts[idx+1].strip() if idx+1 < len(parts) else ""
                if textp:
                    assembled.append(textp)
            if assembled:
                cur["options"].extend(assembled)
                cur["raw"].append(line)
                continue
        # continuation lines
        if cur:
            if not cur["options"]:
                cur["question"] += " " + line.strip()
                cur["raw"].append(line)
            else:
                cur["options"][-1] += " " + line.strip()
                cur["raw"].append(line)
        else:
            continue
    if cur:
        qlist.append(cur)
    # keep only those with >=2 options
    return [q for q in qlist if q["question"] and len(q["options"]) >= 2]

def attach_images_to_questions(pages_data, questions):
    line_to_page = {}
    for pidx, pdata in enumerate(pages_data):
        for ln in pdata["lines"]:
            key = ln.strip()
            if key:
                line_to_page.setdefault(key, []).append(pidx)
    attached = []
    for q in questions:
        found_page = None
        for r in q.get("raw", []):
            pages = line_to_page.get(r.strip(), [])
            if pages:
                found_page = pages[0]
                break
        if found_page is None:
            for pidx, pdata in enumerate(pages_data):
                for ln in pdata["lines"]:
                    if re.search(r'fig(?:ure)?\.?', ln, re.IGNORECASE) and any(word in q["question"] for word in ln.split()[:6]):
                        found_page = pidx
                        break
                if found_page is not None:
                    break
        img = None
        if found_page is not None and pages_data[found_page]["images"]:
            img = pages_data[found_page]["images"][0]["pil"]
        attached.append({"question": q["question"], "options": q["options"], "raw": q.get("raw", []), "image": img})
    return attached

# -------------------------
# Session store
# -------------------------
SESSIONS = {}

# -------------------------
# Bot handlers
# -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me a PDF with questions/notes. I'll parse MCQs (A-D), try to attach images, run quiz, and give a report.\n"
        "Bonus: you can upload an answer-key CSV named 'answer_key.csv' in the repo or send it via chat (format: q_number,answer_letter)."
    )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Please send a PDF.")
        return
    await update.message.reply_text("📥 Downloading PDF…")
    f = await doc.get_file()
    tmp = "uploaded.pdf"
    await f.download_to_drive(custom_path=tmp)
    await update.message.reply_text("🔎 Parsing PDF — this may take a moment…")
    try:
        pages = extract_text_and_images_from_pdf(tmp)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to parse PDF: {e}")
        return
    all_lines = []
    for p in pages:
        all_lines.extend(p["lines"])
    extracted = group_questions_from_lines(all_lines)
    if not extracted:
        await update.message.reply_text("⚠️ No well-formed MCQs detected. Try a different PDF or ensure questions have options A-D.")
        return
    attached = attach_images_to_questions(pages, extracted)
    # Try load answer-key from repo (optional): answer_key.csv with columns (q_number, answer_letter)
    answer_map = {}
    keypath = "answer_key.csv"
    if os.path.exists(keypath):
        try:
            with open(keypath, newline='', encoding='utf-8') as kf:
                reader = csv.reader(kf)
                for row in reader:
                    if not row: continue
                    qnum = int(row[0])
                    ans = row[1].strip().upper()
                    answer_map[qnum-1] = ans  # 0-based index
        except Exception:
            pass
    # build final list (clean options) and detect correct if key present
    final_qs = []
    for i, q in enumerate(attached):
        clean_opts = [re.sub(r'^[A-Da-d][\)\.\-]\s*', '', opt).strip() for opt in q["options"]]
        correct = None
        if i in answer_map:
            idx = ord(answer_map[i]) - ord('A')
            if 0 <= idx < len(clean_opts):
                correct = clean_opts[idx]
        # fallback: try detect "Ans: B" in raw
        if not correct:
            combined = " ".join(q.get("raw", []))
            m = re.search(r'(?:Ans|Answer|Correct)\W*[:\-]?\s*([A-Da-d])', combined, re.IGNORECASE)
            if m:
                ch = m.group(1).upper()
                idx = ord(ch) - ord('A')
                if 0 <= idx < len(clean_opts):
                    correct = clean_opts[idx]
        # final fallback (random) - you can replace with LLM later
        if not correct and clean_opts:
            correct = random.choice(clean_opts)
        final_qs.append({"question": q["question"], "options": clean_opts, "correct": correct, "image": q["image"]})
    # Save session
    chat_id = update.effective_chat.id
    SESSIONS[chat_id] = {"qs": final_qs, "idx": 0, "score": 0, "answers": []}
    await update.message.reply_text(f"✅ Parsed {len(final_qs)} questions. Starting quiz...")
    await send_next_question(chat_id, context)

async def send_next_question(chat_id, context: ContextTypes.DEFAULT_TYPE):
    session = SESSIONS.get(chat_id)
    if not session:
        return
    idx = session["idx"]
    if idx >= len(session["qs"]):
        await show_report(chat_id, context)
        return
    q = session["qs"][idx]
    buttons = []
    for opt in q["options"]:
        buttons.append([InlineKeyboardButton(opt, callback_data=f"ans|{idx}|{opt}")])
    markup = InlineKeyboardMarkup(buttons)
    if q.get("image"):
        bio = io.BytesIO()
        q["image"].save(bio, format="PNG")
        bio.seek(0)
        await context.bot.send_photo(chat_id=chat_id, photo=InputFile(bio, filename=f"q{idx+1}.png"), caption=f"Q{idx+1}. {q['question']}", reply_markup=markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=f"Q{idx+1}. {q['question']}", reply_markup=markup)

async def answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split("|", 2)
    if len(parts) < 3:
        await query.edit_message_text("Invalid payload.")
        return
    _, sidx, chosen = parts
    idx = int(sidx)
    chat_id = query.message.chat.id
    session = SESSIONS.get(chat_id)
    if not session or idx != session["idx"]:
        await query.edit_message_text("This question is no longer active.")
        return
    q = session["qs"][idx]
    def norm(s): return re.sub(r'\s+', ' ', s.strip().lower())
    if norm(chosen) == norm(q["correct"]):
        session["score"] += 1
        result = f"✅ Correct! ({chosen})"
    else:
        result = f"❌ Wrong. You chose: {chosen}\nCorrect: {q['correct']}"
    session["answers"].append({"idx": idx, "chosen": chosen, "correct": q["correct"], "question": q["question"]})
    session["idx"] += 1
    try:
        await query.edit_message_text(result)
    except Exception:
        pass
    await send_next_question(chat_id, context)

async def show_report(chat_id, context: ContextTypes.DEFAULT_TYPE):
    session = SESSIONS.get(chat_id)
    if not session:
        return
    total = len(session["qs"])
    score = session["score"]
    lines = [f"🎯 Quiz complete! Score: {score}/{total}", ""]
    for a in session["answers"]:
        lines.append(f"Q{a['idx']+1}: {a['question']}\nYour: {a['chosen']}  |  Correct: {a['correct']}\n")
    report_text = "\n".join(lines)
    await context.bot.send_message(chat_id=chat_id, text=report_text)
    # CSV
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["q_index", "question", "chosen", "correct"])
    for a in session["answers"]:
        writer.writerow([a["idx"]+1, a["question"], a["chosen"], a["correct"]])
    csv_buffer.seek(0)
    bio = io.BytesIO(csv_buffer.getvalue().encode("utf-8"))
    bio.name = "quiz_report.csv"
    await context.bot.send_document(chat_id=chat_id, document=InputFile(bio, filename="quiz_report.csv"))
    del SESSIONS[chat_id]

# -------------------------
# Entry point
# -------------------------
def main():
    Thread(target=run_flask).start()
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", cmd_start))
    app_tg.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app_tg.add_handler(CallbackQueryHandler(answer_handler))
    print("🚀 Bot running (polling)...")
    app_tg.run_polling()

if __name__ == "__main__":
    main()

