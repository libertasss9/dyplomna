if (ensureAuthOrRedirect()) {
  renderNav("report");
}

function renderReportSection(container, title, items) {
  const section = document.createElement("div");
  section.className = "report-section";
  appendTextElement(section, "h3", title);
  const list = document.createElement("ul");
  (items || []).forEach((item) => appendTextElement(list, "li", item));
  section.appendChild(list);
  container.appendChild(section);
}

function renderWorkflowReport(container, workflow) {
  const section = document.createElement("div");
  section.className = "report-section";
  appendTextElement(section, "h3", "Стан виконання етапів");
  const list = document.createElement("div");
  list.className = "workflow-report";
  workflow.forEach((step) => {
    const item = document.createElement("div");
    item.className = `workflow-report-item ${step.status}`;
    appendTextElement(item, "strong", step.step);
    appendTextElement(item, "span", step.detail);
    list.appendChild(item);
  });
  section.appendChild(list);
  container.appendChild(section);
}

function renderTargetReport(container, targets) {
  const section = document.createElement("div");
  section.className = "report-section";
  appendTextElement(section, "h3", "Цільові колонки");
  if (!targets?.length) {
    appendTextElement(section, "p", "Потенційних цільових колонок не знайдено.", "muted");
    container.appendChild(section);
    return;
  }
  targets.forEach((target) => {
    const block = document.createElement("div");
    block.className = "target-report";
    appendTextElement(block, "strong", target.column);
    if (target.description) {
      appendTextElement(block, "p", target.description);
    }
    const classes = (target.classes || [])
      .slice(0, 5)
      .map((item) => `${item.value}: ${item.count} (${formatNumber(item.percent, 2)}%)${item.description ? ` - ${item.description}` : ""}`)
      .join("; ");
    appendTextElement(block, "small", classes || "Немає даних про класи");
    section.appendChild(block);
  });
  container.appendChild(section);
}

function renderModelReport(container, modelResult) {
  const section = document.createElement("div");
  section.className = "report-section";
  appendTextElement(section, "h3", "Останнє моделювання");
  if (!modelResult) {
    appendTextElement(section, "p", "Моделі ще не запускались або результат не збережено.", "muted");
    container.appendChild(section);
    return;
  }

  const overview = [
    `Ціль: ${modelResult.target}`,
    `Режим: ${modelResult.task_type === "regression" ? "регресія" : "класифікація"}`,
    `Вибірка: ${sampleInfoLabel(modelResult.sample_info)}`,
    `Навчальна вибірка: ${modelResult.rows_train}`,
    `Тестова вибірка: ${modelResult.rows_test}`,
    `Використано ознак: ${modelResult.preprocessing?.selected_features?.length ?? "-"}`
  ];
  const list = document.createElement("ul");
  overview.forEach((item) => appendTextElement(list, "li", item));
  section.appendChild(list);

  const tableWrap = document.createElement("div");
  tableWrap.className = "preview-table";
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const body = document.createElement("tbody");
  if (modelResult.task_type === "regression") {
    appendTableRow(head, ["Модель", "MAE", "RMSE", "R2"], "th");
    modelResult.models.forEach((model) => appendTableRow(body, [model.name, formatNumber(model.mae), formatNumber(model.rmse), formatNumber(model.r2)]));
  } else {
    appendTableRow(head, ["Модель", "Accuracy", "Balanced accuracy", "Macro F1", "Weighted F1"], "th");
    modelResult.models.forEach((model) => appendTableRow(body, [model.name, formatNumber(model.accuracy), formatNumber(model.balanced_accuracy), formatNumber(model.f1_macro), formatNumber(model.f1_weighted)]));
  }
  table.appendChild(head);
  table.appendChild(body);
  tableWrap.appendChild(table);
  section.appendChild(tableWrap);

  if (modelResult.feature_importance?.length) {
    appendTextElement(
      section,
      "p",
      `Найважливіші ознаки: ${modelResult.feature_importance.slice(0, 5).map((item) => `${item.feature} (${formatNumber(item.importance)})`).join(", ")}.`
    );
  }
  if (modelResult.excluded_features?.length) {
    appendTextElement(
      section,
      "p",
      `Виключені ознаки: ${modelResult.excluded_features.slice(0, 5).map((item) => item.column).join(", ")}.`,
      "muted"
    );
  }
  container.appendChild(section);
}

async function loadSummaryReport() {
  const container = document.getElementById("summaryReport");
  clearElement(container);
  try {
    const report = await apiRequest("/report/summary", { method: "GET" });
    setDatasetContextFromPayload(report);
    renderReportSection(container, "Огляд", report.overview);
    renderWorkflowReport(container, report.workflow || []);

    const qualitySection = document.createElement("div");
    qualitySection.className = "report-section";
    appendTextElement(qualitySection, "h3", "Якість даних");
    const qualityList = document.createElement("div");
    qualityList.id = "summaryQualityWarnings";
    qualityList.className = "insight-list";
    qualitySection.appendChild(qualityList);
    container.appendChild(qualitySection);
    renderInsightList("summaryQualityWarnings", report.quality_warnings || []);

    renderReportSection(container, "Рекомендовані наступні дії", report.recommended_actions);
    renderTargetReport(container, report.target_summaries || []);
    renderModelReport(container, report.latest_model);
    setStatus("reportStatus", "Підсумковий звіт сформовано", "ok");
  } catch (error) {
    setStatus("reportStatus", error.message, "error");
  }
}

document.getElementById("summaryReportBtn").addEventListener("click", loadSummaryReport);
loadSummaryReport();
