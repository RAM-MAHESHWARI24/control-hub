/**
 * Widget: Sleep Guard Power Automation Controller
 * Handles installed / not_installed / disabled / skip / override / default states,
 * dual midnight-wrapping 24h timeline segments, quick shifts, and scheduler modal.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { closeModal, openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { renderOverview } from "./overview.js";

const sleepCard = $("sleep-guard-card");
const sleepIcon = $("sleep-icon");
const sleepStatusTitle = $("sleep-status-title");
const sleepCountdown = $("sleep-countdown");
const sleepSubtext = $("sleep-subtext");
const sleepToggleBtn = $("sleep-toggle-btn");
const sleepBtnText = $("sleep-btn-text");
const sleepBtnSpinner = $("sleep-btn-spinner");
const sleepWindowZone = $("sleep-window-zone");
const sleepWindowZoneWrap = $("sleep-window-zone-wrap");
const sleepTimeline = $("sleep-timeline-container");
const sleepOverridePill = $("sleep-override-pill");
const sleepOverrideText = $("sleep-override-text");
const btnClearHeroOverride = $("btn-clear-hero-override");

const btnShift1h = $("btn-shift-1h");
const btnShift2h = $("btn-shift-2h");
const btnOpenSleepModal = $("btn-open-sleep-modal");

const sleepModal = $("sleep-schedule-modal");
const btnCloseModal = $("sleep-modal-close");
const btnCancelModal = $("sleep-modal-cancel");
const btnSaveModal = $("sleep-modal-save");
const saveModalSpinner = $("sleep-modal-spinner");
const saveModalText = $("sleep-modal-save-text");
const modalFooterHint = $("sleep-modal-footer-hint");

const tabBtnTonight = $("tab-btn-tonight");
const tabBtnPermanent = $("tab-btn-permanent");
const tabPaneTonight = $("tab-tonight");
const tabPanePermanent = $("tab-permanent");

const tonightActiveBanner = $("tonight-active-banner");
const tonightActiveText = $("tonight-active-text");
const btnRevertTonight = $("btn-revert-tonight");
const tonightSleepInput = $("tonight-sleep-input");
const tonightWakeInput = $("tonight-wake-input");
const tonightDurationBadge = $("tonight-duration-badge");
const tonightPreviewText = $("tonight-preview-text");

const permEnabledCheckbox = $("perm-enabled-checkbox");
const permSleepInput = $("perm-sleep-input");
const permWakeInput = $("perm-wake-input");
const permDurationBadge = $("perm-duration-badge");
const permPreviewText = $("perm-preview-text");

let activeTab = "tab-tonight";
let permanentConfig = { enabled: true, sleep_time: "00:00", wake_time: "06:00", duration_hours: 6.0 };
let tonightOverride = null;

function tzLabel() {
  return state.tzAbbr || state.timezone || "local";
}

function setSleepIcon(iconName) {
  if (!sleepIcon) return;
  const useEl = sleepIcon.querySelector("use");
  if (useEl) useEl.setAttribute("href", `/img/icons/ui-sprite.svg#icon-${iconName}`);
}

function updateTzBadges() {
  const abbr = tzLabel();
  document.querySelectorAll(".tz-badge").forEach((el) => {
    el.textContent = abbr;
  });
}

function calculateWindowDuration(sleepTimeStr, wakeTimeStr) {
  if (!sleepTimeStr || !wakeTimeStr) return { hours: "6", mins: 360 };
  const sParts = sleepTimeStr.split(":");
  const wParts = wakeTimeStr.split(":");
  const sMins = parseInt(sParts[0], 10) * 60 + parseInt(sParts[1], 10);
  const wMins = parseInt(wParts[0], 10) * 60 + parseInt(wParts[1], 10);
  let diff = wMins - sMins;
  if (diff <= 0) diff += 1440;
  return {
    hours: (diff / 60).toFixed(1).replace(/\.0$/, ""),
    mins: diff,
  };
}

function updateTonightPreview() {
  if (!tonightSleepInput || !tonightWakeInput) return;
  const sVal = tonightSleepInput.value || "01:00";
  const wVal = tonightWakeInput.value || "07:00";
  const dur = calculateWindowDuration(sVal, wVal);
  const tz = tzLabel();

  if (tonightDurationBadge) tonightDurationBadge.textContent = `${dur.hours} hrs`;
  if (tonightPreviewText) tonightPreviewText.textContent = `Sleep at ${sVal} ${tz} · Wake at ${wVal} ${tz}`;
}

function updatePermanentPreview() {
  if (!permSleepInput || !permWakeInput) return;
  const sVal = permSleepInput.value || "00:00";
  const wVal = permWakeInput.value || "06:00";
  const dur = calculateWindowDuration(sVal, wVal);
  const tz = tzLabel();

  if (permDurationBadge) permDurationBadge.textContent = `${dur.hours} hrs`;
  if (permPreviewText) {
    permPreviewText.textContent = (permEnabledCheckbox && !permEnabledCheckbox.checked)
      ? "Automated nightly sleep disabled"
      : `Every night from ${sVal} ${tz} to ${wVal} ${tz}`;
  }
}

function switchTab(tabId) {
  activeTab = tabId;
  const isTonight = tabId === "tab-tonight";
  if (tabBtnTonight) {
    tabBtnTonight.classList.toggle("active", isTonight);
    tabBtnTonight.setAttribute("aria-selected", isTonight ? "true" : "false");
  }
  if (tabBtnPermanent) {
    tabBtnPermanent.classList.toggle("active", !isTonight);
    tabBtnPermanent.setAttribute("aria-selected", !isTonight ? "true" : "false");
  }
  if (tabPaneTonight) tabPaneTonight.classList.toggle("active", isTonight);
  if (tabPanePermanent) tabPanePermanent.classList.toggle("active", !isTonight);
  if (saveModalText) saveModalText.textContent = isTonight ? "Apply for Tonight Only" : "Save Default Schedule";
  if (modalFooterHint) {
    modalFooterHint.textContent = isTonight
      ? "One-off shift (reverts to default after wake)"
      : "Permanent schedule (updates cron & /etc/server-suspend.conf)";
  }
}

export function openSleepModal(initialTab = "tab-tonight", triggerEl = null) {
  if (!sleepModal) return;
  switchTab(initialTab);
  updateTzBadges();

  if (tonightOverride && tonightOverride.active) {
    if (tonightActiveBanner) tonightActiveBanner.style.display = "flex";
    if (tonightActiveText) {
      const tz = tzLabel();
      tonightActiveText.textContent = `Active Override: ${tonightOverride.sleep_time} → ${tonightOverride.wake_time} ${tz}`;
    }
    if (tonightSleepInput) tonightSleepInput.value = tonightOverride.sleep_time || "01:00";
    if (tonightWakeInput) tonightWakeInput.value = tonightOverride.wake_time || "07:00";
  } else {
    if (tonightActiveBanner) tonightActiveBanner.style.display = "none";
    const baseSleep = permanentConfig.sleep_time || "00:00";
    const sParts = baseSleep.split(":");
    const nextH = (parseInt(sParts[0], 10) + 1) % 24;
    const nextStr = `${String(nextH).padStart(2, "0")}:${sParts[1] || "00"}`;
    if (tonightSleepInput) tonightSleepInput.value = nextStr;

    const durHours = parseFloat(permanentConfig.duration_hours) || 6.0;
    const wakeH = Math.round((nextH + durHours) % 24);
    const wakeStr = `${String(wakeH).padStart(2, "0")}:${sParts[1] || "00"}`;
    if (tonightWakeInput) tonightWakeInput.value = wakeStr;
  }

  if (permEnabledCheckbox) permEnabledCheckbox.checked = permanentConfig.enabled !== false;
  if (permSleepInput) permSleepInput.value = permanentConfig.sleep_time || "00:00";
  if (permWakeInput) permWakeInput.value = permanentConfig.wake_time || "06:00";

  updateTonightPreview();
  updatePermanentPreview();
  openModal(sleepModal, triggerEl);
}

export async function sendShiftTonight(payload) {
  try {
    const res = await fetch(ENDPOINTS.sleepShiftTonight, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.success) {
      showToast(payload.clear ? "Schedule Restored" : "Tonight's Sleep Shifted", data.message, "success");
      await fetchSleepStatus();
      return true;
    }
    showToast("Shift Failed", data.error || "Could not apply tonight's sleep shift", "danger");
    return false;
  } catch (_) {
    showToast("Network Error", "Could not reach sleep guard API", "danger");
    return false;
  }
}

export async function sendSchedulePermanent(payload) {
  try {
    const res = await fetch(ENDPOINTS.sleepSchedulePermanent, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.success) {
      showToast("Permanent Schedule Saved", data.message, "success");
      await fetchSleepStatus();
      return true;
    }
    showToast("Schedule Failed", data.error || "Could not save permanent schedule", "danger");
    return false;
  } catch (_) {
    showToast("Network Error", "Could not reach sleep guard API", "danger");
    return false;
  }
}

function renderTimelineSegments(data) {
  if (!sleepWindowZone) return;
  const segs = Array.isArray(data.window_segments) && data.window_segments.length
    ? data.window_segments
    : (typeof data.window_left_pct === "number"
      ? [{ left_pct: data.window_left_pct, width_pct: data.window_width_pct }]
      : []);

  const title = `Sleep Window (${data.effective_sleep_time} - ${data.effective_wake_time})`;
  if (segs[0]) {
    sleepWindowZone.hidden = false;
    sleepWindowZone.style.left = `${segs[0].left_pct}%`;
    sleepWindowZone.style.width = `${segs[0].width_pct}%`;
    sleepWindowZone.setAttribute("title", title);
  } else {
    sleepWindowZone.hidden = true;
  }

  if (sleepWindowZoneWrap) {
    if (segs[1]) {
      sleepWindowZoneWrap.hidden = false;
      sleepWindowZoneWrap.style.left = `${segs[1].left_pct}%`;
      sleepWindowZoneWrap.style.width = `${segs[1].width_pct}%`;
      sleepWindowZoneWrap.setAttribute("title", title);
    } else {
      sleepWindowZoneWrap.hidden = true;
    }
  }
}

export async function fetchSleepStatus() {
  try {
    const res = await fetch(ENDPOINTS.sleepStatus);
    if (!res.ok) return false;
    const data = await res.json();

    if (data.timezone) state.timezone = data.timezone;
    if (data.tz_abbr) state.tzAbbr = data.tz_abbr;
    updateTzBadges();

    const installed = data.installed !== false;
    const mode = data.state_mode || (installed ? "default" : "not_installed");
    state.sleepInstalled = installed;
    state.modules.sleepGuard = installed;
    state.sleepEnabled = data.enabled !== false;
    state.sleepSkipActive = Boolean(data.skip_active);
    state.sleepStateMode = mode;
    state.sleepSecondsRemaining = data.seconds_until_sleep || 0;

    if (data.permanent_config) permanentConfig = data.permanent_config;
    tonightOverride = data.tonight_override || null;

    renderTimelineSegments(data);

    const tz = tzLabel();
    const controls = [btnShift1h, btnShift2h, btnOpenSleepModal, sleepToggleBtn];

    if (!installed || mode === "not_installed") {
      setSleepIcon("sun");
      if (sleepStatusTitle) sleepStatusTitle.textContent = "Sleep Guard Not Installed";
      if (sleepSubtext) sleepSubtext.textContent = "Automated S3 suspend is not enabled on this server (install sleep_guard module to configure).";
      if (sleepCountdown) sleepCountdown.textContent = "Always On";
      if (sleepOverridePill) sleepOverridePill.style.display = "none";
      if (sleepTimeline) sleepTimeline.hidden = true;
      controls.forEach((b) => { if (b) b.hidden = true; });
      state.sleepLabel = "Not Installed";
      setCardSummary("sleep-guard-card", "Sleep Guard not installed");
    } else if (mode === "disabled") {
      setSleepIcon("sun");
      if (sleepTimeline) sleepTimeline.hidden = false;
      if (sleepStatusTitle) sleepStatusTitle.textContent = "Auto-Sleep Disabled";
      if (sleepSubtext) sleepSubtext.textContent = `Permanent nightly suspend is turned off (saved rule: ${permanentConfig.sleep_time} → ${permanentConfig.wake_time} ${tz}).`;
      if (sleepCountdown) sleepCountdown.textContent = "Schedule Off";
      if (sleepOverridePill) sleepOverridePill.style.display = "none";
      if (btnShift1h) btnShift1h.hidden = true;
      if (btnShift2h) btnShift2h.hidden = true;
      if (btnOpenSleepModal) btnOpenSleepModal.hidden = false;
      if (sleepToggleBtn) sleepToggleBtn.hidden = true;
      state.sleepLabel = "Disabled";
      setCardSummary("sleep-guard-card", "Auto-Sleep Disabled");
    } else if (mode === "skip" || state.sleepSkipActive) {
      setSleepIcon("sun");
      if (sleepTimeline) sleepTimeline.hidden = false;
      controls.forEach((b) => { if (b) b.hidden = false; });
      if (sleepStatusTitle) sleepStatusTitle.textContent = "Staying Awake Tonight";
      if (sleepCountdown) sleepCountdown.textContent = "Skip Active";
      if (sleepSubtext) sleepSubtext.textContent = "Server staying awake all night. Resumes normal schedule tomorrow.";
      if (sleepBtnText) sleepBtnText.textContent = "Re-arm Sleep Tonight";
      if (sleepOverridePill) sleepOverridePill.style.display = "none";
      state.sleepLabel = "Skip Tonight";
      setCardSummary("sleep-guard-card", "Staying awake tonight (Skip active)");
    } else if (mode === "override" && tonightOverride) {
      setSleepIcon("moon");
      if (sleepTimeline) sleepTimeline.hidden = false;
      controls.forEach((b) => { if (b) b.hidden = false; });
      if (sleepStatusTitle) sleepStatusTitle.textContent = "Sleep Shifted Tonight";
      if (sleepSubtext) {
        sleepSubtext.textContent = `Override armed: suspends at ${tonightOverride.sleep_time} ${tz} for ${tonightOverride.duration_hours}h (wakes at ${tonightOverride.wake_time} ${tz})`;
      }
      if (sleepBtnText) sleepBtnText.textContent = "Prevent Sleep Tonight";
      if (sleepOverridePill) {
        sleepOverridePill.style.display = "inline-flex";
        if (sleepOverrideText) sleepOverrideText.textContent = `Shifted: ${tonightOverride.sleep_time} → ${tonightOverride.wake_time}`;
      }
      state.sleepLabel = `Shifted ${tonightOverride.sleep_time}`;
      setCardSummary("sleep-guard-card", `Shifted ${tonightOverride.sleep_time} → ${tonightOverride.wake_time} ${tz}`);
    } else {
      setSleepIcon("moon");
      if (sleepTimeline) sleepTimeline.hidden = false;
      controls.forEach((b) => { if (b) b.hidden = false; });
      if (sleepStatusTitle) sleepStatusTitle.textContent = "Sleep Armed";
      const dur = permanentConfig.duration_hours || 6;
      if (sleepSubtext) {
        sleepSubtext.textContent = `Automatic suspend armed at ${permanentConfig.sleep_time} ${tz} for ${dur}h (wakes at ${permanentConfig.wake_time} ${tz})`;
      }
      if (sleepBtnText) sleepBtnText.textContent = "Prevent Sleep Tonight";
      if (sleepOverridePill) sleepOverridePill.style.display = "none";
      state.sleepLabel = `Armed ${permanentConfig.sleep_time} ${tz}`;
      setCardSummary("sleep-guard-card", `Armed ${permanentConfig.sleep_time} → ${permanentConfig.wake_time} ${tz}`);
    }

    renderOverview();
    return true;
  } catch (err) {
    console.error("Error fetching sleep status:", err);
    return false;
  }
}

export async function toggleSleepMode() {
  if (!sleepToggleBtn) return;
  sleepToggleBtn.disabled = true;
  if (sleepBtnSpinner) sleepBtnSpinner.style.display = "inline-block";

  try {
    const res = await fetch(ENDPOINTS.sleepToggle, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(data.skip_active ? "Sleep Skipped Tonight" : "Sleep Guard Re-armed", data.message, "success");
      await fetchSleepStatus();
    } else {
      showToast("Error", data.error || "Failed to toggle sleep mode", "danger");
    }
  } catch (_) {
    showToast("Network Error", "Could not communicate with Sleep Guard API", "danger");
  } finally {
    sleepToggleBtn.disabled = false;
    if (sleepBtnSpinner) sleepBtnSpinner.style.display = "none";
  }
}

export function setupSleepGuard() {
  registerModal(sleepModal, { closeButtons: [btnCloseModal, btnCancelModal] });

  if (sleepToggleBtn) sleepToggleBtn.addEventListener("click", toggleSleepMode);

  if (btnShift1h) {
    btnShift1h.addEventListener("click", async () => {
      btnShift1h.disabled = true;
      await sendShiftTonight({ delay_hours: 1 });
      btnShift1h.disabled = false;
    });
  }

  if (btnShift2h) {
    btnShift2h.addEventListener("click", async () => {
      btnShift2h.disabled = true;
      await sendShiftTonight({ delay_hours: 2 });
      btnShift2h.disabled = false;
    });
  }

  if (btnClearHeroOverride) {
    btnClearHeroOverride.addEventListener("click", async (e) => {
      e.stopPropagation();
      await sendShiftTonight({ clear: true });
    });
  }

  if (btnOpenSleepModal) btnOpenSleepModal.addEventListener("click", () => openSleepModal(state.sleepStateMode === "disabled" ? "tab-permanent" : "tab-tonight", btnOpenSleepModal));
  if (tabBtnTonight) tabBtnTonight.addEventListener("click", () => switchTab("tab-tonight"));
  if (tabBtnPermanent) tabBtnPermanent.addEventListener("click", () => switchTab("tab-permanent"));

  if (btnRevertTonight) {
    btnRevertTonight.addEventListener("click", async () => {
      btnRevertTonight.disabled = true;
      const success = await sendShiftTonight({ clear: true });
      btnRevertTonight.disabled = false;
      if (success) {
        if (tonightActiveBanner) tonightActiveBanner.style.display = "none";
        closeModal(sleepModal);
      }
    });
  }

  document.querySelectorAll(".preset-card").forEach((card) => {
    card.addEventListener("click", () => {
      document.querySelectorAll(".preset-card").forEach((c) => c.classList.remove("active"));
      card.classList.add("active");
      const delay = parseInt(card.getAttribute("data-delay"), 10) || 1;
      const baseSleep = permanentConfig.sleep_time || "00:00";
      const sParts = baseSleep.split(":");
      const bHour = parseInt(sParts[0], 10);
      const bMin = sParts[1] || "00";
      const sH = (bHour + delay) % 24;
      const sStr = `${String(sH).padStart(2, "0")}:${bMin}`;
      const durHours = parseFloat(permanentConfig.duration_hours) || 6.0;
      const wH = Math.round((sH + durHours) % 24);
      const wStr = `${String(wH).padStart(2, "0")}:${bMin}`;
      if (tonightSleepInput) tonightSleepInput.value = sStr;
      if (tonightWakeInput) tonightWakeInput.value = wStr;
      updateTonightPreview();
    });
  });

  if (tonightSleepInput) tonightSleepInput.addEventListener("input", updateTonightPreview);
  if (tonightWakeInput) tonightWakeInput.addEventListener("input", updateTonightPreview);
  if (permSleepInput) permSleepInput.addEventListener("input", updatePermanentPreview);
  if (permWakeInput) permWakeInput.addEventListener("input", updatePermanentPreview);
  if (permEnabledCheckbox) permEnabledCheckbox.addEventListener("change", updatePermanentPreview);

  if (btnSaveModal) {
    btnSaveModal.addEventListener("click", async () => {
      btnSaveModal.disabled = true;
      if (saveModalSpinner) saveModalSpinner.style.display = "inline-block";

      const success = activeTab === "tab-tonight"
        ? await sendShiftTonight({
          sleep_time: tonightSleepInput ? tonightSleepInput.value : "01:00",
          wake_time: tonightWakeInput ? tonightWakeInput.value : "07:00",
        })
        : await sendSchedulePermanent({
          sleep_time: permSleepInput ? permSleepInput.value : "00:00",
          wake_time: permWakeInput ? permWakeInput.value : "06:00",
          enabled: permEnabledCheckbox ? permEnabledCheckbox.checked : true,
        });

      btnSaveModal.disabled = false;
      if (saveModalSpinner) saveModalSpinner.style.display = "none";
      if (success) closeModal(sleepModal);
    });
  }
}
