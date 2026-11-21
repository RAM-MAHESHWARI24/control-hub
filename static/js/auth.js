/**
 * Control Hub - sign-in guard & account dialog.
 *
 * Loaded before the ES-module app. Uses the dashboard's design tokens so
 * sign-in and account dialogs match both Dark and Light themes cleanly.
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

  function trapFocus(container, onEscape) {
    container.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && typeof onEscape === "function") {
        ev.preventDefault();
        onEscape();
        return;
      }
      if (ev.key !== "Tab") return;
      const items = Array.from(container.querySelectorAll("input, button, a[href], [tabindex]:not([tabindex='-1'])"))
        .filter((node) => !node.disabled);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
      }
    });
  }

  function overlay(id, titleId, html) {
    const el = document.createElement("div");
    el.id = id;
    el.className = "auth-overlay";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-labelledby", titleId);
    el.innerHTML = html;
    document.body.appendChild(el);
    return el;
  }

  function wirePasswordToggles(root) {
    root.querySelectorAll("[data-pw-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const target = document.getElementById(btn.getAttribute("data-pw-toggle"));
        if (!target) return;
        const showing = target.type === "text";
        target.type = showing ? "password" : "text";
        btn.setAttribute("aria-pressed", showing ? "false" : "true");
        btn.setAttribute("aria-label", showing ? "Show password" : "Hide password");
        const useEl = btn.querySelector("use");
        if (useEl) {
          useEl.setAttribute("href", "/img/icons/ui-sprite.svg#" + (showing ? "icon-eye" : "icon-eye-off"));
        }
      });
    });
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

  function passwordField(id, label, placeholder, autocomplete) {
    return (
      '<div class="form-field">' +
      '<label for="' + id + '">' + label + "</label>" +
      '<div class="auth-input-wrap">' +
      '<input id="' + id + '" type="password" class="form-input" autocomplete="' + autocomplete + '" placeholder="' + placeholder + '">' +
      '<button type="button" class="auth-pw-toggle" data-pw-toggle="' + id + '" aria-label="Show password" aria-pressed="false">' +
      '<svg class="ui-icon" aria-hidden="true"><use href="/img/icons/ui-sprite.svg#icon-eye"></use></svg>' +
      "</button>" +
      "</div>" +
      "</div>"
    );
  }

  function showPrompt(message) {
    if (document.getElementById("hub-auth-overlay")) {
      if (message) document.getElementById("hub-auth-error").textContent = message;
      return;
    }
    const el = overlay(
      "hub-auth-overlay",
      "hub-auth-title",
      '<form id="hub-auth-form" class="auth-card">' +
      '<div class="auth-brand-row">' +
      '<div class="brand-emblem" aria-hidden="true"><svg class="ui-icon"><use href="/img/icons/ui-sprite.svg#icon-server"></use></svg></div>' +
      '<div><h2 id="hub-auth-title" class="auth-title">Sign in to Control Hub</h2>' +
      '<p class="auth-subtitle">Home server command center</p></div>' +
      "</div>" +
      '<p class="auth-desc">Use your dashboard password (the master password from setup unless changed). This browser stays signed in.</p>' +
      passwordField("hub-auth-input", "Dashboard password", "Enter password", "current-password") +
      '<div id="hub-auth-error" class="auth-feedback is-error" role="alert"></div>' +
      '<div class="auth-actions">' +
      '<button type="submit" class="btn-primary auth-full-btn">Sign in</button>' +
      "</div>" +
      "</form>"
    );
    if (message) document.getElementById("hub-auth-error").textContent = message;

    wirePasswordToggles(el);
    const input = document.getElementById("hub-auth-input");
    input.focus();
    trapFocus(el);
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

  function showAccount(triggerEl) {
    if (document.getElementById("hub-account-overlay")) return;
    const prevFocus = triggerEl || document.activeElement;
    const el = overlay(
      "hub-account-overlay",
      "hub-account-title",
      '<form id="hub-account-form" class="auth-card">' +
      '<div class="auth-brand-row">' +
      '<div class="brand-emblem" aria-hidden="true"><svg class="ui-icon"><use href="/img/icons/ui-sprite.svg#icon-user"></use></svg></div>' +
      '<div><h2 id="hub-account-title" class="auth-title">Dashboard password</h2>' +
      '<p class="auth-subtitle">Session &amp; sign-in settings</p></div>' +
      "</div>" +
      '<p class="auth-desc">Changing it signs out every other device. It does not change qBittorrent, Jellyfin or Seerr passwords.</p>' +
      passwordField("hub-pw-current", "Current password", "Current password", "current-password") +
      passwordField("hub-pw-new", "New password (at least 8 characters)", "New password", "new-password") +
      passwordField("hub-pw-repeat", "Repeat new password", "Repeat new password", "new-password") +
      '<div id="hub-account-msg" class="auth-feedback" role="status" aria-live="polite"></div>' +
      '<div class="auth-actions">' +
      '<button type="submit" class="btn-primary auth-full-btn">Change password</button>' +
      '<div class="auth-secondary-row">' +
      '<button type="button" id="hub-signout" class="btn-secondary">Sign out</button>' +
      '<button type="button" id="hub-account-close" class="btn-ghost">Close</button>' +
      "</div>" +
      "</div>" +
      "</form>"
    );

    function closeAccount() {
      el.remove();
      if (prevFocus && typeof prevFocus.focus === "function" && document.contains(prevFocus)) {
        prevFocus.focus();
      }
    }

    wirePasswordToggles(el);
    const msg = document.getElementById("hub-account-msg");
    document.getElementById("hub-pw-current").focus();
    trapFocus(el, closeAccount);
    el.addEventListener("click", function (ev) {
      if (ev.target === el) closeAccount();
    });
    document.getElementById("hub-account-close").addEventListener("click", closeAccount);
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
        msg.className = "auth-feedback is-error";
        msg.textContent = "The new passwords do not match.";
        return;
      }
      const res = await postJson("/api/auth/password", { current: current, new: next });
      msg.className = "auth-feedback " + (res.ok ? "is-success" : "is-error");
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
    document.querySelectorAll("[data-open-account], #btn-open-account").forEach(function (btn) {
      btn.addEventListener("click", function () { showAccount(btn); });
    });
  });
})();
