const DATA_SOURCES = ["data/rounds.json", "data/demo.json"];

const state = {
  dataset: null,
  rounds: [],
  datasetSignature: "",
  decisions: {},
  category: "all",
  status: "undecided",
  filtered: [],
  index: 0,
};

const els = {
  loadingState: document.querySelector("#loadingState"),
  content: document.querySelector("#content"),
  curationCard: document.querySelector("#curationCard"),
  emptyState: document.querySelector("#emptyState"),
  reviewImage: document.querySelector("#reviewImage"),
  imageFallback: document.querySelector("#imageFallback"),
  positionLabel: document.querySelector("#positionLabel"),
  roundId: document.querySelector("#roundId"),
  decisionPill: document.querySelector("#decisionPill"),
  sourceCategory: document.querySelector("#sourceCategory"),
  productTitle: document.querySelector("#productTitle"),
  productMeta: document.querySelector("#productMeta"),
  reviewStars: document.querySelector("#reviewStars"),
  reviewTitle: document.querySelector("#reviewTitle"),
  reviewText: document.querySelector("#reviewText"),
  choiceList: document.querySelector("#choiceList"),
  sourceLink: document.querySelector("#sourceLink"),
  rejectButton: document.querySelector("#rejectButton"),
  keepButton: document.querySelector("#keepButton"),
  previousButton: document.querySelector("#previousButton"),
  nextButton: document.querySelector("#nextButton"),
  categorySelect: document.querySelector("#categorySelect"),
  statusSelect: document.querySelector("#statusSelect"),
  reviewedStat: document.querySelector("#reviewedStat"),
  keptStat: document.querySelector("#keptStat"),
  rejectedStat: document.querySelector("#rejectedStat"),
  remainingStat: document.querySelector("#remainingStat"),
  exportButton: document.querySelector("#exportButton"),
  importButton: document.querySelector("#importButton"),
  importInput: document.querySelector("#importInput"),
  resetButton: document.querySelector("#resetButton"),
  datasetNote: document.querySelector("#datasetNote"),
};

function cleanText(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function humanizeCategory(value) {
  return cleanText(value, "Other").replaceAll("_and_", " & ").replaceAll("_", " ");
}

function categoryKey(round) {
  return cleanText(round.source_category) || cleanText(round.product?.category) || "Other";
}

function starString(rating) {
  const value = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)));
  return `${"★".repeat(value)}${"☆".repeat(5 - value)}`;
}

function datasetSignature(rounds) {
  return GameCore.hashString(rounds.map((round) => round.id).sort().join("|")).toString(16);
}

function storageKey() {
  return `mystery-cart-curation:${state.datasetSignature}`;
}

function loadStoredDecisions() {
  try {
    const raw = localStorage.getItem(storageKey());
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && parsed.decisions && typeof parsed.decisions === "object"
      ? parsed.decisions
      : {};
  } catch {
    return {};
  }
}

function saveDecisions() {
  localStorage.setItem(storageKey(), JSON.stringify({
    dataset_signature: state.datasetSignature,
    decisions: state.decisions,
    updated_at: new Date().toISOString(),
  }));
}

async function loadDataset() {
  let lastError = null;
  for (const source of DATA_SOURCES) {
    try {
      const response = await fetch(source, { cache: "no-store" });
      if (!response.ok) throw new Error(`${source}: ${response.status}`);
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.rounds) || !payload.rounds.length) {
        throw new Error(`${source}: no rounds`);
      }
      return { payload, source };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("No dataset found.");
}

function populateCategories() {
  const categories = [...new Set(state.rounds.map(categoryKey))]
    .sort((a, b) => humanizeCategory(a).localeCompare(humanizeCategory(b)));
  const options = [new Option("All categories", "all")];
  categories.forEach((category) => options.push(new Option(humanizeCategory(category), category)));
  els.categorySelect.replaceChildren(...options);
}

function matchesStatus(round) {
  const decision = state.decisions[round.id];
  if (state.status === "all") return true;
  if (state.status === "undecided") return !decision;
  return decision === state.status;
}

function rebuildFilter({ preserveRoundId = null } = {}) {
  state.filtered = state.rounds.filter((round) => {
    const categoryMatch = state.category === "all" || categoryKey(round) === state.category;
    return categoryMatch && matchesStatus(round);
  });

  if (preserveRoundId) {
    const position = state.filtered.findIndex((round) => round.id === preserveRoundId);
    state.index = position >= 0 ? position : Math.min(state.index, Math.max(0, state.filtered.length - 1));
  } else {
    state.index = Math.min(state.index, Math.max(0, state.filtered.length - 1));
  }
  render();
}

function currentRound() {
  return state.filtered[state.index];
}

function formatMeta(product) {
  return [
    cleanText(product.leaf_category) || cleanText(product.category),
    product.price ? `$${Number(product.price).toFixed(2)}` : null,
    cleanText(product.store),
    cleanText(product.asin),
  ].filter(Boolean).join(" · ");
}

function renderChoiceList(round) {
  const items = round.choices.map((choice) => {
    const item = document.createElement("li");
    item.textContent = choice;
    if (choice === round.product.title) item.classList.add("correct");
    return item;
  });
  els.choiceList.replaceChildren(...items);
}

function renderStats() {
  const values = Object.values(state.decisions);
  const kept = values.filter((value) => value === "keep").length;
  const rejected = values.filter((value) => value === "reject").length;
  const reviewed = kept + rejected;
  els.reviewedStat.textContent = reviewed.toLocaleString();
  els.keptStat.textContent = kept.toLocaleString();
  els.rejectedStat.textContent = rejected.toLocaleString();
  els.remainingStat.textContent = Math.max(0, state.rounds.length - reviewed).toLocaleString();
}

function renderDecision(round) {
  const decision = state.decisions[round.id] || "undecided";
  els.decisionPill.textContent = decision === "undecided" ? "Undecided" : decision === "keep" ? "Kept" : "Rejected";
  els.decisionPill.className = `decision-pill ${decision === "undecided" ? "" : decision}`.trim();
}

function render() {
  renderStats();
  const round = currentRound();
  const hasRound = Boolean(round);
  els.curationCard.hidden = !hasRound;
  els.emptyState.hidden = hasRound;
  if (!round) return;

  els.content.hidden = false;
  els.loadingState.hidden = true;
  els.positionLabel.textContent = `${state.index + 1} / ${state.filtered.length}`;
  els.roundId.textContent = round.id;
  els.sourceCategory.textContent = humanizeCategory(categoryKey(round));
  els.productTitle.textContent = round.product.title;
  els.productMeta.textContent = formatMeta(round.product);
  els.reviewStars.textContent = starString(round.rating);
  els.reviewTitle.textContent = cleanText(round.review_title, "Customer review");
  els.reviewText.textContent = cleanText(round.review_text, "No review text.");
  renderChoiceList(round);
  renderDecision(round);

  els.imageFallback.hidden = true;
  els.reviewImage.hidden = false;
  els.reviewImage.src = "";
  els.reviewImage.src = round.review_image;

  if (round.product.source_url) {
    els.sourceLink.href = round.product.source_url;
    els.sourceLink.hidden = false;
  } else {
    els.sourceLink.hidden = true;
    els.sourceLink.removeAttribute("href");
  }
}

function advance(direction = 1) {
  if (!state.filtered.length) return;
  state.index = (state.index + direction + state.filtered.length) % state.filtered.length;
  render();
}

function decide(value) {
  const round = currentRound();
  if (!round) return;
  state.decisions[round.id] = value;
  saveDecisions();
  renderStats();

  if (state.status === "undecided") {
    state.filtered.splice(state.index, 1);
    if (state.index >= state.filtered.length) state.index = Math.max(0, state.filtered.length - 1);
    render();
  } else {
    renderDecision(round);
    advance(1);
  }
}

function decisionExportPayload() {
  const kept = [];
  const rejected = [];
  Object.entries(state.decisions).forEach(([id, decision]) => {
    if (decision === "keep") kept.push(id);
    if (decision === "reject") rejected.push(id);
  });
  kept.sort();
  rejected.sort();
  return {
    version: 1,
    dataset_signature: state.datasetSignature,
    dataset_name: state.dataset?.name || null,
    exported_at: new Date().toISOString(),
    reviewed_count: kept.length + rejected.length,
    kept_ids: kept,
    rejected_ids: rejected,
  };
}

function exportDecisions() {
  const payload = decisionExportPayload();
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `curation-${state.datasetSignature}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function importDecisions(file) {
  const text = await file.text();
  const payload = JSON.parse(text);
  if (!payload || !Array.isArray(payload.kept_ids) || !Array.isArray(payload.rejected_ids)) {
    throw new Error("Not a curation decisions file.");
  }
  if (payload.dataset_signature && payload.dataset_signature !== state.datasetSignature) {
    const proceed = window.confirm("This decisions file was made for a different dataset signature. Import matching round IDs anyway?");
    if (!proceed) return;
  }

  const validIds = new Set(state.rounds.map((round) => round.id));
  payload.kept_ids.forEach((id) => { if (validIds.has(id)) state.decisions[id] = "keep"; });
  payload.rejected_ids.forEach((id) => { if (validIds.has(id)) state.decisions[id] = "reject"; });
  saveDecisions();
  rebuildFilter();
}

function resetDecisions() {
  if (!window.confirm("Clear all local curation decisions for this dataset?")) return;
  state.decisions = {};
  saveDecisions();
  rebuildFilter();
}

function bindEvents() {
  els.keepButton.addEventListener("click", () => decide("keep"));
  els.rejectButton.addEventListener("click", () => decide("reject"));
  els.previousButton.addEventListener("click", () => advance(-1));
  els.nextButton.addEventListener("click", () => advance(1));
  els.exportButton.addEventListener("click", exportDecisions);
  els.importButton.addEventListener("click", () => els.importInput.click());
  els.importInput.addEventListener("change", async () => {
    const [file] = els.importInput.files;
    if (!file) return;
    try {
      await importDecisions(file);
    } catch (error) {
      window.alert(`Could not import decisions: ${error.message}`);
    } finally {
      els.importInput.value = "";
    }
  });
  els.resetButton.addEventListener("click", resetDecisions);
  els.categorySelect.addEventListener("change", () => {
    state.category = els.categorySelect.value;
    state.index = 0;
    rebuildFilter();
  });
  els.statusSelect.addEventListener("change", () => {
    state.status = els.statusSelect.value;
    state.index = 0;
    rebuildFilter();
  });
  els.reviewImage.addEventListener("error", () => {
    els.reviewImage.hidden = true;
    els.imageFallback.hidden = false;
  });
  els.reviewImage.addEventListener("load", () => {
    els.reviewImage.hidden = false;
    els.imageFallback.hidden = true;
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("select, input, textarea")) return;
    if (event.key.toLowerCase() === "k") decide("keep");
    else if (event.key.toLowerCase() === "r") decide("reject");
    else if (event.key === "ArrowLeft") advance(-1);
    else if (event.key === "ArrowRight") advance(1);
  });
}

async function init() {
  bindEvents();
  try {
    const { payload, source } = await loadDataset();
    state.dataset = payload;
    state.rounds = payload.rounds.filter((round) => round?.id && round?.product?.title && round?.review_image);
    state.datasetSignature = datasetSignature(state.rounds);
    state.decisions = loadStoredDecisions();
    populateCategories();
    els.datasetNote.textContent = `${payload.name || source} · ${state.rounds.length.toLocaleString()} rounds · signature ${state.datasetSignature}`;
    rebuildFilter();
  } catch (error) {
    els.loadingState.textContent = `Could not load rounds: ${error.message}`;
    console.error(error);
  }
}

init();
