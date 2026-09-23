(async function () {
  const storage = window.KaizenStorage;
  const stats = window.KaizenStats;
  const $ = selector => document.querySelector(selector);
  let authMode = "login";

  function showAuth(mode) {
    authMode = mode;
    const registering = mode === "register";
    $("#auth").hidden = false;
    $("#app").hidden = true;
    $("#login-tab").classList.toggle("active", !registering);
    $("#register-tab").classList.toggle("active", registering);
    $("#login-tab").setAttribute("aria-selected", String(!registering));
    $("#register-tab").setAttribute("aria-selected", String(registering));
    $("#auth-title").textContent = registering ? "Create your account" : "Welcome back";
    $("#auth-subtitle").textContent = registering ? "Your progress will stay private to you." : "Continue your improvement journey.";
    $("#auth-submit").textContent = registering ? "Create account" : "Log in";
    $("#password").autocomplete = registering ? "new-password" : "current-password";
    $("#auth-error").textContent = "";
  }

  $("#login-tab").addEventListener("click", () => showAuth("login"));
  $("#register-tab").addEventListener("click", () => showAuth("register"));
  $("#auth-form").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("#auth-submit");
    button.disabled = true;
    $("#auth-error").textContent = "";
    try {
      await storage[authMode]($("#email").value.trim(), $("#password").value);
      location.reload();
    } catch (error) {
      $("#auth-error").textContent = error.message;
      button.disabled = false;
    }
  });

  const session = await storage.session();
  if (!session) {
    showAuth("login");
    return;
  }

  let data;
  try {
    data = await storage.load();
  } catch {
    showAuth("login");
    return;
  }
  const today = stats.dateKey(new Date());
  $("#auth").hidden = true;
  $("#app").hidden = false;
  $("#user-name").hidden = false;
  $("#logout-button").hidden = false;
  $("#theme-toggle").hidden = false;
  $("#user-name").textContent = session.email;

  data.days[today] ||= { completed: [], reflection: "", total: data.habits.length };
  data.days[today].total = data.habits.length;
  data.days[today].completed = data.days[today].completed.filter(id => data.habits.some(habit => habit.id === id));

  function persist() {
    data.days[today].total = data.habits.length;
    storage.save(data);
  }

  function render() {
    renderDashboard();
    renderHabits();
    renderWeekly();
    renderHistory();
  }

  function renderDashboard() {
    const progress = stats.dayProgress(data.days[today]);
    const streak = stats.streaks(data.days);
    const messages = progress.percent === 100
      ? "You showed up today. Let that be enough."
      : progress.percent >= 60
        ? "Small progress is still progress."
        : progress.percent > 0
          ? "One step at a time. Keep going."
          : "A small action today can change tomorrow.";

    $("#today-date").textContent = new Intl.DateTimeFormat("en", { weekday: "long", month: "long", day: "numeric" }).format(new Date());
    $("#progress-count").textContent = `${progress.completed} / ${progress.total} habits`;
    $("#progress-percent").textContent = `${progress.percent}%`;
    $("#progress-bar").style.width = `${progress.percent}%`;
    $(".progress-track").setAttribute("aria-valuenow", progress.percent);
    $("#current-streak").textContent = streak.current;
    $("#best-streak").textContent = streak.best;
    $("#total-completed").textContent = Object.values(data.days).reduce((sum, day) => sum + (day.completed?.length || 0), 0);
    $("#motivation").textContent = `“${messages}”`;
  }

  function renderHabits() {
    const list = $("#habit-list");
    list.replaceChildren();
    $("#empty-habits").hidden = data.habits.length > 0;

    data.habits.forEach(habit => {
      const done = data.days[today].completed.includes(habit.id);
      const item = document.createElement("div");
      item.className = `habit${done ? " done" : ""}`;
      item.innerHTML = `
        <input class="habit-check" type="checkbox" ${done ? "checked" : ""} aria-label="Mark ${escapeHtml(habit.name)} complete">
        <div><span class="habit-name">${escapeHtml(habit.name)}</span><span class="habit-meta">🔥 ${stats.habitStreak(data.days, habit.id)} day streak · Added ${formatDate(habit.createdAt)}</span></div>
        <div class="habit-actions"><button type="button" data-action="edit" aria-label="Edit ${escapeHtml(habit.name)}">✎</button><button type="button" data-action="delete" aria-label="Delete ${escapeHtml(habit.name)}">×</button></div>`;
      item.querySelector("input").addEventListener("change", event => toggleHabit(habit.id, event.target.checked));
      item.querySelector('[data-action="edit"]').addEventListener("click", () => openHabitDialog(habit));
      item.querySelector('[data-action="delete"]').addEventListener("click", () => deleteHabit(habit));
      list.append(item);
    });
  }

  function toggleHabit(id, completed) {
    const list = data.days[today].completed;
    if (completed && !list.includes(id)) list.push(id);
    if (!completed) data.days[today].completed = list.filter(item => item !== id);
    persist();
    render();
  }

  function openHabitDialog(habit) {
    $("#dialog-title").textContent = habit ? "Edit habit" : "Add a habit";
    $("#habit-id").value = habit?.id || "";
    $("#habit-name").value = habit?.name || "";
    $("#habit-dialog").showModal();
    $("#habit-name").focus();
  }

  function saveHabit() {
    const name = $("#habit-name").value.trim();
    const id = $("#habit-id").value;
    if (!name) return;
    if (id) data.habits.find(habit => habit.id === id).name = name;
    else data.habits.push({ id: crypto.randomUUID(), name, createdAt: today });
    persist();
    render();
  }

  function deleteHabit(habit) {
    if (!confirm(`Delete “${habit.name}”? Past history totals will be kept.`)) return;
    data.habits = data.habits.filter(item => item.id !== habit.id);
    data.days[today].completed = data.days[today].completed.filter(id => id !== habit.id);
    persist();
    render();
  }

  function renderWeekly() {
    const chart = $("#weekly-chart");
    chart.replaceChildren();
    stats.lastSevenDays(data.days).forEach(day => {
      const row = document.createElement("div");
      row.className = "chart-row";
      row.innerHTML = `<span>${new Intl.DateTimeFormat("en", { weekday: "short" }).format(day.date)}</span><div class="chart-track"><span class="chart-bar" style="width:${day.percent}%"></span></div><span class="chart-value">${day.percent}%</span>`;
      chart.append(row);
    });
  }

  function renderHistory() {
    const list = $("#history-list");
    const entries = Object.entries(data.days)
      .filter(([key, day]) => key !== today && (day.total || day.reflection))
      .sort(([a], [b]) => b.localeCompare(a));
    list.replaceChildren();
    $("#empty-history").hidden = entries.length > 0;
    entries.forEach(([key, day]) => {
      const progress = stats.dayProgress(day);
      const item = document.createElement("article");
      item.className = "history-item";
      item.innerHTML = `<time class="history-date" datetime="${key}">${formatDate(key)}</time><p class="history-reflection">${escapeHtml(day.reflection || "No reflection recorded.")}</p><div class="history-result"><strong>${progress.percent}%</strong><span>${progress.completed} / ${progress.total} completed</span></div>`;
      list.append(item);
    });
  }

  function formatDate(value) {
    return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(new Date(`${value}T12:00:00`));
  }

  function escapeHtml(value) {
    const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return String(value).replace(/[&<>"']/g, character => entities[character]);
  }

  function applyTheme() {
    document.documentElement.dataset.theme = data.settings.theme;
    const dark = data.settings.theme === "dark";
    $("#theme-toggle").textContent = dark ? "☀" : "☾";
    $("#theme-toggle").setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} mode`);
  }

  $("#add-habit").addEventListener("click", () => openHabitDialog());
  $("#habit-form").addEventListener("submit", event => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;
    saveHabit();
    $("#habit-dialog").close();
  });
  $("#theme-toggle").addEventListener("click", () => {
    data.settings.theme = data.settings.theme === "dark" ? "light" : "dark";
    applyTheme();
    persist();
  });
  $("#logout-button").addEventListener("click", async () => {
    await storage.logout();
    location.reload();
  });
  $("#reflection").value = data.days[today].reflection || "";
  $("#reflection-count").textContent = $("#reflection").value.length;
  $("#reflection").addEventListener("input", event => {
    data.days[today].reflection = event.target.value;
    $("#reflection-count").textContent = event.target.value.length;
    persist();
  });

  applyTheme();
  render();
  persist();
})();
