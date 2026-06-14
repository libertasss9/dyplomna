const API_BASE = "http://127.0.0.1:5000";

function getToken() {
  return localStorage.getItem("auth_token") || "";
}

function setToken(token) {
  localStorage.setItem("auth_token", token);
}

function clearToken() {
  localStorage.removeItem("auth_token");
}

function getUsername() {
  return localStorage.getItem("auth_username") || "";
}

function setUsername(username) {
  localStorage.setItem("auth_username", username);
}

function clearUsername() {
  localStorage.removeItem("auth_username");
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    payload = {};
  }

  if (!response.ok) {
    const message = payload.error || "Request failed";
    if (response.status === 401) {
      clearToken();
      clearUsername();
      if (typeof clearDatasetScopedState === "function") {
        clearDatasetScopedState();
      }
      if (!window.location.pathname.endsWith("/login.html")) {
        sessionStorage.setItem("patternlab:redirect_after_login", `${window.location.pathname.split("/").pop() || "upload.html"}${window.location.search || ""}`);
        window.location.replace("login.html");
      }
    }
    if (message === "Dataset not uploaded") {
      if (typeof clearDatasetContext === "function") {
        clearDatasetContext();
      } else if (typeof clearDatasetScopedState === "function") {
        clearDatasetScopedState();
      }
    }
    throw new Error(message);
  }
  return payload;
}

async function registerUser(username, password) {
  return apiRequest("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
}

async function loginUser(username, password) {
  return apiRequest("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
}

async function logoutUser() {
  return apiRequest("/auth/logout", { method: "POST" });
}
