"use strict";

const DATA_ROOT = "data";
const KEYWORD_STORAGE_KEY = "koreaPolicyDashboardKeywordsV1";

const state = {
  config: null,
  manifest: null,
  currentDate: new Date(),
  selectedDate: null,
  keywords: [],
  monthArticles: [],
  matchedByDate: new Map(),
};

const elements = {};
const entityDecoder = document.createElement("textarea");

function decodeHtmlEntities(value, maxPasses = 5) {
  let current = String(value ?? "");
  for (let index = 0; index < maxPasses; index += 1) {
    entityDecoder.innerHTML = current;
    const decoded = entityDecoder.value;
    if (decoded === current) break;
    current = decoded;
  }
  return current;
}

function normalizeDisplayText(value) {
  return decodeHtmlEntities(value)
    .replace(/\u00a0/g, " ")
    .replace(/[\u00ad\u200b\ufeff]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function safeExternalUrl(value) {
  const decoded = normalizeDisplayText(value);
  if (!decoded) return "";
  try {
    const parsed = new URL(decoded, window.location.href);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch (error) {
    console.warn("유효하지 않은 외부 링크입니다.", decoded, error);
    return "";
  }
}

function normalizeArticle(article) {
  const normalized = { ...article };
  normalized.title = normalizeDisplayText(article.title || "");
  normalized.summary = normalizeDisplayText(article.summary || "");
  normalized.ministry = normalizeDisplayText(article.ministry || "기관 미상") || "기관 미상";
  normalized.original_url = safeExternalUrl(article.original_url || "");
  normalized.search_text = normalizeDisplayText(
    article.search_text
      || [normalized.title, normalized.summary, normalized.ministry].join(" "),
  );
  return normalized;
}

function byId(id) {
  return document.getElementById(id);
}

function pad2(value) {
  return String(value).padStart(2, "0");
}

function toDateKey(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function monthKey(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}`;
}

function parseDateKey(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function formatDateKorean(value, includeTime = false) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const options = includeTime
    ? { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { year: "numeric", month: "long", day: "numeric" };
  return new Intl.DateTimeFormat("ko-KR", options).format(date);
}

function formatMonthKorean(date) {
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long" }).format(date);
}

function parseKeywords(value) {
  const seen = new Set();
  return value
    .split(/[\n,;]+/)
    .map((keyword) => normalizeDisplayText(keyword))
    .filter(Boolean)
    .filter((keyword) => {
      const normalized = keyword.toLocaleLowerCase("ko-KR");
      if (seen.has(normalized)) return false;
      seen.add(normalized);
      return true;
    });
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function keywordMatches(text, keyword) {
  const normalizedText = normalizeDisplayText(text).toLocaleLowerCase("ko-KR");
  const normalizedKeyword = normalizeDisplayText(keyword).toLocaleLowerCase("ko-KR");

  if (/^[a-z0-9+#._-]+$/i.test(keyword)) {
    const escaped = escapeRegExp(normalizedKeyword);
    const pattern = new RegExp(`(^|[^a-z0-9])${escaped}($|[^a-z0-9])`, "i");
    return pattern.test(normalizedText);
  }
  return normalizedText.includes(normalizedKeyword);
}

function articleMatches(article, keywords) {
  if (keywords.length === 0) return [];
  return keywords.filter((keyword) => keywordMatches(article.search_text, keyword));
}

async function fetchJson(url, allowNotFound = false) {
  const response = await fetch(url, { cache: "no-cache" });
  if (allowNotFound && response.status === 404) return null;
  if (!response.ok) throw new Error(`${url} 요청 실패 (${response.status})`);
  return response.json();
}

function createEmptyState(message, className = "empty-state") {
  const node = document.createElement("div");
  node.className = className;
  node.textContent = message;
  return node;
}

function renderKeywordChips() {
  elements.keywordChips.replaceChildren();
  if (state.keywords.length === 0) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = "전체 보도자료";
    elements.keywordChips.append(chip);
    return;
  }

  state.keywords.forEach((keyword) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = keyword;
    elements.keywordChips.append(chip);
  });
}

function loadSavedKeywords() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEYWORD_STORAGE_KEY));
    if (Array.isArray(saved)) return saved.filter((item) => typeof item === "string");
  } catch (error) {
    console.warn("저장된 키워드를 읽지 못했습니다.", error);
  }
  return state.config.default_keywords || [];
}

function saveKeywords() {
  localStorage.setItem(KEYWORD_STORAGE_KEY, JSON.stringify(state.keywords));
}

function countMatched() {
  let total = 0;
  let modified = 0;
  state.matchedByDate.forEach((articles) => {
    total += articles.length;
    modified += articles.filter((article) => article.is_modified).length;
  });
  return { total, modified };
}

function applyAggregation() {
  const grouped = new Map();
  state.monthArticles.forEach((article) => {
    const matchedKeywords = state.keywords.length === 0 ? [] : articleMatches(article, state.keywords);
    if (state.keywords.length > 0 && matchedKeywords.length === 0) return;

    const date = article.date || article.publish_date;
    if (!date) return;
    if (!grouped.has(date)) grouped.set(date, []);
    grouped.get(date).push({ ...article, matchedKeywords });
  });

  state.matchedByDate = grouped;
  selectReasonableDate();
  renderKeywordChips();
  renderCalendar();
  renderSelectedDateList();
}

function selectReasonableDate() {
  const currentMonth = monthKey(state.currentDate);
  if (state.selectedDate && state.selectedDate.startsWith(currentMonth)) return;

  const todayKey = toDateKey(new Date());
  if (currentMonth === todayKey.slice(0, 7)) {
    state.selectedDate = todayKey;
    return;
  }

  const firstMatched = [...state.matchedByDate.keys()].sort()[0];
  state.selectedDate = firstMatched || `${currentMonth}-01`;
}

function calendarCell(dateNumber, currentMonthKey, todayKey) {
  const dateKey = `${currentMonthKey}-${pad2(dateNumber)}`;
  const articles = state.matchedByDate.get(dateKey) || [];
  const modifiedCount = articles.filter((article) => article.is_modified).length;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "calendar-cell";
  button.setAttribute("role", "gridcell");
  button.dataset.date = dateKey;
  button.setAttribute(
    "aria-label",
    `${formatDateKorean(`${dateKey}T00:00:00+09:00`)}: ${articles.length}건${modifiedCount ? `, 수정본 ${modifiedCount}건` : ""}`,
  );

  if (dateKey === todayKey) button.classList.add("today");
  if (dateKey === state.selectedDate) button.classList.add("selected");

  const inner = document.createElement("span");
  inner.className = "calendar-cell-inner";

  const dayNumber = document.createElement("span");
  dayNumber.className = "calendar-day-number";
  dayNumber.textContent = String(dateNumber);

  const count = document.createElement("span");
  count.className = "calendar-count";
  if (modifiedCount > 0) count.classList.add("has-modified");
  count.textContent = `${articles.length}건${modifiedCount > 0 ? ` (${modifiedCount}건)` : ""}`;

  inner.append(dayNumber, count);
  button.append(inner);
  button.addEventListener("click", () => {
    state.selectedDate = dateKey;
    renderCalendar();
    renderSelectedDateList();
  });
  return button;
}

function renderCalendar() {
  const year = state.currentDate.getFullYear();
  const month = state.currentDate.getMonth();
  const currentMonthKey = `${year}-${pad2(month + 1)}`;
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const totalCells = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;
  const todayKey = toDateKey(new Date());

  elements.monthTitle.textContent = formatMonthKorean(state.currentDate);
  elements.calendarGrid.replaceChildren();

  for (let index = 0; index < totalCells; index += 1) {
    const dateNumber = index - firstWeekday + 1;
    if (dateNumber < 1 || dateNumber > daysInMonth) {
      const empty = document.createElement("div");
      empty.className = "calendar-cell empty";
      empty.setAttribute("role", "gridcell");
      empty.setAttribute("aria-hidden", "true");
      elements.calendarGrid.append(empty);
    } else {
      elements.calendarGrid.append(calendarCell(dateNumber, currentMonthKey, todayKey));
    }
  }

  const { total, modified } = countMatched();
  elements.monthSummary.textContent = `${total}건${modified > 0 ? ` (${modified}건)` : ""}`;
}

function articleSortValue(article) {
  return String(article.modified_at || article.approved_at || article.publish_date || article.date || "");
}

function renderSelectedDateList() {
  selectReasonableDate();
  const articles = [...(state.matchedByDate.get(state.selectedDate) || [])]
    .sort((left, right) => articleSortValue(right).localeCompare(articleSortValue(left)));
  const modifiedCount = articles.filter((article) => article.is_modified).length;
  const parsedDate = parseDateKey(state.selectedDate);

  elements.selectedDateHeading.textContent = `${formatDateKorean(parsedDate)} 보도자료`;
  elements.selectedDateSummary.textContent = `${articles.length}건${modifiedCount > 0 ? ` (${modifiedCount}건)` : ""}`;
  elements.articleList.replaceChildren();
  elements.articleList.scrollTop = 0;

  if (articles.length === 0) {
    const message = state.keywords.length === 0
      ? "이 날짜에 저장된 보도자료가 없습니다."
      : "이 날짜에 현재 키워드와 일치하는 보도자료가 없습니다.";
    elements.articleList.append(createEmptyState(message));
    return;
  }

  articles.forEach((article) => {
    const fragment = elements.articleCardTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".article-card");
    const topLine = fragment.querySelector(".article-card-topline");
    const title = fragment.querySelector(".article-card-title");
    const summary = fragment.querySelector(".article-card-summary");
    const keywords = fragment.querySelector(".article-card-keywords");
    const linkHint = fragment.querySelector(".article-card-link-hint");

    const originalUrl = safeExternalUrl(article.original_url || "");
    if (originalUrl) {
      card.href = originalUrl;
      card.setAttribute("aria-label", `${article.title} 원문을 새 탭에서 열기`);
    } else {
      card.classList.add("is-unavailable");
      card.setAttribute("aria-disabled", "true");
      card.removeAttribute("target");
      card.addEventListener("click", (event) => event.preventDefault());
      linkHint.textContent = "원문 링크 없음";
    }

    const statusText = article.is_modified ? ` · 수정본(변경번호 ${article.modify_id})` : "";
    const dateValue = article.approved_at || article.publish_date || article.date;
    topLine.textContent = `${article.ministry || "기관 미상"} · ${formatDateKorean(dateValue, true)}${statusText}`;
    title.textContent = article.title || "제목 없음";
    summary.textContent = article.summary || "요약 없음";
    keywords.textContent = article.matchedKeywords?.length
      ? `일치 키워드: ${article.matchedKeywords.join(", ")}`
      : "전체 보기";

    elements.articleList.append(fragment);
  });
}

async function loadMonth() {
  const key = monthKey(state.currentDate);
  const [year, month] = key.split("-");
  elements.articleList.replaceChildren(createEmptyState("월별 데이터를 불러오는 중입니다.", "loading-state"));

  try {
    const payload = await fetchJson(`${DATA_ROOT}/${year}/${month}/index.json`, true);
    state.monthArticles = Array.isArray(payload?.articles)
      ? payload.articles.map(normalizeArticle)
      : [];
    applyAggregation();
  } catch (error) {
    console.error(error);
    state.monthArticles = [];
    state.matchedByDate = new Map();
    renderCalendar();
    elements.articleList.replaceChildren(createEmptyState("월별 데이터를 불러오지 못했습니다.", "error-state"));
  }
}

function reaggregateFromInput() {
  state.keywords = parseKeywords(elements.keywordInput.value);
  elements.keywordInput.value = state.keywords.join(", ");
  saveKeywords();
  applyAggregation();
}

async function moveMonth(offset) {
  state.currentDate = new Date(state.currentDate.getFullYear(), state.currentDate.getMonth() + offset, 1);
  state.selectedDate = null;
  await loadMonth();
}

function bindEvents() {
  elements.reaggregateButton.addEventListener("click", reaggregateFromInput);
  elements.resetKeywordsButton.addEventListener("click", () => {
    state.keywords = [...(state.config.default_keywords || [])];
    elements.keywordInput.value = state.keywords.join(", ");
    saveKeywords();
    applyAggregation();
  });

  elements.keywordInput.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") reaggregateFromInput();
  });

  elements.previousMonthButton.addEventListener("click", () => moveMonth(-1));
  elements.nextMonthButton.addEventListener("click", () => moveMonth(1));
  elements.todayButton.addEventListener("click", async () => {
    state.currentDate = new Date();
    state.selectedDate = toDateKey(new Date());
    await loadMonth();
  });
}

function cacheElements() {
  Object.assign(elements, {
    siteTitle: byId("site-title"),
    lastUpdated: byId("last-updated"),
    datasetSummary: byId("dataset-summary"),
    keywordInput: byId("keyword-input"),
    keywordChips: byId("keyword-chips"),
    reaggregateButton: byId("reaggregate-button"),
    resetKeywordsButton: byId("reset-keywords-button"),
    previousMonthButton: byId("previous-month-button"),
    nextMonthButton: byId("next-month-button"),
    todayButton: byId("today-button"),
    monthTitle: byId("month-title"),
    monthSummary: byId("month-summary"),
    calendarGrid: byId("calendar-grid"),
    selectedDateHeading: byId("selected-date-heading"),
    selectedDateSummary: byId("selected-date-summary"),
    articleList: byId("article-list"),
    articleCardTemplate: byId("article-card-template"),
    sourceListLink: byId("source-list-link"),
    copyrightLink: byId("copyright-link"),
  });
}

async function initialize() {
  cacheElements();
  try {
    [state.config, state.manifest] = await Promise.all([
      fetchJson(`${DATA_ROOT}/config.json`),
      fetchJson(`${DATA_ROOT}/manifest.json`),
    ]);

    const siteTitle = normalizeDisplayText(state.config.site_title || "정책브리핑 보도자료 대시보드");
    document.title = siteTitle;
    elements.siteTitle.textContent = siteTitle;
    elements.sourceListLink.href = safeExternalUrl(state.config.source_list_url);
    elements.copyrightLink.href = safeExternalUrl(state.config.copyright_policy_url);
    elements.lastUpdated.textContent = state.manifest.last_updated
      ? formatDateKorean(state.manifest.last_updated, true)
      : "수집 전";
    elements.datasetSummary.textContent = `저장 ${state.manifest.article_count || 0}건 · ${state.manifest.available_months?.length || 0}개월`;

    state.keywords = loadSavedKeywords();
    elements.keywordInput.value = state.keywords.join(", ");
    state.selectedDate = toDateKey(new Date());

    bindEvents();
    renderKeywordChips();
    await loadMonth();
  } catch (error) {
    console.error(error);
    elements.articleList.replaceChildren(
      createEmptyState("대시보드 설정을 불러오지 못했습니다. GitHub Pages 배포 상태를 확인하세요.", "error-state"),
    );
  }
}

document.addEventListener("DOMContentLoaded", initialize);
