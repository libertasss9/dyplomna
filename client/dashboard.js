if (ensureAuthOrRedirect()) {
  renderNav("dashboard");
}

let overviewColumns = [];
let columnProfiles = [];
let metadataByColumn = {};
let missingChart = null;

function roleLabel(role) {
  const labels = {
    continuous: "Неперервна",
    binary: "Бінарна",
    categorical_encoded: "Закодована категорія",
    categorical: "Категоріальна",
    text: "Текстова",
    constant: "Константна",
    feature: "Ознака",
    target: "Ціль",
    identifier: "Ідентифікатор",
    ignore: "Не використовувати",
    sensitive: "Чутлива",
    group: "Групувальна",
    unspecified: "Не визначено"
  };
  return labels[role] || role || "-";
}

function renderProfileCards(profile) {
  const container = document.getElementById("profileCards");
  clearElement(container);
  const items = [
    { label: "Рядки", value: profile.rows_count },
    { label: "Колонки", value: profile.columns_count },
    { label: "Вибірка", value: sampleInfoLabel(profile.sample_info) },
    { label: "Числові", value: profile.numeric_columns?.length ?? 0 },
    { label: "Категоріальні", value: (profile.categorical_columns?.length ?? 0) + (profile.categorical_encoded_columns?.length ?? 0) },
    { label: "Пропуски", value: profile.quality?.missing_total ?? 0 },
    { label: "Дублікати", value: profile.quality?.duplicate_rows ?? 0 },
    { label: "Цільові ознаки", value: profile.target_suggestions?.length ?? 0 },
    { label: "Метадані", value: `${profile.metadata_coverage?.percent ?? 0}%` }
  ];
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "metric-card";
    appendTextElement(card, "div", item.label, "metric-label");
    appendTextElement(card, "div", item.value, "metric-value");
    container.appendChild(card);
  });
}

function renderTargetProfiles(items) {
  const body = document.getElementById("targetProfileBody");
  clearElement(body);
  if (!items?.length) {
    renderEmptyRow(body, 5, "Система не знайшла очевидних цільових колонок");
    return;
  }
  items.forEach((item) => {
    const values = item.items
      .slice(0, 4)
      .map((value) => `${value.value}: ${value.count} (${formatNumber(value.percent, 2)}%)`)
      .join("; ");
    appendTableRow(body, [
      item.column,
      item.classes_count,
      `${formatNumber(item.coverage_percent, 2)}%`,
      item.imbalance_ratio ? formatNumber(item.imbalance_ratio, 2) : "-",
      values || "-"
    ]);
  });
}

function renderMetadataTable() {
  const body = document.getElementById("metadataBody");
  clearElement(body);
  if (!columnProfiles.length) {
    renderEmptyRow(body, 6, "Завантажте профіль даних");
    return;
  }
  columnProfiles.forEach((profile) => {
    const metadata = metadataByColumn[profile.name] || {};
    const classCount = Object.keys(metadata.class_descriptions || {}).length;
    appendTableRow(body, [
      profile.name,
      roleLabel(profile.role),
      roleLabel(metadata.semantic_role || "unspecified"),
      metadata.source_column || "-",
      metadata.description || "-",
      classCount ? `${classCount} описів` : "-"
    ]);
  });
}

function populateSourceColumnSelect(columns) {
  const select = document.getElementById("metaSourceColumn");
  clearElement(select);
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "Немає джерела";
  select.appendChild(empty);
  (columns || []).forEach((column) => {
    const option = document.createElement("option");
    option.value = column;
    option.textContent = column;
    select.appendChild(option);
  });
}

function fillMetadataForm(column) {
  const metadata = metadataByColumn[column] || {};
  document.getElementById("metaRole").value = metadata.semantic_role || "unspecified";
  document.getElementById("metaSourceColumn").value = metadata.source_column || "";
  document.getElementById("metaDescription").value = metadata.description || "";
  document.getElementById("metaClasses").value = keyValueObjectToLines(metadata.class_descriptions || {});
}

function clearMetadataForm() {
  document.getElementById("metaRole").value = "unspecified";
  document.getElementById("metaSourceColumn").value = "";
  document.getElementById("metaDescription").value = "";
  document.getElementById("metaClasses").value = "";
}

async function loadProfile() {
  try {
    const profile = await apiRequest("/dataset/profile", { method: "GET" });
    setDatasetContextFromPayload(profile);
    renderProfileCards(profile);
    renderInsightList("qualityWarnings", profile.quality_warnings || []);
    renderTargetProfiles(profile.target_profiles || []);
    overviewColumns = profile.columns || [];
    columnProfiles = profile.column_profiles || [];
    metadataByColumn = profile.metadata || {};
    populateSelectWithPlaceholder("metaColumn", overviewColumns, "Оберіть колонку");
    populateSourceColumnSelect(overviewColumns);
    renderMetadataTable();
    setStatus("dashboardStatus", "Профіль даних оновлено", "ok");
  } catch (error) {
    setStatus("dashboardStatus", error.message, "error");
  }
}

async function loadMissing() {
  try {
    const data = await apiRequest("/missing-values", { method: "GET" });
    const body = document.getElementById("missingBody");
    clearElement(body);
    data.items.forEach((item) => {
      appendTableRow(body, [item.column, item.missing_count, `${item.missing_percent}%`]);
    });
    const topMissing = data.items.filter((item) => item.missing_count > 0).slice(0, 12);
    if (missingChart) {
      missingChart.destroy();
    }
    missingChart = new Chart(document.getElementById("missingChart"), {
      type: "bar",
      data: {
        labels: topMissing.map((item) => item.column),
        datasets: [
          {
            label: "Пропуски",
            data: topMissing.map((item) => item.missing_count),
            backgroundColor: "rgba(175,120,102,0.45)",
            borderColor: "#8d554a",
            borderWidth: 1
          }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true }, y: { ticks: { autoSkip: false } } }
      }
    });
    setStatus("dashboardStatus", "Таблицю пропусків оновлено", "ok");
  } catch (error) {
    setStatus("dashboardStatus", error.message, "error");
  }
}

async function saveMetadata() {
  const column = document.getElementById("metaColumn").value;
  if (!column) {
    setStatus("metadataStatus", "Оберіть колонку для опису", "error");
    return;
  }
  try {
    const payload = {
      column,
      semantic_role: document.getElementById("metaRole").value,
      source_column: document.getElementById("metaSourceColumn").value,
      description: document.getElementById("metaDescription").value,
      class_descriptions: parseKeyValueLines(document.getElementById("metaClasses").value)
    };
    const data = await apiRequest("/metadata/column", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    metadataByColumn[column] = data.metadata;
    renderMetadataTable();
    setStatus("metadataStatus", "Опис колонки збережено", "ok");
  } catch (error) {
    setStatus("metadataStatus", error.message, "error");
  }
}

document.getElementById("profileBtn").addEventListener("click", loadProfile);
document.getElementById("missingBtn").addEventListener("click", loadMissing);
document.getElementById("saveMetaBtn").addEventListener("click", saveMetadata);
document.getElementById("clearMetaFormBtn").addEventListener("click", clearMetadataForm);
document.getElementById("metaColumn").addEventListener("change", (event) => fillMetadataForm(event.target.value));

loadProfile();
