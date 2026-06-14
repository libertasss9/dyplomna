const DEFAULT_PRIVATE_PAGE = "upload.html?v=20260614-1";
const LOGIN_PAGE = "login.html";
const PUBLIC_PAGES = new Set([LOGIN_PAGE]);
const DATASET_STATE_KEYS = [
  "analysis/latest",
  "risk/latest",
  "modeling/latest",
  "risk/job",
  "modeling/job"
];

function currentPageName() {
  return window.location.pathname.split("/").pop() || "index.html";
}

function currentClientTarget() {
  return `${currentPageName()}${window.location.search || ""}`;
}

function isPublicPage() {
  return PUBLIC_PAGES.has(currentPageName());
}

function redirectToLogin() {
  if (!isPublicPage()) {
    sessionStorage.setItem("patternlab:redirect_after_login", currentClientTarget());
  }
  window.location.replace(LOGIN_PAGE);
}

function redirectAfterLoginTarget() {
  const saved = sessionStorage.getItem("patternlab:redirect_after_login");
  sessionStorage.removeItem("patternlab:redirect_after_login");
  if (!saved || saved.includes("login.html") || saved.startsWith("http")) {
    return DEFAULT_PRIVATE_PAGE;
  }
  return saved;
}

function enforcePageAccess() {
  const hasToken = Boolean(getToken());
  if (!hasToken && !isPublicPage()) {
    window.__authBlocked = true;
    document.documentElement.classList.add("auth-blocked");
    redirectToLogin();
    return false;
  }
  if (hasToken && isPublicPage()) {
    window.location.replace(DEFAULT_PRIVATE_PAGE);
    return false;
  }
  return true;
}

const PAGE_ACCESS_ALLOWED = enforcePageAccess();

function ensureAuthOrRedirect() {
  if (!PAGE_ACCESS_ALLOWED || !getToken()) {
    if (!isPublicPage()) {
      redirectToLogin();
    }
    return false;
  }
  return true;
}

async function logout() {
  try {
    if (getToken()) {
      await logoutUser();
    }
  } catch (error) {
    // The local session should still be cleared if the API request fails.
  } finally {
    clearToken();
    clearUsername();
    window.location.href = "login.html";
  }
}

function renderWorkflow(activePage) {
  const shell = document.querySelector(".app-shell.with-nav");
  const heading = shell?.querySelector("h1");
  if (!shell || !heading || document.getElementById("workflowStrip")) {
    return;
  }

  const stepByPage = {
    upload: 0,
    clean: 1,
    dashboard: 2,
    outliers: 3,
    analysis: 3,
    risk: 3,
    modeling: 5,
    report: 6,
    history: 6
  };
  const activeIndex = stepByPage[activePage] ?? 0;
  const steps = [
    { title: "CSV прийнято", hint: "структура і розмір" },
    { title: "Якість перевірено", hint: "пропуски, дублікати" },
    { title: "Зміст описано", hint: "словник і ролі" },
    { title: "Зв'язки знайдено", hint: "розподіли, викиди" },
    { title: "Ціль визначено", hint: "клас або число" },
    { title: "Моделі оцінено", hint: "метрики і важливість" },
    { title: "Висновок зібрано", hint: "звіт і подальші дії" }
  ];

  const strip = document.createElement("div");
  strip.id = "workflowStrip";
  strip.className = "workflow-strip";
  steps.forEach((step, index) => {
    const item = document.createElement("div");
    item.className = "workflow-step";
    if (index < activeIndex) {
      item.classList.add("done");
    }
    if (index === activeIndex) {
      item.classList.add("active");
    }
    appendTextElement(item, "span", String(index + 1), "workflow-index");
    const textWrap = document.createElement("span");
    textWrap.className = "workflow-copy";
    appendTextElement(textWrap, "strong", step.title);
    appendTextElement(textWrap, "small", step.hint);
    item.appendChild(textWrap);
    strip.appendChild(item);
  });
  heading.after(strip);
}

function renderNav(activePage) {
  const nav = document.getElementById("topNav");
  if (!nav) {
    return;
  }
  document.querySelector(".app-shell")?.classList.add("with-nav");
  clearElement(nav);

  const navTitle = document.createElement("div");
  navTitle.className = "nav-title";
  appendTextElement(navTitle, "span", "Зміст аналізу");
  appendTextElement(navTitle, "strong", "PatternLab");
  nav.appendChild(navTitle);

  const links = [
    { href: "upload.html?v=20260614-1", text: "1. Дані", key: "upload" },
    { href: "clean.html?v=20260614-1", text: "2. Очищення", key: "clean" },
    { href: "dashboard.html?v=20260614-1", text: "3. Профіль", key: "dashboard" },
    { href: "outliers.html?v=20260614-1", text: "4. Викиди", key: "outliers" },
    { href: "analysis.html?v=20260614-1", text: "5. Аналіз", key: "analysis" },
    { href: "risk.html?v=20260614-1", text: "6. Рейтинг", key: "risk" },
    { href: "modeling.html?v=20260614-1", text: "7. Моделі", key: "modeling" },
    { href: "report.html?v=20260614-1", text: "8. Звіт", key: "report" },
    { href: "history.html?v=20260614-1", text: "Історія", key: "history" }
  ];

  links.forEach((item) => {
    const link = document.createElement("a");
    link.href = item.href;
    link.textContent = item.text;
    if (item.key === activePage) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
    nav.appendChild(link);
  });

  const navFooter = document.createElement("div");
  navFooter.className = "nav-footer";
  appendTextElement(navFooter, "span", getUsername() || "Користувач");
  const logoutButton = appendTextElement(navFooter, "button", "Вийти", "nav-logout");
  logoutButton.type = "button";
  logoutButton.addEventListener("click", logout);
  nav.appendChild(navFooter);

  renderWorkflow(activePage);
}

function setStatus(elementId, text, type = "ok") {
  const el = document.getElementById(elementId);
  if (!el) {
    return;
  }
  el.className = `status ${type}`;
  el.textContent = text;
}

function toPrettyJson(data) {
  return JSON.stringify(data, null, 2);
}

function clearElement(element) {
  if (element) {
    element.replaceChildren();
  }
}

function appendTextElement(parent, tagName, text, className = "") {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  element.textContent = text ?? "";
  parent.appendChild(element);
  return element;
}

function appendTableRow(tbody, values, cellTag = "td") {
  const row = document.createElement("tr");
  values.forEach((value) => appendTextElement(row, cellTag, value));
  tbody.appendChild(row);
  return row;
}

function renderEmptyRow(tbody, colspan, text) {
  clearElement(tbody);
  const row = document.createElement("tr");
  const cell = appendTextElement(row, "td", text);
  cell.colSpan = colspan;
  tbody.appendChild(row);
}

function formatNumber(value, digits = 4) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function sampleInfoLabel(sampleInfo) {
  if (!sampleInfo) {
    return "-";
  }
  if (sampleInfo.is_limited) {
    return `${sampleInfo.current_rows} з ${sampleInfo.source_rows}`;
  }
  return "Повний набір";
}

function sampleInfoDescription(sampleInfo) {
  if (!sampleInfo) {
    return "";
  }
  if (sampleInfo.is_limited) {
    return (
      `Використовується ${sampleInfo.current_rows} з ${sampleInfo.source_rows} рядків ` +
      `(${formatNumber(sampleInfo.percent, 2)}%).`
    );
  }
  if (sampleInfo.requested_limit) {
    return `Запитане обмеження ${sampleInfo.requested_limit} не скоротило набір даних.`;
  }
  return `Використовується повний набір: ${sampleInfo.current_rows} рядків.`;
}

function populateSelectWithPlaceholder(selectId, options, placeholder) {
  const select = document.getElementById(selectId);
  if (!select) {
    return;
  }
  clearElement(select);
  const first = document.createElement("option");
  first.value = "";
  first.textContent = placeholder;
  first.disabled = true;
  first.selected = true;
  select.appendChild(first);

  if (!options || options.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Немає доступних колонок";
    option.disabled = true;
    select.appendChild(option);
    return;
  }

  options.forEach((item) => {
    const option = document.createElement("option");
    option.value = item;
    option.textContent = item;
    select.appendChild(option);
  });
}

function renderInsightList(containerId, items, emptyText = "Поки немає висновків") {
  const container = document.getElementById(containerId);
  if (!container) {
    return;
  }
  clearElement(container);
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    appendTextElement(container, "p", emptyText, "muted");
    return;
  }
  list.forEach((item) => {
    const card = document.createElement("div");
    const level = typeof item === "object" ? item.level || "info" : "info";
    card.className = `insight-item ${level}`;
    if (typeof item === "object") {
      appendTextElement(card, "strong", item.title || "Висновок");
      appendTextElement(card, "p", item.message || "");
      if (item.columns?.length) {
        appendTextElement(card, "small", `Колонки: ${item.columns.join(", ")}`);
      }
    } else {
      appendTextElement(card, "p", item);
    }
    container.appendChild(card);
  });
}

function parseKeyValueLines(text) {
  const result = {};
  String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const separatorIndex = line.indexOf("=");
      if (separatorIndex === -1) {
        return;
      }
      const key = line.slice(0, separatorIndex).trim();
      const value = line.slice(separatorIndex + 1).trim();
      if (key && value) {
        result[key] = value;
      }
    });
  return result;
}

function keyValueObjectToLines(data) {
  return Object.entries(data || {})
    .map(([key, value]) => `${key} = ${value}`)
    .join("\n");
}

function userStateKey(key) {
  return `patternlab:${getUsername() || "anonymous"}:${key}`;
}

function getCurrentDatasetId() {
  return localStorage.getItem(userStateKey("dataset/id")) || "";
}

function clearDatasetScopedState() {
  DATASET_STATE_KEYS.forEach((key) => localStorage.removeItem(userStateKey(key)));
}

function setDatasetContextFromPayload(payload, options = {}) {
  const datasetId = payload?.dataset_id || payload?.profile?.dataset_id || "";
  if (!datasetId) {
    return;
  }
  const previousDatasetId = getCurrentDatasetId();
  if (options.clearScopedState || (previousDatasetId && previousDatasetId !== datasetId)) {
    clearDatasetScopedState();
  }
  localStorage.setItem(userStateKey("dataset/id"), datasetId);
}

function clearDatasetContext() {
  clearDatasetScopedState();
  localStorage.removeItem(userStateKey("dataset/id"));
}

function attachDatasetContext(payload) {
  const datasetId = getCurrentDatasetId();
  if (!datasetId || !payload || typeof payload !== "object" || Array.isArray(payload)) {
    return payload;
  }
  return { ...payload, dataset_id: datasetId };
}

function stateMatchesCurrentDataset(payload) {
  const datasetId = getCurrentDatasetId();
  if (!datasetId || !payload || typeof payload !== "object") {
    return true;
  }
  return payload.dataset_id === datasetId;
}

function saveLocalState(key, payload) {
  try {
    localStorage.setItem(userStateKey(key), JSON.stringify(attachDatasetContext(payload)));
  } catch (error) {
    // State restore is a convenience feature; analysis should continue if storage is full.
  }
}

function loadLocalState(key) {
  try {
    const raw = localStorage.getItem(userStateKey(key));
    const payload = raw ? JSON.parse(raw) : null;
    return stateMatchesCurrentDataset(payload) ? payload : null;
  } catch (error) {
    return null;
  }
}

async function saveServerState(key, payload) {
  const pathKey = String(key).split("/").map(encodeURIComponent).join("/");
  return apiRequest(`/state/${pathKey}`, {
    method: "POST",
    body: JSON.stringify(attachDatasetContext(payload))
  });
}

async function loadServerState(key) {
  const pathKey = String(key).split("/").map(encodeURIComponent).join("/");
  const state = await apiRequest(`/state/${pathKey}`, { method: "GET" });
  if (state?.payload && !stateMatchesCurrentDataset(state.payload)) {
    throw new Error("Saved state belongs to another dataset");
  }
  return state;
}
