/**
 * Control Hub - bearer token client guard.
 *
 * Loaded before the ES-module app. Wraps window.fetch so every same-origin
 * /api/ request carries `Authorization: Bearer <token>`, and shows a token
 * prompt whenever the server answers 401. The token is kept in localStorage
 * (per browser) and may also be supplied once via ?token=... in the URL.
 */
(function () {
  const STORAGE_KEY = "homelab_hub_token";
  let token = "";
  try { token = localStorage.getItem(STORAGE_KEY) || ""; } catch (_) { /* storage blocked */ }

  // Accept ?token=... once, then scrub it from the address bar.
  try {
    const url = new URL(window.location.href);
    const fromUrl = url.searchParams.get("token");
    if (fromUrl) {
      token = fromUrl;
      try { localStorage.setItem(STORAGE_KEY, token); } catch (_) { /* ignore */ }
      url.searchParams.delete("token");
      window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
    }
  } catch (_) { /* ignore */ }

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const requestUrl = typeof input === "string" ? input : (input && input.url) || "";
    const isApi = requestUrl.startsWith("/api/") || requestUrl.startsWith(window.location.origin + "/api/");
    init = init || {};
    if (isApi && token) {
      const headers = new Headers(init.headers || (typeof input !== "string" && input.headers) || {});
      headers.set("Authorization", "Bearer " + token);
      init.headers = headers;
    }
    const response = await originalFetch(input, init);
    if (isApi && response.status === 401) showPrompt();
    return response;
  };

  function showPrompt(message) {
    if (document.getElementById("hub-auth-overlay")) {
      if (message) document.getElementById("hub-auth-error").textContent = message;
      return;
    }
    const overlay = document.createElement("div");
    overlay.id = "hub-auth-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;" +
      "background:rgba(5,8,20,.82);backdrop-filter:blur(6px);font-family:system-ui,sans-serif;";
    overlay.innerHTML =
      '<form id="hub-auth-form" style="width:min(92vw,420px);background:#0f172a;border:1px solid #1e293b;border-radius:14px;padding:28px;color:#e2e8f0;box-shadow:0 20px 60px rgba(0,0,0,.6)">' +
      '<h2 style="margin:0 0 6px;font-size:1.25rem">Control Hub access</h2>' +
      '<p style="margin:0 0 18px;color:#94a3b8;font-size:.92rem;line-height:1.45">Paste the access token shown when the server was set up. On the server run <code style="color:#67e8f9">sudo ./setup.sh token</code> to display it again.</p>' +
      '<input id="hub-auth-input" type="password" autocomplete="off" spellcheck="false" placeholder="Access token" ' +
      'style="width:100%;box-sizing:border-box;padding:12px 14px;border-radius:10px;border:1px solid #334155;background:#020617;color:#f8fafc;font-size:1rem;font-family:ui-monospace,monospace">' +
      '<div id="hub-auth-error" style="min-height:1.2em;margin:10px 0 14px;color:#fb7185;font-size:.88rem"></div>' +
      '<button type="submit" style="width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(135deg,#06b6d4,#3b82f6);color:#fff;font-weight:600;font-size:1rem;cursor:pointer">Unlock dashboard</button>' +
      "</form>";
    document.body.appendChild(overlay);
    if (message) document.getElementById("hub-auth-error").textContent = message;

    const input = document.getElementById("hub-auth-input");
    input.focus();
    document.getElementById("hub-auth-form").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const candidate = input.value.trim();
      if (!candidate) return;
      try {
        const res = await originalFetch("/api/auth/check", { headers: { Authorization: "Bearer " + candidate } });
        if (res.ok) {
          token = candidate;
          try { localStorage.setItem(STORAGE_KEY, token); } catch (_) { /* ignore */ }
          window.location.reload();
          return;
        }
        document.getElementById("hub-auth-error").textContent = "That token was not accepted.";
      } catch (err) {
        document.getElementById("hub-auth-error").textContent = "Could not reach the server.";
      }
    });
  }

  window.HomelabAuth = {
    getToken: function () { return token; },
    forget: function () {
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) { /* ignore */ }
      token = "";
      window.location.reload();
    },
    prompt: showPrompt,
  };
})();
