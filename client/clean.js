if (ensureAuthOrRedirect()) {
  renderNav("clean");
}

let currentPlan = null;
let selectedDropColumns = new Set();

function shapeFromPayload(payload) {
  if (Array.isArray(payload?.shape)) {
    return payload.shape;
  }
  return [payload?.profile?.rows_count ?? 0, payload?.profile?.columns_count ?? 0];
}

function renderCleanSummary(plan) {
  const container = document.getElementById("cleanSummaryCards");
  clearElement(container);
  const summary = plan.summary || {};
  const items = [
    { label: "Рядки", value: summary.rows_count ?? "-" },
    { label: "Колонки", value: summary.columns_count ?? "-" },
    { label: "Пропуски", value: summary.missing_total ?? 0 },
    { label: "Дублікати", value: summary.duplicate_rows ?? 0 },
    { label: "Константні", value: summary.constant_columns_count ?? 0 },
    { label: "Нулі для перевірки", value: summary.zero_candidate_columns_count ?? 0 }
  ];
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "metric-card";
    appendTextElement(card, "div", item.label, "metric-label");
    appendTextElement(card, "div", item.value, "metric-value");
    container.appendChild(card);
  });
}

function renderZeroCandidates(items) {
  const container = document.getElementById("zeroCandidates");
  clearElement(container);
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    appendTextElement(container, "p", "Колонок із підозрілими нульовими значеннями не знайдено.", "muted");
    return;
  }
  list.forEach((item) => {
    const label = document.createElement("label");
    label.className = "check-row compact";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = item.column;
    checkbox.dataset.zeroColumn = "true";
    const text = document.createElement("span");
    text.textContent = `${item.column}: ${item.zero_count} нулів (${formatNumber(item.zero_percent, 2)}%)`;
    label.appendChild(checkbox);
    label.appendChild(text);
    container.appendChild(label);
  });
}

function columnDropReason(profile) {
  if (!profile) {
    return "Ручне виключення за рішенням користувача";
  }
  if (profile.role === "constant") {
    return "Константна колонка, зазвичай не корисна для аналізу";
  }
  if (profile.role === "text" && profile.unique_count > 50) {
    return "Текстова колонка з великою кількістю унікальних значень";
  }
  if (/id|identifier|street|address|url|email/i.test(profile.name)) {
    return "Схожа на ідентифікатор або службове поле";
  }
  return `Автоматична роль: ${profile.role}`;
}

function renderDropColumnChoices() {
  const container = document.getElementById("dropColumnChoices");
  clearElement(container);
  const query = document.getElementById("dropColumnSearch").value.trim().toLowerCase();
  const profiles = currentPlan?.profile?.column_profiles || [];
  const filtered = profiles.filter((item) => item.name.toLowerCase().includes(query));
  if (!filtered.length) {
    appendTextElement(container, "p", "Колонок за таким пошуком не знайдено.", "muted");
    return;
  }
  filtered.forEach((profile) => {
    const label = document.createElement("label");
    label.className = "check-row compact column-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = profile.name;
    checkbox.checked = selectedDropColumns.has(profile.name);
    checkbox.dataset.dropColumn = "true";
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        selectedDropColumns.add(profile.name);
      } else {
        selectedDropColumns.delete(profile.name);
      }
    });
    appendTextElement(label, "span", profile.name);
    const reason = document.createElement("small");
    reason.textContent = columnDropReason(profile);
    label.prepend(checkbox);
    label.appendChild(reason);
    container.appendChild(label);
  });
}

function renderColumnSelectors(plan) {
  const columns = plan.profile?.columns || [];
  selectedDropColumns = new Set(Array.from(selectedDropColumns).filter((column) => columns.includes(column)));
  renderDropColumnChoices();

  populateSelectWithPlaceholder(
    "classSource",
    (plan.class_source_columns || []).map((item) => item.column),
    "Оберіть колонку"
  );
  renderSelectedClassSource();
}

function renderChanges(changes, shape) {
  const items = (changes || []).map((message) => ({
    level: "ok",
    title: "Зміна застосована",
    message
  }));
  if (shape) {
    items.unshift({
      level: "info",
      title: "Поточний розмір датасету",
      message: `${shape[0]} рядків, ${shape[1]} колонок.`
    });
  }
  renderInsightList("cleanResult", items);
}

function selectedDropColumnValues() {
  return Array.from(selectedDropColumns);
}

function selectedZeroColumns() {
  return Array.from(document.querySelectorAll("[data-zero-column='true']:checked")).map(
    (checkbox) => checkbox.value
  );
}

function getSelectedClassSource() {
  const source = document.getElementById("classSource").value;
  return (currentPlan?.class_source_columns || []).find((item) => item.column === source) || null;
}

function renderSelectedClassSource() {
  const container = document.getElementById("classSourceInfo");
  clearElement(container);
  const source = getSelectedClassSource();
  if (!source) {
    appendTextElement(container, "p", "Оберіть колонку, щоб побачити її підказки для формування класів.", "muted");
    return;
  }

  const facts = [
    `Тип: ${source.dtype}`,
    `Роль: ${source.role}`,
    `Унікальних значень: ${source.unique_count}`,
    `Пропусків: ${source.missing_count}`
  ];
  if (source.is_numeric) {
    facts.push(`Мінімум: ${formatNumber(source.min, 4)}`);
    facts.push(`Медіана: ${formatNumber(source.median, 4)}`);
    facts.push(`Максимум: ${formatNumber(source.max, 4)}`);
  }

  const grid = document.createElement("div");
  grid.className = "source-facts";
  facts.forEach((fact) => appendTextElement(grid, "span", fact));
  container.appendChild(grid);

  if (source.top_values?.length) {
    const values = source.top_values
      .map((item) => `${item.value}: ${item.count}`)
      .join("; ");
    appendTextElement(container, "small", `Найчастіші значення: ${values}`);
  }
}

function updateClassRulesPlaceholder() {
  const rules = document.getElementById("classRules");
  if (document.getElementById("classMode").value === "ranges") {
    rules.placeholder = [
      "0 | 0 | 24.99 | Низьке значення",
      "1 | 25 | 29.99 | Середнє значення",
      "2 | 30 | | Високе значення"
    ].join("\n");
  } else {
    rules.placeholder = [
      "0 | 0 | Негативний клас",
      "1 | 1, 2 | Позитивний або підвищений клас"
    ].join("\n");
  }
}

async function loadCleaningPlan() {
  try {
    const plan = await apiRequest("/cleaning/plan", { method: "GET" });
    setDatasetContextFromPayload(plan);
    currentPlan = plan;
    renderCleanSummary(plan);
    renderInsightList("cleanRecommendations", plan.recommendations || []);
    renderZeroCandidates(plan.zero_candidates || []);
    renderColumnSelectors(plan);
    const [rows, columns] = shapeFromPayload(plan);
    setStatus("cleanStatus", `План очищення готовий: ${rows} рядків, ${columns} колонок`, "ok");
  } catch (error) {
    setStatus("cleanStatus", error.message, "error");
  }
}

async function applyCleaning() {
  const payload = {
    drop_duplicate_rows: document.getElementById("dropDuplicates").checked,
    drop_constant_columns: document.getElementById("dropConstants").checked,
    drop_high_cardinality_text: document.getElementById("dropHighCardinality").checked,
    missing_strategy: document.getElementById("missingStrategy").value,
    drop_columns: selectedDropColumnValues(),
    zero_as_missing_columns: selectedZeroColumns()
  };

  try {
    const result = await apiRequest("/cleaning/apply", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    setDatasetContextFromPayload(result);
    const shape = shapeFromPayload(result);
    renderChanges(result.changes || [], shape);
    setStatus("cleanStatus", `Очищення застосовано: ${shape[0]} рядків, ${shape[1]} колонок`, "ok");
    await loadCleaningPlan();
  } catch (error) {
    setStatus("cleanStatus", error.message, "error");
  }
}

function renderClassResult(result) {
  const distribution = Object.entries(result.class_distribution || {})
    .map(([label, count]) => `клас ${label}: ${count}`)
    .join("; ");
  const descriptions = Object.entries(result.class_descriptions || {})
    .map(([label, text]) => `${label} = ${text}`)
    .join("; ");
  renderInsightList("classResult", [
    {
      level: "ok",
      title: `Створено колонку ${result.column}`,
      message: distribution || "Класи створено."
    },
    {
      level: "info",
      title: "Описи класів",
      message: descriptions || "Описи класів можна уточнити у словнику колонок."
    },
    {
      level: result.unmatched_count ? "warning" : "ok",
      title: "Рядки без призначеного класу",
      message: result.unmatched_count
        ? `${result.unmatched_count} рядків не потрапили під жодне правило. За потреби додайте окремий клас або ширший діапазон.`
        : "Усі рядки отримали клас за заданими правилами."
    }
  ]);
}

function normalizeRuleNumber(value) {
  const text = String(value || "").trim().replace(",", ".");
  if (!text) {
    return null;
  }
  const number = Number(text);
  if (!Number.isFinite(number)) {
    throw new Error(`Некоректна числова межа: ${value}`);
  }
  return number;
}

function parseClassRules() {
  const mode = document.getElementById("classMode").value;
  const lines = document
    .getElementById("classRules")
    .value.split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    throw new Error("Додайте хоча б два правила класів");
  }

  return lines.map((line) => {
    const parts = line.split("|").map((part) => part.trim());
    const code = parts[0] || "";
    if (!code) {
      throw new Error("Кожне правило має починатися з коду класу");
    }

    if (mode === "ranges") {
      if (parts.length < 3) {
        throw new Error("Для діапазонів потрібен формат: код | мінімум | максимум | опис");
      }
      return {
        code,
        min: normalizeRuleNumber(parts[1]),
        max: normalizeRuleNumber(parts[2]),
        label: parts.slice(3).join(" | ").trim()
      };
    }

    if (parts.length < 2) {
      throw new Error("Для значень потрібен формат: код | значення1, значення2 | опис");
    }
    return {
      code,
      values: parts[1]
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
      label: parts.slice(2).join(" | ").trim()
    };
  });
}

function fillClassTemplate() {
  const source = getSelectedClassSource();
  const modeSelect = document.getElementById("classMode");
  const rules = document.getElementById("classRules");
  if (!source) {
    setStatus("classStatus", "Оберіть колонку для створення прикладу правил", "error");
    return;
  }

  if (modeSelect.value === "ranges" && source.is_numeric) {
    const min = formatNumber(source.min, 4);
    const q25 = formatNumber(source.q25, 4);
    const q75 = formatNumber(source.q75, 4);
    const max = formatNumber(source.max, 4);
    rules.value = [
      `0 | ${min} | ${q25} | Низький діапазон`,
      `1 | ${q25} | ${q75} | Середній діапазон`,
      `2 | ${q75} | ${max} | Високий діапазон`
    ].join("\n");
    return;
  }

  modeSelect.value = "values";
  const values = (source.top_values || []).slice(0, 6);
  rules.value = values
    .map((item, index) => `${index} | ${item.value} | Клас для значення ${item.value}`)
    .join("\n");
}

async function createClasses() {
  const source = document.getElementById("classSource").value;
  if (!source) {
    setStatus("classStatus", "Оберіть колонку для створення класів", "error");
    return;
  }
  const sourceInfo = getSelectedClassSource();
  const mode = document.getElementById("classMode").value;
  if (mode === "ranges" && sourceInfo && !sourceInfo.is_numeric) {
    setStatus("classStatus", "Діапазони можна використовувати тільки для числових колонок. Для цієї колонки оберіть групування значень.", "error");
    return;
  }

  try {
    const payload = {
      source_column: source,
      mode,
      new_column: document.getElementById("newClassColumn").value,
      rules: parseClassRules()
    };
    const result = await apiRequest("/classes/create", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    setDatasetContextFromPayload(result);
    renderClassResult(result);
    setStatus("classStatus", `Класову колонку ${result.column} створено`, "ok");
    await loadCleaningPlan();
  } catch (error) {
    setStatus("classStatus", error.message, "error");
  }
}

document.getElementById("refreshPlanBtn").addEventListener("click", loadCleaningPlan);
document.getElementById("applyCleanBtn").addEventListener("click", applyCleaning);
document.getElementById("createClassesBtn").addEventListener("click", createClasses);
document.getElementById("fillClassTemplateBtn").addEventListener("click", fillClassTemplate);
document.getElementById("classSource").addEventListener("change", renderSelectedClassSource);
document.getElementById("classMode").addEventListener("change", updateClassRulesPlaceholder);
document.getElementById("dropColumnSearch").addEventListener("input", renderDropColumnChoices);

updateClassRulesPlaceholder();
loadCleaningPlan();
