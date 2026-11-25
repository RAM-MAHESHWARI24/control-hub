/**
 * Widget: Available Updates & Safe One-Click Updater (Phase 2C)
 * Compares pinned container image tags and the Blueprint checkout against
 * cached GitHub releases, runs backup + rollback-protected one-click updates,
 * handles Blueprint self-updates, and toggles optional auto-patch updates.
 */

import { $, copyTextToClipboard } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";
import { state } from "../state.js";
import { renderOverview } from "./overview.js";

const updatesSubtitle = $("updates-subtitle");
const updatesSummaryBadge = $("updates-summary-badge");
const updatesJobBanner = $("updates-job-banner");
const updatesMajorCallout = $("updates-major-callout");
const updatesTableWrap = $("updates-table-wrap");
const btnCheckUpdates = $("btn-check-updates");
const btnUpdateAllSafe = $("btn-update-all-safe");
const btnSelfUpdate = $("btn-self-update");
const btnAutoPatch = $("btn-updates-auto-patch");
const checkUpdatesSpinner = $("updates-check-spinner");
const checkUpdatesLabel = $("updates-check-label");

let lastUpdatesSignature = "";
let jobPollTimer = null;

function statusStamp(kind) {
  switch (kind) {
    case "up_to_date":
      return { cls: "badge-status-synced", label: "Up to Date", rowCls: "" };
    case "major":
      return { cls: "badge-status-error", label: "Manual Migration", rowCls: "row--minus" };
    case "update":
      return { cls: "badge-status-pending", label: "Update Available", rowCls: "" };
    case "rebuild":
      return { cls: "badge-status-pending", label: "New Image Build", rowCls: "" };
    case "newer_than_release":
      return { cls: "badge-status-syncing", label: "Ahead of Release", rowCls: "" };
    case "error":
      return { cls: "badge-status-error", label: "Check Failed", rowCls: "" };
    default:
      return { cls: "badge-status-unknown", label: "Not Tracked", rowCls: "" };
  }
}

function renderJobBanner(job) {
  if (!updatesJobBanner) return;
  if (!job || (!job.running && !job.message)) {
    updatesJobBanner.hidden = true;
    return;
  }
  updatesJobBanner.hidden = false;
  if (job.running) {
    updatesJobBanner.className = "inline-callout is-info";
    updatesJobBanner.textContent = job.message || "Update in progress (backing up config & waiting for container health)...";
    scheduleJobPoll();
  } else if (job.ok) {
    updatesJobBanner.className = "inline-callout is-success";
    updatesJobBanner.textContent = job.message || "Update finished.";
  } else {
    updatesJobBanner.className = job.rolled_back ? "inline-callout is-warning" : "inline-callout is-error";
    updatesJobBanner.textContent = job.message || "Update failed.";
  }
}

function scheduleJobPoll() {
  if (jobPollTimer) return;
  jobPollTimer = setTimeout(async () => {
    jobPollTimer = null;
    try {
      const res = await fetch(ENDPOINTS.updatesJob);
      if (!res.ok) return;
      const job = await res.json();
      renderJobBanner(job);
      if (!job.running) {
        lastUpdatesSignature = "";
        await fetchUpdates();
      }
    } catch (_) {
      /* Retry silently on transient network interruption (e.g. self-update restart). */
    }
  }, 2000);
}

function renderActionCell(row, title, helperAvailable, jobRunning) {
  if (row.container === "control-hub") {
    if (helperAvailable && row.latest && ["update", "rebuild", "major"].includes(row.kind)) {
      return `<button type="button" class="btn-primary btn-apply-self-update" data-tag="${escapeHtml(row.latest)}" ${jobRunning ? "disabled" : ""}>Self-Update</button>`;
    }
    if (row.command && ["update", "rebuild", "major"].includes(row.kind)) {
      return `<button type="button" class="btn-secondary btn-copy-update-cmd" data-cmd="${escapeHtml(row.command)}" aria-label="Copy blueprint update instructions">Copy Cmd</button>`;
    }
    return `<span class="text-muted font-mono">${row.kind === "up_to_date" ? "Current" : "Manual"}</span>`;
  }

  if (helperAvailable && row.one_click_allowed && row.latest) {
    return `<button type="button" class="btn-primary btn-apply-app-update" data-container="${escapeHtml(row.container)}" data-tag="${escapeHtml(row.latest)}" ${jobRunning ? "disabled" : ""} aria-label="Update ${title} with automatic rollback">Update</button>`;
  }

  if (row.command && ["update", "rebuild", "major"].includes(row.kind)) {
    return `<button type="button" class="btn-secondary btn-copy-update-cmd" data-cmd="${escapeHtml(row.command)}" aria-label="Copy update command for ${title}">Copy Cmd</button>`;
  }

  return `<span class="text-muted font-mono">${row.kind === "up_to_date" ? "Current" : "Manual"}</span>`;
}

export function renderUpdates(data) {
  if (!data || !updatesTableWrap) return;
  state.updatesSnapshot = data;

  const rows = Array.isArray(data.rows) ? data.rows : [];
  const pending = Number(data.pending || 0);
  const majors = Number(data.majors || 0);
  const safePending = Number(data.safe_pending || 0);
  const helperAvailable = Boolean(data.helper_available);
  const policy = data.policy || {};
  const job = data.job || {};
  const jobRunning = Boolean(job.running);
  const selfInfo = data.self_update || {};

  renderJobBanner(job);

  if (btnAutoPatch) {
    btnAutoPatch.hidden = !helperAvailable;
    const enabled = Boolean(policy.auto_patch);
    btnAutoPatch.setAttribute("aria-pressed", enabled ? "true" : "false");
    btnAutoPatch.textContent = enabled ? "Auto-Patch: On" : "Auto-Patch: Off";
  }

  if (btnUpdateAllSafe) {
    btnUpdateAllSafe.hidden = !helperAvailable || safePending === 0;
    btnUpdateAllSafe.disabled = jobRunning;
    btnUpdateAllSafe.textContent = safePending > 0 ? `Update All Safe (${safePending})` : "Update All Safe";
  }

  if (btnSelfUpdate) {
    const showSelf = Boolean(helperAvailable && selfInfo.update_ready);
    btnSelfUpdate.hidden = !showSelf;
    btnSelfUpdate.disabled = jobRunning;
    if (selfInfo.latest) {
      btnSelfUpdate.textContent = `Self-Update (${selfInfo.latest})`;
    }
  }

  if (updatesSubtitle) {
    const parts = [];
    if (data.checked_at_str) parts.push(`Last checked ${data.checked_at_str}`);
    else parts.push("Not checked against GitHub yet");
    parts.push(`${rows.length} tracked target${rows.length === 1 ? "" : "s"}`);
    if (policy.last_auto_summary) parts.push(policy.last_auto_summary);
    if (data.docker_error) parts.push(data.docker_error);
    updatesSubtitle.textContent = parts.join(" · ");
  }

  if (updatesSummaryBadge) {
    if (!data.checked_at) {
      updatesSummaryBadge.className = "badge";
      updatesSummaryBadge.textContent = "Not Checked";
    } else if (majors > 0) {
      updatesSummaryBadge.className = "badge badge-warning";
      updatesSummaryBadge.textContent = `${pending} Pending (${majors} Major)`;
    } else if (pending > 0) {
      updatesSummaryBadge.className = "badge badge-info";
      updatesSummaryBadge.textContent = `${pending} Update${pending === 1 ? "" : "s"}`;
    } else {
      updatesSummaryBadge.className = "badge badge-success";
      updatesSummaryBadge.textContent = "Up to Date";
    }
  }

  if (updatesMajorCallout) {
    if (majors > 0) {
      updatesMajorCallout.textContent = `${majors} major version update${majors === 1 ? "" : "s"} marked manual — read migration notes before upgrading.`;
      updatesMajorCallout.hidden = false;
    } else {
      updatesMajorCallout.hidden = true;
    }
  }

  const sig = JSON.stringify([
    helperAvailable,
    jobRunning,
    rows.map((r) => [r.container, r.current, r.latest, r.kind, r.reason, r.one_click_allowed]),
  ]);
  if (sig === lastUpdatesSignature && updatesTableWrap.querySelector("table")) {
    renderOverview();
    return;
  }
  lastUpdatesSignature = sig;

  if (rows.length === 0) {
    updatesTableWrap.innerHTML = `<div class="empty-state">No Compose-managed applications or Blueprint target found.</div>`;
    renderOverview();
    return;
  }

  const bodyHtml = rows.map((row) => {
    const { cls, label, rowCls } = statusStamp(row.kind);
    const title = escapeHtml(row.container === "control-hub" ? "Homelab Blueprint" : (row.service || row.container));
    const sub = escapeHtml(row.image_name || row.repo || "");
    const cur = escapeHtml(row.current || "--");
    const latestHtml = row.latest
      ? (row.release_url
        ? `<a href="${escapeHtml(row.release_url)}" target="_blank" rel="noopener" class="updates-release-link font-mono">${escapeHtml(row.latest)} &nearr;</a>`
        : `<span class="font-mono">${escapeHtml(row.latest)}</span>`)
      : `<span class="text-muted font-mono">${escapeHtml(row.reason || "Not checked")}</span>`;

    const actionHtml = renderActionCell(row, title, helperAvailable, jobRunning);

    return `
      <tr class="service-row update-row ${rowCls}">
        <td class="ledger-cell-service">
          <div class="service-row-info">
            <span class="service-row-name">${title}</span>
            <span class="service-row-desc font-mono">${sub}</span>
          </div>
        </td>
        <td class="ledger-cell-port num-col">
          <span class="tile-port font-mono">${cur}</span>
        </td>
        <td class="ledger-cell-latest">
          ${latestHtml}
        </td>
        <td class="ledger-cell-health">
          <span class="${cls}" title="${escapeHtml(row.reason || row.kind_text || label)}">${escapeHtml(label)}</span>
        </td>
        <td class="ledger-cell-actions actions-col">
          ${actionHtml}
        </td>
      </tr>
    `;
  }).join("");

  updatesTableWrap.innerHTML = `
    <table class="service-ledger updates-ledger">
      <thead>
        <tr>
          <th scope="col">Application</th>
          <th scope="col" class="num-col">Pinned</th>
          <th scope="col">Latest Release</th>
          <th scope="col">Status</th>
          <th scope="col" class="actions-col">Action</th>
        </tr>
      </thead>
      <tbody>${bodyHtml}</tbody>
    </table>
  `;

  updatesTableWrap.querySelectorAll(".btn-copy-update-cmd").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const ok = await copyTextToClipboard(btn.dataset.cmd || "");
      showToast(
        ok ? "Command Copied" : "Copy Blocked",
        ok ? "Paste in SSH to apply the update safely." : "Browser clipboard unavailable over plain HTTP.",
        ok ? "success" : "warning"
      );
    });
  });

  updatesTableWrap.querySelectorAll(".btn-apply-app-update").forEach((btn) => {
    btn.addEventListener("click", () => startAppUpdate({ container: btn.dataset.container }));
  });

  updatesTableWrap.querySelectorAll(".btn-apply-self-update").forEach((btn) => {
    btn.addEventListener("click", () => startSelfUpdate(btn.dataset.tag || ""));
  });

  renderOverview();
}

async function startAppUpdate(payload) {
  try {
    const res = await fetch(ENDPOINTS.updatesApply, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast("Update Declined", data.error || "Could not start update.", "warning");
      return;
    }
    showToast("Update Started", "Backing up config and updating with automatic health rollback.", "info");
    renderJobBanner(data.job);
    lastUpdatesSignature = "";
    await fetchUpdates();
  } catch (_) {
    showToast("Update Error", "Could not start background update.", "danger");
  }
}

async function startSelfUpdate(tag) {
  try {
    const res = await fetch(ENDPOINTS.updatesSelfUpdate, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(tag ? { tag } : {}),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast("Self-Update Unavailable", data.error || "Could not start blueprint self-update.", "warning");
      return;
    }
    showToast("Blueprint Update Started", "Updating release tag and re-applying configuration.", "info");
    renderJobBanner(data.job);
  } catch (_) {
    showToast("Self-Update Error", "Could not start blueprint self-update.", "danger");
  }
}

async function toggleAutoPatch() {
  if (!btnAutoPatch) return;
  const current = btnAutoPatch.getAttribute("aria-pressed") === "true";
  const next = !current;
  btnAutoPatch.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.updatesPolicy, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_patch: next }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(
        next ? "Auto-Patch Enabled" : "Auto-Patch Disabled",
        next ? "Patch and image-build updates will apply automatically (never majors)." : "Automatic patch updates paused.",
        "success"
      );
      await fetchUpdates();
    } else {
      showToast("Policy Update Failed", data.error || "Could not update policy.", "danger");
    }
  } catch (_) {
    showToast("Policy Error", "Could not save auto-patch setting.", "danger");
  } finally {
    btnAutoPatch.disabled = false;
  }
}

export async function fetchUpdates() {
  if (!updatesTableWrap) return false;
  try {
    const res = await fetch(ENDPOINTS.updates);
    if (!res.ok) return false;
    const data = await res.json();
    renderUpdates(data);
    return true;
  } catch (err) {
    console.error("Error fetching updates:", err);
    return false;
  }
}

export async function checkUpdatesNow() {
  if (!btnCheckUpdates) return;
  btnCheckUpdates.disabled = true;
  if (checkUpdatesSpinner) checkUpdatesSpinner.style.display = "inline-block";
  if (checkUpdatesLabel) checkUpdatesLabel.textContent = "Checking...";

  try {
    const res = await fetch(ENDPOINTS.updatesCheck, { method: "POST" });
    const data = await res.json();
    lastUpdatesSignature = "";
    renderUpdates(data);
    if (data.throttled) {
      const mins = Math.max(1, Math.ceil((data.cooldown_remaining_s || 60) / 60));
      showToast("Recently Checked", `Using cached GitHub data (next manual check in ~${mins} min).`, "info");
    } else if (data.pending > 0) {
      showToast("Updates Found", `${data.pending} release update${data.pending === 1 ? "" : "s"} available.`, data.majors > 0 ? "warning" : "info");
    } else {
      showToast("All Up to Date", "Running pinned versions match the latest tracked GitHub releases.", "success");
    }
  } catch (_) {
    showToast("Check Failed", "Could not query release status.", "danger");
  } finally {
    btnCheckUpdates.disabled = false;
    if (checkUpdatesSpinner) checkUpdatesSpinner.style.display = "none";
    if (checkUpdatesLabel) checkUpdatesLabel.textContent = "Check Releases";
  }
}

export function setupUpdates() {
  if (btnCheckUpdates) {
    btnCheckUpdates.addEventListener("click", checkUpdatesNow);
  }
  if (btnUpdateAllSafe) {
    btnUpdateAllSafe.addEventListener("click", () => startAppUpdate({ all: true }));
  }
  if (btnSelfUpdate) {
    btnSelfUpdate.addEventListener("click", () => {
      const latest = state.updatesSnapshot?.self_update?.latest || "";
      startSelfUpdate(latest);
    });
  }
  if (btnAutoPatch) {
    btnAutoPatch.addEventListener("click", toggleAutoPatch);
  }
}
