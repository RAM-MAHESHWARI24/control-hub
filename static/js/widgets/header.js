/**
 * Widget: Header (Cyber-HUD, Clock, Kiosk Mode)
 */

import { $ } from "../shared/dom.js";
import { state } from "../state.js";

const liveClock = $("live-clock");
const systemUptime = $("system-uptime");
const btnKioskToggle = $("btn-kiosk-toggle");
const sleepCountdown = $("sleep-countdown");
const sleepCurrentNeedle = $("sleep-current-needle");

export function updateClock() {
  const now = new Date();
  const timeStr = now.toLocaleTimeString("en-GB", { hour12: false, timeZone: "Asia/Kolkata" });
  if (liveClock) liveClock.textContent = `${timeStr} IST`;

  // Sleep countdown decrement
  if (state.sleepSecondsRemaining > 0 && !state.sleepSkipActive) {
    state.sleepSecondsRemaining--;
    const h = Math.floor(state.sleepSecondsRemaining / 3600);
    const m = Math.floor((state.sleepSecondsRemaining % 3600) / 60);
    const s = state.sleepSecondsRemaining % 60;
    if (sleepCountdown) {
      sleepCountdown.textContent = `${h}h ${m}m ${s}s to sleep`;
    }
  }

  // 24-Hour Timeline needle position (IST minutes from midnight: 0 to 1440)
  try {
    const parts = timeStr.split(":");
    const curHours = parseInt(parts[0], 10);
    const curMins = parseInt(parts[1], 10);
    const totalMins = curHours * 60 + curMins;
    const needlePct = Math.min(100, Math.max(0, (totalMins / 1440) * 100));
    if (sleepCurrentNeedle) {
      sleepCurrentNeedle.style.left = `${needlePct.toFixed(1)}%`;
    }
  } catch (e) {}
}

export function setUptime(uptimeText) {
  if (systemUptime && uptimeText) {
    systemUptime.textContent = uptimeText;
  }
}

export function setupHeader() {
  updateClock();
  setInterval(updateClock, 1000);

  if (btnKioskToggle) {
    btnKioskToggle.addEventListener("click", () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else {
        if (document.exitFullscreen) document.exitFullscreen();
      }
    });
  }
}
