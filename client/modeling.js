if (ensureAuthOrRedirect()) {
  renderNav("modeling");
}

let modelChart = null;
let importanceChart = null;
let classDistributionChart = null;
let modelingOptions = null;
let modelingPollTimer = null;

function modelTargetOption(column) {
  return (modelingOptions?.targets || []).find((item) => item.column === column) || null;
}

function renderProgressSteps(stepText, progress, status = "running") {
  const container = document.getElementById("modelProgressSteps");
  clearElement(container);
  const steps = [
    "Перевірка цілі",
    "Вибір ознак",
    "Обробка пропусків",
    "Навчання моделей",
    "Розрахунок метрик"
  ];
  const activeIndex = Math.min(steps.length - 1, Math.floor((Number(progress) || 0) / 22));
  steps.forEach((step, index) => {
    const item = document.createElement("div");
    item.className = "progress-step";
    if (status === "done" || index < activeIndex) {
      item.classList.add("done");
    }
    if (status === "error") {
      item.classList.toggle("done", index < activeIndex);
      item.classList.toggle("active", index === activeIndex);
      item.classList.toggle("error", index === activeIndex);
    } else if (status === "running" && index === activeIndex) {
      item.classList.add("active");
    }
    appendTextElement(item, "span", String(index + 1), "progress-step-index");
    const text = status !== "done" && index === activeIndex ? stepText || step : step;
    appendTextElement(item, "strong", text);
    container.appendChild(item);
  });
}

function setModelingBusy(isBusy) {
  const button = document.getElementById("runModelBtn");
  const target = document.getElementById("modelTarget");
  const taskType = document.getElementById("modelTaskType");
  button.disabled = isBusy;
  target.disabled = isBusy;
  taskType.disabled = isBusy;
  button.textContent = isBusy ? "Моделі обчислюються..." : "Запустити моделі";
}

function updateModelingProgress(job) {
  const status = job?.status || "running";
  const progress = status === "done" ? 100 : Number(job?.progress || 0);
  const panel = document.getElementById("modelProgress");
  panel.classList.remove("hidden", "running", "done", "error");
  panel.classList.add(status === "error" ? "error" : status === "done" ? "done" : "running");
  document.getElementById("modelProgressTitle").textContent = job?.step || "Моделювання виконується";
  document.getElementById("modelProgressElapsed").textContent = `${progress}%`;
  document.getElementById("modelProgressBar").style.width = `${Math.max(1, Math.min(100, progress))}%`;
  document.getElementById("modelProgressHint").textContent =
    job?.status === "running"
      ? "Задача виконується на сервері. Можна перейти на іншу сторінку, а потім повернутися до результату."
      : job?.status === "error"
        ? "Обчислення зупинено через помилку. Перевірте параметри та запустіть задачу ще раз."
      : "Результат збережено для поточного користувача.";
  renderProgressSteps(job?.step, progress, status);
}

function stopPolling() {
  if (modelingPollTimer) {
    window.clearInterval(modelingPollTimer);
    modelingPollTimer = null;
  }
}

function clearActiveModelingJob() {
  stopPolling();
  setModelingBusy(false);
  localStorage.removeItem(userStateKey("modeling/job"));
}

async function restoreSavedModelingResult() {
  try {
    const state = await loadServerState("modeling/latest");
    if (state?.payload) {
      renderModelingResult(state.payload);
      setStatus("modelStatus", "Відновлено останній результат моделювання", "ok");
      return true;
    }
  } catch (error) {
    const local = loadLocalState("modeling/latest");
    if (local) {
      renderModelingResult(local);
      setStatus("modelStatus", "Відновлено локально збережений результат моделювання", "ok");
      return true;
    }
  }
  return false;
}

function populateModelTargets(options) {
  const select = document.getElementById("modelTarget");
  clearElement(select);
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.disabled = true;
  placeholder.selected = true;
  placeholder.textContent = "Оберіть цільову колонку";
  select.appendChild(placeholder);

  (options.targets || []).forEach((item) => {
    const option = document.createElement("option");
    option.value = item.column;
    const modes = item.task_types?.length ? item.task_types.join(", ") : "не пропонується";
    option.textContent = `${item.column} (${modes})`;
    option.disabled = !item.task_types?.length;
    if (item.column === options.default_target) {
      option.selected = true;
      placeholder.selected = false;
    }
    select.appendChild(option);
  });
}

function renderTargetExplanation() {
  const target = document.getElementById("modelTarget").value;
  const selected = modelTargetOption(target);
  const rejected = (modelingOptions?.targets || [])
    .filter((item) => !item.task_types?.length)
    .slice(0, 5);
  const items = [];
  if (selected) {
    items.push({
      level: selected.task_types?.length ? "ok" : "warning",
      title: selected.column,
      message: selected.reason
    });
  }
  if (rejected.length) {
    items.push({
      level: "info",
      title: "Чому частина колонок не пропонується",
      message: rejected.map((item) => `${item.column}: ${item.reason}`).join("; ")
    });
  }
  renderInsightList("targetExplanation", items, "Оберіть ціль, щоб побачити пояснення");
}

function featureLabel(item) {
  const role = item.semantic_role && item.semantic_role !== "unspecified"
    ? `${item.role}, ${item.semantic_role}`
    : item.role;
  return `${item.column} (${role || "ознака"})`;
}

function renderFeatureChecklist(options) {
  const container = document.getElementById("featureChecklist");
  clearElement(container);
  const items = Array.isArray(options) ? options : [];
  if (!items.length) {
    appendTextElement(container, "p", "Оберіть цільову колонку, щоб сформувати список ознак.", "muted");
    return;
  }

  items.forEach((item) => {
    if (item.locked) {
      return;
    }
    const label = document.createElement("label");
    label.className = item.selected ? "check-row compact feature-row" : "check-row compact feature-row muted-feature";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = item.column;
    checkbox.checked = Boolean(item.selected);
    checkbox.dataset.featureColumn = "true";
    const text = document.createElement("span");
    text.textContent = featureLabel(item);
    const reason = document.createElement("small");
    reason.textContent = item.reason || "";
    label.appendChild(checkbox);
    label.appendChild(text);
    label.appendChild(reason);
    container.appendChild(label);
  });

  renderFeatureWarnings(items);
}

function renderFeatureWarnings(items) {
  const excluded = (items || []).filter((item) => !item.selected && !item.locked);
  renderInsightList(
    "featureWarnings",
    excluded.slice(0, 8).map((item) => ({
      level: "info",
      title: item.column,
      message: item.reason
    })),
    "Автоматичних виключень немає"
  );
}

function selectedFeatures() {
  return Array.from(document.querySelectorAll("[data-feature-column='true']:checked")).map(
    (checkbox) => checkbox.value
  );
}

async function loadModelOptions(target = "") {
  const path = target ? `/modeling/options?target=${encodeURIComponent(target)}` : "/modeling/options";
  modelingOptions = await apiRequest(path, { method: "GET" });
  setDatasetContextFromPayload(modelingOptions);
  if (!target) {
    populateModelTargets(modelingOptions);
  }
  renderTargetExplanation();
  renderFeatureChecklist(modelingOptions.feature_options || []);
}

function renderModelMetrics(data) {
  const head = document.getElementById("modelMetricsHead");
  const body = document.getElementById("modelMetricsBody");
  clearElement(head);
  clearElement(body);

  if (data.task_type === "regression") {
    appendTableRow(head, ["Модель", "MAE", "RMSE", "R2"], "th");
    data.models.forEach((model) => {
      appendTableRow(body, [
        model.name,
        formatNumber(model.mae),
        formatNumber(model.rmse),
        formatNumber(model.r2)
      ]);
    });
  } else {
    appendTableRow(head, ["Модель", "Accuracy", "Balanced accuracy", "Macro F1", "Weighted F1"], "th");
    data.models.forEach((model) => {
      appendTableRow(body, [
        model.name,
        formatNumber(model.accuracy),
        formatNumber(model.balanced_accuracy),
        formatNumber(model.f1_macro),
        formatNumber(model.f1_weighted)
      ]);
    });
  }

  if (modelChart) {
    modelChart.destroy();
  }
  const metricName = data.task_type === "regression" ? "r2" : "balanced_accuracy";
  modelChart = new Chart(document.getElementById("modelChart"), {
    type: "bar",
    data: {
      labels: data.models.map((model) => model.name),
      datasets: [
        {
          label: data.task_type === "regression" ? "R2" : "Balanced accuracy",
          data: data.models.map((model) => model[metricName]),
          backgroundColor: ["rgba(83,111,149,0.5)", "rgba(104,143,131,0.52)"],
          borderColor: ["#536f95", "#41685d"],
          borderWidth: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: data.task_type !== "regression" } }
    }
  });
}

function renderClassDistribution(data) {
  const wrap = document.getElementById("classDistributionWrap");
  if (classDistributionChart) {
    classDistributionChart.destroy();
    classDistributionChart = null;
  }
  if (data.task_type !== "classification" || !data.class_distribution) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "block";
  const entries = Object.entries(data.class_distribution);
  classDistributionChart = new Chart(document.getElementById("classDistributionChart"), {
    type: "bar",
    data: {
      labels: entries.map(([label]) => label),
      datasets: [
        {
          label: "Розподіл класів",
          data: entries.map(([, count]) => count),
          backgroundColor: "rgba(141,128,168,0.48)",
          borderColor: "#8d80a8",
          borderWidth: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, title: { display: true, text: "Розподіл класів" } },
      scales: { y: { beginAtZero: true } }
    }
  });
}

function renderModelSummary(data) {
  const container = document.getElementById("modelSummaryCards");
  clearElement(container);
  const items = [
    { label: "Режим", value: data.task_type === "regression" ? "Регресія" : "Класифікація" },
    { label: "Вибірка", value: sampleInfoLabel(data.sample_info) },
    { label: "Навчання", value: data.rows_train },
    { label: "Тест", value: data.rows_test },
    { label: "Ознак", value: data.preprocessing?.selected_features?.length ?? "-" },
    { label: "Після кодування", value: data.preprocessing?.encoded_features_count ?? "-" },
    { label: "Ціль", value: data.target }
  ];
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "metric-card";
    appendTextElement(card, "div", item.label, "metric-label");
    appendTextElement(card, "div", item.value, "metric-value");
    container.appendChild(card);
  });
}

function renderFeatureImportance(items) {
  const body = document.getElementById("importanceBody");
  clearElement(body);
  (items || []).forEach((item) => appendTableRow(body, [item.feature, formatNumber(item.importance)]));

  if (importanceChart) {
    importanceChart.destroy();
  }
  importanceChart = new Chart(document.getElementById("importanceChart"), {
    type: "bar",
    data: {
      labels: (items || []).map((item) => item.feature),
      datasets: [
        {
          label: "Importance",
          data: (items || []).map((item) => item.importance),
          backgroundColor: "rgba(141,128,168,0.48)",
          borderColor: "#8d80a8",
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
}

function renderConfusionMatrix(data) {
  const model = data.task_type === "classification" ? data.models?.[0] : null;
  const head = document.getElementById("confusionHead");
  const body = document.getElementById("confusionBody");
  clearElement(head);
  clearElement(body);
  if (!model || !model.confusion_matrix || !model.labels) {
    renderEmptyRow(body, 1, data.task_type === "regression" ? "Для регресії матриця помилок не застосовується" : "Матриця помилок недоступна");
    return;
  }
  appendTableRow(head, ["Факт / прогноз", ...model.labels], "th");
  const maxValue = Math.max(...model.confusion_matrix.flat(), 1);
  model.confusion_matrix.forEach((row, index) => {
    const tableRow = document.createElement("tr");
    appendTextElement(tableRow, "td", model.labels[index]);
    row.forEach((value) => {
      const cell = appendTextElement(tableRow, "td", value);
      const alpha = 0.12 + (Number(value) / maxValue) * 0.58;
      cell.style.backgroundColor = `rgba(83, 111, 149, ${alpha})`;
    });
    body.appendChild(tableRow);
  });
}

function renderPreprocessingInsights(data) {
  const extra = [];
  if (data.sample_info) {
    extra.push({
      level: "info",
      title: "Використана вибірка",
      message: sampleInfoDescription(data.sample_info)
    });
  }
  if (data.preprocessing?.missing_actions?.length) {
    extra.push({
      level: "info",
      title: "Обробка пропусків",
      message: data.preprocessing.missing_actions.join("; ")
    });
  }
  if (data.excluded_features?.length) {
    extra.push({
      level: "info",
      title: "Автоматично виключені ознаки",
      message: data.excluded_features.slice(0, 8).map((item) => `${item.column}: ${item.reason}`).join("; ")
    });
  }
  renderInsightList("modelInsights", [...(data.insights || []), ...extra]);
}

function renderModelingResult(data) {
  renderModelSummary(data);
  renderClassDistribution(data);
  renderModelMetrics(data);
  renderFeatureImportance(data.feature_importance || []);
  renderConfusionMatrix(data);
  renderPreprocessingInsights(data);
  saveLocalState("modeling/latest", data);
}

async function pollModelingJob(jobId) {
  let job;
  try {
    job = await apiRequest(`/modeling/jobs/${jobId}`, { method: "GET" });
  } catch (error) {
    clearActiveModelingJob();
    const restored = await restoreSavedModelingResult();
    if (restored) {
      updateModelingProgress({ progress: 100, step: "Результат моделювання відновлено", status: "done" });
      return;
    }
    const staleJob = String(error.message || "").toLowerCase().includes("not found");
    updateModelingProgress({ progress: 100, step: "Моделювання неактивне", status: "error" });
    setStatus(
      "modelStatus",
      staleJob
        ? "Попередня задача моделювання вже недоступна після перезапуску сервера. Оберіть ціль і запустіть моделі ще раз."
        : error.message,
      staleJob ? "ok" : "error"
    );
    return;
  }
  updateModelingProgress(job);
  if (job.status === "done") {
    clearActiveModelingJob();
    renderModelingResult(job.result);
    setStatus("modelStatus", `Моделі навчені (train: ${job.result.rows_train}, test: ${job.result.rows_test})`, "ok");
    return;
  }
  if (job.status === "error") {
    clearActiveModelingJob();
    setStatus("modelStatus", job.error || "Помилка моделювання", "error");
  }
}

async function runModeling() {
  const target = document.getElementById("modelTarget").value;
  if (!target) {
    setStatus("modelStatus", "Спочатку оберіть цільову колонку", "error");
    return;
  }
  const features = selectedFeatures();
  if (!features.length) {
    setStatus("modelStatus", "Оберіть хоча б одну ознаку для моделювання", "error");
    return;
  }
  setModelingBusy(true);
  updateModelingProgress({ progress: 1, step: "Запуск задачі моделювання", status: "running" });
  setStatus("modelStatus", "Моделювання запущено на сервері.", "ok");

  try {
    const data = await apiRequest("/modeling/jobs", {
      method: "POST",
      body: JSON.stringify({
        target,
        task_type: document.getElementById("modelTaskType").value,
        features
      })
    });
    localStorage.setItem(userStateKey("modeling/job"), data.job_id);
    stopPolling();
    modelingPollTimer = window.setInterval(() => pollModelingJob(data.job_id), 1200);
    await pollModelingJob(data.job_id);
  } catch (error) {
    clearActiveModelingJob();
    updateModelingProgress({ progress: 100, step: "Помилка запуску моделювання", status: "error" });
    setStatus("modelStatus", error.message, "error");
  }
}

async function restoreModelingState() {
  const activeJobId = localStorage.getItem(userStateKey("modeling/job"));
  if (activeJobId) {
    setModelingBusy(true);
    modelingPollTimer = window.setInterval(() => pollModelingJob(activeJobId), 1200);
    await pollModelingJob(activeJobId);
    return;
  }
  await restoreSavedModelingResult();
}

function setRecommendedFeatures(onlyRecommended) {
  document.querySelectorAll("[data-feature-column='true']").forEach((checkbox) => {
    checkbox.checked = onlyRecommended
      ? Boolean((modelingOptions.feature_options || []).find((item) => item.column === checkbox.value)?.selected)
      : true;
  });
}

document.getElementById("runModelBtn").addEventListener("click", runModeling);
document.getElementById("modelTarget").addEventListener("change", async (event) => {
  await loadModelOptions(event.target.value);
});
document.getElementById("selectRecommendedFeaturesBtn").addEventListener("click", () => setRecommendedFeatures(true));
document.getElementById("selectAllFeaturesBtn").addEventListener("click", () => setRecommendedFeatures(false));

(async function initModelingPage() {
  try {
    await loadModelOptions();
    await restoreModelingState();
  } catch (error) {
    setStatus("modelStatus", error.message, "error");
  }
})();
