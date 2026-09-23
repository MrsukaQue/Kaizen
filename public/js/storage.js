(function () {
  let csrfToken = "";
  let saveQueue = Promise.resolve();

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      credentials: "same-origin",
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
        ...options.headers
      }
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || "Something went wrong.");
    if (result.csrfToken) csrfToken = result.csrfToken;
    return result;
  }

  const session = () => request("/api/session").catch(() => null);
  const login = (email, password) => request("/api/login", { method: "POST", body: JSON.stringify({ email, password }) });
  const register = (email, password) => request("/api/register", { method: "POST", body: JSON.stringify({ email, password }) });
  const logout = () => request("/api/logout", { method: "POST" });
  const load = async () => (await request("/api/data")).data;
  const save = data => {
    saveQueue = saveQueue.catch(() => {}).then(() => request("/api/data", { method: "PUT", body: JSON.stringify({ data }) }));
    return saveQueue;
  };

  window.KaizenStorage = { session, login, register, logout, load, save };
})();
