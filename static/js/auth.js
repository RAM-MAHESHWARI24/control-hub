/**
 * Control Hub - sign-in guard.
 *
 * Loaded before the ES-module app. When the server answers 401, it shows a
 * password prompt. Signing in sets an HttpOnly session cookie, so each browser
 * signs in once. An access token, if one was saved or given once via
 * ?token=..., is still sent as `Authorization: Bearer <token>` for old setups.
 * window.HomelabAuth.account() opens the "change password / sign out" panel.
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
    if (isApi) {
      init.credentials = init.credentials || "same-origin";
      if (token) {
        const headers = new Headers(init.headers || (typeof input !== "string" && input.headers) || {});
        headers.set("Authorization", "Bearer " + token);
        init.headers = headers;
      }
    }
    const response = await originalFetch(input, init);
    if (isApi && response.status === 401 && !requestUrl.includes("/api/auth/")) showPrompt();
    return response;
  };

  const CARD = "width:min(92vw,420px);background:#0f172a;border:1px solid #1e293b;border-radius:14px;padding:28px;color:#e2e8f0;box-shadow:0 20px 60px rgba(0,0,0,.6)";
  const INPUT = "width:100%;box-sizing:border-box;padding:12px 14px;margin-top:10px;border-radius:10px;border:1px solid #334155;background:#020617;color:#f8fafc;font-size:1rem";
  const BUTTON = "width:100%;padding:12px;border:0;border-radius:10px;background:linear-gradient(135deg,#06b6d4,#3b82f6);color:#fff;font-weight:600;font-size:1rem;cursor:pointer";
  const LINK = "width:100%;margin-top:10px;padding:10px;border:1px solid #334155;border-radius:10px;background:transparent;color:#cbd5e1;font-size:.95rem;cursor:pointer";

  function overlay(id, html) {
    const el = document.createElement("div");
    el.id = id;
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;" +
      "background:rgba(5,8,20,.82);backdrop-filter:blur(6px);font-family:system-ui,sans-serif;";
    el.innerHTML = html;
    document.body.appendChild(el);
    return el;
  }

  async function postJson(path, body) {
    const res = await originalFetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty body */ }
    return { ok: res.ok, status: res.status, data: data };
  }

  function showPrompt(message) {
    if (document.getElementById("hub-auth-overlay")) {
      if (message) document.getElementById("hub-auth-error").textContent = message;
      return;
    }
    overlay("hub-auth-overlay",
      '<form id="hub-auth-form" style="' + CARD + '">' +
      '<h2 style="margin:0 0 6px;font-size:1.25rem">Sign in to Control Hub</h2>' +
      '<p style="margin:0 0 8px;color:#94a3b8;font-size:.92rem;line-height:1.45">Use the dashboard password. Unless you changed it, it is the master password from setup. This browser stays signed in.</p>' +
      '<input id="hub-auth-input" type="password" autocomplete="current-password" placeholder="Password" style="' + INPUT + '">' +
      '<div id="hub-auth-error" style="min-height:1.2em;margin:10px 0 14px;color:#fb7185;font-size:.88rem"></div>' +
      '<button type="submit" style="' + BUTTON + '">Sign in</button>' +
      "</form>");
    if (message) document.getElementById("hub-auth-error").textContent = message;

    const input = document.getElementById("hub-auth-input");
    input.focus();
    document.getElementById("hub-auth-form").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const candidate = input.value;
      if (!candidate) return;
      try {
        const res = await postJson("/api/auth/login", { password: candidate });
        if (res.ok) {
          window.location.reload();
          return;
        }
        document.getElementById("hub-auth-error").textContent = res.data.error || "Sign-in failed.";
      } catch (err) {
        document.getElementById("hub-auth-error").textContent = "Could not reach the server.";
      }
    });
  }

  function showAccount() {
    if (document.getElementById("hub-account-overlay")) return;
    const el = overlay("hub-account-overlay",
      '<form id="hub-account-form" style="' + CARD + '">' +
      '<h2 style="margin:0 0 6px;font-size:1.25rem">Dashboard password</h2>' +
      '<p style="margin:0 0 8px;color:#94a3b8;font-size:.92rem;line-height:1.45">Changing it signs out every other device. It does not change the qBittorrent, Jellyfin or Seerr passwords.</p>' +
      '<input id="hub-pw-current" type="password" autocomplete="current-password" placeholder="Current password" style="' + INPUT + '">' +
      '<input id="hub-pw-new" type="password" autocomplete="new-password" placeholder="New password (at least 8 characters)" style="' + INPUT + '">' +
      '<input id="hub-pw-repeat" type="password" autocomplete="new-password" placeholder="Repeat new password" style="' + INPUT + '">' +
      '<div id="hub-account-msg" style="min-height:1.2em;margin:10px 0 14px;color:#fb7185;font-size:.88rem"></div>' +
      '<button type="submit" style="' + BUTTON + '">Change password</button>' +
      '<button type="button" id="hub-signout" style="' + LINK + '">Sign out of this browser</button>' +
      '<button type="button" id="hub-account-close" style="' + LINK + '">Close</button>' +
      "</form>");
    const msg = document.getElementById("hub-account-msg");
    document.getElementById("hub-account-close").addEventListener("click", function () { el.remove(); });
    document.getElementById("hub-signout").addEventListener("click", async function () {
      await postJson("/api/auth/logout");
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) { /* ignore */ }
      token = "";
      window.location.reload();
    });
    document.getElementById("hub-account-form").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const current = document.getElementById("hub-pw-current").value;
      const next = document.getElementById("hub-pw-new").value;
      if (next !== document.getElementById("hub-pw-repeat").value) {
        msg.style.color = "#fb7185";
        msg.textContent = "The new passwords do not match.";
        return;
      }
      const res = await postJson("/api/auth/password", { current: current, new: next });
      msg.style.color = res.ok ? "#4ade80" : "#fb7185";
      msg.textContent = res.ok ? (res.data.message || "Password changed.") : (res.data.error || "Could not change the password.");
      if (res.ok) ["hub-pw-current", "hub-pw-new", "hub-pw-repeat"].forEach(function (id) { document.getElementById(id).value = ""; });
    });
  }

  window.HomelabAuth = {
    getToken: function () { return token; },
    forget: function () {
      postJson("/api/auth/logout").finally(function () {
        try { localStorage.removeItem(STORAGE_KEY); } catch (_) { /* ignore */ }
        token = "";
        window.location.reload();
      });
    },
    prompt: showPrompt,
    account: showAccount,
  };

  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("btn-open-account");
    if (btn) btn.addEventListener("click", showAccount);
  });
})();
