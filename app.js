const DATA_SOURCES = ["data/rounds.json", "data/demo.json"];
const DEFAULT_MODE = localStorage.getItem("mystery-cart-mode") || "photo";
const DEFAULT_CATEGORY = localStorage.getItem("mystery-cart-category") || "all";
const DEFAULT_ROUND_COUNT = localStorage.getItem("mystery-cart-round-count") || "10";

const state = {
  dataset: null,
  datasetSignature: "",
  rounds: [],
  order: [],
  index: 0,
  score: 0,
  correct: 0,
  streak: 0,
  skipped: 0,
  answered: false,
  outcomes: [],
  mode: DEFAULT_MODE,
  category: DEFAULT_CATEGORY,
  roundCount: DEFAULT_ROUND_COUNT,
  daily: false,
  dailyDate: null,
};

const els = {
  loadingState: document.querySelector("#loadingState"),
  gameContent: document.querySelector("#gameContent"),
  gameCard: document.querySelector("#gameCard"),
  finishCard: document.querySelector("#finishCard"),
  reviewImage: document.querySelector("#reviewImage"),
  photoFallback: document.querySelector("#photoFallback"),
  photoCaption: document.querySelector("#photoCaption"),
  skipBrokenButton: document.querySelector("#skipBrokenButton"),
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
  dailyButton: document.querySelector("#dailyButton"),
  playAgainButton: document.querySelector("#playAgainButton"),
  finishHeadline: document.querySelector("#finishHeadline"),
  finishSummary: document.querySelector("#finishSummary"),
  finishScore: document.querySelector("#finishScore"),
  resultSquares: document.querySelector("#resultSquares"),
  shareButton: document.querySelector("#shareButton"),
  shareStatus: document.querySelector("#shareStatus"),
  datasetNote: document.querySelector("#datasetNote"),
  aboutButton: document.querySelector("#aboutButton"),
  aboutDialog: document.querySelector("#aboutDialog"),
  closeAboutButton: document.querySelector("#closeAboutButton"),
  categorySelect: document.querySelector("#categorySelect"),
  roundCountSelect: document.querySelector("#roundCountSelect"),
  challengeBanner: document.querySelector("#challengeBanner"),
  challengeTitle: document.querySelector("#challengeTitle"),
  challengeDate: document.querySelector("#challengeDate"),
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

function cleanText(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function categoryKey(round) {
  return cleanText(round.source_category) || cleanText(round.product?.category) || "Other";
}

function humanizeCategory(value) {
  return cleanText(value, "Other").replaceAll("_and_", " & ").replaceAll("_", " ");
}

function normalizeData(payload) {
  if (!payload || !Array.isArray(payload.rounds)) {
    throw new Error("Dataset must contain a rounds array.");
  }

  const rounds = payload.rounds.filter((round) => {
    return round
      && round.id
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

function formatMeta(product) {
  const category = cleanText(product.leaf_category) || cleanText(product.category);
  return [
    category,
    product.price ? `$${Number(product.price).toFixed(2)}` : null,
    cleanText(product.store),
  ].filter(Boolean).join(" · ");
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

function populateCategorySelect() {
  const categories = [...new Set(state.rounds.map(categoryKey))]
    .sort((left, right) => humanizeCategory(left).localeCompare(humanizeCategory(right)));

  const options = [new Option("All categories", "all")];
  categories.forEach((category) => options.push(new Option(humanizeCategory(category), category)));
  els.categorySelect.replaceChildren(...options);

  if (state.category !== "all" && !categories.includes(state.category)) {
    state.category = "all";
  }
  els.categorySelect.value = state.category;
}

function selectedPool() {
  if (state.category === "all") return state.rounds;
  return state.rounds.filter((round) => categoryKey(round) === state.category);
}

function normalizedRoundCount(poolSize) {
  if (state.roundCount === "all") return poolSize;
  const requested = Number.parseInt(state.roundCount, 10);
  if (!Number.isFinite(requested) || requested < 1) return Math.min(10, poolSize);
  return Math.min(requested, poolSize);
}

function resetScoreState() {
  state.index = 0;
  state.score = 0;
  state.correct = 0;
  state.streak = 0;
  state.skipped = 0;
  state.answered = false;
  state.outcomes = [];
  els.scoreStatus.textContent = "0";
  els.streakStatus.textContent = "0";
  els.shareStatus.textContent = "";
}

function setDailyUrl(dateKey) {
  const url = new URL(window.location.href);
  url.searchParams.delete("daily");
  if (dateKey) url.searchParams.set("daily", dateKey);
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function setDailyUi(active, dateKey = null) {
  els.challengeBanner.hidden = !active;
  els.categorySelect.disabled = active;
  els.roundCountSelect.disabled = active;
  els.modeButtons.forEach((button) => { button.disabled = active; });
  els.dailyButton.classList.toggle("is-active", active);
  if (active) {
    els.challengeTitle.textContent = "Daily challenge";
    els.challengeDate.textContent = dateKey;
  }
}

function startNormalGame() {
  state.daily = false;
  state.dailyDate = null;
  setDailyUi(false);
  setDailyUrl(null);
  setMode(state.mode);
  resetScoreState();

  let pool = selectedPool();
  if (!pool.length) {
    state.category = "all";
    els.categorySelect.value = "all";
    pool = state.rounds;
  }
  state.order = shuffle(pool).slice(0, normalizedRoundCount(pool.length));

  els.finishCard.hidden = true;
  els.gameCard.hidden = false;
  renderRound();
}

function dailyStorageKey(dateKey) {
  return `mystery-cart-daily:${state.datasetSignature}:${dateKey}`;
}

function readSavedDaily(dateKey) {
  try {
    const raw = localStorage.getItem(dailyStorageKey(dateKey));
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (!value || !Array.isArray(value.outcomes)) return null;
    return value;
  } catch {
    return null;
  }
}

function saveDailyResult() {
  if (!state.daily || !state.dailyDate) return;
  const payload = {
    score: state.score,
    correct: state.correct,
    skipped: state.skipped,
    outcomes: state.outcomes,
  };
  localStorage.setItem(dailyStorageKey(state.dailyDate), JSON.stringify(payload));
}

function startDailyGame(dateKey = GameCore.utcDateKey()) {
  const resolvedDate = GameCore.isDateKey(dateKey) ? dateKey : GameCore.utcDateKey();
  state.daily = true;
  state.dailyDate = resolvedDate;
  setMode("photo");
  setDailyUi(true, resolvedDate);
  setDailyUrl(resolvedDate);
  resetScoreState();
  state.order = GameCore.dailyRounds(state.rounds, resolvedDate, 5);

  const saved = readSavedDaily(resolvedDate);
  if (saved) {
    state.score = Number(saved.score) || 0;
    state.correct = Number(saved.correct) || 0;
    state.skipped = Number(saved.skipped) || 0;
    state.outcomes = saved.outcomes.slice(0, state.order.length);
    while (state.outcomes.length < state.order.length) state.outcomes.push("skipped");
    state.index = state.order.length;
    finishGame({ restored: true });
    return;
  }

  els.finishCard.hidden = true;
  els.gameCard.hidden = false;
  renderRound();
}

function currentRound() {
  return state.order[state.index];
}

function roundChoices(round) {
  const choices = round.choices.slice(0, 4);
  if (state.daily) return GameCore.dailyChoices(choices, state.dailyDate, round.id);
  return shuffle(choices);
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
  els.reviewImage.src = "";
  els.reviewImage.src = round.review_image;
  els.photoCaption.textContent = `${humanizeCategory(categoryKey(round))} · customer review photo`;

  els.roundStatus.textContent = `${state.index + 1} / ${state.order.length}`;
  els.scoreStatus.textContent = String(state.score);
  els.streakStatus.textContent = String(state.streak);

  els.clueStars.textContent = starString(round.rating);
  els.clueStars.setAttribute("aria-label", `${round.rating || 0} out of 5 stars`);
  els.clueTitle.textContent = cleanText(round.review_title, "Customer review");
  els.clueText.textContent = cleanText(round.review_text, "No review text included.");
  els.reviewClue.hidden = state.mode !== "review";

  els.choices.replaceChildren(...roundChoices(round).map((choice, index) => makeChoice(choice, index)));
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
    state.outcomes[state.index] = "correct";
  } else {
    state.streak = 0;
    state.outcomes[state.index] = "wrong";
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

function advanceRound() {
  state.index += 1;
  if (state.index >= state.order.length) {
    finishGame();
  } else {
    renderRound();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function nextRound() {
  if (!state.answered) return;
  advanceRound();
}

function skipBrokenRound() {
  if (state.answered) return;
  state.skipped += 1;
  state.streak = 0;
  state.outcomes[state.index] = "skipped";
  els.streakStatus.textContent = "0";
  advanceRound();
}

function finishGame({ restored = false } = {}) {
  const total = state.order.length;
  while (state.outcomes.length < total) state.outcomes.push("skipped");
  const answeredTotal = Math.max(0, total - state.skipped);
  const ratio = total ? state.correct / total : 0;
  let headline = "That was weird.";
  if (total && ratio === 1) headline = "Perfect cart detective.";
  else if (ratio >= 0.75) headline = "You know your review photos.";
  else if (ratio >= 0.5) headline = "Solid detective work.";

  const skipCopy = state.skipped ? ` ${state.skipped} broken photo${state.skipped === 1 ? " was" : "s were"} skipped.` : "";
  els.finishHeadline.textContent = restored ? "Today's result" : headline;
  els.finishSummary.textContent = state.daily
    ? `You got ${state.correct} of ${total} daily products right.${skipCopy}`
    : `You got ${state.correct} of ${answeredTotal} answered products right.${skipCopy}`;
  els.finishScore.textContent = String(state.score);
  els.gameCard.hidden = true;
  els.finishCard.hidden = false;

  if (state.daily) {
    saveDailyResult();
    els.resultSquares.textContent = GameCore.resultSquares(state.outcomes.slice(0, total));
    els.resultSquares.hidden = false;
    els.shareButton.hidden = false;
    els.playAgainButton.textContent = "Play another game";
  } else {
    els.resultSquares.hidden = true;
    els.shareButton.hidden = true;
    els.playAgainButton.textContent = "Play again";
  }

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showImageFallback() {
  els.reviewImage.hidden = true;
  els.photoFallback.hidden = false;
}

function hideImageFallback() {
  els.photoFallback.hidden = true;
  els.reviewImage.hidden = false;
}

function updateDatasetNote(source) {
  const label = cleanText(
    state.dataset?.name,
    source.endsWith("demo.json") ? "Bundled demo" : "Local dataset",
  );
  const categoryCount = new Set(state.rounds.map(categoryKey)).size;
  const categoryCopy = `${categoryCount} ${categoryCount === 1 ? "category" : "categories"}`;
  els.datasetNote.textContent = `${label} · ${state.rounds.length.toLocaleString()} playable rounds · ${categoryCopy}.`;
}

function dailyShareUrl() {
  const url = new URL(window.location.href);
  url.search = "";
  url.searchParams.set("daily", state.dailyDate);
  url.hash = "";
  return url.toString();
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

async function shareDailyResult() {
  if (!state.daily || !state.dailyDate) return;
  const text = GameCore.buildDailyShare({
    dateKey: state.dailyDate,
    correct: state.correct,
    total: state.order.length,
    score: state.score,
    outcomes: state.outcomes.slice(0, state.order.length),
    url: dailyShareUrl(),
  });

  try {
    if (navigator.share) {
      await navigator.share({ title: "What Did They Buy?", text });
      els.shareStatus.textContent = "Shared.";
    } else {
      await copyText(text);
      els.shareStatus.textContent = "Result copied to clipboard.";
    }
  } catch (error) {
    if (error?.name !== "AbortError") {
      try {
        await copyText(text);
        els.shareStatus.textContent = "Result copied to clipboard.";
      } catch {
        els.shareStatus.textContent = "Could not share automatically.";
      }
    }
  }
}

function requestedDailyDate() {
  const value = new URLSearchParams(window.location.search).get("daily");
  if (value === "1" || value === "today") return GameCore.utcDateKey();
  return GameCore.isDateKey(value) ? value : null;
}

function bindEvents() {
  els.nextButton.addEventListener("click", nextRound);
  els.newGameButton.addEventListener("click", startNormalGame);
  els.dailyButton.addEventListener("click", () => startDailyGame());
  els.playAgainButton.addEventListener("click", () => {
    if (state.daily) startNormalGame();
    else startNormalGame();
  });
  els.shareButton.addEventListener("click", shareDailyResult);
  els.skipBrokenButton.addEventListener("click", skipBrokenRound);
  els.reviewImage.addEventListener("error", showImageFallback);
  els.reviewImage.addEventListener("load", hideImageFallback);

  els.modeButtons.forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });

  els.categorySelect.addEventListener("change", () => {
    state.category = els.categorySelect.value;
    localStorage.setItem("mystery-cart-category", state.category);
    startNormalGame();
  });

  els.roundCountSelect.addEventListener("change", () => {
    state.roundCount = els.roundCountSelect.value;
    localStorage.setItem("mystery-cart-round-count", state.roundCount);
    startNormalGame();
  });

  els.aboutButton.addEventListener("click", () => els.aboutDialog.showModal());
  els.closeAboutButton.addEventListener("click", () => els.aboutDialog.close());
  els.aboutDialog.addEventListener("click", (event) => {
    if (event.target === els.aboutDialog) els.aboutDialog.close();
  });

  document.addEventListener("keydown", (event) => {
    if (els.aboutDialog.open) return;
    if (!state.answered && !els.photoFallback.hidden && event.key.toLowerCase() === "s") {
      skipBrokenRound();
      return;
    }
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
  els.roundCountSelect.value = [...els.roundCountSelect.options].some((option) => option.value === state.roundCount)
    ? state.roundCount
    : "10";
  state.roundCount = els.roundCountSelect.value;

  try {
    const { payload, source } = await loadDataset();
    state.dataset = payload;
    state.rounds = payload.rounds;
    state.datasetSignature = GameCore.hashString(
      state.rounds.map((round) => round.id).sort().join("|"),
    ).toString(16);
    populateCategorySelect();
    els.loadingState.hidden = true;
    els.gameContent.hidden = false;
    updateDatasetNote(source);

    const dailyDate = requestedDailyDate();
    if (dailyDate) startDailyGame(dailyDate);
    else startNormalGame();
  } catch (error) {
    els.loadingState.textContent = `Could not load game data: ${error.message}`;
    console.error(error);
  }
}

init();
