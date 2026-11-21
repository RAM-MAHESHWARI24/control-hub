/**
 * Widget: Scheduled Automations (cron.d & systemd timers)
 * Renders only installed automations with real schedules, SVG sprite icons,
 * diff-checked updates, and accessible log viewer.
 */

import { $, setCardSummary, uiIcon } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { toggleSleepMode } from "./sleepGuard.js";

const cronGrid = $("cron-grid");
const cronSubtitle = $("cron-card-subtitle");
const btnRefreshCron = $("btn-refresh-cron");
const cronLogModal = $("cron-log-modal");
const cronModalTitle = $("cron-modal-title");
const cronModalSubPath = $("cron-modal-sub-path");
const cronModalLogContent = $("cron-modal-log-content");
const cronModalClose = $("cron-modal-close");
const cronModalDismiss = $("cron-modal-dismiss");
const cronModalRefresh = $("cron-modal-refresh");

let activeCronJobId = null;
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

    if (cronSubtitle) {
      cronSubtitle.textContent = `cron.d & systemd timers · ${jobs.length} installed`;
    }
    setCardSummary("automation-section", `${jobs.length} installed automation${jobs.length === 1 ? "" : "s"}`);

    const sig = JSON.stringify(jobs);
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

      return `
        <div class="cron-item-card" id="cron-card-${escapeHtml(job.id)}">
          <div>
            <div class="cron-item-top">
              <div class="cron-item-brand">
                <div class="cron-icon-box" aria-hidden="true">${uiIcon(spriteName)}</div>
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
              <span>Last Run: <strong class="font-mono">${escapeHtml(job.last_run)}</strong></span>
            </div>
            <div class="cron-actions-row">
              <button type="button" class="btn-secondary btn-cron-log" data-log-id="${escapeHtml(job.id)}" data-log-name="${safeName}" aria-label="View log for ${safeName}">
                View Log
              </button>
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

export function setupCronTasks() {
  registerModal(cronLogModal, { closeButtons: [cronModalClose, cronModalDismiss] });
  if (btnRefreshCron) btnRefreshCron.addEventListener("click", () => { lastJobsSignature = ""; fetchCronTasks(); });
  if (cronModalRefresh) cronModalRefresh.addEventListener("click", refreshCronModalLog);
}
