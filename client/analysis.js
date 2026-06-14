if (ensureAuthOrRedirect()) {
  renderNav("analysis");
}

let correlationChart = null;
let regressionChart = null;
let distChart = null;
let analysisState = loadLocalState("analysis/latest") || {};

function renderCards(containerId, items) {
  const container = document.getElementById(containerId);
  clearElement(container);
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "metric-card";
    appendTextElement(card, "div", item.label, "metric-label");
    appendTextElement(card, "div", item.value, "metric-value");
    container.appendChild(card);
  });
}

function renderSampleInfo(sampleInfo) {
  if (!sampleInfo) {
    return;
  }
  renderCards("limitCards", [
    { label: "Режим", value: sampleInfo.is_limited ? "Обмежена вибірка" : "Повний набір" },
    { label: "Поточні рядки", value: sampleInfo.current_rows },
    { label: "Рядків у джерелі", value: sampleInfo.source_rows },
    { label: "Частка", value: `${formatNumber(sampleInfo.percent, 2)}%` }
  ]);
  const rowLimit = document.getElementById("rowLimit");
  rowLimit.value = sampleInfo.requested_limit ? String(sampleInfo.requested_limit) : "";
}

function renderStatsTable(data) {
  const metrics = ["count", "mean", "std", "min", "25%", "50%", "75%", "max"];
  const columns = Object.keys(data);
  const head = document.getElementById("overviewStatsHead");
  const body = document.getElementById("overviewStatsBody");
  clearElement(head);
  clearElement(body);
  appendTableRow(head, ["Метрика", ...columns], "th");
  metrics.forEach((metric) => {
    appendTableRow(
      body,
      [
        metric,
        ...columns.map((col) => {
          const value = data[col]?.[metric];
          if (value === undefined || value === "") {
            return "-";
          }
          return Number.isFinite(Number(value)) ? Number(value).toFixed(3) : value;
        })
      ]
    );
  });
  document.getElementById("overviewStatsWrap").style.display = "block";
}

async function loadAnalysisColumns() {
  try {
    const data = await apiRequest("/columns", { method: "GET" });
    setDatasetContextFromPayload(data);
    const numeric = data.numeric_columns || [];
    populateSelectWithPlaceholder("corrX", numeric, "Оберіть X");
    populateSelectWithPlaceholder("corrY", numeric, "Оберіть Y");
    populateSelectWithPlaceholder("regX", numeric, "Оберіть ознаку");
    populateSelectWithPlaceholder("regY", numeric, "Оберіть ціль");
    populateSelectWithPlaceholder("distColumn", data.columns || [], "Оберіть колонку");
    renderSampleInfo(data.sample_info);
    setStatus("analysisStatus", "Колонки для аналізу завантажено", "ok");
  } catch (error) {
    setStatus("analysisStatus", error.message, "error");
  }
}

async function applyLimit(limitValue) {
  try {
    const data = await apiRequest("/limit", {
      method: "POST",
      body: JSON.stringify({ limit: limitValue })
    });
    setDatasetContextFromPayload(data);
    renderSampleInfo(data.sample_info);
    await loadAnalysisColumns();
    setStatus("analysisStatus", "Вибірку оновлено", "ok");
  } catch (error) {
    setStatus("analysisStatus", error.message, "error");
  }
}

async function loadStats() {
  try {
    const stats = await apiRequest("/statistics", { method: "GET" });
    renderStatsTable(stats);
    setStatus("analysisStatus", "Описову статистику завантажено", "ok");
  } catch (error) {
    setStatus("analysisStatus", error.message, "error");
  }
}

async function showDistribution() {
  const column = document.getElementById("distColumn").value;
  const bins = Number(document.getElementById("distBins").value);
  if (!column) {
    setStatus("analysisStatus", "Спочатку оберіть колонку", "error");
    return;
  }
  try {
    const data = await apiRequest("/histogram", {
      method: "POST",
      body: JSON.stringify({ column, bins })
    });
    if (distChart) {
      distChart.destroy();
    }
    const labels =
      data.kind === "categorical"
        ? data.labels
        : data.edges.slice(0, -1).map((edge, idx) => `${edge.toFixed(1)}-${data.edges[idx + 1].toFixed(1)}`);
    distChart = new Chart(document.getElementById("distChart"), {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: `Розподіл ${column}`,
            data: data.counts,
            backgroundColor: "rgba(83,111,149,0.5)",
            borderColor: "#536f95",
            borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxRotation: 45, minRotation: 0 } },
          y: { beginAtZero: true }
        }
      }
    });
    saveAnalysisState({ distribution: data, distributionInput: { column, bins } });
    setStatus("analysisStatus", "Розподіл побудовано", "ok");
  } catch (error) {
    setStatus("analysisStatus", error.message, "error");
  }
}

function validatePair(colX, colY) {
  if (!colX || !colY) {
    throw new Error("Оберіть обидві колонки");
  }
  if (colX === colY) {
    throw new Error("Колонки мають бути різними");
  }
}

function trendKindLabel(kind) {
  return kind === "grouped" ? "Групи" : "Інтервали";
}

function trendStatusText(kind) {
  const axisMode = kind === "grouped" ? "групами X" : "інтервалами X";
  return `Графік показує середнє значення Y за ${axisMode}, тому він відображає закономірність без шуму окремих точок`;
}

function renderTrendChart(canvasId, oldChart, title, trend, regression = null) {
  if (oldChart) {
    oldChart.destroy();
  }

  const points = trend?.points || [];
  const labels = points.map((point) => point.label);
  const averages = points.map((point) => point.y);
  const datasets = [
    {
      type: "bar",
      label: trend?.y_label || "Середнє значення",
      data: averages,
      backgroundColor: "rgba(83,111,149,0.52)",
      borderColor: "#536f95",
      borderWidth: 1,
      borderRadius: 6,
      maxBarThickness: 44
    }
  ];

  if (regression) {
    datasets.push({
      type: "line",
      label: "Лінія регресії",
      data: points.map((point) => regression.slope * point.x + regression.intercept),
      borderColor: "#41685d",
      backgroundColor: "#41685d",
      pointRadius: 0,
      pointHoverRadius: 0,
      borderWidth: 2,
      tension: 0.2
    });
  }

  return new Chart(document.getElementById(canvasId), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        title: { display: true, text: title },
        tooltip: {
          callbacks: {
            label(context) {
              const point = points[context.dataIndex] || {};
              const value = context.dataset.data[context.dataIndex];
              if (context.dataset.type === "line") {
                return `Лінія регресії: ${formatNumber(value)}`;
              }
              return `${trend?.y_label || "Середнє"}: ${formatNumber(value)}, рядків: ${point.count ?? "-"}`;
            }
          }
        }
      },
      scales: {
        x: {
          title: { display: true, text: trend?.x_label || "X" },
          grid: { display: false }
        },
        y: {
          beginAtZero: false,
          title: { display: true, text: trend?.y_label || "Y" }
        }
      }
    }
  });
}

function saveAnalysisState(partial) {
  analysisState = { ...analysisState, ...partial, savedAt: new Date().toISOString() };
  saveLocalState("analysis/latest", analysisState);
  saveServerState("analysis/latest", analysisState).catch(() => {});
}

function colorForCorrelation(value) {
  const numeric = Number(value) || 0;
  const alpha = Math.min(0.72, 0.12 + Math.abs(numeric) * 0.6);
  return numeric >= 0
    ? `rgba(83, 111, 149, ${alpha})`
    : `rgba(175, 120, 102, ${alpha})`;
}

function renderCorrelationMatrix(data) {
  const wrap = document.getElementById("correlationMatrixWrap");
  clearElement(wrap);
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const body = document.createElement("tbody");
  appendTableRow(head, ["", ...(data.columns || [])], "th");
  (data.matrix || []).forEach((row, rowIndex) => {
    const tr = document.createElement("tr");
    appendTextElement(tr, "th", data.columns[rowIndex]);
    row.forEach((value) => {
      const cell = appendTextElement(tr, "td", formatNumber(value, 3));
      cell.style.backgroundColor = colorForCorrelation(value);
    });
    body.appendChild(tr);
  });
  table.appendChild(head);
  table.appendChild(body);
  wrap.appendChild(table);
}

async function runCorrelationMatrix() {
  try {
    const method = document.getElementById("matrixMethod").value;
    const data = await apiRequest("/correlation/matrix", {
      method: "POST",
      body: JSON.stringify({ method })
    });
    renderCorrelationMatrix(data);
    saveAnalysisState({ correlationMatrix: data, matrixMethod: method });
    setStatus("analysisStatus", "Матрицю кореляцій побудовано", "ok");
  } catch (error) {
    setStatus("analysisStatus", error.message, "error");
  }
}

function renderSavedDistribution(data, input = {}) {
  if (!data) {
    return;
  }
  if (distChart) {
    distChart.destroy();
  }
  const labels =
    data.kind === "categorical"
      ? data.labels
      : data.edges.slice(0, -1).map((edge, idx) => `${edge.toFixed(1)}-${data.edges[idx + 1].toFixed(1)}`);
  distChart = new Chart(document.getElementById("distChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: `Розподіл ${input.column || data.column}`,
          data: data.counts,
          backgroundColor: "rgba(83,111,149,0.5)",
          borderColor: "#536f95",
          borderWidth: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxRotation: 45, minRotation: 0 } },
        y: { beginAtZero: true }
      }
    }
  });
}

async function restoreAnalysisState() {
  try {
    const serverState = await loadServerState("analysis/latest");
    if (serverState?.payload) {
      analysisState = serverState.payload;
    }
  } catch (error) {
    // Local state is already loaded.
  }
  if (analysisState.distribution) {
    renderSavedDistribution(analysisState.distribution, analysisState.distributionInput);
  }
  if (analysisState.correlationMatrix) {
    document.getElementById("matrixMethod").value = analysisState.matrixMethod || analysisState.correlationMatrix.method || "pearson";
    renderCorrelationMatrix(analysisState.correlationMatrix);
  }
  if (analysisState.correlation) {
    correlationChart = renderTrendChart(
      "correlationChart",
      correlationChart,
      `${analysisState.correlationInput?.colX || ""} vs ${analysisState.correlationInput?.colY || ""}`,
      analysisState.correlation.trend
    );
    renderCards("correlationCards", [
      { label: "Метод", value: analysisState.correlation.method },
      { label: "Коефіцієнт", value: formatNumber(analysisState.correlation.coefficient) },
      { label: "Рядків використано", value: analysisState.correlation.rows_used },
      { label: "Агрегація", value: trendKindLabel(analysisState.correlation.trend?.kind) }
    ]);
    renderInsightList("correlationInsights", analysisState.correlation.insights || []);
  }
  if (analysisState.regression) {
    regressionChart = renderTrendChart(
      "regressionChart",
      regressionChart,
      `${analysisState.regressionInput?.colX || ""} прогнозує ${analysisState.regressionInput?.colY || ""}`,
      analysisState.regression.trend,
      { slope: analysisState.regression.slope, intercept: analysisState.regression.intercept }
    );
    renderCards("regressionCards", [
      { label: "Нахил", value: formatNumber(analysisState.regression.slope) },
      { label: "Вільний член", value: formatNumber(analysisState.regression.intercept) },
      { label: "R2", value: formatNumber(analysisState.regression.r2) },
      { label: "Рядків використано", value: analysisState.regression.rows_used },
      { label: "Агрегація", value: trendKindLabel(analysisState.regression.trend?.kind) }
    ]);
    renderInsightList("regressionInsights", analysisState.regression.insights || []);
  }
}

async function runCorrelation() {
  try {
    const colX = document.getElementById("corrX").value;
    const colY = document.getElementById("corrY").value;
    const method = document.getElementById("corrMethod").value;
    validatePair(colX, colY);
    const data = await apiRequest("/correlation", {
      method: "POST",
      body: JSON.stringify({ col_x: colX, col_y: colY, method })
    });
    renderCards("correlationCards", [
      { label: "Метод", value: data.method },
      { label: "Коефіцієнт", value: formatNumber(data.coefficient) },
      { label: "Рядків використано", value: data.rows_used },
      { label: "Агрегація", value: trendKindLabel(data.trend?.kind) }
    ]);
    correlationChart = renderTrendChart(
      "correlationChart",
      correlationChart,
      `${colX} vs ${colY}`,
      data.trend
    );
    renderInsightList("correlationInsights", data.insights || []);
    saveAnalysisState({ correlation: data, correlationInput: { colX, colY, method } });
    setStatus("analysisStatus", trendStatusText(data.trend?.kind), "ok");
  } catch (error) {
    setStatus("analysisStatus", error.message, "error");
  }
}

async function runRegression() {
  try {
    const colX = document.getElementById("regX").value;
    const colY = document.getElementById("regY").value;
    validatePair(colX, colY);
    const data = await apiRequest("/regression", {
      method: "POST",
      body: JSON.stringify({ col_x: colX, col_y: colY })
    });
    renderCards("regressionCards", [
      { label: "Нахил", value: formatNumber(data.slope) },
      { label: "Вільний член", value: formatNumber(data.intercept) },
      { label: "R2", value: formatNumber(data.r2) },
      { label: "Рядків використано", value: data.rows_used },
      { label: "Агрегація", value: trendKindLabel(data.trend?.kind) }
    ]);
    regressionChart = renderTrendChart(
      "regressionChart",
      regressionChart,
      `${colX} прогнозує ${colY}`,
      data.trend,
      { slope: data.slope, intercept: data.intercept }
    );
    renderInsightList("regressionInsights", data.insights || []);
    saveAnalysisState({ regression: data, regressionInput: { colX, colY } });
    setStatus("analysisStatus", trendStatusText(data.trend?.kind), "ok");
  } catch (error) {
    setStatus("analysisStatus", error.message, "error");
  }
}

document.getElementById("applyLimitBtn").addEventListener("click", () => {
  applyLimit(document.getElementById("rowLimit").value);
});
document.getElementById("resetLimitBtn").addEventListener("click", () => {
  document.getElementById("rowLimit").value = "";
  applyLimit(null);
});
document.getElementById("loadStatsBtn").addEventListener("click", loadStats);
document.getElementById("distBtn").addEventListener("click", showDistribution);
document.getElementById("runCorrelationBtn").addEventListener("click", runCorrelation);
document.getElementById("matrixBtn").addEventListener("click", runCorrelationMatrix);
document.getElementById("runRegressionBtn").addEventListener("click", runRegression);

loadAnalysisColumns().then(restoreAnalysisState);
