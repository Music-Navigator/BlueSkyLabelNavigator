(() => {
  "use strict";

  const MAX_RESULTS = 100;
  const INDEX_URL = "assets/search/search-index.json";

  function normalize(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLocaleLowerCase("ja")
      .replace(/\s+/g, " ")
      .trim();
  }

  function queryWords(value) {
    return normalize(value).split(" ").filter(Boolean);
  }

  function matches(item, words) {
    const searchable = normalize(item.k);
    return words.every((word) => searchable.includes(word));
  }

  function makeResult(item) {
    const row = document.createElement("li");
    row.className = "search-result-item";

    const kind = document.createElement("span");
    kind.className = "search-result-kind";
    kind.textContent = item.t === "composer" ? "作曲家" : "作品";

    const link = document.createElement("a");
    link.href = item.u;
    link.textContent = item.n;
    link.dataset.track = "internal";
    link.dataset.trackLabel = `search-${item.t}`;

    row.append(kind);
    if (item.c) {
      const composer = document.createElement("span");
      composer.className = "search-result-composer";
      composer.textContent = item.c;
      row.append(composer);
    }
    row.append(link);
    return row;
  }

  async function run() {
    const form = document.querySelector("[data-search-form]");
    const input = document.querySelector("[data-search-input]");
    const status = document.querySelector("[data-search-status]");
    const list = document.querySelector("[data-search-results]");
    if (!form || !input || !status || !list) return;

    const query = new URLSearchParams(location.search).get("q") || "";
    input.value = query;
    const words = queryWords(query);
    if (!words.length) {
      status.textContent = "検索語を入力してください。";
      return;
    }

    status.textContent = "検索しています…";
    try {
      let data = window.BLUE_SKY_SEARCH_INDEX;
      if (!data) {
        const response = await fetch(INDEX_URL, { credentials: "same-origin" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        data = await response.json();
      }
      if (!data || !Array.isArray(data.items)) throw new Error("invalid index");

      const results = data.items.filter((item) => matches(item, words));
      document.title = `${query}の検索結果｜BlueSkyLabel Navigator`;

      if (!results.length) {
        status.textContent = `「${query}」に一致する項目はありませんでした。`;
        return;
      }
      if (results.length > MAX_RESULTS) {
        status.textContent = `「${query}」の検索結果は${results.length}件です。結果が多すぎるため、キーワードを追加して絞り込んでください。`;
        return;
      }

      status.textContent = `「${query}」の検索結果：${results.length}件`;
      const fragment = document.createDocumentFragment();
      results.forEach((item) => fragment.append(makeResult(item)));
      list.append(fragment);
    } catch (error) {
      console.error("Search index could not be loaded", error);
      status.textContent = "検索データを読み込めませんでした。時間をおいてもう一度お試しください。";
    }
  }

  document.addEventListener("DOMContentLoaded", run);
})();
