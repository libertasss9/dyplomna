if (ensureAuthOrRedirect()) {
  renderNav("risk");
}

let riskChart = null;
let riskPollTimer = null;
let riskState = loadLocalState("risk/latest") || {};

function renderRiskProgressSteps(stepText, progress, status = "running") {
  const container = document.getElementById("riskProgressSteps");
  clearElement(container);
  const steps = [
    "Перевірка цілі",
    "Підготовка ознак",
    "Розрахунок кореляцій",
    "Сортування рейтингу",
    "Збереження результату"
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

function setRiskBusy(isBusy) {
  document.getElementById("riskRunBtn").disabled = isBusy;
  document.getElementById("riskTarget").disabled = isBusy;
  document.getElementById("riskMethod").disabled = isBusy;
  document.getElementById("riskRunBtn").textContent = isBusy ? "Рейтинг обчислюється..." : "Побудувати рейтинг";
}

function updateRiskProgress(job) {
  const status = job?.status || "running";
  const progress = status === "done" ? 100 : Number(job?.progress || 0);
  const panel = document.getElementById("riskProgress");
  panel.classList.remove("hidden", "running", "done", "error");
  panel.classList.add(status === "error" ? "error" : status === "done" ? "done" : "running");
  document.getElementById("riskProgressTitle").textContent = job?.step || "Рейтинг закономірностей обчислюється";
  document.getElementById("riskProgressPercent").textContent = `${progress}%`;
  document.getElementById("riskProgressBar").style.width = `${Math.max(1, Math.min(100, progress))}%`;
  document.getElementById("riskProgressHint").textContent =
    job?.status === "running"
      ? "Задача виконується на сервері. Можна перейти на іншу сторінку, а потім повернутися до результату."
      : job?.status === "error"
        ? "Обчислення зупинено через помилку. Перевірте параметри та запустіть задачу ще раз."
      : "Результат збережено для поточного користувача.";
  renderRiskProgressSteps(job?.step, progress, status);
}

function stopRiskPolling() {
  if (riskPollTimer) {
    window.clearInterval(riskPollTimer);
    riskPollTimer = null;
  }
}

function clearActiveRiskJob() {
  stopRiskPolling();
  setRiskBusy(false);
  localStorage.removeItem(userStateKey("risk/job"));
}

async function restoreSavedRiskResult() {
  try {
    const state = await loadServerState("risk/latest");
    if (state?.payload) {
      renderRiskResult(state.payload);
      setStatus("riskStatus", "Відновлено останній рейтинг закономірностей", "ok");
      return true;
    }
  } catch (error) {
    if (riskState?.items) {
      renderRiskResult(riskState);
      setStatus("riskStatus", "Відновлено локально збережений рейтинг", "ok");
      return true;
    }
  }
  return false;
}

function applyRiskInput(input = {}) {
  if (input.target && document.getElementById("riskTarget")) {
    document.getElementById("riskTarget").value = input.target;
  }
  if (input.method && document.getElementById("riskMethod")) {
    document.getElementById("riskMethod").value = input.method;
  }
}

async function loadRiskTargets() {
  try {
    const data = await apiRequest("/columns", { method: "GET" });
    setDatasetContextFromPayload(data);
    const targets = (data.target_suggestions || []).filter((item) => data.numeric_columns.includes(item));
    populateSelectWithPlaceholder(
      "riskTarget",
      targets.length ? targets : data.numeric_columns,
      "Оберіть цільову колонку"
    );
    setStatus("riskStatus", "Колонки для рейтингу завантажено", "ok");
  } catch (error) {
    riskState = {};
    setStatus("riskStatus", error.message, "error");
    return false;
  }
  return true;
}

function renderRiskResult(data) {
  const result = data || {};
  const top = (result.items || []).slice(0, 10);
  const body = document.getElementById("riskBody");
  clearElement(body);

  if (!top.length) {
    renderEmptyRow(body, 3, "Немає числових ознак з достатньою кількістю значень для рейтингу.");
  } else {
    top.forEach((item) => {
      appendTableRow(body, [
        item.feature,
        formatNumber(item.coefficient),
        item.rows_used ? String(item.rows_used) : "-"
      ]);
    });
  }

  if (riskChart) {
    riskChart.destroy();
  }
  riskChart = new Chart(document.getElementById("riskChart"), {
    type: "bar",
    data: {
      labels: top.map((item) => item.feature),
      datasets: [
        {
          label: `Кореляція з ${result.target || ""}`,
          data: top.map((item) => item.coefficient),
          backgroundColor: top.map((item) =>
            item.coefficient >= 0 ? "rgba(83,111,149,0.5)" : "rgba(175,120,102,0.45)"
          ),
          borderColor: top.map((item) => (item.coefficient >= 0 ? "#536f95" : "#8d554a")),
          borderWidth: 1
        }
      ]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { min: -1, max: 1 }, y: { ticks: { autoSkip: false } } }
    }
  });

  const sampleInsight = result.sample_info
    ? [{ level: "info", title: "Використана вибірка", message: sampleInfoDescription(result.sample_info) }]
    : [];
  renderInsightList("riskInsights", [...(result.insights || []), ...sampleInsight]);
  riskState = { ...result, savedAt: new Date().toISOString() };
  saveLocalState("risk/latest", riskState);
  applyRiskInput(result.input || { target: result.target, method: result.method });
}

async function pollRiskJob(jobId) {
  try {
    const job = await apiRequest(`/target-correlation/jobs/${jobId}`, { method: "GET" });
    updateRiskProgress(job);
    if (job.status === "done") {
      clearActiveRiskJob();
      renderRiskResult(job.result);
      setStatus("riskStatus", "Рейтинг закономірностей готовий", "ok");
      return;
    }
    if (job.status === "error") {
      clearActiveRiskJob();
      setStatus("riskStatus", job.error || "Помилка розрахунку рейтингу", "error");
    }
  } catch (error) {
    clearActiveRiskJob();
    const restored = await restoreSavedRiskResult();
    if (restored) {
      updateRiskProgress({ progress: 100, step: "Рейтинг закономірностей відновлено", status: "done" });
      return;
    }
    const staleJob = String(error.message || "").toLowerCase().includes("not found");
    updateRiskProgress({ progress: 100, step: "Розрахунок рейтингу неактивний", status: "error" });
    setStatus(
      "riskStatus",
      staleJob
        ? "Попередня задача рейтингу вже недоступна після перезапуску сервера. Запустіть рейтинг ще раз."
        : error.message,
      staleJob ? "ok" : "error"
    );
  }
}

async function runRiskCorrelation() {
  const target = document.getElementById("riskTarget").value;
  const method = document.getElementById("riskMethod").value;
  if (!target || !method) {
    setStatus("riskStatus", "Оберіть цільову колонку та метод", "error");
    return;
  }

  setRiskBusy(true);
  updateRiskProgress({ progress: 1, step: "Запуск розрахунку рейтингу", status: "running" });
  setStatus("riskStatus", "Рейтинг запущено на сервері.", "ok");

  try {
    const data = await apiRequest("/target-correlation/jobs", {
      method: "POST",
      body: JSON.stringify({ target, method })
    });
    localStorage.setItem(userStateKey("risk/job"), data.job_id);
    stopRiskPolling();
    riskPollTimer = window.setInterval(() => pollRiskJob(data.job_id), 1200);
    await pollRiskJob(data.job_id);
  } catch (error) {
    clearActiveRiskJob();
    updateRiskProgress({ progress: 100, step: "Помилка запуску рейтингу", status: "error" });
    setStatus("riskStatus", error.message, "error");
  }
}

async function restoreRiskState() {
  const activeJobId = localStorage.getItem(userStateKey("risk/job"));
  if (activeJobId) {
    setRiskBusy(true);
    riskPollTimer = window.setInterval(() => pollRiskJob(activeJobId), 1200);
    await pollRiskJob(activeJobId);
    return;
  }

  await restoreSavedRiskResult();
}

document.getElementById("riskRunBtn").addEventListener("click", runRiskCorrelation);

(async function initRiskPage() {
  const hasDataset = await loadRiskTargets();
  if (hasDataset) {
    await restoreRiskState();
  }
})();
