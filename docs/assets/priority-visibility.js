"use strict";

// 대시보드와 Telegram이 docs/data/config.json의 동일한 키워드·유사어
// 사전을 사용하도록 한다. 화면에는 사용자가 입력한 대표 키워드를 표시하되,
// 실제 검색은 같은 그룹의 유사어까지 OR 조건으로 확장한다.
const baseKeywordMatches = keywordMatches;

function normalizeKeywordLookup(value) {
  return normalizeDisplayText(value).toLocaleLowerCase("ko-KR");
}

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
