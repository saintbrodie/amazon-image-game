const DATA_SOURCES = ["data/rounds.json", "data/demo.json"];
const DEFAULT_MODE = localStorage.getItem("mystery-cart-mode") || "photo";

const state = {
  dataset: null,
  rounds: [],
  order: [],
  index: 0,
  score: 0,
  correct: 0,
  streak: 0,
  answered: false,
  mode: DEFAULT_MODE,
};

const els = {
  loadingState: document.querySelector("#loadingState"),
  gameContent: document.querySelector("#gameContent"),
  gameCard: document.querySelector("#gameCard"),
  finishCard: document.querySelector("#finishCard"),
  reviewImage: document.querySelector("#reviewImage"),
  photoFallback: document.querySelector("#photoFallback"),
  reviewClue: document.querySelector("#reviewClue"),
  clueStars: document.querySelector("#clueStars"),
  clueTitle: document.querySelector("#clueTitle"),
  clueText: document.querySelector("#clueText"),
  choices: document.querySelector("#choices"),
  roundStatus: document.querySelector("#roundStatus"),
  scoreStatus: document.querySelector("#scoreStatus"),
  streakStatus: document.querySelector("#streakStatus"),
  revealCard: document.querySelector("#revealCard"),
  resultBadge: document.querySelector("#resultBadge"),
  pointsAwarded: document.querySelector("#pointsAwarded"),
  productTitle: document.querySelector("#productTitle"),
  productMeta: document.querySelector("#productMeta"),
  revealStars: document.querySelector("#revealStars"),
  reviewTitle: document.querySelector("#reviewTitle"),
  reviewText: document.querySelector("#reviewText"),
  sourceLink: document.querySelector("#sourceLink"),
  nextButton: document.querySelector("#nextButton"),
  newGameButton: document.querySelector("#newGameButton"),
  playAgainButton: document.querySelector("#playAgainButton"),
  finishHeadline: document.querySelector("#finishHeadline"),
  finishSummary: document.querySelector("#finishSummary"),
  finishScore: document.querySelector("#finishScore"),
  datasetNote: document.querySelector("#datasetNote"),
  aboutButton: document.querySelector("#aboutButton"),
  aboutDialog: document.querySelector("#aboutDialog"),
  closeAboutButton: document.querySelector("#closeAboutButton"),
  modeButtons: [...document.querySelectorAll(".mode-button")],
};

function shuffle(items) {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function normalizeData(payload) {
  if (!payload || !Array.isArray(payload.rounds)) {
    throw new Error("Dataset must contain a rounds array.");
  }

  const rounds = payload.rounds.filter((round) => {
    return round
      && round.review_image
      && round.product?.title
      && Array.isArray(round.choices)
      && round.choices.length >= 2
      && round.choices.includes(round.product.title);
  });

  if (!rounds.length) {
    throw new Error("Dataset does not contain any playable rounds.");
  }

  return { ...payload, rounds };
}

async function loadDataset() {
  let lastError = null;

  for (const source of DATA_SOURCES) {
    try {
      const response = await fetch(source, { cache: "no-store" });
      if (!response.ok) throw new Error(`${source}: ${response.status}`);
      const payload = normalizeData(await response.json());
      return { payload, source };
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError || new Error("No game dataset could be loaded.");
}

function starString(rating) {
  const value = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)));
  return `${"★".repeat(value)}${"☆".repeat(5 - value)}`;
}

function cleanText(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function formatMeta(product) {
  return [product.category, product.price ? `$${Number(product.price).toFixed(2)}` : null]
    .filter(Boolean)
    .join(" · ");
}

function setMode(mode) {
  state.mode = mode === "review" ? "review" : "photo";
  localStorage.setItem("mystery-cart-mode", state.mode);
  els.modeButtons.forEach((button) => {
    const active = button.dataset.mode === state.mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  els.reviewClue.hidden = state.mode !== "review";
}

function startGame() {
  state.index = 0;
  state.score = 0;
  state.correct = 0;
  state.streak = 0;
  state.answered = false;
  state.order = shuffle(state.rounds.map((_, index) => index));
  els.finishCard.hidden = true;
  els.gameCard.hidden = false;
  renderRound();
}

function currentRound() {
  return state.rounds[state.order[state.index]];
}

function renderRound() {
  const round = currentRound();
  if (!round) {
    finishGame();
    return;
  }

  state.answered = false;
  els.revealCard.hidden = true;
  els.photoFallback.hidden = true;
  els.reviewImage.hidden = false;
  els.reviewImage.alt = `Customer review photo for mystery product, round ${state.index + 1}`;
  els.reviewImage.src = round.review_image;

  els.roundStatus.textContent = `${state.index + 1} / ${state.order.length}`;
  els.scoreStatus.textContent = String(state.score);
  els.streakStatus.textContent = String(state.streak);

  els.clueStars.textContent = starString(round.rating);
  els.clueStars.setAttribute("aria-label", `${round.rating || 0} out of 5 stars`);
  els.clueTitle.textContent = cleanText(round.review_title, "Customer review");
  els.clueText.textContent = cleanText(round.review_text, "No review text included.");
  els.reviewClue.hidden = state.mode !== "review";

  const choices = shuffle(round.choices.slice(0, 4));
  els.choices.replaceChildren(...choices.map((choice, index) => makeChoice(choice, index)));
}

function makeChoice(choice, index) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "choice-button";
  button.dataset.choice = choice;

  const key = document.createElement("span");
  key.className = "choice-key";
  key.textContent = String(index + 1);

  const label = document.createElement("span");
  label.textContent = choice;

  button.append(key, label);
  button.addEventListener("click", () => answer(choice, button));
  return button;
}

function answer(choice, selectedButton) {
  if (state.answered) return;
  state.answered = true;

  const round = currentRound();
  const correct = choice === round.product.title;
  let points = 0;

  if (correct) {
    state.streak += 1;
    state.correct += 1;
    points = 100 + Math.min(state.streak - 1, 5) * 20;
    state.score += points;
  } else {
    state.streak = 0;
  }

  [...els.choices.querySelectorAll(".choice-button")].forEach((button) => {
    button.disabled = true;
    if (button.dataset.choice === round.product.title) button.classList.add("is-correct");
  });
  if (!correct) selectedButton.classList.add("is-wrong");

  els.scoreStatus.textContent = String(state.score);
  els.streakStatus.textContent = String(state.streak);
  renderReveal(round, correct, points);
}

function renderReveal(round, correct, points) {
  els.resultBadge.textContent = correct ? "Correct" : "Not quite";
  els.resultBadge.className = `result-badge ${correct ? "correct" : "wrong"}`;
  els.pointsAwarded.textContent = correct ? `+${points} points` : "0 points";
  els.productTitle.textContent = round.product.title;
  els.productMeta.textContent = formatMeta(round.product);
  els.revealStars.textContent = starString(round.rating);
  els.revealStars.setAttribute("aria-label", `${round.rating || 0} out of 5 stars`);
  els.reviewTitle.textContent = cleanText(round.review_title, "Customer review");
  els.reviewText.textContent = cleanText(round.review_text, "No review text included.");

  const sourceUrl = round.product.source_url || "";
  if (sourceUrl) {
    els.sourceLink.href = sourceUrl;
    els.sourceLink.hidden = false;
  } else {
    els.sourceLink.removeAttribute("href");
    els.sourceLink.hidden = true;
  }

  els.nextButton.textContent = state.index === state.order.length - 1 ? "See results" : "Next round";
  els.revealCard.hidden = false;
  els.revealCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function nextRound() {
  if (!state.answered) return;
  state.index += 1;
  if (state.index >= state.order.length) {
    finishGame();
  } else {
    renderRound();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function finishGame() {
  const total = state.order.length;
  const ratio = total ? state.correct / total : 0;
  let headline = "That was weird.";
  if (ratio === 1) headline = "Perfect cart detective.";
  else if (ratio >= 0.75) headline = "You know your review photos.";
  else if (ratio >= 0.5) headline = "Solid detective work.";

  els.finishHeadline.textContent = headline;
  els.finishSummary.textContent = `You got ${state.correct} of ${total} products right.`;
  els.finishScore.textContent = String(state.score);
  els.gameCard.hidden = true;
  els.finishCard.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showImageFallback() {
  els.reviewImage.hidden = true;
  els.photoFallback.hidden = false;
}

function bindEvents() {
  els.nextButton.addEventListener("click", nextRound);
  els.newGameButton.addEventListener("click", startGame);
  els.playAgainButton.addEventListener("click", startGame);
  els.reviewImage.addEventListener("error", showImageFallback);

  els.modeButtons.forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });

  els.aboutButton.addEventListener("click", () => els.aboutDialog.showModal());
  els.closeAboutButton.addEventListener("click", () => els.aboutDialog.close());
  els.aboutDialog.addEventListener("click", (event) => {
    if (event.target === els.aboutDialog) els.aboutDialog.close();
  });

  document.addEventListener("keydown", (event) => {
    if (els.aboutDialog.open) return;
    if (!state.answered && /^[1-4]$/.test(event.key)) {
      const button = els.choices.querySelectorAll(".choice-button")[Number(event.key) - 1];
      button?.click();
    } else if (state.answered && (event.key === "Enter" || event.key.toLowerCase() === "n")) {
      nextRound();
    }
  });
}

async function init() {
  bindEvents();
  setMode(state.mode);

  try {
    const { payload, source } = await loadDataset();
    state.dataset = payload;
    state.rounds = payload.rounds;
    els.loadingState.hidden = true;
    els.gameContent.hidden = false;

    const label = cleanText(payload.name, source.endsWith("demo.json") ? "Bundled demo" : "Local dataset");
    els.datasetNote.textContent = `${label} · ${state.rounds.length} playable rounds loaded.`;
    startGame();
  } catch (error) {
    els.loadingState.textContent = `Could not load game data: ${error.message}`;
    console.error(error);
  }
}

init();
