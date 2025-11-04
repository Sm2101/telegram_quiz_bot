let pdfText = "";
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
  if (!file) return alert("Please upload a PDF file!");

  loader.classList.remove("hidden");
  const text = await extractPDF(file);
  loader.classList.add("hidden");

  pdfText = text;
  questions = parseQuestions(pdfText);
  if (questions.length === 0) return alert("No questions found!");

  startQuiz();
};

async function extractPDF(file) {
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  let text = "";
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    text += content.items.map((t) => t.str).join(" ");
  }
  return text;
}

function parseQuestions(text) {
  const pattern = /(\d+\.\s.*?)(?=\d+\.|$)/gs;
  const matches = text.match(pattern);
  if (!matches) return [];

  return matches.map((q) => {
    const parts = q.split(/[\(a\)\(b\)\(c\)\(d\)]/i);
    const question = parts[0].trim();
    const opts = q.match(/\(a\)(.*?)\(b\)(.*?)\(c\)(.*?)\(d\)(.*)/i);
    return opts
      ? {
          question,
          options: [opts[1], opts[2], opts[3], opts[4]].map((o) =>
            o ? o.trim() : ""
          ),
        }
      : { question, options: [] };
  });
}

function startQuiz() {
  quizBox.classList.remove("hidden");
  current = 0;
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
