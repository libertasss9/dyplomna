if (ensureAuthOrRedirect()) {
  renderNav("outliers");
}

function renderCards(items) {
  const wrap = document.getElementById("outlierCards");
  clearElement(wrap);
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "metric-card";
    appendTextElement(card, "div", item.label, "metric-label");
    appendTextElement(card, "div", item.value, "metric-value");
    wrap.appendChild(card);
  });
}

function renderOutlierValues(values) {
  const body = document.getElementById("outlierValuesBody");
  if (!values || values.length === 0) {
    renderEmptyRow(body, 2, "Викидів не знайдено");
    return;
  }
  clearElement(body);
  values.forEach((value, index) => appendTableRow(body, [index + 1, formatNumber(value)]));
}

function renderOutlierBoxplot(summary) {
  const container = document.getElementById("outlierBoxplot");
  clearElement(container);
  if (!summary) {
    return;
  }
  const min = Number(summary.min);
  const max = Number(summary.max);
  const range = max - min || 1;
  const percent = (value) => Math.max(0, Math.min(100, ((Number(value) - min) / range) * 100));
  const box = document.createElement("div");
  box.className = "boxplot";
  const whisker = document.createElement("span");
  whisker.className = "boxplot-whisker";
  const quartile = document.createElement("span");
  quartile.className = "boxplot-box";
  quartile.style.left = `${percent(summary.q1)}%`;
  quartile.style.width = `${Math.max(1, percent(summary.q3) - percent(summary.q1))}%`;
  const median = document.createElement("span");
  median.className = "boxplot-median";
  median.style.left = `${percent(summary.median)}%`;
  box.appendChild(whisker);
  box.appendChild(quartile);
  box.appendChild(median);
  container.appendChild(box);
  const facts = document.createElement("div");
  facts.className = "source-facts";
  [
    ["Min", summary.min],
    ["Q1", summary.q1],
    ["Median", summary.median],
    ["Q3", summary.q3],
    ["Max", summary.max],
    ["IQR межі", `${formatNumber(summary.iqr_lower)} - ${formatNumber(summary.iqr_upper)}`]
  ].forEach(([label, value]) => appendTextElement(facts, "span", `${label}: ${Number.isFinite(Number(value)) ? formatNumber(value) : value}`));
  container.appendChild(facts);
}

async function loadOutlierColumns() {
  try {
    const data = await apiRequest("/columns", { method: "GET" });
    const outlierColumns = data.continuous_columns || [];
    populateSelectWithPlaceholder(
      "outlierColumn",
      outlierColumns.length ? outlierColumns : data.numeric_columns || [],
      "Оберіть неперервну колонку"
    );
  } catch (error) {
    setStatus("outlierStatus", error.message, "error");
  }
}

async function runOutliers() {
  const column = document.getElementById("outlierColumn").value;
  const threshold = Number(document.getElementById("outlierThreshold").value);
  if (!column) {
    setStatus("outlierStatus", "Оберіть колонку для пошуку викидів", "error");
    return;
  }
  try {
    const data = await apiRequest("/outliers", {
      method: "POST",
      body: JSON.stringify({ column, threshold })
    });
    renderCards([
      { label: "Колонка", value: data.column },
      { label: "Поріг", value: data.threshold },
      { label: "Кількість викидів", value: data.outliers_count }
    ]);
    renderOutlierBoxplot(data.summary);
    renderOutlierValues(data.outliers);
    setStatus("outlierStatus", "Пошук викидів завершено", "ok");
  } catch (error) {
    setStatus("outlierStatus", error.message, "error");
  }
}

document.getElementById("outlierRunBtn").addEventListener("click", runOutliers);
loadOutlierColumns();
