let questions = [];
let current = 0;
let timer;
let timeLeft = 30;

const pdfFile = document.getElementById("pdfFile");
const extractBtn = document.getElementById("extractBtn");
const loader = document.getElementById("loader");
const quizBox = document.getElementById("quiz-box");
const qArea = document.getElementById("question-area");
const optArea = document.getElementById("options-area");
const timerEl = document.getElementById("timer");

extractBtn.onclick = async () => {
  const file = pdfFile.files[0];
  if (!file) return alert("Please upload a PDF file first!");

  loader.classList.remove("hidden");
  try {
    const text = await extractPDF(file);
    loader.classList.add("hidden");

    questions = parseSmartQuestions(text);
    if (questions.length === 0) {
      alert("❌ No valid MCQs found in PDF!");
      return;
    }
    startQuiz();
  } catch (err) {
    console.error(err);
    loader.classList.add("hidden");
    alert("Error reading PDF! Try another file.");
  }
};

async function extractPDF(file) {
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  let text = "";
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    const pageText = content.items.map((t) => t.str).join(" ");
    text += "\n" + pageText;
  }
  return text;
}

function parseSmartQuestions(rawText) {
  let text = rawText
    .replace(/\s+/g, " ")
    .replace(/Page\s*\d+/gi, "")
    .replace(/Section\s*[A-Z]/gi, "")
    .trim();

  const regex =
    /(\d+[\.\)]\s*[^(\d\.)]+?)\s*(?:\(a\)|a\))\s*(.+?)\s*(?:\(b\)|b\))\s*(.+?)\s*(?:\(c\)|c\))\s*(.+?)\s*(?:\(d\)|d\))\s*(.+?)(?=\d+[\.\)]|$)/gis;

  let matches = [...text.matchAll(regex)];
  let parsed = matches.map((m) => ({
    question: cleanText(m[1]),
    options: [m[2], m[3], m[4], m[5]].map(cleanText),
  }));

  parsed = parsed.filter(
    (q) => q.question.length > 10 && q.options.every((o) => o.length > 0)
  );

  return parsed;
}

function cleanText(t) {
  return t.replace(/\s+/g, " ").replace(/[^\w\s,.'’\-+/*=°]/g, "").trim();
}

function startQuiz() {
  current = 0;
  quizBox.classList.remove("hidden");
  showQuestion();
}

function showQuestion() {
  clearInterval(timer);
  timeLeft = 30;
  timerEl.textContent = `⏱ ${timeLeft}s`;
  timer = setInterval(() => {
    timeLeft--;
    timerEl.textContent = `⏱ ${timeLeft}s`;
    if (timeLeft <= 0) nextQ();
  }, 1000);

  const q = questions[current];
  qArea.innerHTML = `<h3>Q${current + 1}. ${q.question}</h3>`;
  optArea.innerHTML = "";
  q.options.forEach((opt) => {
    const div = document.createElement("div");
    div.classList.add("option");
    div.textContent = opt;
    div.onclick = () => {
      document.querySelectorAll(".option").forEach((o) => (o.style.background = "#292929"));
      div.style.background = "#03dac5";
    };
    optArea.appendChild(div);
  });
}

document.getElementById("nextBtn").onclick = nextQ;
document.getElementById("prevBtn").onclick = () => {
  if (current > 0) {
    current--;
    showQuestion();
  }
};

function nextQ() {
  if (current < questions.length - 1) {
    current++;
    showQuestion();
  } else {
    clearInterval(timer);
    alert("✅ Quiz finished!");
  }
}
