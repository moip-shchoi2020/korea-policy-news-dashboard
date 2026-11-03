"use strict";

// Telegram 정기 브리핑과 대시보드의 상위 중요도 표시 기준을 일치시킨다.
// 매우 중요·중요 자료는 사용자가 입력한 키워드와 일치하지 않더라도 항상 표시한다.
const DASHBOARD_ALWAYS_VISIBLE_LEVELS = new Set(["critical", "important"]);

function isDashboardPriorityArticle(article) {
  return DASHBOARD_ALWAYS_VISIBLE_LEVELS.has(article.ip_relevance?.level || "");
}

applyAggregation = function applyAggregationWithPriority() {
  const grouped = new Map();

  state.monthArticles.forEach((article) => {
    const matchedKeywords = state.keywords.length === 0
      ? []
      : articleMatches(article, state.keywords);
    const includedByPriority = isDashboardPriorityArticle(article) && matchedKeywords.length === 0;

    if (state.keywords.length > 0 && matchedKeywords.length === 0 && !includedByPriority) {
      return;
    }

    const date = article.date || article.publish_date;
    if (!date) return;
    if (!grouped.has(date)) grouped.set(date, []);
    grouped.get(date).push({
      ...article,
      matchedKeywords,
      includedByPriority,
    });
  });

  state.matchedByDate = grouped;
  selectReasonableDate();
  renderKeywordChips();
  renderCalendar();
  renderSelectedDateList();
};

const renderSelectedDateListBase = renderSelectedDateList;
renderSelectedDateList = function renderSelectedDateListWithPriorityReason() {
  renderSelectedDateListBase();

  const articles = [...(state.matchedByDate.get(state.selectedDate) || [])].sort(compareArticles);
  const cards = elements.articleList.querySelectorAll(".article-card");
  cards.forEach((card, index) => {
    const article = articles[index];
    if (!article?.includedByPriority) return;
    const keywordLabel = card.querySelector(".article-card-keywords");
    if (keywordLabel) keywordLabel.textContent = "중요도 우선 표시 · 텔레그램 발송 기준";
  });
};
