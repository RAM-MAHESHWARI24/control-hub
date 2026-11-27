/**
 * Control Hub - sign-in guard, device sessions, 2FA (TOTP), Family access, and account dialog.
 *
 * Loaded before the ES-module app. Uses the dashboard's design tokens so
 * sign-in and account dialogs match both Dark and Light themes cleanly.
 */
(function () {
  const STORAGE_KEY = "homelab_hub_token";
  let token = "";
  try { token = localStorage.getItem(STORAGE_KEY) || ""; } catch (_) { /* storage blocked */ }

  let authStatus = {
    authenticated: false,
    password_set: true,
    role: null,
    auth_via: "none",
    session_id: null,
    family_enabled: false,
    family_lan_open: false,
    family_password_set: false,
    totp_enabled: false,
  };
  let statusPromise = null;

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

  function esc(val) {
    return String(val == null ? "" : val)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function relTime(unixSeconds) {
    const ts = Number(unixSeconds || 0);
    if (!ts) return "Unknown";
    const diff = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (diff < 60) return "Just now";
    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
    return Math.floor(diff / 86400) + "d ago";
  }

  async function apiJson(method, path, body) {
    const headers = {};
    if (token) headers["Authorization"] = "Bearer " + token;
    const opts = { method: method, credentials: "same-origin", headers: headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body || {});
    }
    const res = await originalFetch(path, opts);
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty body */ }
    return { ok: res.ok, status: res.status, data: data };
  }

  async function postJson(path, body) {
    return apiJson("POST", path, body || {});
  }

  async function refreshStatus(force) {
    if (!statusPromise || force) {
      statusPromise = apiJson("GET", "/api/auth/status")
        .then(function (res) {
          if (res.ok && res.data && typeof res.data === "object") {
            authStatus = Object.assign({}, authStatus, res.data);
            document.documentElement.dataset.authRole = authStatus.role || "";
          }
          return authStatus;
        })
        .catch(function () {
          return authStatus;
        });
    }
    return statusPromise;
  }

  function trapFocus(container, onEscape) {
    container.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && typeof onEscape === "function") {
        ev.preventDefault();
        onEscape();
        return;
      }
      if (ev.key !== "Tab") return;
      const items = Array.from(container.querySelectorAll("input, select, button, a[href], [tabindex]:not([tabindex='-1'])"))
        .filter((node) => !node.disabled && node.offsetParent !== null);
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

  function showPrompt(message, opts) {
    opts = opts || {};
    const ownerOnlyMode = opts.mode === "owner";
    const existing = document.getElementById("hub-auth-overlay");
    if (existing) {
      if (message) document.getElementById("hub-auth-error").textContent = message;
      return;
    }
    const prevFocus = document.activeElement;
    const titleText = ownerOnlyMode ? "Owner Sign In" : "Sign in to Control Hub";
    const descText = ownerOnlyMode
      ? "Enter the owner password to unlock full server controls and configuration."
      : "Use your dashboard password (or family password if enabled). This browser stays signed in.";

    const el = overlay(
      "hub-auth-overlay",
      "hub-auth-title",
      '<form id="hub-auth-form" class="auth-card">' +
      '<div class="auth-brand-row">' +
      '<div class="brand-emblem" aria-hidden="true"><svg class="ui-icon"><use href="/img/icons/ui-sprite.svg#icon-server"></use></svg></div>' +
      '<div><h2 id="hub-auth-title" class="auth-title">' + titleText + "</h2>" +
      '<p class="auth-subtitle">Home server command center</p></div>' +
      "</div>" +
      '<p class="auth-desc">' + descText + "</p>" +
      passwordField("hub-auth-input", "Dashboard password", "Enter password", "current-password") +
      '<div id="hub-auth-totp-wrap" class="form-field" hidden>' +
      '<label for="hub-auth-totp">Authenticator or recovery code</label>' +
      '<input id="hub-auth-totp" type="text" class="form-input font-mono" autocomplete="one-time-code" placeholder="6-digit code or XXXX-XXXX">' +
      "</div>" +
      '<div id="hub-auth-error" class="auth-feedback is-error" role="alert"></div>' +
      '<div class="auth-actions">' +
      '<button type="submit" class="btn-primary auth-full-btn">Sign in</button>' +
      (ownerOnlyMode ? '<button type="button" id="hub-auth-cancel" class="btn-ghost auth-full-btn">Stay in Family View</button>' : "") +
      "</div>" +
      "</form>"
    );
    if (message) document.getElementById("hub-auth-error").textContent = message;

    function closePrompt() {
      el.remove();
      if (prevFocus && typeof prevFocus.focus === "function" && document.contains(prevFocus)) {
        prevFocus.focus();
      }
    }

    wirePasswordToggles(el);
    const input = document.getElementById("hub-auth-input");
    const totpWrap = document.getElementById("hub-auth-totp-wrap");
    const totpInput = document.getElementById("hub-auth-totp");
    input.focus();
    trapFocus(el, ownerOnlyMode ? closePrompt : null);

    const cancelBtn = document.getElementById("hub-auth-cancel");
    if (cancelBtn) cancelBtn.addEventListener("click", closePrompt);

    document.getElementById("hub-auth-form").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const candidate = input.value;
      if (!candidate) return;
      const code = totpInput ? totpInput.value.trim() : "";
      try {
        const res = await postJson("/api/auth/login", {
          password: candidate,
          code: code,
          mode: ownerOnlyMode ? "owner" : "auto",
        });
        if (res.ok) {
          window.location.reload();
          return;
        }
        if (res.data && res.data.totp_required && totpWrap) {
          totpWrap.hidden = false;
          if (totpInput && !code) totpInput.focus();
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

    if (authStatus.role === "family") {
      const famEl = overlay(
        "hub-account-overlay",
        "hub-account-title",
        '<div class="auth-card">' +
        '<div class="auth-brand-row">' +
        '<div class="brand-emblem" aria-hidden="true"><svg class="ui-icon"><use href="/img/icons/ui-sprite.svg#icon-user"></use></svg></div>' +
        '<div><h2 id="hub-account-title" class="auth-title">Family View (Read-Only)</h2>' +
        '<p class="auth-subtitle">Status, What\'s New, and requests</p></div>' +
        "</div>" +
        '<p class="auth-desc">You are viewing the dashboard in read-only family mode. Sign in with the owner password to manage server controls and settings.</p>' +
        '<div class="auth-actions">' +
        '<button type="button" id="hub-fam-owner-login" class="btn-primary auth-full-btn">Owner Sign In</button>' +
        '<div class="auth-secondary-row">' +
        '<button type="button" id="hub-signout" class="btn-secondary">Sign out</button>' +
        '<button type="button" id="hub-account-close" class="btn-ghost">Close</button>' +
        "</div></div></div>"
      );
      function closeFam() {
        famEl.remove();
        if (prevFocus && typeof prevFocus.focus === "function" && document.contains(prevFocus)) prevFocus.focus();
      }
      trapFocus(famEl, closeFam);
      famEl.addEventListener("click", function (ev) { if (ev.target === famEl) closeFam(); });
      document.getElementById("hub-account-close").addEventListener("click", closeFam);
      document.getElementById("hub-fam-owner-login").addEventListener("click", function () {
        closeFam();
        showPrompt("", { mode: "owner" });
      });
      document.getElementById("hub-signout").addEventListener("click", async function () {
        await postJson("/api/auth/logout");
        try { localStorage.removeItem(STORAGE_KEY); } catch (_) { /* ignore */ }
        token = "";
        window.location.reload();
      });
      document.getElementById("hub-fam-owner-login").focus();
      return;
    }

    const el = overlay(
      "hub-account-overlay",
      "hub-account-title",
      '<div class="auth-card auth-card-wide">' +
      '<div class="auth-brand-row">' +
      '<div class="brand-emblem" aria-hidden="true"><svg class="ui-icon"><use href="/img/icons/ui-sprite.svg#icon-user"></use></svg></div>' +
      '<div><h2 id="hub-account-title" class="auth-title">Account &amp; Access</h2>' +
      '<p class="auth-subtitle">Password, 2FA, signed-in devices, and Family View</p></div>' +
      "</div>" +

      '<div class="auth-tabs" role="tablist" aria-label="Account sections">' +
      '<button type="button" role="tab" class="auth-tab-btn" id="acct-tab-btn-security" data-acct-tab="security" aria-selected="true">Password &amp; 2FA</button>' +
      '<button type="button" role="tab" class="auth-tab-btn" id="acct-tab-btn-devices" data-acct-tab="devices" aria-selected="false">Signed-in Devices</button>' +
      '<button type="button" role="tab" class="auth-tab-btn" id="acct-tab-btn-family" data-acct-tab="family" aria-selected="false">Family View</button>' +
      '<button type="button" role="tab" class="auth-tab-btn" id="acct-tab-btn-tokens" data-acct-tab="tokens" aria-selected="false">API Tokens</button>' +
      "</div>" +

      '<div id="acct-panel-security" class="auth-tab-panel">' +
      '<form id="hub-account-form" class="auth-section-stack">' +
      '<p class="auth-desc">Changing the owner password signs out every other device. It does not change qBittorrent, Jellyfin or Seerr passwords.</p>' +
      passwordField("hub-pw-current", "Current password", "Current password", "current-password") +
      passwordField("hub-pw-new", "New password (at least 8 characters)", "New password", "new-password") +
      passwordField("hub-pw-repeat", "Repeat new password", "Repeat new password", "new-password") +
      '<div id="hub-account-msg" class="auth-feedback" role="status" aria-live="polite"></div>' +
      '<button type="submit" class="btn-primary auth-full-btn">Change password</button>' +
      "</form>" +

      '<div id="hub-totp-panel" class="auth-subcard">' +
      '<div class="auth-subcard-head">' +
      '<div><strong>Two-Factor Authentication (TOTP)</strong><p class="auth-subtitle" id="hub-totp-status-text">Checking 2FA status...</p></div>' +
      '<button type="button" id="btn-totp-setup" class="btn-secondary">Set up 2FA</button>' +
      '<button type="button" id="btn-totp-disable-toggle" class="btn-ghost" hidden>Turn off 2FA</button>' +
      "</div>" +

      '<div id="hub-totp-setup-box" class="auth-section-stack" hidden>' +
      '<p class="auth-desc">Add this setup key in Bitwarden, 1Password, Google Authenticator, or Aegis, then confirm with a 6-digit code.</p>' +
      '<div class="totp-secret-box font-mono" id="totp-secret-display"></div>' +
      '<div class="auth-secondary-row">' +
      '<button type="button" id="btn-totp-copy-uri" class="btn-secondary">Copy otpauth URI</button>' +
      '<input id="totp-verify-code" type="text" class="form-input font-mono" inputmode="numeric" placeholder="6-digit code">' +
      "</div>" +
      '<button type="button" id="btn-totp-enable" class="btn-primary auth-full-btn">Confirm &amp; Enable 2FA</button>' +
      "</div>" +

      '<div id="hub-totp-recovery-box" class="auth-section-stack" hidden>' +
      '<p class="auth-desc"><strong>Save these one-time recovery codes offline.</strong> Each works once if you lose your authenticator.</p>' +
      '<div id="totp-recovery-list" class="totp-recovery-grid font-mono"></div>' +
      "</div>" +

      '<div id="hub-totp-disable-box" class="auth-section-stack" hidden>' +
      passwordField("totp-disable-pw", "Confirm owner password to turn off 2FA", "Owner password", "current-password") +
      '<button type="button" id="btn-totp-disable-confirm" class="btn-secondary auth-full-btn">Disable Two-Factor Auth</button>' +
      "</div>" +

      '<div id="hub-totp-msg" class="auth-feedback" role="status" aria-live="polite"></div>' +
      "</div>" +
      "</div>" +

      '<div id="acct-panel-devices" class="auth-tab-panel" hidden>' +
      '<div class="auth-subcard-head">' +
      '<p class="auth-desc">Every signed-in browser session is tracked on the server and can be signed out individually.</p>' +
      '<button type="button" id="btn-sessions-revoke-others" class="btn-secondary">Sign out others</button>' +
      "</div>" +
      '<div id="hub-sessions-list" class="auth-devices-list">' +
      '<div class="empty-state">Loading signed-in devices...</div>' +
      "</div>" +
      '<div id="hub-sessions-msg" class="auth-feedback" role="status" aria-live="polite"></div>' +
      "</div>" +

      '<div id="acct-panel-family" class="auth-tab-panel" hidden>' +
      '<form id="hub-family-form" class="auth-section-stack">' +
      '<p class="auth-desc">Family View shows server status, What\'s New in Jellyfin, and Seerr media requests, with all settings and controls hidden.</p>' +
      '<label class="auth-check-row" for="hub-family-enabled">' +
      '<input id="hub-family-enabled" type="checkbox">' +
      '<span>Enable Read-Only Family View</span>' +
      "</label>" +
      '<div class="form-field">' +
      '<label for="hub-family-mode">How family members sign in</label>' +
      '<select id="hub-family-mode" class="form-input">' +
      '<option value="password">Separate family password (works anywhere)</option>' +
      '<option value="lan_open">Automatic on home Wi-Fi / LAN (no password locally)</option>' +
      "</select>" +
      "</div>" +
      '<div id="hub-family-pw-wrap">' +
      passwordField("hub-family-pw", "Family password (min 8 characters; leave blank to keep current)", "Set family password", "new-password") +
      "</div>" +
      '<div id="hub-family-msg" class="auth-feedback" role="status" aria-live="polite"></div>' +
      '<button type="submit" id="btn-family-save" class="btn-primary auth-full-btn">Save Family Settings</button>' +
      "</form>" +
      "</div>" +

      '<div id="acct-panel-tokens" class="auth-tab-panel" hidden>' +
      '<form id="hub-token-form" class="auth-section-stack">' +
      '<p class="auth-desc">Create scoped bearer tokens for Home Assistant, Prometheus, or backup scripts. Read-only tokens cannot trigger restarts, cleanup, or config changes.</p>' +
      '<div class="auth-secondary-row">' +
      '<input id="hub-token-name" type="text" class="form-input" aria-label="Token label" placeholder="Token label (e.g. Home Assistant)" maxlength="64">' +
      '<select id="hub-token-scope" class="form-input" aria-label="Token scope">' +
      '<option value="read">Read-Only (sensors &amp; status)</option>' +
      '<option value="full">Full Access (sleep &amp; controls)</option>' +
      "</select>" +
      "</div>" +
      '<button type="submit" id="btn-token-create" class="btn-primary auth-full-btn">Create API Token</button>' +
      '<div id="hub-token-reveal" class="totp-secret-box font-mono" hidden></div>' +
      "</form>" +
      '<div id="hub-tokens-msg" class="auth-feedback" role="status" aria-live="polite"></div>' +
      '<div id="hub-tokens-list" class="auth-devices-list">' +
      '<div class="empty-state">Loading scoped tokens...</div>' +
      "</div>" +
      "</div>" +

      '<div class="auth-actions">' +
      '<div class="auth-secondary-row">' +
      '<button type="button" id="hub-signout" class="btn-secondary">Sign out this browser</button>' +
      '<button type="button" id="hub-account-close" class="btn-ghost">Close</button>' +
      "</div>" +
      "</div>" +
      "</div>"
    );

    function closeAccount() {
      el.remove();
      if (prevFocus && typeof prevFocus.focus === "function" && document.contains(prevFocus)) {
        prevFocus.focus();
      }
    }

    wirePasswordToggles(el);
    trapFocus(el, closeAccount);
    el.addEventListener("click", function (ev) { if (ev.target === el) closeAccount(); });
    document.getElementById("hub-account-close").addEventListener("click", closeAccount);
    document.getElementById("hub-signout").addEventListener("click", async function () {
      await postJson("/api/auth/logout");
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) { /* ignore */ }
      token = "";
      window.location.reload();
    });

    // Tab switching
    const tabs = el.querySelectorAll("[data-acct-tab]");
    const panels = {
      security: document.getElementById("acct-panel-security"),
      devices: document.getElementById("acct-panel-devices"),
      family: document.getElementById("acct-panel-family"),
      tokens: document.getElementById("acct-panel-tokens"),
    };
    function activateAcctTab(key) {
      tabs.forEach(function (btn) {
        const active = btn.getAttribute("data-acct-tab") === key;
        btn.setAttribute("aria-selected", active ? "true" : "false");
      });
      Object.keys(panels).forEach(function (k) {
        panels[k].hidden = k !== key;
      });
      if (key === "devices") loadDevices();
      if (key === "tokens") loadTokens();
    }
    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        activateAcctTab(btn.getAttribute("data-acct-tab"));
      });
    });

    // Password update
    const msg = document.getElementById("hub-account-msg");
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

    // Access settings (TOTP + Family)
    let pendingTotpUri = "";
    const totpStatusText = document.getElementById("hub-totp-status-text");
    const btnTotpSetup = document.getElementById("btn-totp-setup");
    const btnTotpDisableToggle = document.getElementById("btn-totp-disable-toggle");
    const totpSetupBox = document.getElementById("hub-totp-setup-box");
    const totpRecoveryBox = document.getElementById("hub-totp-recovery-box");
    const totpDisableBox = document.getElementById("hub-totp-disable-box");
    const totpMsg = document.getElementById("hub-totp-msg");
    const famEnabledChk = document.getElementById("hub-family-enabled");
    const famModeSel = document.getElementById("hub-family-mode");
    const famPwWrap = document.getElementById("hub-family-pw-wrap");
    const famMsg = document.getElementById("hub-family-msg");

    function syncFamilyModeUi() {
      famPwWrap.hidden = famModeSel.value === "lan_open";
    }
    famModeSel.addEventListener("change", syncFamilyModeUi);

    function applyAccessState(data) {
      const totp = (data && data.totp) || {};
      const fam = (data && data.family) || {};
      const enabled = Boolean(totp.enabled);
      totpStatusText.textContent = enabled
        ? "Enabled (" + Number(totp.recovery_remaining || 0) + " recovery codes remaining)"
        : "Optional second factor for browser logins (currently off)";
      btnTotpSetup.hidden = enabled;
      btnTotpDisableToggle.hidden = !enabled;
      if (!enabled) totpDisableBox.hidden = true;

      famEnabledChk.checked = Boolean(fam.enabled);
      famModeSel.value = fam.lan_open ? "lan_open" : "password";
      syncFamilyModeUi();
    }

    async function loadAccess() {
      const res = await apiJson("GET", "/api/auth/access");
      if (res.ok && res.data) applyAccessState(res.data);
    }

    btnTotpSetup.addEventListener("click", async function () {
      totpMsg.textContent = "";
      totpRecoveryBox.hidden = true;
      const res = await postJson("/api/auth/totp/setup", {});
      if (!res.ok) {
        totpMsg.className = "auth-feedback is-error";
        totpMsg.textContent = res.data.error || "Could not start 2FA setup.";
        return;
      }
      pendingTotpUri = res.data.uri || "";
      document.getElementById("totp-secret-display").textContent = res.data.formatted_secret || res.data.secret || "";
      totpSetupBox.hidden = false;
      document.getElementById("totp-verify-code").focus();
    });

    document.getElementById("btn-totp-copy-uri").addEventListener("click", async function () {
      if (!pendingTotpUri) return;
      try {
        await navigator.clipboard.writeText(pendingTotpUri);
        totpMsg.className = "auth-feedback is-success";
        totpMsg.textContent = "Copied otpauth:// URI to clipboard.";
      } catch (_) {
        totpMsg.className = "auth-feedback";
        totpMsg.textContent = pendingTotpUri;
      }
    });

    document.getElementById("btn-totp-enable").addEventListener("click", async function () {
      const code = document.getElementById("totp-verify-code").value.trim();
      const res = await postJson("/api/auth/totp/enable", { code: code });
      if (!res.ok) {
        totpMsg.className = "auth-feedback is-error";
        totpMsg.textContent = res.data.error || "Verification failed.";
        return;
      }
      totpSetupBox.hidden = true;
      document.getElementById("totp-verify-code").value = "";
      const codes = Array.isArray(res.data.recovery_codes) ? res.data.recovery_codes : [];
      document.getElementById("totp-recovery-list").innerHTML = codes.map(function (c) {
        return '<span class="well">' + esc(c) + "</span>";
      }).join("");
      totpRecoveryBox.hidden = codes.length === 0;
      totpMsg.className = "auth-feedback is-success";
      totpMsg.textContent = res.data.message || "Two-factor authentication enabled.";
      loadAccess();
      refreshStatus(true);
    });

    btnTotpDisableToggle.addEventListener("click", function () {
      totpDisableBox.hidden = !totpDisableBox.hidden;
      if (!totpDisableBox.hidden) document.getElementById("totp-disable-pw").focus();
    });

    document.getElementById("btn-totp-disable-confirm").addEventListener("click", async function () {
      const pw = document.getElementById("totp-disable-pw").value;
      const res = await postJson("/api/auth/totp/disable", { password: pw });
      if (!res.ok) {
        totpMsg.className = "auth-feedback is-error";
        totpMsg.textContent = res.data.error || "Could not disable 2FA.";
        return;
      }
      document.getElementById("totp-disable-pw").value = "";
      totpDisableBox.hidden = true;
      totpRecoveryBox.hidden = true;
      totpMsg.className = "auth-feedback is-success";
      totpMsg.textContent = res.data.message || "2FA disabled.";
      loadAccess();
      refreshStatus(true);
    });

    // Devices list
    const devicesList = document.getElementById("hub-sessions-list");
    const sessionsMsg = document.getElementById("hub-sessions-msg");
    async function loadDevices() {
      const res = await apiJson("GET", "/api/auth/sessions");
      if (!res.ok) {
        devicesList.innerHTML = '<div class="empty-state">Could not load signed-in devices.</div>';
        return;
      }
      const list = Array.isArray(res.data.sessions) ? res.data.sessions : [];
      if (!list.length) {
        devicesList.innerHTML = '<div class="empty-state">No browser cookie sessions active right now (using API token).</div>';
        return;
      }
      devicesList.innerHTML = list.map(function (s) {
        const badge = s.is_current
          ? '<span class="badge-status-synced">This browser</span>'
          : '<span class="badge">' + esc(s.role === "family" ? "Family" : "Owner") + "</span>";
        return (
          '<div class="auth-device-row">' +
          '<div class="auth-device-meta">' +
          '<div class="auth-device-title">' + esc(s.device) + " " + badge + "</div>" +
          '<div class="auth-subtitle font-mono">' + esc(s.ip) + " &middot; Last seen " + esc(relTime(s.last_seen)) + "</div>" +
          "</div>" +
          '<button type="button" class="btn-ghost btn-revoke-session" data-sid="' + esc(s.id) + '" data-current="' + (s.is_current ? "1" : "0") + '">' +
          (s.is_current ? "Sign out" : "Revoke") +
          "</button>" +
          "</div>"
        );
      }).join("");

      devicesList.querySelectorAll(".btn-revoke-session").forEach(function (btn) {
        btn.addEventListener("click", async function () {
          const sid = btn.getAttribute("data-sid");
          const isCur = btn.getAttribute("data-current") === "1";
          const r = await apiJson("DELETE", "/api/auth/sessions/" + encodeURIComponent(sid));
          if (r.ok) {
            if (isCur) {
              window.location.reload();
              return;
            }
            sessionsMsg.className = "auth-feedback is-success";
            sessionsMsg.textContent = "Device signed out.";
            loadDevices();
          } else {
            sessionsMsg.className = "auth-feedback is-error";
            sessionsMsg.textContent = r.data.error || "Could not sign out device.";
          }
        });
      });
    }

    document.getElementById("btn-sessions-revoke-others").addEventListener("click", async function () {
      const res = await postJson("/api/auth/sessions/revoke-others", {});
      sessionsMsg.className = "auth-feedback " + (res.ok ? "is-success" : "is-error");
      sessionsMsg.textContent = res.ok
        ? ("Signed out " + Number(res.data.revoked_count || 0) + " other device(s).")
        : (res.data.error || "Could not sign out other devices.");
      loadDevices();
    });

    // Scoped API Tokens list & creation
    const tokensList = document.getElementById("hub-tokens-list");
    const tokensMsg = document.getElementById("hub-tokens-msg");
    const tokenReveal = document.getElementById("hub-token-reveal");

    async function loadTokens() {
      const res = await apiJson("GET", "/api/auth/tokens");
      if (!res.ok) {
        tokensList.innerHTML = '<div class="empty-state">Could not load API tokens.</div>';
        return;
      }
      const rows = Array.isArray(res.data.tokens) ? res.data.tokens : [];
      if (!rows.length) {
        tokensList.innerHTML = '<div class="empty-state">No scoped tokens created yet.</div>';
        return;
      }
      tokensList.innerHTML = rows.map(function (t) {
        const badge = t.scope === "full"
          ? '<span class="badge-status-synced">Full</span>'
          : '<span class="badge">Read-Only</span>';
        return (
          '<div class="auth-device-row">' +
          '<div class="auth-device-meta">' +
          '<div class="auth-device-title">' + esc(t.name) + " " + badge + "</div>" +
          '<div class="auth-subtitle font-mono">' + esc(t.prefix) + "&hellip; &middot; Last used " + esc(relTime(t.last_used)) + "</div>" +
          "</div>" +
          '<button type="button" class="btn-ghost btn-revoke-token" data-tid="' + esc(t.id) + '">Revoke</button>' +
          "</div>"
        );
      }).join("");

      tokensList.querySelectorAll(".btn-revoke-token").forEach(function (btn) {
        btn.addEventListener("click", async function () {
          const tid = btn.getAttribute("data-tid");
          const r = await apiJson("DELETE", "/api/auth/tokens/" + encodeURIComponent(tid));
          if (r.ok) {
            tokensMsg.className = "auth-feedback is-success";
            tokensMsg.textContent = "API token revoked.";
            loadTokens();
          } else {
            tokensMsg.className = "auth-feedback is-error";
            tokensMsg.textContent = r.data.error || "Could not revoke API token.";
          }
        });
      });
    }

    document.getElementById("hub-token-form").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const name = document.getElementById("hub-token-name").value.trim();
      const scope = document.getElementById("hub-token-scope").value;
      const res = await postJson("/api/auth/tokens", { name: name, scope: scope });
      if (!res.ok) {
        tokensMsg.className = "auth-feedback is-error";
        tokensMsg.textContent = res.data.error || "Could not create API token.";
        return;
      }
      document.getElementById("hub-token-name").value = "";
      if (tokenReveal && res.data.token) {
        tokenReveal.textContent = "Copy now (shown once): " + res.data.token;
        tokenReveal.hidden = false;
      }
      tokensMsg.className = "auth-feedback is-success";
      tokensMsg.textContent = res.data.message || "Scoped token created.";
      loadTokens();
    });

    // Family save
    document.getElementById("hub-family-form").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const pw = document.getElementById("hub-family-pw").value;
      const res = await postJson("/api/auth/access", {
        family_enabled: famEnabledChk.checked,
        family_lan_open: famModeSel.value === "lan_open",
        family_password: pw ? pw : null,
      });
      famMsg.className = "auth-feedback " + (res.ok ? "is-success" : "is-error");
      famMsg.textContent = res.ok ? (res.data.message || "Family settings saved.") : (res.data.error || "Could not save family settings.");
      if (res.ok) {
        document.getElementById("hub-family-pw").value = "";
        refreshStatus(true);
      }
    });

    loadAccess();
    document.getElementById("hub-pw-current").focus();
  }

  window.HomelabAuth = {
    getToken: function () { return token; },
    getStatus: function () { return Object.assign({}, authStatus); },
    ready: function () { return refreshStatus(false); },
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
