# quiz_bot.py
# Advanced PDF -> MCQ quiz bot (text + images). Designed to run on Render (includes tiny Flask server).
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

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

# --- Flask mini-server so Render detects a port (keeps web service alive) ---
app = Flask(__name__)

@app.route("/")
def index():
    return "Quiz Bot is running"

def run_flask():
    # Use port 10000 (Render will detect it)
    app.run(host="0.0.0.0", port=10000)

# ---------------------------
# Utilities: PDF parsing
# ---------------------------
QUESTION_REGEXES = [
    re.compile(r'^\s*(?:Q|q)?\s*(\d+)[\).:-]\s*(.+)', re.UNICODE),      # 1. Question...
    re.compile(r'^\s*(?:Q|q)\s*(\d+)\s*[:.\-]\s*(.+)', re.UNICODE),
]

# Option detection: formats like a) , a. , A) , (a) , a)
OPTION_LINE_RE = re.compile(r'^\s*([A-Da-d])[\)\.\-]?\s*(.+)')
OPTION_LETTER_INLINE_RE = re.compile(r'\b([A-Da-d])[\)\.\-]\s*')  # inline letter markers

def extract_text_and_images_from_pdf(pdf_path):
    """
    Returns a list of objects for each page:
    [{'text_lines': [...], 'images': [{'bbox':..., 'pil': PIL.Image}]}, ...]
    """
    pages_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            lines = [ln.rstrip() for ln in page_text.split("\n") if ln.strip()]

            # Extract images (bounding boxes) and crop via page.to_image()
            images = []
            try:
                pi = page.to_image(resolution=150)  # higher res for clearer images
                for img_dict in page.images:
                    # bbox in pdf coordinates (x0, top, x1, bottom)
                    bbox = (img_dict.get("x0"), img_dict.get("top"), img_dict.get("x1"), img_dict.get("bottom"))
                    # crop -> PIL
                    crop = pi.crop(bbox).original
                    images.append({"bbox": bbox, "pil": crop})
            except Exception:
                images = []

            pages_data.append({"lines": lines, "images": images})
    return pages_data

def group_questions_from_lines(lines):
    """
    Heuristic: Scan lines, detect question starters and following option lines.
    Produces list of question dicts:
    {"question": str, "options": [str,...], "correct": None, "raw": [lines]}
    """
    qlist = []
    cur = None

    # Helper: treat contiguous lines as continuation if no new question or option found.
    for i, line in enumerate(lines):
        # Try detect question start
        qmatch = None
        # common pattern: "1. What is ...?" or "Q1. ..." etc.
        m = re.match(r'^\s*(?:Q|q)?\s*(\d+)[\).:-]\s*(.+)', line)
        if m:
            # start new question
            if cur:
                qlist.append(cur)
            qtext = m.group(2).strip()
            cur = {"question": qtext, "options": [], "raw": [line]}
            continue

        # if no numeric prefix, but line ends with '?', treat as question (standalone)
        if "?" in line and (len(line.split()) > 3) and (cur is None or len(cur.get("options", []))==0):
            # start new question without number
            if cur:
                qlist.append(cur)
            cur = {"question": line.strip(), "options": [], "raw": [line]}
            continue

        # Try detect option line
        om = OPTION_LINE_RE.match(line)
        if om and cur:
            letter = om.group(1).upper()
            opt_text = om.group(2).strip()
            cur["options"].append(opt_text)
            cur["raw"].append(line)
            continue

        # If line starts with something like (a) or "a) text" inline (but not matched), check inline markers
        inline_letters = OPTION_LETTER_INLINE_RE.findall(line)
        if inline_letters and cur:
            # try split by inline markers
            parts = re.split(r'\b([A-Da-d])[\)\.\-]\s*', line)
            # parts structure: before, letter, text, letter, text ...
            # We'll assemble texts after each letter
            assembled = []
            for idx in range(1, len(parts), 2):
                letter = parts[idx]
                textp = parts[idx+1].strip() if idx+1 < len(parts) else ""
                assembled.append(textp)
            if assembled:
                for p in assembled:
                    if p:
                        cur["options"].append(p.strip())
                cur["raw"].append(line)
                continue

        # Otherwise, if continuation of current question or option, append to last text
        if cur:
            # if no options yet -> continuation of question text
            if not cur["options"]:
                cur["question"] += " " + line.strip()
                cur["raw"].append(line)
            else:
                # continuation of last option
                cur["options"][-1] += " " + line.strip()
                cur["raw"].append(line)
        else:
            # orphan lines - ignore
            continue

    if cur:
        qlist.append(cur)

    # Filter questions that look valid (have question and >=2 options)
    cleaned = []
    for q in qlist:
        if q["question"] and len(q["options"]) >= 2:
            cleaned.append(q)
    return cleaned

def attach_page_images_to_questions(pages_data, questions):
    """
    Attempt to attach an image to question if question raw lines reference 'Fig' or are on same page.
    Simple heuristic: if question raw text appears on page i lines, attach that page's first image.
    """
    attached = []
    # Build a mapping of lines -> page index
    line_to_page = {}
    for pidx, pdata in enumerate(pages_data):
        for ln in pdata["lines"]:
            key = ln.strip()
            if key:
                line_to_page.setdefault(key, []).append(pidx)

    for q in questions:
        attached_img = None
        found_page = None
        # search for any raw line literal in pages mapping
        for r in q.get("raw", []):
            pages = line_to_page.get(r.strip(), [])
            if pages:
                found_page = pages[0]
                break
        # If found and that page has images, attach first one
        if found_page is None:
            # fallback: if any page lines contain a word like "Figure" or "Fig." near question
            for pidx, pdata in enumerate(pages_data):
                for ln in pdata["lines"]:
                    if re.search(r'fig(?:ure)?\.?', ln, re.IGNORECASE) and any(word in q["question"] for word in ln.split()[:6]):
                        found_page = pidx
                        break
                if found_page is not None:
                    break

        if found_page is not None:
            imgs = pages_data[found_page]["images"]
            if imgs:
                attached_img = imgs[0]["pil"]  # PIL image
        attached.append({"question": q["question"], "options": q["options"], "answer": None, "image": attached_img})
    return attached

# ---------------------------
# Bot behavior / state
# ---------------------------
# In-memory store: chat_id -> quiz session
SESSIONS = {}

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me a PDF (question bank / notes). I'll parse questions and serve an MCQ quiz.\n\n"
        "Supported: numbered questions, options A-D (a) A. a) etc.).\n"
        "I will also try to include figures from the same page."
    )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Download file
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Please send a PDF file.")
        return
    await update.message.reply_text("📥 Downloading and parsing PDF — please wait...")
    f = await doc.get_file()
    temp_path = "uploaded.pdf"
    await f.download(custom_path=temp_path)

    # Parse pdf
    try:
        pages = extract_text_and_images_from_pdf(temp_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to parse PDF: {e}")
        return

    # Collect all lines across pages (keeps order)
    all_lines = []
    for p in pages:
        all_lines.extend(p["lines"])

    # Extract questions from lines
    extracted = group_questions_from_lines(all_lines)
    if not extracted:
        await update.message.reply_text("⚠️ Could not find well-formed questions with options in this PDF.")
        return

    # Attach images heuristically
    q_with_images = attach_page_images_to_questions(pages, extracted)

    # Finalize options order (shuffle) and set a dummy 'correct' if pattern has (ans) or a letter marked
    final_qs = []
    for q in q_with_images:
        options = q["options"]
        # Clean whitespace and strip any leading letters
        clean_opts = [re.sub(r'^[A-Da-d][\)\.\-]\s*', '', opt).strip() for opt in options]
        # Try detect correct answer inline e.g., "(Ans: B)" or "Correct: C"
        combined = " ".join(q.get("raw", [])) if q.get("raw") else q["question"]
        ans_match = re.search(r'(?:Ans|Answer|Correct)\W*[:\-]?\s*([A-Da-d])', combined)
        correct = None
        if ans_match:
            correct_letter = ans_match.group(1).upper()
            # map letter to index if present
            alpha = ["A","B","C","D"]
            if correct_letter in alpha and len(clean_opts) >= alpha.index(correct_letter)+1:
                correct = clean_opts[alpha.index(correct_letter)]
        # If no correct found, select random as placeholder (you can integrate an answer-key or AI later)
        if not correct and clean_opts:
            correct = random.choice(clean_opts)

        # build final item
        final_qs.append({
            "question": q["question"],
            "options": clean_opts,
            "correct": correct,
            "image": q["image"]
        })

    # Save session
    chat_id = update.effective_chat.id
    SESSIONS[chat_id] = {"qs": final_qs, "idx": 0, "score": 0, "answers": []}
    await update.message.reply_text(f"✅ Parsed {len(final_qs)} questions. Starting quiz...")
    await send_next_question(chat_id, context)

async def send_next_question(chat_id_or_update, context: ContextTypes.DEFAULT_TYPE):
    # Accept either update or chat_id
    if isinstance(chat_id_or_update, Update):
        chat_id = chat_id_or_update.effective_chat.id
        reply_target = chat_id_or_update
    else:
        chat_id = chat_id_or_update
        reply_target = None

    session = SESSIONS.get(chat_id)
    if not session:
        return

    idx = session["idx"]
    if idx >= len(session["qs"]):
        # finish
        await show_report(chat_id, context)
        return

    q = session["qs"][idx]
    # Build buttons
    buttons = []
    for opt in q["options"]:
        # send option as callback_data (we'll compare strings)
        buttons.append([InlineKeyboardButton(opt, callback_data=f"ans|{idx}|{opt}")])
    markup = InlineKeyboardMarkup(buttons)

    # If image exists, send it first
    if q.get("image"):
        bio = io.BytesIO()
        q["image"].save(bio, format="PNG")
        bio.seek(0)
        await context.bot.send_photo(chat_id=chat_id, photo=InputFile(bio, filename=f"q{idx+1}.png"), caption=q["question"], reply_markup=markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=f"Q{idx+1}. {q['question']}", reply_markup=markup)

async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    # format: ans|{idx}|{option}
    parts = data.split("|", 2)
    if len(parts) < 3:
        await query.edit_message_text("Invalid answer payload.")
        return
    _, sidx, chosen = parts
    idx = int(sidx)
    chat_id = query.message.chat.id
    session = SESSIONS.get(chat_id)
    if not session or idx != session["idx"]:
        await query.edit_message_text("This question is no longer active.")
        return

    q = session["qs"][idx]
    correct = q["correct"]
    # normalize compare
    def norm(s): return re.sub(r'\s+', ' ', s.strip().lower())
    if norm(chosen) == norm(correct):
        session["score"] += 1
        result_text = f"✅ Correct! ({chosen})"
    else:
        result_text = f"❌ Wrong. You chose: {chosen}\nCorrect: {correct}"

    # record answer
    session["answers"].append({"idx": idx, "chosen": chosen, "correct": correct, "question": q["question"]})
    session["idx"] += 1

    # edit message to show result
    try:
        await query.edit_message_text(result_text)
    except Exception:
        pass

    # Send next
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

    # Offer CSV download
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["q_index", "question", "chosen", "correct"])
    for a in session["answers"]:
        writer.writerow([a["idx"]+1, a["question"], a["chosen"], a["correct"]])
    csv_buffer.seek(0)
    bio = io.BytesIO(csv_buffer.getvalue().encode("utf-8"))
    bio.name = "quiz_report.csv"
    await context.bot.send_document(chat_id=chat_id, document=InputFile(bio, filename="quiz_report.csv"))

    # cleanup session (optional)
    del SESSIONS[chat_id]

# ---------------------------
# Bot start / wiring
# ---------------------------
def main():
    Thread(target=run_flask).start()
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", cmd_start))
    app_tg.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app_tg.add_handler(CallbackQueryHandler(answer_callback))
    print("🚀 Bot running (polling)...")
    app_tg.run_polling()

if __name__ == "__main__":
    main()
