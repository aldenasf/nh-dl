(() => {
  "use strict";

  const appEl = document.getElementById("app");
  const searchWrap = document.getElementById("search-wrap");
  const searchForm = document.getElementById("search-form");
  const searchInput = document.getElementById("search-input");
  const searchClear = document.getElementById("search-clear");
  const searchDropdown = document.getElementById("search-dropdown");
  const favNavCount = document.getElementById("fav-nav-count");
  const randomBtn = document.getElementById("random-btn");
  const toastEl = document.getElementById("toast");

  const store = {
    galleries: [],
    byKey: new Map(),
    details: new Map(),
    outputDir: "",
    state: {
      library_dir: null,
      bookmarks: [],
      progress: {},
      reader_prefs: { mode: "vertical", fit: "width" },
      search_history: [],
    },
    sort: "downloaded",
    sortDir: "desc",
    perPage: 25,
    page: 1,
    observer: null,
    keyHandler: null,
    progressTimer: null,
    toastTimer: null,
    dropdownOpen: false,
    dropdownItems: [],
    dropdownIndex: -1,
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function showToast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.remove("hidden");
    clearTimeout(store.toastTimer);
    store.toastTimer = setTimeout(() => toastEl.classList.add("hidden"), 2400);
  }

  function bookmarkSet() {
    return new Set(store.state.bookmarks || []);
  }

  function updateFavCount() {
    favNavCount.textContent = String((store.state.bookmarks || []).length);
  }

  async function apiJson(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
      const err = await res.text().catch(() => res.statusText);
      throw new Error(err || `HTTP ${res.status}`);
    }
    return res.json();
  }

  async function patchState(payload) {
    const updated = await apiJson("/api/state", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    store.state = updated;
    updateFavCount();
    return updated;
  }

  function saveProgressDebounced(key, page) {
    if (!store.state.progress) store.state.progress = {};
    store.state.progress[key] = { page, updated_at: new Date().toISOString() };
    clearTimeout(store.progressTimer);
    store.progressTimer = setTimeout(() => {
      patchState({ progress: { [key]: { page } } }).catch(() => {});
    }, 350);
  }

  function cleanupReader() {
    if (store.observer) {
      store.observer.disconnect();
      store.observer = null;
    }
    if (store.keyHandler) {
      window.removeEventListener("keydown", store.keyHandler);
      store.keyHandler = null;
    }
    appEl.classList.remove("reader-mode");
  }

  function parseRoute() {
    const raw = (window.location.hash || "#/").slice(1);
    const [pathPart, queryPart = ""] = raw.split("?");
    const segments = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
    const params = new URLSearchParams(queryPart);
    return { segments, params };
  }

  function buildHash(path, paramsObj = {}) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(paramsObj)) {
      if (v !== undefined && v !== null && String(v).trim() !== "") {
        qs.set(k, String(v).trim());
      }
    }
    const query = qs.toString();
    return `#${path}${query ? `?${query}` : ""}`;
  }

  function updateActiveNav(routeName) {
    document.querySelectorAll(".nav-links a[data-nav]").forEach((a) => {
      a.classList.toggle("active", a.dataset.nav === routeName);
    });
  }

  function computeFacetCounts(field) {
    const counts = new Map();
    for (const g of store.galleries) {
      for (const val of g[field] || []) {
        counts.set(val, (counts.get(val) || 0) + 1);
      }
    }
    return counts;
  }

  const FACET_PREFIXES = {
    tag: { field: "tags", badge: "TAG", cls: "sd-badge-tag" },
    artist: { field: "artists", badge: "ARTIST", cls: "sd-badge-artist" },
    parody: { field: "parodies", badge: "PARODY", cls: "sd-badge-parody" },
    character: { field: "characters", badge: "CHARACTER", cls: "sd-badge-character" },
    group: { field: "groups", badge: "GROUP", cls: "sd-badge-group" },
    language: { field: "languages", badge: "LANGUAGE", cls: "sd-badge-language" },
    lang: { field: "languages", badge: "LANGUAGE", cls: "sd-badge-language" },
    category: { field: "categories", badge: "CATEGORY", cls: "sd-badge-category" },
  };

  const SYNTAX_HINTS = [
    { label: "tag:...", insert: "tag:", cursorBack: 0, desc: "Filter by tag" },
    { label: "artist:...", insert: "artist:", cursorBack: 0, desc: "Filter by artist" },
    { label: "parody:...", insert: "parody:", cursorBack: 0, desc: "Filter by parody" },
    { label: "character:...", insert: "character:", cursorBack: 0, desc: "Filter by character" },
    { label: "group:...", insert: "group:", cursorBack: 0, desc: "Filter by group" },
    { label: "language:...", insert: "language:", cursorBack: 0, desc: "Filter by language" },
    { label: "category:...", insert: "category:", cursorBack: 0, desc: "Filter by category" },
    { label: "pages:N", insert: "pages:", cursorBack: 0, desc: "Filter by page count" },
    { label: "uploaded:Nd", insert: "uploaded:", cursorBack: 0, desc: "Filter by download date" },
    { label: 'title:"..."', insert: 'title:""', cursorBack: 1, desc: "Search title text" },
    { label: 'jtitle:"..."', insert: 'jtitle:""', cursorBack: 1, desc: "Search Japanese title" },
  ];

  function tokenizeQuery(str) {
    const tokens = [];
    let i = 0;
    const n = str.length;
    while (i < n) {
      while (i < n && str[i] === " ") i++;
      if (i >= n) break;
      const start = i;
      let inQuotes = false;
      while (i < n) {
        const ch = str[i];
        if (ch === '"') {
          inQuotes = !inQuotes;
          i++;
        } else if (ch === " " && !inQuotes) {
          break;
        } else {
          i++;
        }
      }
      tokens.push({ raw: str.slice(start, i), start, end: i });
    }
    return tokens;
  }

  function unwrapQuotes(val) {
    if (val.startsWith('"') && val.endsWith('"') && val.length >= 2) {
      return val.slice(1, -1);
    }
    if (val.startsWith('"')) {
      return val.slice(1);
    }
    return val;
  }

  function parseToken(raw) {
    const negated = raw.startsWith("-") && raw.length > 1;
    const body = negated ? raw.slice(1) : raw;
    const colonIdx = body.indexOf(":");
    if (colonIdx > 0) {
      const prefix = body.slice(0, colonIdx).toLowerCase();
      const rawVal = body.slice(colonIdx + 1);
      const hasQuotes = rawVal.includes('"');
      const value = unwrapQuotes(rawVal);
      return { raw, negated, prefix, rawVal, value, hasQuotes };
    }
    return { raw, negated, prefix: null, rawVal: body, value: unwrapQuotes(body), hasQuotes: body.includes('"') };
  }

  function getTokenAtCursor(str, cursorPos) {
    const tokens = tokenizeQuery(str);
    for (const tok of tokens) {
      if (cursorPos >= tok.start && cursorPos <= tok.end) {
        return tok;
      }
    }
    return null;
  }

  function matchNumericPages(pageCount, expr) {
    const s = expr.trim();
    if (!s) return true;
    const rangeMatch = s.match(/^(\d+)\s*-\s*(\d+)$/);
    if (rangeMatch) {
      const lo = parseInt(rangeMatch[1], 10);
      const hi = parseInt(rangeMatch[2], 10);
      return pageCount >= lo && pageCount <= hi;
    }
    const cmpMatch = s.match(/^(>=|<=|>|<|=)?\s*(\d+)$/);
    if (!cmpMatch) return false;
    const op = cmpMatch[1] || "=";
    const target = parseInt(cmpMatch[2], 10);
    if (op === ">") return pageCount > target;
    if (op === "<") return pageCount < target;
    if (op === ">=") return pageCount >= target;
    if (op === "<=") return pageCount <= target;
    return pageCount === target;
  }

  function matchUploadedDays(downloadedAt, expr) {
    const m = expr.trim().toLowerCase().match(/^(\d+)\s*d?$/);
    if (!m) return true;
    const days = parseInt(m[1], 10);
    if (!downloadedAt) return false;
    const ts = Date.parse(downloadedAt);
    if (Number.isNaN(ts)) return false;
    return Date.now() - ts <= days * 86400000;
  }

  function matchesToken(g, parsed) {
    const val = parsed.value.trim().toLowerCase();
    if (parsed.prefix) {
      if (!val) return true; // Incomplete prefix (e.g. tag: or title:"") shouldn't wipe results
      const facetSpec = FACET_PREFIXES[parsed.prefix];
      if (facetSpec) {
        const list = (g[facetSpec.field] || []).map((x) => x.toLowerCase());
        return list.some((item) => item.includes(val));
      }
      if (parsed.prefix === "title") {
        const hay = `${g.display_title || ""} ${g.title?.english || ""} ${g.title?.pretty || ""}`.toLowerCase();
        return hay.includes(val);
      }
      if (parsed.prefix === "jtitle") {
        return (g.title?.japanese || "").toLowerCase().includes(val);
      }
      if (parsed.prefix === "pages") {
        return matchNumericPages(g.page_count || 0, val);
      }
      if (parsed.prefix === "uploaded") {
        return matchUploadedDays(g.downloaded_at, val);
      }
    }

    if (!val) return true;
    if (val.startsWith("#") && /^\d+$/.test(val.slice(1))) {
      return String(g.id || "") === val.slice(1);
    }
    const hay = [
      g.id ? String(g.id) : "",
      g.display_title,
      g.title?.english || "",
      g.title?.japanese || "",
      ...(g.artists || []),
      ...(g.parodies || []),
      ...(g.tags || []),
      ...(g.characters || []),
      ...(g.groups || []),
      ...(g.languages || []),
      ...(g.categories || []),
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(val);
  }

  function matchesSearch(g, query) {
    if (!query || !query.trim()) return true;
    const tokens = tokenizeQuery(query);
    for (const tok of tokens) {
      const parsed = parseToken(tok.raw);
      const hit = matchesToken(g, parsed);
      if (parsed.negated) {
        if (parsed.value.trim() && hit) return false;
      } else if (!hit) {
        return false;
      }
    }
    return true;
  }

  function filterAndSortGalleries({ favoritesOnly, params }) {
    const bmarks = bookmarkSet();
    const q = params.get("q") || "";
    const facetFields = ["tag", "artist", "parody", "character", "group", "language", "category"];
    const fieldPlural = {
      tag: "tags",
      artist: "artists",
      parody: "parodies",
      character: "characters",
      group: "groups",
      language: "languages",
      category: "categories",
    };

    let list = store.galleries.filter((g) => {
      if (favoritesOnly && !bmarks.has(g.key)) return false;
      for (const f of facetFields) {
        const expected = params.get(f);
        if (expected) {
          const vals = (g[fieldPlural[f]] || []).map((x) => x.toLowerCase());
          if (!vals.includes(expected.toLowerCase())) return false;
        }
      }
      return matchesSearch(g, q);
    });

    const prog = store.state.progress || {};
    const dir = store.sortDir === "asc" ? 1 : -1;
    list = list.slice();
    if (store.sort === "title") {
      list.sort((a, b) => dir * a.display_title.localeCompare(b.display_title));
    } else if (store.sort === "id") {
      list.sort((a, b) => dir * ((a.id || 0) - (b.id || 0)));
    } else if (store.sort === "pages") {
      list.sort((a, b) => dir * ((a.page_count || 0) - (b.page_count || 0)));
    } else if (store.sort === "recent") {
      list.sort((a, b) => {
        const ta = prog[a.key]?.updated_at || "";
        const tb = prog[b.key]?.updated_at || "";
        if (!ta && !tb) return 0;
        if (!ta) return 1;
        if (!tb) return -1;
        return dir * ta.localeCompare(tb);
      });
    } else {
      list.sort((a, b) => dir * (a.downloaded_at || "").localeCompare(b.downloaded_at || ""));
    }

    return list;
  }

  function primaryLanguage(langs) {
    if (!langs || !langs.length) return "";
    const filtered = langs.filter((l) => !["translated", "rewrite"].includes(l.toLowerCase()));
    return (filtered[0] || langs[0] || "").toLowerCase();
  }

  function svgEl(tag, attrs = {}) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) {
      node.setAttribute(k, String(v));
    }
    return node;
  }

  function createFlagNode(langs) {
    const lang = primaryLanguage(langs);
    if (!lang) return null;

    if (lang === "english") {
      const svg = svgEl("svg", { viewBox: "0 0 60 36", class: "card-flag", "aria-label": "English" });
      svg.appendChild(svgEl("rect", { width: 60, height: 36, fill: "#012169" }));
      svg.appendChild(svgEl("path", { d: "M0,0 L60,36 M60,0 L0,36", stroke: "#fff", "stroke-width": 7 }));
      svg.appendChild(svgEl("path", { d: "M0,0 L60,36 M60,0 L0,36", stroke: "#C8102E", "stroke-width": 4 }));
      svg.appendChild(svgEl("path", { d: "M30,0 V36 M0,18 H60", stroke: "#fff", "stroke-width": 11 }));
      svg.appendChild(svgEl("path", { d: "M30,0 V36 M0,18 H60", stroke: "#C8102E", "stroke-width": 6.5 }));
      return svg;
    }

    if (lang === "japanese") {
      const svg = svgEl("svg", { viewBox: "0 0 60 40", class: "card-flag", "aria-label": "Japanese" });
      svg.appendChild(svgEl("rect", { width: 60, height: 40, fill: "#ffffff" }));
      svg.appendChild(svgEl("circle", { cx: 30, cy: 20, r: 11.5, fill: "#bc002d" }));
      return svg;
    }

    if (lang === "chinese") {
      const svg = svgEl("svg", { viewBox: "0 0 60 40", class: "card-flag", "aria-label": "Chinese" });
      svg.appendChild(svgEl("rect", { width: 60, height: 40, fill: "#de2910" }));
      svg.appendChild(svgEl("polygon", { points: "12,5 13.8,10.5 19.5,10.5 14.9,13.9 16.6,19.4 12,16 7.4,19.4 9.1,13.9 4.5,10.5 10.2,10.5", fill: "#ffde00" }));
      svg.appendChild(svgEl("circle", { cx: 23, cy: 6, r: 1.5, fill: "#ffde00" }));
      svg.appendChild(svgEl("circle", { cx: 26, cy: 10, r: 1.5, fill: "#ffde00" }));
      svg.appendChild(svgEl("circle", { cx: 26, cy: 15, r: 1.5, fill: "#ffde00" }));
      svg.appendChild(svgEl("circle", { cx: 23, cy: 19, r: 1.5, fill: "#ffde00" }));
      return svg;
    }

    if (lang === "korean") {
      const svg = svgEl("svg", { viewBox: "0 0 60 40", class: "card-flag", "aria-label": "Korean" });
      svg.appendChild(svgEl("rect", { width: 60, height: 40, fill: "#ffffff" }));
      svg.appendChild(svgEl("path", { d: "M21,20 A9,9 0 0,1 39,20 Z", fill: "#cd2e3a" }));
      svg.appendChild(svgEl("path", { d: "M21,20 A9,9 0 0,0 39,20 Z", fill: "#0047a0" }));
      return svg;
    }

    return el("span", "card-flag-text", lang.slice(0, 2).toUpperCase());
  }

  function renderGalleryCard(g) {
    const card = el("a", "gallery-card");
    card.href = `#/g/${encodeURIComponent(g.key)}`;

    const cardTitle = g.title?.english || g.title?.japanese || g.display_title;

    const coverWrap = el("div", "card-cover-wrap");
    if (g.cover_url) {
      const img = el("img");
      img.src = g.cover_url;
      img.alt = cardTitle;
      img.loading = "lazy";
      coverWrap.appendChild(img);
    } else {
      const ph = el("div", "pdf-placeholder");
      ph.appendChild(el("span", "", "PDF"));
      coverWrap.appendChild(ph);
    }

    if (bookmarkSet().has(g.key)) {
      coverWrap.appendChild(el("span", "badge-fav", "★"));
    }

    const prog = store.state.progress?.[g.key];
    if (prog && g.page_count > 0) {
      const label = prog.page >= g.page_count ? "Read" : `${prog.page}/${g.page_count}`;
      coverWrap.appendChild(el("span", "badge-progress", label));
    } else if (g.page_count > 0) {
      coverWrap.appendChild(el("span", "badge-progress", `${g.page_count}p`));
    }

    const captionWrap = el("div", "card-caption-wrap");
    const caption = el("div", "card-caption");
    const flag = createFlagNode(g.languages);
    if (flag) caption.appendChild(flag);
    caption.appendChild(document.createTextNode(cardTitle));
    captionWrap.appendChild(caption);

    card.appendChild(coverWrap);
    card.appendChild(captionWrap);
    return card;
  }

  function renderPagination(totalItems, pageNum, basePath, params) {
    if (store.perPage <= 0) return null;
    const totalPages = Math.max(1, Math.ceil(totalItems / store.perPage));
    if (totalPages <= 1) return null;

    const nav = el("div", "pagination");
    const goPage = (p) => {
      const nextParams = Object.fromEntries(params.entries());
      nextParams.page = String(p);
      window.location.hash = buildHash(basePath, nextParams);
      window.scrollTo({ top: 0, behavior: "smooth" });
    };

    const prev = el("button", "page-btn", "‹");
    prev.disabled = pageNum <= 1;
    prev.addEventListener("click", () => goPage(pageNum - 1));
    nav.appendChild(prev);

    const start = Math.max(1, pageNum - 3);
    const end = Math.min(totalPages, pageNum + 3);
    for (let p = start; p <= end; p++) {
      const btn = el("button", `page-btn${p === pageNum ? " active" : ""}`, String(p));
      btn.addEventListener("click", () => goPage(p));
      nav.appendChild(btn);
    }

    const next = el("button", "page-btn", "›");
    next.disabled = pageNum >= totalPages;
    next.addEventListener("click", () => goPage(pageNum + 1));
    nav.appendChild(next);
    return nav;
  }

  function renderGridView({ favoritesOnly, params }) {
    cleanupReader();
    updateActiveNav(favoritesOnly ? "favorites" : "home");

    const basePath = favoritesOnly ? "/favorites" : "/";
    const q = params.get("q") || "";
    if (searchInput.value !== q) searchInput.value = q;
    syncClearBtn();

    const filtered = filterAndSortGalleries({ favoritesOnly, params });
    const totalPages = store.perPage > 0 ? Math.max(1, Math.ceil(filtered.length / store.perPage)) : 1;
    const reqPage = Math.max(1, Math.min(totalPages, parseInt(params.get("page") || "1", 10) || 1));

    const toolbar = el("div", "toolbar");
    const titleWrap = el("div", "toolbar-title");
    titleWrap.appendChild(el("h1", "toolbar-heading", favoritesOnly ? "Favorites" : "Library"));
    titleWrap.appendChild(el("span", "count-label", `(${filtered.length} galleries)`));

    for (const [k, v] of params.entries()) {
      if (k === "page" || !v) continue;
      const chip = el("span", "filter-chip", `${k}: ${v} `);
      const xBtn = el("button", "", "×");
      xBtn.title = "Clear filter";
      xBtn.addEventListener("click", () => {
        const next = Object.fromEntries(params.entries());
        delete next[k];
        delete next.page;
        window.location.hash = buildHash(basePath, next);
      });
      chip.appendChild(xBtn);
      titleWrap.appendChild(chip);
    }

    const controls = el("div", "toolbar-controls");
    const sortSel = el("select");
    sortSel.setAttribute("aria-label", "Sort field");
    [
      ["downloaded", "Sort: Downloaded"],
      ["recent", "Sort: Recently Read"],
      ["title", "Sort: Title"],
      ["id", "Sort: ID"],
      ["pages", "Sort: Pages"],
    ].forEach(([val, label]) => {
      const opt = el("option", "", label);
      opt.value = val;
      if (store.sort === val) opt.selected = true;
      sortSel.appendChild(opt);
    });
    sortSel.addEventListener("change", () => {
      store.sort = sortSel.value;
      renderCurrentRoute();
    });

    const dirSel = el("select");
    dirSel.setAttribute("aria-label", "Sort direction");
    [
      ["desc", "Descending"],
      ["asc", "Ascending"],
    ].forEach(([val, label]) => {
      const opt = el("option", "", label);
      opt.value = val;
      if (store.sortDir === val) opt.selected = true;
      dirSel.appendChild(opt);
    });
    dirSel.addEventListener("change", () => {
      store.sortDir = dirSel.value;
      renderCurrentRoute();
    });

    const sizeSel = el("select");
    [
      ["25", "25 / page"],
      ["50", "50 / page"],
      ["100", "100 / page"],
      ["0", "Show all"],
    ].forEach(([val, label]) => {
      const opt = el("option", "", label);
      opt.value = val;
      if (String(store.perPage) === val) opt.selected = true;
      sizeSel.appendChild(opt);
    });
    sizeSel.addEventListener("change", () => {
      store.perPage = parseInt(sizeSel.value, 10);
      renderCurrentRoute();
    });

    controls.appendChild(sortSel);
    controls.appendChild(dirSel);
    controls.appendChild(sizeSel);
    toolbar.appendChild(titleWrap);
    toolbar.appendChild(controls);

    appEl.innerHTML = "";
    appEl.appendChild(toolbar);

    if (!filtered.length) {
      const empty = el("div", "empty-state");
      empty.appendChild(el("h2", "", favoritesOnly ? "No bookmarked galleries yet" : "No galleries found"));
      empty.appendChild(
        el(
          "p",
          "",
          store.galleries.length
            ? "Try clearing your search or tag filters."
            : "No galleries found in the configured folder. Check Settings to choose or rescan your folder."
        )
      );
      if (!store.galleries.length) {
        const goSettings = el("a", "btn btn-primary", "Open Settings");
        goSettings.href = "#/settings";
        empty.appendChild(goSettings);
      }
      appEl.appendChild(empty);
      return;
    }

    const slice =
      store.perPage > 0
        ? filtered.slice((reqPage - 1) * store.perPage, reqPage * store.perPage)
        : filtered;

    const grid = el("div", "gallery-grid");
    slice.forEach((g) => grid.appendChild(renderGalleryCard(g)));
    appEl.appendChild(grid);

    const pag = renderPagination(filtered.length, reqPage, basePath, params);
    if (pag) appEl.appendChild(pag);
  }

  function renderDirectoryView(field, paramName, title) {
    cleanupReader();
    updateActiveNav(field);
    const counts = computeFacetCounts(field);
    const items = Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

    appEl.innerHTML = "";
    const toolbar = el("div", "toolbar");
    const tWrap = el("div", "toolbar-title");
    tWrap.appendChild(el("h1", "toolbar-heading", title));
    tWrap.appendChild(el("span", "count-label", `(${items.length})`));
    toolbar.appendChild(tWrap);
    appEl.appendChild(toolbar);

    const box = el("div", "dir-box");
    const filterInput = el("input", "dir-search");
    filterInput.type = "search";
    filterInput.placeholder = `Filter ${title.toLowerCase()}...`;

    const listEl = el("div", "pill-list");
    const drawPills = (needle) => {
      listEl.innerHTML = "";
      const q = needle.trim().toLowerCase();
      for (const [name, count] of items) {
        if (q && !name.toLowerCase().includes(q)) continue;
        const pill = el("a", "tag-pill");
        pill.href = buildHash("/", { [paramName]: name });
        pill.appendChild(el("span", "pill-name", name));
        pill.appendChild(el("span", "pill-count", String(count)));
        listEl.appendChild(pill);
      }
    };

    filterInput.addEventListener("input", () => drawPills(filterInput.value));
    drawPills("");

    box.appendChild(filterInput);
    box.appendChild(listEl);
    appEl.appendChild(box);
  }

  function makeTagRow(label, items, paramName, countsMap) {
    if (!items || !items.length) return null;
    const row = el("div", "meta-row");
    row.appendChild(el("span", "meta-label", `${label}:`));
    const list = el("div", "pill-list");
    for (const item of items) {
      const pill = el("a", "tag-pill");
      pill.href = buildHash("/", { [paramName]: item });
      pill.appendChild(el("span", "pill-name", item));
      pill.appendChild(el("span", "pill-count", String(countsMap.get(item) || 1)));
      list.appendChild(pill);
    }
    row.appendChild(list);
    return row;
  }

  async function ensureGalleryDetail(key) {
    if (store.details.has(key)) return store.details.get(key);
    const detail = await apiJson(`/api/galleries/${encodeURIComponent(key)}`);
    store.details.set(key, detail);
    return detail;
  }

  async function renderDetailView(key) {
    cleanupReader();
    updateActiveNav("");
    appEl.innerHTML = "";

    let detail;
    try {
      detail = await ensureGalleryDetail(key);
    } catch {
      const empty = el("div", "empty-state");
      empty.appendChild(el("h2", "", "Gallery not found"));
      const back = el("a", "btn btn-primary", "Back to Library");
      back.href = "#/";
      empty.appendChild(back);
      appEl.appendChild(empty);
      return;
    }

    const box = el("div", "detail-box");
    const coverLink = el("a", "detail-cover");
    coverLink.href = detail.has_images ? `#/read/${encodeURIComponent(key)}/1` : detail.pdf_url || "#/";
    if (detail.cover_url) {
      const img = el("img");
      img.src = detail.cover_url;
      img.alt = detail.display_title;
      coverLink.appendChild(img);
    } else {
      const ph = el("div", "pdf-placeholder");
      ph.appendChild(el("span", "", "PDF"));
      coverLink.appendChild(ph);
    }
    box.appendChild(coverLink);

    const infoCol = el("div");
    infoCol.appendChild(el("h1", "detail-title", detail.display_title));
    if (detail.title?.japanese && detail.title.japanese !== detail.display_title) {
      infoCol.appendChild(el("h2", "detail-subtitle", detail.title.japanese));
    }
    if (detail.id) {
      infoCol.appendChild(el("span", "detail-id", `#${detail.id}`));
    }

    const metaRows = el("div", "meta-rows");
    const facetSpecs = [
      ["Parodies", "parodies", "parody"],
      ["Characters", "characters", "character"],
      ["Tags", "tags", "tag"],
      ["Artists", "artists", "artist"],
      ["Groups", "groups", "group"],
      ["Languages", "languages", "language"],
      ["Categories", "categories", "category"],
    ];
    for (const [label, field, param] of facetSpecs) {
      const row = makeTagRow(label, detail[field], param, computeFacetCounts(field));
      if (row) metaRows.appendChild(row);
    }
    if (detail.page_count > 0) {
      const pRow = el("div", "meta-row");
      pRow.appendChild(el("span", "meta-label", "Pages:"));
      pRow.appendChild(el("span", "pill-name", String(detail.page_count)));
      metaRows.appendChild(pRow);
    }
    infoCol.appendChild(metaRows);

    const actions = el("div", "detail-actions");
    const prog = store.state.progress?.[key];
    if (detail.has_images) {
      const resumePage = prog && prog.page >= 1 && prog.page <= detail.pages.length ? prog.page : 1;
      const readBtn = el(
        "a",
        "btn btn-primary",
        resumePage > 1 ? `Resume (Page ${resumePage})` : "Start Reading"
      );
      readBtn.href = `#/read/${encodeURIComponent(key)}/${resumePage}`;
      actions.appendChild(readBtn);
    }

    const favBtn = el("button", "btn btn-secondary");
    const syncFavBtn = () => {
      const isFav = bookmarkSet().has(key);
      favBtn.textContent = isFav ? "★ Bookmarked" : "☆ Bookmark";
      favBtn.classList.toggle("bookmarked", isFav);
    };
    syncFavBtn();
    favBtn.addEventListener("click", async () => {
      await patchState({ toggle_bookmark: key });
      syncFavBtn();
    });
    actions.appendChild(favBtn);

    if (detail.pdf_url) {
      const pdfBtn = el("a", "btn btn-secondary", "Open PDF");
      pdfBtn.href = detail.pdf_url;
      pdfBtn.target = "_blank";
      pdfBtn.rel = "noopener";
      actions.appendChild(pdfBtn);
    }

    infoCol.appendChild(actions);
    box.appendChild(infoCol);
    appEl.appendChild(box);

    if (detail.pages && detail.pages.length) {
      const thumbSection = el("div", "thumb-section");
      const grid = el("div", "thumb-grid");
      for (const p of detail.pages) {
        const item = el("a", "thumb-item");
        item.href = `#/read/${encodeURIComponent(key)}/${p.num}`;
        const img = el("img");
        img.src = p.url;
        img.alt = `Page ${p.num}`;
        img.loading = "lazy";
        item.appendChild(img);
        item.appendChild(el("span", "thumb-num", String(p.num)));
        grid.appendChild(item);
      }
      thumbSection.appendChild(grid);
      appEl.appendChild(thumbSection);
    }
  }

  async function renderReaderView(key, pageParam) {
    cleanupReader();
    updateActiveNav("");
    appEl.classList.add("reader-mode");
    appEl.innerHTML = "";

    let detail;
    try {
      detail = await ensureGalleryDetail(key);
    } catch {
      window.location.hash = "#/";
      return;
    }

    if (!detail.pages || !detail.pages.length) {
      window.location.hash = `#/g/${encodeURIComponent(key)}`;
      return;
    }

    const total = detail.pages.length;
    let currentPage = Math.max(1, Math.min(total, parseInt(pageParam || "1", 10) || 1));
    const prefs = store.state.reader_prefs || { mode: "vertical", fit: "width" };

    const bar = el("div", "reader-bar");
    const leftGroup = el("div", "reader-group");
    const backLink = el("a", "reader-btn", "← Gallery");
    backLink.href = `#/g/${encodeURIComponent(key)}`;
    leftGroup.appendChild(backLink);
    leftGroup.appendChild(el("span", "reader-title", detail.display_title));

    const centerGroup = el("div", "reader-group");
    const prevBtn = el("button", "reader-btn", "‹ Prev");
    const pageSelect = el("select", "reader-select");
    for (let i = 1; i <= total; i++) {
      const opt = el("option", "", `Page ${i} / ${total}`);
      opt.value = String(i);
      pageSelect.appendChild(opt);
    }
    const nextBtn = el("button", "reader-btn", "Next ›");
    centerGroup.appendChild(prevBtn);
    centerGroup.appendChild(pageSelect);
    centerGroup.appendChild(nextBtn);

    const rightGroup = el("div", "reader-group");
    const modeBtn = el("button", "reader-btn");
    const fitSel = el("select", "reader-select");
    [
      ["width", "Fit Width"],
      ["height", "Fit Height"],
      ["original", "Original"],
    ].forEach(([val, label]) => {
      const opt = el("option", "", label);
      opt.value = val;
      if (prefs.fit === val) opt.selected = true;
      fitSel.appendChild(opt);
    });

    const favBtn = el("button", "reader-btn");
    const syncFav = () => {
      const on = bookmarkSet().has(key);
      favBtn.textContent = on ? "★ Saved" : "☆ Save";
      favBtn.classList.toggle("active", on);
    };
    syncFav();
    favBtn.addEventListener("click", async () => {
      await patchState({ toggle_bookmark: key });
      syncFav();
    });

    rightGroup.appendChild(modeBtn);
    rightGroup.appendChild(fitSel);
    rightGroup.appendChild(favBtn);

    bar.appendChild(leftGroup);
    bar.appendChild(centerGroup);
    bar.appendChild(rightGroup);
    appEl.appendChild(bar);

    const stage = el("div", `reader-stage fit-${prefs.fit || "width"}`);
    appEl.appendChild(stage);

    const syncHeaderControls = () => {
      modeBtn.textContent = prefs.mode === "vertical" ? "Mode: Vertical" : "Mode: Single";
      pageSelect.value = String(currentPage);
      prevBtn.disabled = currentPage <= 1;
      nextBtn.disabled = currentPage >= total;
    };

    const preloadAhead = (pageNum) => {
      [pageNum + 1, pageNum + 2].forEach((n) => {
        if (n >= 1 && n <= total) {
          const img = new Image();
          img.src = detail.pages[n - 1].url;
        }
      });
    };

    const drawStage = () => {
      if (store.observer) {
        store.observer.disconnect();
        store.observer = null;
      }
      stage.innerHTML = "";
      syncHeaderControls();

      if (prefs.mode === "vertical") {
        const pageWraps = [];
        for (const p of detail.pages) {
          const wrap = el("div", "reader-page-wrap");
          wrap.dataset.page = String(p.num);
          const img = el("img", "reader-img");
          img.src = p.url;
          img.alt = `Page ${p.num}`;
          img.loading = Math.abs(p.num - currentPage) <= 3 ? "eager" : "lazy";
          wrap.appendChild(img);
          stage.appendChild(wrap);
          pageWraps.push(wrap);
        }

        store.observer = new IntersectionObserver(
          (entries) => {
            let best = null;
            for (const entry of entries) {
              if (entry.isIntersecting && (!best || entry.intersectionRatio > best.intersectionRatio)) {
                best = entry;
              }
            }
            if (best) {
              const seenPage = parseInt(best.target.dataset.page, 10);
              if (seenPage && seenPage !== currentPage) {
                currentPage = seenPage;
                syncHeaderControls();
                saveProgressDebounced(key, currentPage);
              }
            }
          },
          { threshold: [0.35, 0.6] }
        );
        pageWraps.forEach((w) => store.observer.observe(w));

        if (currentPage > 1 && pageWraps[currentPage - 1]) {
          requestAnimationFrame(() => {
            pageWraps[currentPage - 1].scrollIntoView({ behavior: "auto", block: "start" });
          });
        }
      } else {
        const p = detail.pages[currentPage - 1];
        const wrap = el("div", "single-nav-overlay");
        const img = el("img", "reader-img");
        img.src = p.url;
        img.alt = `Page ${p.num}`;
        wrap.appendChild(img);
        wrap.addEventListener("click", (ev) => {
          const rect = wrap.getBoundingClientRect();
          if (ev.clientX - rect.left < rect.width * 0.35) {
            goToPage(currentPage - 1);
          } else {
            goToPage(currentPage + 1);
          }
        });
        stage.appendChild(wrap);

        const bottomNav = el("div", "reader-bottom-nav");
        const bPrev = el("button", "reader-btn", "‹ Previous Page");
        bPrev.disabled = currentPage <= 1;
        bPrev.addEventListener("click", () => goToPage(currentPage - 1));
        const bNext = el("button", "reader-btn", "Next Page ›");
        bNext.disabled = currentPage >= total;
        bNext.addEventListener("click", () => goToPage(currentPage + 1));
        bottomNav.appendChild(bPrev);
        bottomNav.appendChild(bNext);
        stage.appendChild(bottomNav);

        preloadAhead(currentPage);
        window.scrollTo({ top: 0, behavior: "auto" });
      }
      saveProgressDebounced(key, currentPage);
    };

    const goToPage = (target) => {
      const clamped = Math.max(1, Math.min(total, target));
      if (clamped === currentPage && prefs.mode === "single") return;
      currentPage = clamped;
      if (prefs.mode === "vertical") {
        const elWrap = stage.querySelector(`[data-page="${currentPage}"]`);
        if (elWrap) elWrap.scrollIntoView({ behavior: "smooth", block: "start" });
        syncHeaderControls();
        saveProgressDebounced(key, currentPage);
      } else {
        window.history.replaceState(null, "", `#/read/${encodeURIComponent(key)}/${currentPage}`);
        drawStage();
      }
    };

    prevBtn.addEventListener("click", () => goToPage(currentPage - 1));
    nextBtn.addEventListener("click", () => goToPage(currentPage + 1));
    pageSelect.addEventListener("change", () => goToPage(parseInt(pageSelect.value, 10)));

    modeBtn.addEventListener("click", () => {
      prefs.mode = prefs.mode === "vertical" ? "single" : "vertical";
      patchState({ reader_prefs: { mode: prefs.mode } }).catch(() => {});
      drawStage();
    });

    fitSel.addEventListener("change", () => {
      prefs.fit = fitSel.value;
      stage.className = `reader-stage fit-${prefs.fit}`;
      patchState({ reader_prefs: { fit: prefs.fit } }).catch(() => {});
    });

    drawStage();

    const onKey = (ev) => {
      if (!appEl.classList.contains("reader-mode")) return;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
      if (ev.key === "ArrowRight" || ev.key.toLowerCase() === "d") {
        ev.preventDefault();
        goToPage(currentPage + 1);
      } else if (ev.key === "ArrowLeft" || ev.key.toLowerCase() === "a") {
        ev.preventDefault();
        goToPage(currentPage - 1);
      } else if (ev.key.toLowerCase() === "m") {
        ev.preventDefault();
        modeBtn.click();
      } else if (ev.key.toLowerCase() === "f") {
        ev.preventDefault();
        if (!document.fullscreenElement) {
          document.documentElement.requestFullscreen?.().catch(() => {});
        } else {
          document.exitFullscreen?.().catch(() => {});
        }
      } else if (ev.key === "Escape" && !document.fullscreenElement) {
        window.location.hash = `#/g/${encodeURIComponent(key)}`;
      }
    };
    store.keyHandler = onKey;
    window.addEventListener("keydown", onKey);
  }

  function renderSettingsView() {
    cleanupReader();
    updateActiveNav("settings");
    appEl.innerHTML = "";

    const toolbar = el("div", "toolbar");
    const tWrap = el("div", "toolbar-title");
    tWrap.appendChild(el("h1", "toolbar-heading", "Settings"));
    toolbar.appendChild(tWrap);
    appEl.appendChild(toolbar);

    const grid = el("div", "settings-grid");

    // 1. Library Folder & Rescan card
    const libCard = el("section", "settings-card");
    libCard.appendChild(el("h2", "", "Library Folder"));
    libCard.appendChild(
      el("p", "settings-help", "Choose the folder containing downloaded galleries, or rescan to pick up new downloads.")
    );

    const folderRow = el("div", "settings-row");
    const pathInput = el("input", "settings-input");
    pathInput.type = "text";
    pathInput.value = store.outputDir || "";
    pathInput.placeholder = "Path to downloads folder";

    const browseBtn = el("button", "btn btn-secondary", "Browse…");
    browseBtn.type = "button";
    const applyBtn = el("button", "btn btn-primary", "Apply Folder");
    applyBtn.type = "button";
    const rescanBtn = el("button", "btn btn-secondary", "Rescan Library");
    rescanBtn.type = "button";

    const statusLine = el(
      "div",
      "settings-status",
      `Active folder: ${store.outputDir || "(none)"} — ${store.galleries.length} galleries indexed`
    );

    const applyLibraryDir = async (dirPath) => {
      applyBtn.disabled = true;
      browseBtn.disabled = true;
      rescanBtn.disabled = true;
      statusLine.classList.remove("error");
      try {
        const data = await apiJson("/api/library-dir", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: dirPath }),
        });
        setGalleries(data.galleries);
        store.outputDir = data.output_dir;
        if (data.state) store.state = data.state;
        pathInput.value = data.output_dir;
        statusLine.textContent = `Active folder: ${data.output_dir} — ${data.count} galleries indexed`;
        showToast(`Loaded ${data.count} galleries`);
      } catch (err) {
        let msg = err.message;
        try {
          msg = JSON.parse(msg).error || msg;
        } catch {}
        statusLine.textContent = msg;
        statusLine.classList.add("error");
      } finally {
        applyBtn.disabled = false;
        browseBtn.disabled = false;
        rescanBtn.disabled = false;
      }
    };

    browseBtn.addEventListener("click", async () => {
      browseBtn.disabled = true;
      try {
        const data = await apiJson("/api/browse-folder", { method: "POST" });
        if (data.path) {
          pathInput.value = data.path;
          await applyLibraryDir(data.path);
        }
      } catch (err) {
        showToast(`Folder picker unavailable: ${err.message}`);
      } finally {
        browseBtn.disabled = false;
      }
    });

    applyBtn.addEventListener("click", () => applyLibraryDir(pathInput.value));
    pathInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        applyLibraryDir(pathInput.value);
      }
    });

    rescanBtn.addEventListener("click", async () => {
      rescanBtn.disabled = true;
      statusLine.classList.remove("error");
      try {
        const data = await apiJson("/api/rescan", { method: "POST" });
        setGalleries(data.galleries);
        if (data.output_dir) store.outputDir = data.output_dir;
        statusLine.textContent = `Active folder: ${store.outputDir} — ${data.count} galleries indexed`;
        showToast(`Rescanned ${data.count} galleries`);
      } catch (err) {
        statusLine.textContent = `Rescan failed: ${err.message}`;
        statusLine.classList.add("error");
      } finally {
        rescanBtn.disabled = false;
      }
    });

    folderRow.appendChild(pathInput);
    folderRow.appendChild(browseBtn);
    folderRow.appendChild(applyBtn);
    folderRow.appendChild(rescanBtn);
    libCard.appendChild(folderRow);
    libCard.appendChild(statusLine);
    grid.appendChild(libCard);

    // 2. Reader Preferences card
    const readerCard = el("section", "settings-card");
    readerCard.appendChild(el("h2", "", "Reader Defaults"));
    readerCard.appendChild(el("p", "settings-help", "Saved locally in .nh_dl_web.json."));

    const prefs = store.state.reader_prefs || { mode: "vertical", fit: "width" };

    const modeField = el("div", "settings-field");
    modeField.appendChild(el("label", "settings-label", "Reading Mode"));
    const modeSel = el("select", "settings-select");
    [
      ["vertical", "Vertical Strip"],
      ["single", "Single Page"],
    ].forEach(([val, label]) => {
      const opt = el("option", "", label);
      opt.value = val;
      if (prefs.mode === val) opt.selected = true;
      modeSel.appendChild(opt);
    });
    modeSel.addEventListener("change", () => {
      patchState({ reader_prefs: { mode: modeSel.value } })
        .then(() => showToast("Reader mode updated"))
        .catch(() => {});
    });
    modeField.appendChild(modeSel);

    const fitField = el("div", "settings-field");
    fitField.appendChild(el("label", "settings-label", "Image Fit"));
    const fitSel = el("select", "settings-select");
    [
      ["width", "Fit Width"],
      ["height", "Fit Height"],
      ["original", "Original"],
    ].forEach(([val, label]) => {
      const opt = el("option", "", label);
      opt.value = val;
      if (prefs.fit === val) opt.selected = true;
      fitSel.appendChild(opt);
    });
    fitSel.addEventListener("change", () => {
      patchState({ reader_prefs: { fit: fitSel.value } })
        .then(() => showToast("Image fit updated"))
        .catch(() => {});
    });
    fitField.appendChild(fitSel);

    readerCard.appendChild(modeField);
    readerCard.appendChild(fitField);
    grid.appendChild(readerCard);

    // 3. Local Data Summary
    const dataCard = el("section", "settings-card");
    dataCard.appendChild(el("h2", "", "Local Library State"));
    const bCount = (store.state.bookmarks || []).length;
    const pCount = Object.keys(store.state.progress || {}).length;
    const hCount = (store.state.search_history || []).length;
    dataCard.appendChild(
      el(
        "p",
        "settings-help",
        `${bCount} bookmarked galleries · ${pCount} reading progress entries · ${hCount} saved/recent searches`
      )
    );
    grid.appendChild(dataCard);

    appEl.appendChild(grid);
  }

  function renderCurrentRoute() {
    const { segments, params } = parseRoute();
    const head = segments[0] || "";

    if (!head) {
      renderGridView({ favoritesOnly: false, params });
    } else if (head === "favorites") {
      renderGridView({ favoritesOnly: true, params });
    } else if (head === "tags") {
      renderDirectoryView("tags", "tag", "Tags");
    } else if (head === "artists") {
      renderDirectoryView("artists", "artist", "Artists");
    } else if (head === "settings") {
      renderSettingsView();
    } else if (head === "g" && segments[1]) {
      renderDetailView(segments[1]);
    } else if (head === "read" && segments[1]) {
      renderReaderView(segments[1], segments[2]);
    } else {
      window.location.hash = "#/";
    }
  }

  function setGalleries(list) {
    store.galleries = list || [];
    store.byKey.clear();
    store.details.clear();
    for (const g of store.galleries) {
      store.byKey.set(g.key, g);
    }
  }

  function formatCount(n) {
    if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
    return String(n);
  }

  function syncClearBtn() {
    searchClear.classList.toggle("hidden", !searchInput.value);
  }

  function closeDropdown() {
    store.dropdownOpen = false;
    store.dropdownItems = [];
    store.dropdownIndex = -1;
    searchDropdown.classList.add("hidden");
    searchDropdown.innerHTML = "";
  }

  function replaceSpan(str, start, end, replacement, caretOffsetFromEnd = 0) {
    const before = str.slice(0, start);
    const after = str.slice(end);
    const nextVal = `${before}${replacement}${after}`;
    const rawPos = start + replacement.length - caretOffsetFromEnd;
    const clamped = Math.max(0, Math.min(nextVal.length, rawPos));
    searchInput.value = nextVal;
    syncClearBtn();
    searchInput.focus();
    searchInput.setSelectionRange(clamped, clamped);
    renderSearchDropdown();
  }

  function submitSearchQuery(qText) {
    const q = qText.trim();
    closeDropdown();
    if (q) {
      patchState({ add_search: q }).catch(() => {});
    }
    window.location.hash = buildHash("/", { q });
  }

  function isQueryStarred(qText) {
    const q = qText.trim();
    return (store.state.search_history || []).some((h) => h.query === q && h.starred);
  }

  function makeStarBtn(query) {
    const starred = isQueryStarred(query);
    const btn = el("button", `sd-icon-btn${starred ? " starred" : ""}`, starred ? "★" : "☆");
    btn.type = "button";
    btn.title = starred ? "Unstar search" : "Save search";
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      await patchState({ toggle_star_search: query });
      renderSearchDropdown();
    });
    return btn;
  }

  function getFacetSuggestions(prefix, needle, limit = 10) {
    const spec = FACET_PREFIXES[prefix];
    if (!spec) return [];
    const counts = computeFacetCounts(spec.field);
    const q = needle.trim().toLowerCase();
    const matches = [];
    for (const [name, count] of counts.entries()) {
      const low = name.toLowerCase();
      if (q && !low.includes(q)) continue;
      const rank = q && low.startsWith(q) ? 0 : 1;
      matches.push({ prefix, spec, name, count, rank });
    }
    matches.sort((a, b) => a.rank - b.rank || b.count - a.count || a.name.localeCompare(b.name));
    return matches.slice(0, limit);
  }

  function getCrossFacetSuggestions(needle, limit = 8) {
    const q = needle.trim().toLowerCase();
    if (!q) return [];
    const seen = new Set();
    const matches = [];
    const order = ["tag", "artist", "parody", "group", "character", "language"];
    for (const prefix of order) {
      const spec = FACET_PREFIXES[prefix];
      const counts = computeFacetCounts(spec.field);
      for (const [name, count] of counts.entries()) {
        const low = name.toLowerCase();
        if (!low.includes(q)) continue;
        const uniq = `${spec.field}:${name}`;
        if (seen.has(uniq)) continue;
        seen.add(uniq);
        const rank = low === q ? 0 : low.startsWith(q) ? 1 : 2;
        matches.push({ prefix, spec, name, count, rank });
      }
    }
    matches.sort((a, b) => a.rank - b.rank || b.count - a.count || a.name.localeCompare(b.name));
    return matches.slice(0, limit);
  }

  function renderSyntaxRows(insertFn) {
    for (const hint of SYNTAX_HINTS) {
      const row = el("div", "sd-row");
      const left = el("div", "sd-left");
      left.appendChild(el("span", "sd-mono", hint.label));
      const right = el("div", "sd-right");
      right.appendChild(el("span", "sd-desc", hint.desc));
      row.appendChild(left);
      row.appendChild(right);
      const action = () => insertFn(hint);
      row.addEventListener("click", action);
      searchDropdown.appendChild(row);
      store.dropdownItems.push({ el: row, action });
    }
  }

  function renderFacetRow(item, onPick) {
    const row = el("div", "sd-row");
    const left = el("div", "sd-left");
    left.appendChild(el("span", `sd-badge ${item.spec.cls}`, item.spec.badge));
    left.appendChild(el("span", "sd-item-name", item.name));
    left.appendChild(el("span", "sd-item-count", formatCount(item.count)));

    const right = el("div", "sd-right");
    right.appendChild(el("span", "sd-arrow", "→"));
    row.appendChild(left);
    row.appendChild(right);

    row.addEventListener("click", () => onPick(item));
    searchDropdown.appendChild(row);
    store.dropdownItems.push({ el: row, action: () => onPick(item) });
  }

  function renderSearchDropdown() {
    if (!store.dropdownOpen) return;
    searchDropdown.innerHTML = "";
    store.dropdownItems = [];
    store.dropdownIndex = -1;

    const val = searchInput.value;
    const trimmed = val.trim();

    if (!trimmed) {
      const history = (store.state.search_history || []).slice();
      history.sort((a, b) => Number(b.starred) - Number(a.starred));
      history.slice(0, 6).forEach((entry) => {
        const row = el("div", "sd-row");
        const left = el("div", "sd-left");
        left.appendChild(el("span", "sd-history-icon", "🕒"));
        left.appendChild(el("span", "sd-mono", entry.query));

        const right = el("div", "sd-right");
        right.appendChild(makeStarBtn(entry.query));
        const rmBtn = el("button", "sd-icon-btn", "×");
        rmBtn.type = "button";
        rmBtn.title = "Remove from history";
        rmBtn.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          ev.preventDefault();
          await patchState({ remove_search: entry.query });
          renderSearchDropdown();
        });
        right.appendChild(rmBtn);

        row.appendChild(left);
        row.appendChild(right);
        const action = () => {
          searchInput.value = entry.query;
          syncClearBtn();
          submitSearchQuery(entry.query);
        };
        row.addEventListener("click", action);
        searchDropdown.appendChild(row);
        store.dropdownItems.push({ el: row, action });
      });

      renderSyntaxRows((hint) => {
        replaceSpan(val, 0, val.length, hint.insert, hint.cursorBack);
      });

      searchDropdown.classList.remove("hidden");
      return;
    }

    // Header row: "↵ Search for <query>"
    const headerRow = el("div", "sd-row sd-header");
    const hLeft = el("div", "sd-left");
    hLeft.appendChild(el("span", "", "↵"));
    hLeft.appendChild(el("span", "", "Search for"));
    hLeft.appendChild(el("span", "sd-mono", trimmed));
    const hRight = el("div", "sd-right");
    hRight.appendChild(makeStarBtn(trimmed));
    headerRow.appendChild(hLeft);
    headerRow.appendChild(hRight);
    const submitAction = () => submitSearchQuery(trimmed);
    headerRow.addEventListener("click", submitAction);
    searchDropdown.appendChild(headerRow);
    store.dropdownItems.push({ el: headerRow, action: submitAction });

    const cursorPos = searchInput.selectionStart ?? val.length;
    const active = getTokenAtCursor(val, cursorPos);

    if (!active) {
      // Cursor is in whitespace (e.g., after "tag:\"yuri\" ") -> offer parameter templates
      const insertPos = cursorPos;
      renderSyntaxRows((hint) => {
        const needsLeadSpace = insertPos > 0 && val[insertPos - 1] !== " ";
        const text = (needsLeadSpace ? " " : "") + hint.insert;
        replaceSpan(val, insertPos, insertPos, text, hint.cursorBack);
      });
      searchDropdown.classList.remove("hidden");
      return;
    }

    const parsed = parseToken(active.raw);
    const showParamActions =
      parsed.negated ||
      parsed.hasQuotes ||
      parsed.value.length > 0 ||
      !parsed.prefix;

    if (showParamActions) {
      // Exclude / Include action row
      const toggleRow = el("div", "sd-row");
      const tLeft = el("div", "sd-left");
      if (parsed.negated) {
        tLeft.appendChild(el("span", "sd-action-include", "+ Include"));
        tLeft.appendChild(el("span", "sd-mono sd-action-include", active.raw.slice(1)));
      } else {
        tLeft.appendChild(el("span", "sd-action-exclude", "− Exclude"));
        tLeft.appendChild(el("span", "sd-mono sd-action-exclude", active.raw));
      }
      toggleRow.appendChild(tLeft);
      const toggleAction = () => {
        const toggled = parsed.negated ? active.raw.slice(1) : `-${active.raw}`;
        replaceSpan(val, active.start, active.end, toggled, 0);
      };
      toggleRow.addEventListener("click", toggleAction);
      searchDropdown.appendChild(toggleRow);
      store.dropdownItems.push({ el: toggleRow, action: toggleAction });

      // Remove action row
      const rmRow = el("div", "sd-row");
      const rLeft = el("div", "sd-left");
      rLeft.appendChild(el("span", "sd-action-remove", "× Remove"));
      rLeft.appendChild(el("span", "sd-mono sd-action-remove", active.raw));
      rmRow.appendChild(rLeft);
      const rmAction = () => {
        const before = val.slice(0, active.start).replace(/\s+$/, "");
        const after = val.slice(active.end).replace(/^\s+/, "");
        const joined = before && after ? `${before} ${after}` : before || after;
        searchInput.value = joined;
        syncClearBtn();
        searchInput.focus();
        const pos = before ? before.length : 0;
        searchInput.setSelectionRange(pos, pos);
        renderSearchDropdown();
      };
      rmRow.addEventListener("click", rmAction);
      searchDropdown.appendChild(rmRow);
      store.dropdownItems.push({ el: rmRow, action: rmAction });
    }

    const negPrefix = parsed.negated ? "-" : "";
    if (parsed.prefix && FACET_PREFIXES[parsed.prefix]) {
      const suggestions = getFacetSuggestions(parsed.prefix, parsed.value, 10);
      suggestions.forEach((item) => {
        renderFacetRow(item, (picked) => {
          const replacement = `${negPrefix}${picked.prefix}:"${picked.name}"`;
          replaceSpan(val, active.start, active.end, replacement, 0);
        });
      });
    } else if (!parsed.prefix && parsed.value && !parsed.value.startsWith("#")) {
      const suggestions = getCrossFacetSuggestions(parsed.value, 8);
      suggestions.forEach((item) => {
        renderFacetRow(item, (picked) => {
          const replacement = `${negPrefix}${picked.prefix}:"${picked.name}"`;
          replaceSpan(val, active.start, active.end, replacement, 0);
        });
      });
    }

    searchDropdown.classList.remove("hidden");
  }

  function highlightDropdownItem(nextIdx) {
    if (!store.dropdownItems.length) return;
    const len = store.dropdownItems.length;
    store.dropdownIndex = ((nextIdx % len) + len) % len;
    store.dropdownItems.forEach((it, idx) => {
      it.el.classList.toggle("selected", idx === store.dropdownIndex);
    });
    store.dropdownItems[store.dropdownIndex].el.scrollIntoView({ block: "nearest" });
  }

  searchInput.addEventListener("focus", () => {
    store.dropdownOpen = true;
    renderSearchDropdown();
  });

  searchInput.addEventListener("input", () => {
    syncClearBtn();
    store.dropdownOpen = true;
    renderSearchDropdown();
  });

  searchInput.addEventListener("click", () => {
    store.dropdownOpen = true;
    renderSearchDropdown();
  });

  searchInput.addEventListener("keyup", (ev) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(ev.key) && store.dropdownOpen) {
      renderSearchDropdown();
    }
  });

  searchInput.addEventListener("keydown", (ev) => {
    if (!store.dropdownOpen) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      highlightDropdownItem(store.dropdownIndex + 1);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      highlightDropdownItem(store.dropdownIndex - 1);
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      closeDropdown();
    } else if (ev.key === "Enter" && store.dropdownIndex > 0) {
      ev.preventDefault();
      store.dropdownItems[store.dropdownIndex]?.action();
    }
  });

  searchDropdown.addEventListener("mousedown", (ev) => {
    ev.preventDefault();
  });

  document.addEventListener("mousedown", (ev) => {
    if (!searchWrap.contains(ev.target)) {
      closeDropdown();
    }
  });

  searchClear.addEventListener("click", () => {
    searchInput.value = "";
    syncClearBtn();
    searchInput.focus();
    store.dropdownOpen = true;
    renderSearchDropdown();
  });

  searchForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    submitSearchQuery(searchInput.value);
  });

  randomBtn.addEventListener("click", () => {
    if (!store.galleries.length) return;
    const pick = store.galleries[Math.floor(Math.random() * store.galleries.length)];
    window.location.hash = `#/g/${encodeURIComponent(pick.key)}`;
  });

  window.addEventListener("hashchange", renderCurrentRoute);

  async function init() {
    try {
      const data = await apiJson("/api/galleries");
      setGalleries(data.galleries);
      if (data.output_dir) store.outputDir = data.output_dir;
      if (data.state) store.state = data.state;
      updateFavCount();
      renderCurrentRoute();
    } catch (err) {
      appEl.innerHTML = "";
      const box = el("div", "empty-state");
      box.appendChild(el("h2", "", "Failed to load library"));
      box.appendChild(el("p", "", err.message));
      appEl.appendChild(box);
    }
  }

  init();
})();
