/**
 * Widget: Scheduled Automations (cron.d & systemd timers)
 * Renders only installed automations with real schedules, SVG sprite icons,
 * diff-checked updates, and accessible log viewer.
 */

import { $, setCardSummary, uiIcon } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { closeModal, openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { state } from "../state.js";
import { renderSleepCronPins, toggleSleepMode } from "./sleepGuard.js";

const cronGrid = $("cron-grid");
const cronSubtitle = $("cron-card-subtitle");
const cronClashCallout = $("cron-clash-callout");
const btnRefreshCron = $("btn-refresh-cron");
const cronLogModal = $("cron-log-modal");
const cronModalTitle = $("cron-modal-title");
const cronModalSubPath = $("cron-modal-sub-path");
const cronModalLogContent = $("cron-modal-log-content");
const cronModalClose = $("cron-modal-close");
const cronModalDismiss = $("cron-modal-dismiss");
const cronModalRefresh = $("cron-modal-refresh");

const cronScheduleModal = $("cron-schedule-modal");
const cronEditTitle = $("cron-edit-title");
const cronEditSub = $("cron-edit-sub");
const cronEditEnabled = $("cron-edit-enabled");
const cronEditTimeLabel = $("cron-edit-time-label");
const cronEditTime = $("cron-edit-time");
const cronEditEndGroup = $("cron-edit-end-group");
const cronEditEndLabel = $("cron-edit-end-label");
const cronEditEndTime = $("cron-edit-end-time");
const cronEditClashPreview = $("cron-edit-clash-preview");
const cronEditClose = $("cron-edit-close");
const cronEditCancel = $("cron-edit-cancel");
const cronEditSave = $("cron-edit-save");
const cronScheduleForm = $("cron-schedule-form");

let activeCronJobId = null;
let editingJobId = null;
let lastJobsSignature = "";

const ICON_MAP = {
  cloud: "cloud",
  database: "database",
  shield: "shield",
  moon: "moon",
  tv: "tv",
  sliders: "sliders",
  cpu: "cpu",
};

export async function fetchCronTasks() {
  if (!cronGrid) return false;
  try {
    const res = await fetch(ENDPOINTS.cronStatus);
    if (!res.ok) return false;
    const data = await res.json();
    const jobs = data.jobs || [];
    const clashes = data.clashes || [];
    state.cronJobs = jobs;
    renderSleepCronPins(jobs);

    if (cronClashCallout) {
      if (clashes.length > 0) {
        cronClashCallout.textContent = clashes.map((c) => c.message).join(" | ");
        cronClashCallout.hidden = false;
      } else {
        cronClashCallout.hidden = true;
      }
    }

    if (cronSubtitle) {
      const clashSuffix = clashes.length ? ` | ${clashes.length} clash warning` : "";
      cronSubtitle.textContent = `cron.d & systemd timers | ${jobs.length} installed${clashSuffix}`;
    }
    setCardSummary(
      "automation-section",
      `${jobs.length} installed automation${jobs.length === 1 ? "" : "s"}${clashes.length ? ` (${clashes.length} clash)` : ""}`
    );

    const sig = JSON.stringify({ jobs, clashes });
    if (sig === lastJobsSignature && cronGrid.children.length > 0) return true;
    lastJobsSignature = sig;

    if (jobs.length === 0) {
      cronGrid.innerHTML = `<div class="empty-state">No scheduled homelab cron jobs or timers detected on this host.</div>`;
      return true;
    }

    cronGrid.innerHTML = jobs.map((job) => {
      const isRunning = Boolean(job.is_running);
      const stLower = String(job.status_text || "").toLowerCase();
      let badgeClass = "";
      if (isRunning) badgeClass = "running";
      else if (stLower.includes("error") || stLower.includes("fail") || stLower.includes("stale") || stLower.includes("interrupted")) badgeClass = "error";
      else if (stLower.includes("disabled") || stLower.includes("conserved") || stLower.includes("not ") || stLower.includes("unknown") || stLower.includes("pending") || stLower.includes("never")) badgeClass = "inactive";

      const runDisabledAttr = (!job.can_run && job.id !== "server_suspend") ? "disabled" : "";
      const safeName = escapeHtml(job.name);
      const spriteName = ICON_MAP[job.icon] || "activity";
      const nextRunTxt = escapeHtml(job.next_run || job.schedule || "--");
      const editBtn = job.editable
        ? `<button type="button" class="btn-secondary btn-cron-edit" id="btn-cron-edit-${escapeHtml(job.id)}" data-edit-id="${escapeHtml(job.id)}" aria-label="Edit schedule for ${safeName}">Edit Time</button>`
        : "";

      return `
        <div class="cron-item-card" id="cron-card-${escapeHtml(job.id)}">
          <div>
            <div class="cron-item-top">
              <div class="cron-item-brand">
                <span class="cron-inline-icon" aria-hidden="true">${uiIcon(spriteName)}</span>
                <div class="cron-title-group">
                  <h4>${safeName}</h4>
                  <span class="cron-schedule font-mono">${escapeHtml(job.schedule)}</span>
                </div>
              </div>
              <span class="cron-status-badge ${badgeClass}" id="cron-badge-${escapeHtml(job.id)}">
                ${escapeHtml(job.status_text)}
              </span>
            </div>
            <p class="cron-desc">${escapeHtml(job.description)}</p>
          </div>

          <div>
            <div class="cron-meta-row">
              <span>Next Run: <strong class="font-mono">${nextRunTxt}</strong></span>
              <span>Last Result: <strong class="font-mono">${escapeHtml(job.last_run)}</strong></span>
            </div>
            <div class="cron-actions-row">
              <button type="button" class="btn-secondary btn-cron-log" data-log-id="${escapeHtml(job.id)}" data-log-name="${safeName}" aria-label="View log for ${safeName}">
                View Log
              </button>
              ${editBtn}
              <button type="button" class="btn-ghost btn-cron-run" id="btn-cron-run-${escapeHtml(job.id)}" data-run-id="${escapeHtml(job.id)}" data-run-name="${safeName}" ${runDisabledAttr}>
                ${escapeHtml(job.run_label)}
              </button>
            </div>
          </div>
        </div>
      `;
    }).join("");

    cronGrid.querySelectorAll(".btn-cron-log").forEach((btn) => {
      btn.onclick = () => openCronLog(btn.dataset.logId, btn.dataset.logName, btn);
    });
    cronGrid.querySelectorAll(".btn-cron-edit").forEach((btn) => {
      const targetJob = jobs.find((j) => j.id === btn.dataset.editId);
      btn.onclick = () => targetJob && openCronScheduleEditor(targetJob, btn);
    });
    cronGrid.querySelectorAll(".btn-cron-run").forEach((btn) => {
      btn.onclick = () => {
        if (btn.dataset.runId === "server_suspend") {
          toggleSleepMode();
        } else {
          runCronJob(btn.dataset.runId, btn.dataset.runName);
        }
      };
    });
    return true;
  } catch (err) {
    console.error("Error fetching cron tasks:", err);
    return false;
  }
}

export async function openCronLog(jobId, jobName, triggerEl = null) {
  activeCronJobId = jobId;
  if (cronModalTitle) cronModalTitle.textContent = `${jobName} Log`;
  if (cronModalSubPath) cronModalSubPath.textContent = `Job: ${jobId}`;
  if (cronModalLogContent) cronModalLogContent.textContent = "Loading task output log...";
  openModal(cronLogModal, triggerEl);
  await refreshCronModalLog();
}

export async function refreshCronModalLog() {
  if (!activeCronJobId) return;
  try {
    const res = await fetch(ENDPOINTS.cronLog(activeCronJobId));
    const data = await res.json();
    if (cronModalLogContent) {
      cronModalLogContent.textContent = data.log || "No log lines available.";
      cronModalLogContent.scrollTop = cronModalLogContent.scrollHeight;
    }
    if (cronModalSubPath && data.log_file) {
      cronModalSubPath.textContent = `File: ${data.log_file}`;
    }
  } catch (err) {
    if (cronModalLogContent) cronModalLogContent.textContent = `Error reading log: ${err.message}`;
  }
}

export async function runCronJob(jobId, jobName) {
  const btn = $(`btn-cron-run-${jobId}`);
  if (btn) btn.disabled = true;
  showToast("Automation Triggered", `Executing '${jobName}' in background...`, "info");

  try {
    const res = await fetch(ENDPOINTS.cronRun(jobId), { method: "POST" });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast("Task Started", data.message, "success");
      lastJobsSignature = "";
      await fetchCronTasks();
    } else {
      showToast("Notice", data.message || data.error || "Could not start task", "warning");
    }
  } catch (_) {
    showToast("Error", `Could not trigger task '${jobName}'`, "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _schedulePayload(previewOnly = false) {
  const payload = {
    time: (cronEditTime?.value || "").trim(),
    enabled: Boolean(cronEditEnabled?.checked),
    preview_only: previewOnly,
  };
  if (editingJobId === "immich_ml") payload.stop_time = (cronEditEndTime?.value || "").trim();
  if (editingJobId === "server_suspend") payload.wake_time = (cronEditEndTime?.value || "").trim();
  return payload;
}

async function previewScheduleClashes() {
  if (!editingJobId || !cronEditTime?.value) return;
  try {
    const res = await fetch(ENDPOINTS.cronSchedule(editingJobId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_schedulePayload(true)),
    });
    const data = await res.json();
    if (!cronEditClashPreview) return;
    const relevant = (data.clashes || []).filter((c) => (c.jobs || []).includes(editingJobId));
    if (relevant.length > 0) {
      cronEditClashPreview.textContent = relevant.map((c) => c.message).join(" | ");
      cronEditClashPreview.hidden = false;
    } else {
      cronEditClashPreview.hidden = true;
    }
  } catch (_) {
    /* ignore transient preview error */
  }
}

export function openCronScheduleEditor(job, triggerEl = null) {
  editingJobId = job.id;
  if (cronEditTitle) cronEditTitle.textContent = `Edit ${job.name}`;
  if (cronEditSub) cronEditSub.textContent = job.description || "Adjust recurring run time.";
  if (cronEditEnabled) cronEditEnabled.checked = job.enabled !== false;
  if (cronEditTime) cronEditTime.value = job.time_hhmm || "22:00";

  if (cronEditEndGroup) {
    if (job.id === "immich_ml") {
      cronEditEndGroup.hidden = false;
      if (cronEditTimeLabel) cronEditTimeLabel.textContent = "ML Start Time (24h)";
      if (cronEditEndLabel) cronEditEndLabel.textContent = "ML Stop Time (24h)";
      if (cronEditEndTime) cronEditEndTime.value = job.stop_hhmm || "10:00";
    } else if (job.id === "server_suspend") {
      cronEditEndGroup.hidden = false;
      if (cronEditTimeLabel) cronEditTimeLabel.textContent = "Sleep Time (24h)";
      if (cronEditEndLabel) cronEditEndLabel.textContent = "Wake Time (24h)";
      if (cronEditEndTime) cronEditEndTime.value = job.wake_hhmm || "06:00";
    } else {
      cronEditEndGroup.hidden = true;
      if (cronEditTimeLabel) cronEditTimeLabel.textContent = "Run Time (24h)";
    }
  }

  openModal(cronScheduleModal, triggerEl);
  previewScheduleClashes();
}

export function setupCronTasks() {
  registerModal(cronLogModal, { closeButtons: [cronModalClose, cronModalDismiss] });
  registerModal(cronScheduleModal, { closeButtons: [cronEditClose, cronEditCancel] });
  if (btnRefreshCron) btnRefreshCron.addEventListener("click", () => { lastJobsSignature = ""; fetchCronTasks(); });
  if (cronModalRefresh) cronModalRefresh.addEventListener("click", refreshCronModalLog);

  if (cronEditTime) cronEditTime.addEventListener("change", previewScheduleClashes);
  if (cronEditEndTime) cronEditEndTime.addEventListener("change", previewScheduleClashes);
  if (cronEditEnabled) cronEditEnabled.addEventListener("change", previewScheduleClashes);

  if (cronScheduleForm) {
    cronScheduleForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!editingJobId) return;
      if (cronEditSave) cronEditSave.disabled = true;
      try {
        const res = await fetch(ENDPOINTS.cronSchedule(editingJobId), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(_schedulePayload(false)),
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          showToast("Schedule Updated", data.message || "Cron schedule saved.", "success");
          closeModal(cronScheduleModal);
          lastJobsSignature = "";
          await fetchCronTasks();
        } else {
          showToast("Update Failed", data.error || "Could not update schedule.", "danger");
        }
      } catch (err) {
        showToast("Error", `Schedule update failed: ${err.message}`, "danger");
      } finally {
        if (cronEditSave) cronEditSave.disabled = false;
      }
    });
  }
}
