/**
 * Widget: System Automation & Scheduled Cron Tasks
 * Renders 5 system background automation cards, real-time running indicators,
 * 1-click execution dispatchers, and universal task log viewer modal.
 */

import { $ } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";
import { toggleSleepMode } from "./sleepGuard.js";

const cronGrid = $("cron-grid");
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
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>`;
    case "moon":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
    case "refresh-cw":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>`;
    case "sliders":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="21" x2="4" y2="14"></line><line x1="4" y1="10" x2="4" y2="3"></line><line x1="12" y1="21" x2="12" y2="12"></line><line x1="12" y1="8" x2="12" y2="3"></line><line x1="20" y1="21" x2="20" y2="16"></line><line x1="20" y1="12" x2="20" y2="3"></line><line x1="1" y1="14" x2="7" y2="14"></line><line x1="9" y1="8" x2="15" y2="8"></line><line x1="17" y1="16" x2="23" y2="16"></line></svg>`;
    case "cpu":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect><line x1="9" y1="1" x2="9" y2="4"></line><line x1="15" y1="1" x2="15" y2="4"></line><line x1="9" y1="20" x2="9" y2="23"></line><line x1="15" y1="20" x2="15" y2="23"></line><line x1="20" y1="9" x2="23" y2="9"></line><line x1="20" y1="14" x2="23" y2="14"></line><line x1="1" y1="9" x2="4" y2="9"></line><line x1="1" y1="14" x2="4" y2="14"></line></svg>`;
    default:
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle></svg>`;
  }
}

export async function fetchCronTasks() {
  if (!cronGrid) return;
  try {
    const res = await fetch(ENDPOINTS.cronStatus);
    if (!res.ok) return;
    const data = await res.json();
    const jobs = data.jobs || [];

    cronGrid.innerHTML = jobs.map(job => {
      const isRunning = job.is_running;
      let badgeClass = isRunning ? "running" : "";
      if (job.id === "immich_ml" && !job.is_running) badgeClass = "inactive";
      if (job.id === "server_suspend" && job.status_text && job.status_text.includes("Disabled")) badgeClass = "running";

      const runDisabledAttr = (!job.can_run && job.id !== "server_suspend") ? "disabled" : "";

      return `
        <div class="cron-item-card" id="cron-card-${job.id}">
          <div>
            <div class="cron-item-top">
              <div class="cron-item-brand">
                <div class="cron-icon-box">
                  ${getCronIconSvg(job.icon)}
                </div>
                <div class="cron-title-group">
                  <h4>${escapeHtml(job.name)}</h4>
                  <span class="cron-schedule">${escapeHtml(job.schedule)}</span>
                </div>
              </div>
              <span class="cron-status-badge ${badgeClass}" id="cron-badge-${job.id}">
                ${isRunning ? '<span class="pulsing-dot active-pulse" style="width:6px;height:6px;"></span>' : ''}
                ${escapeHtml(job.status_text)}
              </span>
            </div>

            <p class="cron-desc" style="margin-top: 10px;">${escapeHtml(job.description)}</p>
          </div>

          <div>
            <div class="cron-meta-row">
              <span>Last Run: <strong>${escapeHtml(job.last_run)}</strong></span>
            </div>

            <div class="cron-actions-row" style="margin-top: 10px;">
              <button class="btn-cron-log" data-log-id="${job.id}" data-log-name="${escapeHtml(job.name)}" title="View recent task output log">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="micro-icon">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                </svg>
                View Log
              </button>
              <button class="btn-cron-run" id="btn-cron-run-${job.id}" data-run-id="${job.id}" data-run-name="${escapeHtml(job.name)}" ${runDisabledAttr} title="Execute task on demand">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="micro-icon">
                  <polygon points="5 3 19 12 5 21 5 3"></polygon>
                </svg>
                ${escapeHtml(job.run_label)}
              </button>
            </div>
          </div>
        </div>
      `;
    }).join("");

    // Bind action buttons
    cronGrid.querySelectorAll(".btn-cron-log").forEach(btn => {
      btn.onclick = () => openCronLog(btn.dataset.logId, btn.dataset.logName);
    });
    cronGrid.querySelectorAll(".btn-cron-run").forEach(btn => {
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

export async function openCronLog(jobId, jobName) {
  activeCronJobId = jobId;
  if (cronModalTitle) cronModalTitle.textContent = `${jobName} Live Log`;
  if (cronModalSubPath) cronModalSubPath.textContent = `Job: ${jobId} • Fetching /var/log/...`;
  if (cronModalLogContent) cronModalLogContent.textContent = "Loading task output log...";
  if (cronLogModal) cronLogModal.style.display = "flex";

  await refreshCronModalLog();
}

export function closeCronLogModal() {
  if (cronLogModal) cronLogModal.style.display = "none";
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
    if (cronModalLogContent) {
      cronModalLogContent.textContent = "Error reading log: " + err.message;
    }
  }
}

export async function runCronJob(jobId, jobName) {
  const btn = $(`btn-cron-run-${jobId}`);
  if (btn) btn.disabled = true;
  showToast("Task Started", `Triggering on-demand execution for ${jobName}...`, "⚡", 4000);

  try {
    const res = await fetch(ENDPOINTS.cronRun(jobId), { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Execution Triggered", data.message || `${jobName} started.`, "✅", 4000);
      await fetchCronTasks();
    } else {
      showToast("Execution Notice", data.message || data.error || "Failed to start task", "ℹ️", 4000);
    }
  } catch (err) {
    showToast("Task Error", err.message, "⚠️", 5000);
  } finally {
    if (btn) btn.disabled = false;
  }
}

export function setupCronTasks() {
  if (btnRefreshCron) {
    btnRefreshCron.addEventListener("click", () => {
      fetchCronTasks();
      showToast("Automations Refreshed", "Sampled all 5 cron job statuses.", "🔄", 2500);
    });
  }
  if (cronModalClose) cronModalClose.addEventListener("click", closeCronLogModal);
  if (cronModalDismiss) cronModalDismiss.addEventListener("click", closeCronLogModal);
  if (cronModalRefresh) cronModalRefresh.addEventListener("click", refreshCronModalLog);
}
