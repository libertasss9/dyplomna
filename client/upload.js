if (ensureAuthOrRedirect()) {
  renderNav("upload");
}

function renderUploadSummary(data) {
  const container = document.getElementById("uploadSummaryCards");
  clearElement(container);
  const shape = Array.isArray(data.shape) ? data.shape : [data.rows_count ?? "-", data.columns_count ?? "-"];
  const items = [
    { label: "Рядки", value: shape[0] },
    { label: "Колонки", value: shape[1] },
    { label: "Пропуски", value: data.quality?.missing_total ?? "-" },
    { label: "Рекомендовані цілі", value: data.target_suggestions?.length ?? 0 }
  ];
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "metric-card";
    appendTextElement(card, "div", item.label, "metric-label");
    appendTextElement(card, "div", item.value, "metric-value");
    container.appendChild(card);
  });
}

function renderPreview(records) {
  const head = document.getElementById("previewHead");
  const body = document.getElementById("previewBody");
  clearElement(head);
  clearElement(body);
  if (!records || records.length === 0) {
    return;
  }

  const columns = Object.keys(records[0]);
  appendTableRow(head, columns, "th");
  records.forEach((row) => {
    appendTableRow(
      body,
      columns.map((col) => row[col])
    );
  });
}

function renderNextStep(data) {
  const container = document.getElementById("uploadNextStep");
  clearElement(container);
  const link = document.createElement("a");
  link.href = "clean.html?v=20260614-1";
  link.textContent = data.target_suggestions?.length
    ? "Перейти до очищення та перевірити якість даних"
    : "Перейти до очищення та за потреби створити класову колонку";
  container.appendChild(link);
}

async function upload() {
  const fileInput = document.getElementById("fileInput");
  const file = fileInput.files[0];
  if (!file) {
    setStatus("uploadStatus", "Оберіть CSV-файл", "error");
    return;
  }
  if (!file.name.toLowerCase().endsWith(".csv")) {
    setStatus("uploadStatus", "Дозволено лише CSV-файли", "error");
    return;
  }

  try {
    const formData = new FormData();
    formData.append("file", file);
    const data = await apiRequest("/upload", { method: "POST", body: formData });
    setDatasetContextFromPayload(data, { clearScopedState: true });
    const shape = Array.isArray(data.shape) ? data.shape : [data.rows_count ?? "-", data.columns_count ?? "-"];
    setStatus("uploadStatus", `Завантажено ${shape[0]} рядків і ${shape[1]} колонок`, "ok");
    renderUploadSummary(data);
    renderPreview(data.preview);
    renderInsightList("uploadWarnings", data.quality_warnings || []);
    renderNextStep(data);
  } catch (error) {
    setStatus("uploadStatus", error.message, "error");
  }
}

document.getElementById("uploadBtn").addEventListener("click", upload);
