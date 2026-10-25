/**
 * Widget: Sleep Guard Hero Command Module
 * Handles S3 RAM Suspend status, overnight toggle, quick shifts (+1h/+2h),
 * visual 24h timeline window zone, and granular scheduler modal (Tonight vs Permanent).
 */

import { $ } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { showToast } from "../shared/toast.js";

// Sleep Guard Hero Elements
const sleepCard = $("sleep-guard-card");
const sleepIcon = $("sleep-icon");
const sleepStatusTitle = $("sleep-status-title");
const sleepCountdown = $("sleep-countdown");
const sleepSubtext = $("sleep-subtext");
const sleepToggleBtn = $("sleep-toggle-btn");
const sleepBtnText = $("sleep-btn-text");
const sleepBtnSpinner = $("sleep-btn-spinner");
const sleepWindowZone = $("sleep-window-zone");
const sleepOverridePill = $("sleep-override-pill");
const sleepOverrideText = $("sleep-override-text");
const btnClearHeroOverride = $("btn-clear-hero-override");

// Quick Shift buttons on Hero Card
const btnShift1h = $("btn-shift-1h");
const btnShift2h = $("btn-shift-2h");
const btnOpenSleepModal = $("btn-open-sleep-modal");

// Modal Elements
const sleepModal = $("sleep-schedule-modal");
const btnCloseModal = $("sleep-modal-close");
const btnCancelModal = $("sleep-modal-cancel");
const btnSaveModal = $("sleep-modal-save");
const saveModalSpinner = $("sleep-modal-spinner");
const saveModalText = $("sleep-modal-save-text");
const modalFooterHint = $("sleep-modal-footer-hint");

// Modal Tabs
const tabBtnTonight = $("tab-btn-tonight");
const tabBtnPermanent = $("tab-btn-permanent");
const tabPaneTonight = $("tab-tonight");
const tabPanePermanent = $("tab-permanent");

// Tab 1 (Tonight's Shift) Elements
const tonightActiveBanner = $("tonight-active-banner");
const tonightActiveText = $("tonight-active-text");
const btnRevertTonight = $("btn-revert-tonight");
const presetCards = document.querySelectorAll(".preset-card");
const tonightSleepInput = $("tonight-sleep-input");
const tonightWakeInput = $("tonight-wake-input");
const tonightDurationBadge = $("tonight-duration-badge");
const tonightPreviewText = $("tonight-preview-text");

// Tab 2 (Permanent Schedule) Elements
const permEnabledCheckbox = $("perm-enabled-checkbox");
const permSleepInput = $("perm-sleep-input");
const permWakeInput = $("perm-wake-input");
const permDurationBadge = $("perm-duration-badge");
const permPreviewText = $("perm-preview-text");

let activeTab = "tab-tonight";
let permanentConfig = { enabled: true, sleep_time: "00:00", wake_time: "06:00", duration_hours: 6.0 };
let tonightOverride = null;

/**
 * Calculates duration in hours between sleep time (HH:MM) and wake time (HH:MM)
 */
function calculateWindowDuration(sleepTimeStr, wakeTimeStr) {
  if (!sleepTimeStr || !wakeTimeStr) return { hours: "6.0", mins: 360 };
  const sParts = sleepTimeStr.split(":");
  const wParts = wakeTimeStr.split(":");
  const sMins = parseInt(sParts[0], 10) * 60 + parseInt(sParts[1], 10);
  const wMins = parseInt(wParts[0], 10) * 60 + parseInt(wParts[1], 10);
  let diff = wMins - sMins;
  if (diff <= 0) diff += 1440;
  return {
    hours: (diff / 60).toFixed(1).replace(/\.0$/, ""),
    mins: diff
  };
}

/**
 * Live updates Tonight summary card based on input fields
 */
function updateTonightPreview() {
  if (!tonightSleepInput || !tonightWakeInput) return;
  const sVal = tonightSleepInput.value || "01:00";
  const wVal = tonightWakeInput.value || "07:00";
  const dur = calculateWindowDuration(sVal, wVal);

  if (tonightDurationBadge) tonightDurationBadge.textContent = `${dur.hours} hrs`;
  if (tonightPreviewText) tonightPreviewText.textContent = `Sleep at ${sVal} IST • Wake at ${wVal} IST`;
}

/**
 * Live updates Permanent summary card based on input fields
 */
function updatePermanentPreview() {
  if (!permSleepInput || !permWakeInput) return;
  const sVal = permSleepInput.value || "00:00";
  const wVal = permWakeInput.value || "06:00";
  const dur = calculateWindowDuration(sVal, wVal);

  if (permDurationBadge) permDurationBadge.textContent = `${dur.hours} hrs`;
  if (permPreviewText) {
    if (permEnabledCheckbox && !permEnabledCheckbox.checked) {
      permPreviewText.textContent = `Automated nightly sleep disabled`;
    } else {
      permPreviewText.textContent = `Every night from ${sVal} IST to ${wVal} IST`;
    }
  }
}

/**
 * Selects active tab in the scheduler modal
 */
function switchTab(tabId) {
  activeTab = tabId;
  if (tabId === "tab-tonight") {
    if (tabBtnTonight) tabBtnTonight.classList.add("active");
    if (tabBtnPermanent) tabBtnPermanent.classList.remove("active");
    if (tabPaneTonight) tabPaneTonight.style.display = "flex";
    if (tabPanePermanent) tabPanePermanent.style.display = "none";
    if (saveModalText) saveModalText.textContent = "Apply for Tonight Only";
    if (modalFooterHint) modalFooterHint.textContent = "Mode: Tonight's One-Off Shift (Resets to default after wake)";
  } else {
    if (tabBtnPermanent) tabBtnPermanent.classList.add("active");
    if (tabBtnTonight) tabBtnTonight.classList.remove("active");
    if (tabPanePermanent) tabPanePermanent.style.display = "flex";
    if (tabPaneTonight) tabPaneTonight.style.display = "none";
    if (saveModalText) saveModalText.textContent = "Save as Default Schedule";
    if (modalFooterHint) modalFooterHint.textContent = "Mode: Permanent Schedule (Updates cron & config forever)";
  }
}

/**
 * Updates preset delay buttons text to match current default base time
 */
function updatePresetLabels() {
  const baseSleep = permanentConfig.sleep_time || "00:00";
  const sParts = baseSleep.split(":");
  const bHour = parseInt(sParts[0], 10);
  const bMin = sParts[1] || "00";
  const durHours = parseFloat(permanentConfig.duration_hours) || 6.0;

  for (let delay = 1; delay <= 4; delay++) {
    const calcEl = $(`preset-calc-${delay}`);
    if (calcEl) {
      const sH = (bHour + delay) % 24;
      const sStr = `${String(sH).padStart(2, "0")}:${String(bMin).padStart(2, "0")}`;
      const wH = Math.round((sH + durHours) % 24);
      const wStr = `${String(wH).padStart(2, "0")}:${String(bMin).padStart(2, "0")}`;
      calcEl.textContent = `${sStr} → ${wStr}`;
    }
  }
}

/**
 * Open scheduler modal and populate with latest configs
 */
export function openSleepModal(initialTab = "tab-tonight") {
  if (!sleepModal) return;
  switchTab(initialTab);
  updatePresetLabels();

  if (tonightOverride && tonightOverride.active) {
    if (tonightActiveBanner) tonightActiveBanner.style.display = "flex";
    if (tonightActiveText) {
      tonightActiveText.textContent = `Active Override: Sleep shifted to ${tonightOverride.sleep_time} IST (wakes at ${tonightOverride.wake_time} IST)`;
    }
    if (tonightSleepInput) tonightSleepInput.value = tonightOverride.sleep_time || "01:00";
    if (tonightWakeInput) tonightWakeInput.value = tonightOverride.wake_time || "07:00";
  } else {
    if (tonightActiveBanner) tonightActiveBanner.style.display = "none";
    // Default suggestion: +1 hour from permanent sleep
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

  // Populate permanent settings
  if (permEnabledCheckbox) permEnabledCheckbox.checked = permanentConfig.enabled !== false;
  if (permSleepInput) permSleepInput.value = permanentConfig.sleep_time || "00:00";
  if (permWakeInput) permWakeInput.value = permanentConfig.wake_time || "06:00";

  updateTonightPreview();
  updatePermanentPreview();

  sleepModal.style.display = "flex";
}

export function closeSleepModal() {
  if (sleepModal) sleepModal.style.display = "none";
}

/**
 * Sends one-off tonight shift to backend
 */
export async function sendShiftTonight(payload) {
  try {
    const res = await fetch(ENDPOINTS.sleepShiftTonight, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast(
        payload.clear ? "Schedule Restored" : "Tonight's Sleep Shifted",
        data.message,
        payload.clear ? "🔁" : "🌙"
      );
      await fetchSleepStatus();
      return true;
    } else {
      showToast("Shift Failed", data.error || "Could not apply tonight's sleep shift", "❌");
      return false;
    }
  } catch (err) {
    showToast("Network Error", "Could not reach sleep guard API", "❌");
    return false;
  }
}

/**
 * Sends permanent recurring schedule update to backend
 */
export async function sendSchedulePermanent(payload) {
  try {
    const res = await fetch(ENDPOINTS.sleepSchedulePermanent, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast("Permanent Schedule Saved", data.message, "💾");
      await fetchSleepStatus();
      return true;
    } else {
      showToast("Schedule Failed", data.error || "Could not save permanent schedule", "❌");
      return false;
    }
  } catch (err) {
    showToast("Network Error", "Could not reach sleep guard API", "❌");
    return false;
  }
}

/**
 * Fetches status and updates UI
 */
export async function fetchSleepStatus() {
  try {
    const res = await fetch(ENDPOINTS.sleepStatus);
    const data = await res.json();

    state.sleepSkipActive = data.skip_active;
    state.sleepSecondsRemaining = data.seconds_until_sleep || 0;

    if (data.permanent_config) permanentConfig = data.permanent_config;
    tonightOverride = data.tonight_override;

    // Dynamically adjust 24h timeline window zone
    if (sleepWindowZone && typeof data.window_left_pct === "number") {
      sleepWindowZone.style.left = `${data.window_left_pct}%`;
      sleepWindowZone.style.width = `${data.window_width_pct}%`;
      sleepWindowZone.setAttribute(
        "title",
        `Sleep Window (${data.effective_sleep_time} - ${data.effective_wake_time})`
      );
    }

    if (sleepCard) {
      // 1. Skip Active (Staying awake tonight)
      if (state.sleepSkipActive) {
        sleepCard.classList.add("skip-active");
        if (sleepIcon) sleepIcon.textContent = "☀️";
        if (sleepStatusTitle) sleepStatusTitle.textContent = "Sleep Disabled Tonight";
        if (sleepCountdown) sleepCountdown.textContent = "Awake all night (Skip active)";
        if (sleepSubtext) {
          sleepSubtext.textContent = "Server staying awake all night. Resumes normal automated sleep tomorrow.";
        }
        if (sleepBtnText) sleepBtnText.textContent = "Re-arm Sleep Tonight";
        if (sleepOverridePill) sleepOverridePill.style.display = "none";
      }
      // 2. Tonight Override (Shifted for one day)
      else if (tonightOverride && tonightOverride.active) {
        sleepCard.classList.remove("skip-active");
        if (sleepIcon) sleepIcon.textContent = "🌙";
        if (sleepStatusTitle) sleepStatusTitle.textContent = "Sleep Shifted Tonight";
        if (sleepSubtext) {
          sleepSubtext.textContent = `Temporary override armed: suspends at ${tonightOverride.sleep_time} IST for ${tonightOverride.duration_hours}h (wakes at ${tonightOverride.wake_time} IST)`;
        }
        if (sleepBtnText) sleepBtnText.textContent = "Prevent Sleep Tonight";

        if (sleepOverridePill) {
          sleepOverridePill.style.display = "inline-flex";
          if (sleepOverrideText) {
            sleepOverrideText.textContent = `Shifted: ${tonightOverride.sleep_time} ➔ ${tonightOverride.wake_time}`;
          }
        }
      }
      // 3. Normal Default Schedule
      else {
        sleepCard.classList.remove("skip-active");
        if (sleepIcon) sleepIcon.textContent = "🌙";
        if (sleepStatusTitle) sleepStatusTitle.textContent = "Sleep Armed";
        const dur = permanentConfig.duration_hours || 6;
        if (sleepSubtext) {
          sleepSubtext.textContent = `Automatic suspend armed at ${permanentConfig.sleep_time} IST for ${dur} hours (wakes at ${permanentConfig.wake_time} IST)`;
        }
        if (sleepBtnText) sleepBtnText.textContent = "Prevent Sleep Tonight";
        if (sleepOverridePill) sleepOverridePill.style.display = "none";
      }
    }
  } catch (err) {
    console.error("Error fetching sleep status:", err);
  }
}

/**
 * Toggle overnight stay awake / re-arm
 */
export async function toggleSleepMode() {
  if (!sleepToggleBtn) return;
  sleepToggleBtn.disabled = true;
  if (sleepBtnSpinner) sleepBtnSpinner.style.display = "inline-block";

  try {
    const res = await fetch(ENDPOINTS.sleepToggle, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(
        data.skip_active ? "Sleep Guard Disabled" : "Sleep Guard Re-armed",
        data.message,
        data.skip_active ? "☀️" : "🌙"
      );
      await fetchSleepStatus();
    } else {
      showToast("Error", data.error || "Failed to toggle sleep mode", "❌");
    }
  } catch (err) {
    showToast("Network Error", "Could not communicate with Sleep Guard API", "❌");
  } finally {
    sleepToggleBtn.disabled = false;
    if (sleepBtnSpinner) sleepBtnSpinner.style.display = "none";
  }
}

/**
 * Bind all event listeners for Sleep Guard and Scheduler Modal
 */
export function setupSleepGuard() {
  // Hero Toggle Button
  if (sleepToggleBtn) {
    sleepToggleBtn.addEventListener("click", toggleSleepMode);
  }

  // Hero Quick Shift Buttons (+1h and +2h)
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

  // Clear Override from Hero Pill
  if (btnClearHeroOverride) {
    btnClearHeroOverride.addEventListener("click", async (e) => {
      e.stopPropagation();
      await sendShiftTonight({ clear: true });
    });
  }

  // Open Modal Button
  if (btnOpenSleepModal) {
    btnOpenSleepModal.addEventListener("click", () => openSleepModal("tab-tonight"));
  }

  // Modal Close & Dismiss Buttons
  if (btnCloseModal) btnCloseModal.addEventListener("click", closeSleepModal);
  if (btnCancelModal) btnCancelModal.addEventListener("click", closeSleepModal);

  // Modal Tab Switching
  if (tabBtnTonight) tabBtnTonight.addEventListener("click", () => switchTab("tab-tonight"));
  if (tabBtnPermanent) tabBtnPermanent.addEventListener("click", () => switchTab("tab-permanent"));

  // Revert Tonight button inside modal
  if (btnRevertTonight) {
    btnRevertTonight.addEventListener("click", async () => {
      btnRevertTonight.disabled = true;
      const success = await sendShiftTonight({ clear: true });
      btnRevertTonight.disabled = false;
      if (success) {
        if (tonightActiveBanner) tonightActiveBanner.style.display = "none";
        closeSleepModal();
      }
    });
  }

  // Preset Card Clicks
  const pCards = document.querySelectorAll(".preset-card");
  pCards.forEach((card) => {
    card.addEventListener("click", () => {
      pCards.forEach((c) => c.classList.remove("active"));
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

  // Time Inputs Live Update
  if (tonightSleepInput) tonightSleepInput.addEventListener("input", updateTonightPreview);
  if (tonightWakeInput) tonightWakeInput.addEventListener("input", updateTonightPreview);

  if (permSleepInput) permSleepInput.addEventListener("input", updatePermanentPreview);
  if (permWakeInput) permWakeInput.addEventListener("input", updatePermanentPreview);
  if (permEnabledCheckbox) permEnabledCheckbox.addEventListener("change", updatePermanentPreview);

  // Modal Save Button (Handles either Tonight or Permanent depending on active tab)
  if (btnSaveModal) {
    btnSaveModal.addEventListener("click", async () => {
      btnSaveModal.disabled = true;
      if (saveModalSpinner) saveModalSpinner.style.display = "inline-block";

      let success = false;
      if (activeTab === "tab-tonight") {
        const payload = {
          sleep_time: tonightSleepInput ? tonightSleepInput.value : "01:00",
          wake_time: tonightWakeInput ? tonightWakeInput.value : "07:00"
        };
        success = await sendShiftTonight(payload);
      } else {
        const payload = {
          sleep_time: permSleepInput ? permSleepInput.value : "00:00",
          wake_time: permWakeInput ? permWakeInput.value : "06:00",
          enabled: permEnabledCheckbox ? permEnabledCheckbox.checked : true
        };
        success = await sendSchedulePermanent(payload);
      }

      btnSaveModal.disabled = false;
      if (saveModalSpinner) saveModalSpinner.style.display = "none";

      if (success) {
        closeSleepModal();
      }
    });
  }
}
