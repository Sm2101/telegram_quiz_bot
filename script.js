let quiz = [
  { question: "What is H₂O?", options: ["Water", "Oxygen", "Hydrogen", "Helium"], answer: 0 },
  { question: "Who discovered gravity?", options: ["Newton", "Einstein", "Galileo", "Tesla"], answer: 0 },
  { question: "2 + 2 = ?", options: ["3", "4", "5", "6"], answer: 1 },
  { question: "Which planet is known as the Red Planet?", options: ["Earth", "Mars", "Jupiter", "Venus"], answer: 1 }
];

let shuffledQuiz = [];
let current = 0;
let score = 0;
let timer;
let timeLeft = 30;

const questionEl = document.getElementById("question");
const optionsEl = document.getElementById("options");
const nextBtn = document.getElementById("next-btn");
const quizBox = document.getElementById("quiz-box");
const resultBox = document.getElementById("result-box");
const scoreEl = document.getElementById("score");
const summaryEl = document.getElementById("summary");
const startBtn = document.getElementById("start-btn");
const startBox = document.getElementById("start-box");
const timerEl = document.getElementById("timer");
const fileInput = document.getElementById("fileInput");

startBtn.onclick = () => {
  startBox.classList.add("hidden");
  quizBox.classList.remove("hidden");
  startQuiz();
};

function startQuiz() {
  score = 0;
  current = 0;
  shuffledQuiz = quiz.sort(() => Math.random() - 0.5);
  loadQuestion();
}

function loadQuestion() {
  clearInterval(timer);
  timeLeft = 30;
  timerEl.textContent = `⏱ ${timeLeft}s`;
  timer = setInterval(() => {
    timeLeft--;
    timerEl.textContent = `⏱ ${timeLeft}s`;
    if (timeLeft <= 0) {
      clearInterval(timer);
      nextQuestion();
    }
  }, 1000);

  const q = shuffledQuiz[current];
  questionEl.textContent = `Q${current + 1}. ${q.question}`;
  optionsEl.innerHTML = "";

  q.options.forEach((opt, i) => {
    const div = document.createElement("div");
    div.classList.add("option");
    div.textContent = opt;
    div.onclick = () => checkAnswer(i, div);
    optionsEl.appendChild(div);
  });

  nextBtn.style.display = "none";
}

function checkAnswer(selected, div) {
  const correct = shuffledQuiz[current].answer;
  clearInterval(timer);
  const options = document.querySelectorAll(".option");
  options.forEach((opt, i) => {
    if (i === correct) opt.classList.add("correct");
    else if (i === selected && i !== correct) opt.classList.add("wrong");
    opt.style.pointerEvents = "none";
  });

  if (selected === correct) score++;
  nextBtn.style.display = "block";
}

nextBtn.onclick = nextQuestion;

function nextQuestion() {
  current++;
  if (current < shuffledQuiz.length) {
    loadQuestion();
  } else {
    showResult();
  }
}

function showResult() {
  clearInterval(timer);
  quizBox.classList.add("hidden");
  resultBox.classList.remove("hidden");
  scoreEl.textContent = `You scored ${score}/${shuffledQuiz.length}`;
  const percent = ((score / shuffledQuiz.length) * 100).toFixed(1);
  let msg =
    percent === 100 ? "🔥 Perfect!" :
    percent >= 70 ? "💪 Great Job!" :
    percent >= 40 ? "🙂 Keep Practicing!" : "😅 Try Again!";
  summaryEl.textContent = msg;
}

function restartQuiz() {
  resultBox.classList.add("hidden");
  startBox.classList.remove("hidden");
}

fileInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (event) => {
    const text = event.target.result;
    if (file.name.endsWith(".json")) {
      quiz = JSON.parse(text);
    } else if (file.name.endsWith(".csv")) {
      quiz = parseCSV(text);
    }
    alert("✅ Questions loaded successfully!");
  };
  reader.readAsText(file);
});

function parseCSV(text) {
  const lines = text.trim().split("\n");
  return lines.map((line) => {
    const [question, opt1, opt2, opt3, opt4, correct] = line.split(",");
    return {
      question,
      options: [opt1, opt2, opt3, opt4],
      answer: parseInt(correct) - 1
    };
  });
}
