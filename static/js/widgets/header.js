/**
 * Widget: Slim Top Bar (Hostname, Truthful Connection Pill, Theme Switcher,
 * Clock/Uptime, Tools Dropdown, Kiosk Mode & Sleep Needle)
 */

import { $ } from "../shared/dom.js";
import { state } from "../state.js";

const THEME_STORAGE_KEY = "hub_theme";
const SIDEBAR_STORAGE_KEY = "hub_sidebar_collapsed";

const liveClock = $("live-clock");
const liveClockMobile = $("live-clock-mobile");
const systemUptime = $("system-uptime");
const systemUptimeMobile = $("system-uptime-mobile");
const hubHostname = $("hub-hostname");
const footerBrandText = $("footer-brand-text");

const connPill = $("connection-pill");
const connPillText = $("connection-pill-text");

const btnKioskToggle = $("btn-kiosk-toggle");
const btnThemeToggle = $("btn-theme-toggle");
const themeToggleIcon = $("theme-toggle-icon");
const btnHeaderMenu = $("btn-header-menu");
const headerActionsMenu = $("header-actions-menu");
const btnSidebarToggle = $("btn-sidebar-toggle");
const sidebarToggleIcon = $("sidebar-toggle-icon");
const sidebarToggleLabel = document.querySelector(".sidebar-toggle-label");
const mainContent = $("main-content");

const sleepCountdown = $("sleep-countdown");
const sleepCurrentNeedle = $("sleep-current-needle");

let onThemeChangedCallback = null;
let onRetryConnectionCallback = null;

function resolveTheme(pref) {
  if (pref === "system") {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  if (pref === "high-contrast") return "high-contrast";
  return pref === "light" ? "light" : "dark";
}

export function applyTheme(pref = "dark") {
  const validPref = ["dark", "light", "high-contrast", "system"].includes(pref) ? pref : "dark";
  const resolved = resolveTheme(validPref);
  state.themePreference = validPref;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePref = validPref;

  try {
    localStorage.setItem(THEME_STORAGE_KEY, validPref);
  } catch (_) {
    /* ignore storage errors */
  }

  // Update header toggle icon & aria-label
  if (themeToggleIcon) {
    const useEl = themeToggleIcon.querySelector("use");
    const iconId = validPref === "system" ? "icon-monitor" : (resolved === "light" ? "icon-sun" : "icon-moon");
    if (useEl) useEl.setAttribute("href", `/img/icons/ui-sprite.svg#${iconId}`);
  }
  if (btnThemeToggle) {
    btnThemeToggle.setAttribute("aria-label", `Switch theme (current: ${validPref})`);
  }

  // Sync segmented buttons inside dropdown
  document.querySelectorAll(".theme-opt-btn").forEach((btn) => {
    const active = btn.getAttribute("data-theme-choice") === validPref;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  });

  if (typeof onThemeChangedCallback === "function") {
    onThemeChangedCallback(resolved);
  }
}

export function setThemeChangeHandler(fn) {
  onThemeChangedCallback = fn;
}

export function setRetryConnectionHandler(fn) {
  onRetryConnectionCallback = fn;
}

export function recordPollResult(ok) {
  if (ok) {
    state.consecutivePollFailures = 0;
    state.lastSuccessfulPollAt = Date.now();
  } else {
    state.consecutivePollFailures += 1;
  }

  if (!connPill || !connPillText) return;
  if (state.consecutivePollFailures === 0) {
    connPill.className = "conn-pill is-live";
    connPillText.textContent = "Live";
    connPill.setAttribute("aria-label", "Connection status: Live. Click to refresh.");
  } else if (state.consecutivePollFailures === 1) {
    connPill.className = "conn-pill is-reconnecting";
    connPillText.textContent = "Reconnecting";
    connPill.setAttribute("aria-label", "Connection status: Reconnecting. Click to retry.");
  } else {
    connPill.className = "conn-pill is-offline";
    connPillText.textContent = "Offline";
    connPill.setAttribute("aria-label", "Connection status: Offline. Click to retry.");
  }
}

export function setHostIdentity(hostname, port) {
  if (hostname) {
    state.hostname = hostname;
    if (hubHostname) {
      hubHostname.textContent = hostname;
      hubHostname.hidden = false;
    }
    document.title = `Control Hub · ${hostname}`;
  }
  if (port) {
    state.hubPort = String(port);
  }
  if (footerBrandText) {
    const hostPart = state.hostname ? ` · ${state.hostname}` : "";
    footerBrandText.textContent = `Homelab Control Hub${hostPart} · Port ${state.hubPort || "7575"}`;
  }
}

function compactTzLabel(raw) {
  const s = String(raw || "").trim();
  if (!s) return "UTC";
  if (s.length <= 6 || !s.includes(" ")) return s;
  const initials = s.split(/\s+/).map((w) => w[0]).join("").toUpperCase();
  return initials.length >= 2 && initials.length <= 5 ? initials : s.slice(0, 8);
}

function formatLocalClockParts() {
  const now = new Date();
  const tz = state.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  try {
    const timeStr = now.toLocaleTimeString("en-GB", { hour12: false, timeZone: tz });
    const rawTz = state.tzAbbr || (now.toLocaleTimeString("en-US", { timeZone: tz, timeZoneName: "short" }).split(" ").pop() || tz);
    return { timeStr, tzName: compactTzLabel(rawTz) };
  } catch (_) {
    return {
      timeStr: now.toLocaleTimeString("en-GB", { hour12: false }),
      tzName: compactTzLabel(state.tzAbbr || "Local"),
    };
  }
}

export function updateClock() {
  const { timeStr, tzName } = formatLocalClockParts();
  const formatted = `${timeStr} ${tzName}`;
  if (liveClock) liveClock.textContent = formatted;
  if (liveClockMobile) liveClockMobile.textContent = formatted;

  if (
    state.sleepInstalled
    && state.sleepStateMode !== "disabled"
    && state.sleepStateMode !== "not_installed"
    && state.sleepSecondsRemaining > 0
    && !state.sleepSkipActive
  ) {
    state.sleepSecondsRemaining -= 1;
    const h = Math.floor(state.sleepSecondsRemaining / 3600);
    const m = Math.floor((state.sleepSecondsRemaining % 3600) / 60);
    const s = state.sleepSecondsRemaining % 60;
    if (sleepCountdown) {
      sleepCountdown.textContent = `${h}h ${m}m ${s}s to sleep`;
    }
  }

  try {
    const parts = timeStr.split(":");
    const curHours = parseInt(parts[0], 10);
    const curMins = parseInt(parts[1], 10);
    const totalMins = curHours * 60 + curMins;
    const needlePct = Math.min(100, Math.max(0, (totalMins / 1440) * 100));
    if (sleepCurrentNeedle) {
      sleepCurrentNeedle.style.left = `${needlePct.toFixed(1)}%`;
    }
  } catch (_) {
    /* ignore */
  }
}

export function setUptime(uptimeText) {
  if (!uptimeText) return;
  if (systemUptime) systemUptime.textContent = uptimeText;
  if (systemUptimeMobile) systemUptimeMobile.textContent = uptimeText;
}

export function setMenuOpen(open) {
  if (!headerActionsMenu || !btnHeaderMenu) return;
  headerActionsMenu.classList.toggle("is-open", open);
  btnHeaderMenu.setAttribute("aria-expanded", open ? "true" : "false");
}

export function setSidebarCollapsed(collapsed, persist = true) {
  const isCollapsed = Boolean(collapsed);
  document.documentElement.dataset.sidebarCollapsed = isCollapsed ? "true" : "false";
  if (persist) {
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, isCollapsed ? "true" : "false");
    } catch (_) {
      /* ignore storage errors */
    }
  }

  if (btnSidebarToggle) {
    btnSidebarToggle.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    btnSidebarToggle.setAttribute("aria-label", isCollapsed ? "Expand sidebar" : "Collapse sidebar");
    btnSidebarToggle.setAttribute("title", isCollapsed ? "Expand sidebar" : "Collapse sidebar");
  }
  if (sidebarToggleIcon) {
    const useEl = sidebarToggleIcon.querySelector("use");
    if (useEl) {
      useEl.setAttribute("href", `/img/icons/ui-sprite.svg#${isCollapsed ? "icon-arrow-right" : "icon-arrow-left"}`);
    }
  }
  if (sidebarToggleLabel) {
    sidebarToggleLabel.textContent = isCollapsed ? "Expand" : "Collapse";
  }
}

export function setupHeader() {
  // Initialize theme from pre-boot dataset or localStorage
  const initialPref = document.documentElement.dataset.themePref || "dark";
  applyTheme(initialPref);

  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
      if (state.themePreference === "system") applyTheme("system");
    });
  }

  if (btnThemeToggle) {
    btnThemeToggle.addEventListener("click", () => {
      const order = ["dark", "light", "system"];
      const next = order[(order.indexOf(state.themePreference) + 1) % order.length];
      applyTheme(next);
    });
  }

  document.querySelectorAll(".theme-opt-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyTheme(btn.getAttribute("data-theme-choice") || "dark");
    });
  });

  if (connPill) {
    connPill.addEventListener("click", () => {
      if (typeof onRetryConnectionCallback === "function") onRetryConnectionCallback();
    });
  }

  updateClock();
  setInterval(updateClock, 1000);

  if (btnHeaderMenu && headerActionsMenu) {
    btnHeaderMenu.addEventListener("click", (e) => {
      e.stopPropagation();
      const next = !headerActionsMenu.classList.contains("is-open");
      setMenuOpen(next);
    });
    document.addEventListener("click", (e) => {
      if (
        headerActionsMenu.classList.contains("is-open")
        && !headerActionsMenu.contains(e.target)
        && !btnHeaderMenu.contains(e.target)
      ) {
        setMenuOpen(false);
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && headerActionsMenu.classList.contains("is-open")) {
        setMenuOpen(false);
        btnHeaderMenu.focus();
      }
    });
  }

  // Proxy buttons inside dropdown & System tools panel to trigger main modal openers
  document.querySelectorAll("[data-proxy-click]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-proxy-click");
      setMenuOpen(false);
      const target = targetId ? $(targetId) : null;
      if (target) target.click();
    });
  });

  // Collapsible sidebar (expand -> / collapse <- button + auto-collapse on main-content click)
  const initialCollapsed = document.documentElement.dataset.sidebarCollapsed === "true";
  setSidebarCollapsed(initialCollapsed, false);

  if (btnSidebarToggle) {
    btnSidebarToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      const currentlyCollapsed = document.documentElement.dataset.sidebarCollapsed === "true";
      setSidebarCollapsed(!currentlyCollapsed, true);
    });
  }

  if (mainContent) {
    mainContent.addEventListener("click", () => {
      if (window.innerWidth < 600) return;
      const sel = window.getSelection ? window.getSelection().toString() : "";
      if (sel && sel.length > 0) return;
      if (document.documentElement.dataset.sidebarCollapsed !== "true") {
        setSidebarCollapsed(true, true);
      }
    });
  }
}
