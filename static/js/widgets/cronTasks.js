/**
 * Widget: System Automation & Scheduled Cron Tasks
 * Renders registered automation cards, dynamic task counts, and accessible log viewer.
 */

import { $, setCardSummary } from "../shared/dom.js";
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

function getCronIconSvg(iconName) {
  switch (iconName) {
    case "cloud":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>`;
    case "moon":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
    case "tv":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect><polyline points="17 2 12 7 7 2"></polyline></svg>`;
    case "sliders":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="4" y1="21" x2="4" y2="14"></line><line x1="4" y1="10" x2="4" y2="3"></line><line x1="12" y1="21" x2="12" y2="12"></line><line x1="12" y1="8" x2="12" y2="3"></line><line x1="20" y1="21" x2="20" y2="16"></line><line x1="20" y1="12" x2="20" y2="3"></line></svg>`;
    case "cpu":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect></svg>`;
    default:
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle></svg>`;
  }
}

export async function fetchCronTasks() {
  if (!cronGrid) return;
  try {
    const res = await fetch(ENDPOINTS.cronStatus);
    if (!res.ok) return;
    const data = await res.json();
    const jobs = data.jobs || [];

    if (cronSubtitle) {
      cronSubtitle.textContent = `cron.d & systemd automations • ${jobs.length} tasks`;
    }
    setCardSummary("automation-section", `Schedules: ${jobs.length} configured tasks`);

    cronGrid.innerHTML = jobs.map((job) => {
      const isRunning = job.is_running;
      let badgeClass = isRunning ? "running" : "";
      if (job.id === "immich_ml" && !job.is_running) badgeClass = "inactive";
      if (job.id === "server_suspend" && job.status_text && job.status_text.includes("Disabled")) badgeClass = "running";

      const runDisabledAttr = (!job.can_run && job.id !== "server_suspend") ? "disabled" : "";
      const safeName = escapeHtml(job.name);

      return `
        <div class="cron-item-card" id="cron-card-${escapeHtml(job.id)}">
          <div>
            <div class="cron-item-top">
              <div class="cron-item-brand">
                <div class="cron-icon-box" aria-hidden="true">
                  ${getCronIconSvg(job.icon)}
                </div>
                <div class="cron-title-group">
                  <h4>${safeName}</h4>
                  <span class="cron-schedule">${escapeHtml(job.schedule)}</span>
                </div>
              </div>
              <span class="cron-status-badge ${badgeClass}" id="cron-badge-${escapeHtml(job.id)}">
                ${isRunning ? '<span class="pulsing-dot active-pulse" aria-hidden="true"></span>' : ""}
                ${escapeHtml(job.status_text)}
              </span>
            </div>
            <p class="cron-desc">${escapeHtml(job.description)}</p>
          </div>

          <div>
            <div class="cron-meta-row">
              <span>Last Run: <strong>${escapeHtml(job.last_run)}</strong></span>
            </div>
            <div class="cron-actions-row">
              <button type="button" class="btn-cron-log" data-log-id="${escapeHtml(job.id)}" data-log-name="${safeName}" aria-label="View log for ${safeName}">
                View Log
              </button>
              <button type="button" class="btn-cron-run" id="btn-cron-run-${escapeHtml(job.id)}" data-run-id="${escapeHtml(job.id)}" data-run-name="${safeName}" ${runDisabledAttr}>
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
  } catch (err) {
    console.error("Error fetching cron tasks:", err);
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
  showToast("Automation Triggered", `Executing '${jobName}' in background...`, "⚡");

  try {
    const res = await fetch(ENDPOINTS.cronRun(jobId), { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Task Started", data.message, "✓");
      await fetchCronTasks();
    } else {
      showToast("Notice", data.message || data.error || "Could not start task", "⚠️");
    }
  } catch (_) {
    showToast("Error", `Could not trigger task '${jobName}'`, "❌");
  } finally {
    if (btn) btn.disabled = false;
  }
}

export function setupCronTasks() {
  registerModal(cronLogModal, { closeButtons: [cronModalClose, cronModalDismiss] });
  if (btnRefreshCron) btnRefreshCron.addEventListener("click", fetchCronTasks);
  if (cronModalRefresh) cronModalRefresh.addEventListener("click", refreshCronModalLog);
}
