/**
 * Widget: Header (Clock, Uptime, Kiosk Mode, Responsive Menu & Status Strip)
 */

import { $ } from "../shared/dom.js";
import { state } from "../state.js";

const liveClock = $("live-clock");
const systemUptime = $("system-uptime");
const btnKioskToggle = $("btn-kiosk-toggle");
const sleepCountdown = $("sleep-countdown");
const sleepCurrentNeedle = $("sleep-current-needle");
const btnHeaderMenu = $("btn-header-menu");
const headerActionsMenu = $("header-actions-menu");
const btnStatusStripToggle = $("btn-status-strip-toggle");
const hudChipsStrip = $("hud-chips-strip");

function formatLocalClockParts() {
  const now = new Date();
  const tz = state.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  try {
    const timeStr = now.toLocaleTimeString("en-GB", { hour12: false, timeZone: tz });
    const tzName = state.tzAbbr || (now.toLocaleTimeString("en-US", { timeZone: tz, timeZoneName: "short" }).split(" ").pop() || tz);
    return { timeStr, tzName };
  } catch (_) {
    return {
      timeStr: now.toLocaleTimeString("en-GB", { hour12: false }),
      tzName: state.tzAbbr || "Local",
    };
  }
}

export function updateClock() {
  const { timeStr, tzName } = formatLocalClockParts();
  if (liveClock) liveClock.textContent = `${timeStr} ${tzName}`;

  if (state.sleepSecondsRemaining > 0 && !state.sleepSkipActive) {
    state.sleepSecondsRemaining--;
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
  } catch (_) { /* ignore */ }
}

export function setUptime(uptimeText) {
  if (systemUptime && uptimeText) {
    systemUptime.textContent = uptimeText;
  }
}

export function setMenuOpen(open) {
  if (!headerActionsMenu || !btnHeaderMenu) return;
  headerActionsMenu.classList.toggle("is-open", open);
  btnHeaderMenu.setAttribute("aria-expanded", open ? "true" : "false");
}

export function setupHeader() {
  updateClock();
  setInterval(updateClock, 1000);

  if (btnKioskToggle) {
    btnKioskToggle.addEventListener("click", () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => { });
      } else if (document.exitFullscreen) {
        document.exitFullscreen();
      }
    });
  }

  if (btnHeaderMenu && headerActionsMenu) {
    btnHeaderMenu.addEventListener("click", () => {
      const next = !headerActionsMenu.classList.contains("is-open");
      setMenuOpen(next);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && headerActionsMenu.classList.contains("is-open")) {
        setMenuOpen(false);
        btnHeaderMenu.focus();
      }
    });
  }

  if (btnStatusStripToggle && hudChipsStrip) {
    btnStatusStripToggle.addEventListener("click", () => {
      const isOpen = hudChipsStrip.classList.toggle("is-open");
      btnStatusStripToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
  }
}
