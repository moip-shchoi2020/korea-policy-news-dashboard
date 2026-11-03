"use strict";

// 대시보드와 Telegram이 docs/data/config.json의 동일한 키워드·유사어
// 사전을 사용하도록 한다. 화면에는 사용자가 입력한 대표 키워드를 표시하되,
// 실제 검색은 같은 그룹의 유사어까지 OR 조건으로 확장한다.
const baseKeywordMatches = keywordMatches;
const baseLoadSavedKeywords = loadSavedKeywords;
const LEGACY_DEFAULT_KEYWORDS = ["AI", "정보화 사업", "시스템", "AX"];

function normalizeKeywordLookup(value) {
  return normalizeDisplayText(value).toLocaleLowerCase("ko-KR");
}

function sameKeywordSet(left, right) {
  const leftSet = new Set((Array.isArray(left) ? left : []).map(normalizeKeywordLookup).filter(Boolean));
  const rightSet = new Set((Array.isArray(right) ? right : []).map(normalizeKeywordLookup).filter(Boolean));
  return leftSet.size === rightSet.size && [...leftSet].every((item) => rightSet.has(item));
}

// 기존 브라우저에 이전 기본값이 localStorage로 저장돼 있으면 새 기본값인
// '보안'이 보이지 않는다. 사용자가 별도로 수정하지 않은 이전 기본값만
// 새 기본값으로 한 차례 승격하고, 사용자 지정 키워드는 그대로 보존한다.
loadSavedKeywords = function loadSavedKeywordsWithCurrentDefaults() {
  const saved = baseLoadSavedKeywords();
  const defaults = Array.isArray(state.config?.default_keywords)
    ? state.config.default_keywords.map(normalizeDisplayText).filter(Boolean)
    : [];

  if (defaults.length > 0 && sameKeywordSet(saved, LEGACY_DEFAULT_KEYWORDS)) {
    try {
      localStorage.setItem(KEYWORD_STORAGE_KEY, JSON.stringify(defaults));
    } catch (error) {
      console.warn("새 기본 키워드를 저장하지 못했습니다.", error);
    }
    return defaults;
  }
  return saved;
};

function keywordVariants(keyword) {
  const normalizedKeyword = normalizeKeywordLookup(keyword);
  const aliases = state.config?.keyword_aliases;
  if (!normalizedKeyword || !aliases || typeof aliases !== "object") {
    return [keyword];
  }

  for (const [canonical, rawAliases] of Object.entries(aliases)) {
    const group = [canonical, ...(Array.isArray(rawAliases) ? rawAliases : [])]
      .map(normalizeDisplayText)
      .filter(Boolean);
    if (!group.some((term) => normalizeKeywordLookup(term) === normalizedKeyword)) {
      continue;
    }

    const seen = new Set();
    return group.filter((term) => {
      const key = normalizeKeywordLookup(term);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  return [keyword];
}

keywordMatches = function keywordMatchesWithAliases(text, keyword) {
  return keywordVariants(keyword).some((variant) => baseKeywordMatches(text, variant));
};

articleMatches = function articleMatchesWithAliases(article, keywords) {
  if (keywords.length === 0) return [];
  return keywords.filter((keyword) => keywordMatches(article.search_text, keyword));
};
