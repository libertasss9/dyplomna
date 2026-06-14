const panelLogin = document.getElementById("panelLogin");
const panelRegister = document.getElementById("panelRegister");
const loginBtn = document.getElementById("loginBtn");
const registerBtn = document.getElementById("registerBtn");
const showRegisterBtn = document.getElementById("showRegisterBtn");
const showLoginBtn = document.getElementById("showLoginBtn");

function showLoginForm() {
  panelLogin.classList.remove("auth-panel-hidden");
  panelRegister.classList.add("auth-panel-hidden");
}

function showRegisterForm() {
  panelRegister.classList.remove("auth-panel-hidden");
  panelLogin.classList.add("auth-panel-hidden");
}

function readLoginInput() {
  const username = document.getElementById("loginUsername").value.trim().toLowerCase();
  const password = document.getElementById("loginPassword").value;
  return { username, password };
}

function readRegisterInput() {
  const username = document.getElementById("registerUsername").value.trim().toLowerCase();
  const password = document.getElementById("registerPassword").value;
  const passwordConfirm = document.getElementById("registerPasswordConfirm").value;
  return { username, password, passwordConfirm };
}

function validateAuthInput(username, password) {
  if (username.length < 3) {
    throw new Error("Ім'я користувача має містити щонайменше 3 символи");
  }
  if (password.length < 6) {
    throw new Error("Пароль має містити щонайменше 6 символів");
  }
}

async function login() {
  try {
    const { username, password } = readLoginInput();
    validateAuthInput(username, password);
    const data = await loginUser(username, password);
    setToken(data.token);
    setUsername(data.username);
    setStatus("authStatus", "Вхід виконано успішно", "ok");
    window.location.href = redirectAfterLoginTarget();
  } catch (error) {
    setStatus("authStatus", error.message, "error");
  }
}

async function register() {
  try {
    const { username, password, passwordConfirm } = readRegisterInput();
    validateAuthInput(username, password);
    if (password !== passwordConfirm) {
      throw new Error("Підтвердження пароля не збігається");
    }
    await registerUser(username, password);
    setStatus("authStatus", "Реєстрація успішна. Тепер можна увійти.", "ok");
    document.getElementById("loginUsername").value = username;
    document.getElementById("loginPassword").value = "";
    showLoginForm();
  } catch (error) {
    setStatus("authStatus", error.message, "error");
  }
}

showRegisterBtn.addEventListener("click", showRegisterForm);
showLoginBtn.addEventListener("click", showLoginForm);
loginBtn.addEventListener("click", login);
registerBtn.addEventListener("click", register);
