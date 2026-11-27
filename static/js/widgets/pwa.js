/**
 * Widget: Progressive Web App (PWA) & Opt-In Browser Alert Notifications (Phase 4B)
 * Registers sw.js, captures beforeinstallprompt for home-screen installation,
 * and dispatches desktop/phone browser notifications when new 2B alerts fire.
 */

import { $ } from "../shared/dom.js";
import { showToast } from "../shared/toast.js";

const NOTIF_PREF_KEY = "hub_browser_notifications";
let deferredPrompt = null;
let swRegistration = null;
const notifiedAlertKeys = new Set();

function isNotifEnabled() {
  try {
    return localStorage.getItem(NOTIF_PREF_KEY) === "on";
  } catch (_) {
    return false;
  }
}

function syncNotifButton() {
  const btn = $("btn-browser-notifications");
  const label = $("browser-notif-label");
  if (!btn) return;
  const supported = "Notification" in window;
  if (!supported) {
    btn.hidden = true;
    return;
  }
  const active = isNotifEnabled() && Notification.permission === "granted";
  btn.setAttribute("aria-pressed", active ? "true" : "false");
  if (label) {
    label.textContent = active ? "Browser Alerts: On" : "Browser Alerts: Off";
  }
}

export function notifyFiringAlerts(firing) {
  if (!Array.isArray(firing) || !firing.length) return;
  if (!("Notification" in window) || Notification.permission !== "granted" || !isNotifEnabled()) return;

  const activeKeys = new Set();
  for (const item of firing) {
    const key = `${item.id || item.rule || item.title}:${item.since || ""}`;
    activeKeys.add(key);
    if (notifiedAlertKeys.has(key)) continue;
    notifiedAlertKeys.add(key);
    const title = `Control Hub Alert: ${item.title || "Server notice"}`;
    const body = item.message || "Inspect Control Hub Alerts for details.";
    try {
      if (swRegistration && swRegistration.showNotification) {
        swRegistration.showNotification(title, {
          body,
          icon: "/img/icons/hub-app.svg",
          badge: "/img/icons/hub-app.svg",
          tag: `hub-alert-${item.id || item.title || "notice"}`,
        });
      } else {
        new Notification(title, { body, icon: "/img/icons/hub-app.svg" });
      }
    } catch (_) {
      /* Notification blocked on insecure context */
    }
  }
  for (const oldKey of Array.from(notifiedAlertKeys)) {
    if (!activeKeys.has(oldKey)) notifiedAlertKeys.delete(oldKey);
  }
}

export function setupPwa() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" })
      .then((reg) => { swRegistration = reg; })
      .catch(() => { /* SW registration skipped in restricted origins */ });
  }

  const installBtn = $("btn-pwa-install");
  window.addEventListener("beforeinstallprompt", (ev) => {
    ev.preventDefault();
    deferredPrompt = ev;
    if (installBtn) installBtn.hidden = false;
  });

  if (installBtn) {
    installBtn.addEventListener("click", async () => {
      if (!deferredPrompt) {
        showToast("Install Control Hub", "Use your browser's Add to Home Screen or Install App menu.", "info");
        return;
      }
      deferredPrompt.prompt();
      try {
        await deferredPrompt.userChoice;
      } catch (_) { /* cancelled */ }
      deferredPrompt = null;
      installBtn.hidden = true;
    });
  }

  const notifBtn = $("btn-browser-notifications");
  if (notifBtn) {
    notifBtn.addEventListener("click", async () => {
      if (!("Notification" in window)) {
        showToast("Unavailable", "This browser does not support desktop/phone notifications.", "warning");
        return;
      }
      if (isNotifEnabled() && Notification.permission === "granted") {
        try { localStorage.setItem(NOTIF_PREF_KEY, "off"); } catch (_) { /* ignore */ }
        syncNotifButton();
        showToast("Browser Alerts Paused", "Browser push alerts turned off on this device.", "info");
        return;
      }
      let perm = Notification.permission;
      if (perm === "default") {
        try { perm = await Notification.requestPermission(); } catch (_) { perm = "denied"; }
      }
      if (perm === "granted") {
        try { localStorage.setItem(NOTIF_PREF_KEY, "on"); } catch (_) { /* ignore */ }
        syncNotifButton();
        showToast("Browser Alerts Enabled", "New server alerts will also notify this device.", "success");
      } else {
        try { localStorage.setItem(NOTIF_PREF_KEY, "off"); } catch (_) { /* ignore */ }
        syncNotifButton();
        showToast("Permission Blocked", "Allow notifications in your browser site settings (requires HTTPS or localhost).", "warning");
      }
    });
  }

  syncNotifButton();
}
