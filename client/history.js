if (ensureAuthOrRedirect()) {
  renderNav("history");
}

function renderHistory(items) {
  const body = document.getElementById("historyBody");
  if (!items.length) {
    renderEmptyRow(body, 3, "Історія поки порожня");
    return;
  }
  clearElement(body);
  items.forEach((item) => {
    const row = document.createElement("tr");
    appendTextElement(row, "td", new Date(item.created_at).toLocaleString());
    appendTextElement(row, "td", item.action);
    const payloadCell = document.createElement("td");
    appendTextElement(payloadCell, "code", JSON.stringify(item.payload));
    row.appendChild(payloadCell);
    body.appendChild(row);
  });
}

async function loadHistory() {
  try {
    const data = await apiRequest("/history", { method: "GET" });
    renderHistory(data.items || []);
    setStatus("historyStatus", "Історію завантажено", "ok");
  } catch (error) {
    setStatus("historyStatus", error.message, "error");
  }
}

document.getElementById("refreshHistoryBtn").addEventListener("click", loadHistory);
loadHistory();
