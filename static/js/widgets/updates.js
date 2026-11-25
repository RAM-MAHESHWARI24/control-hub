/**
 * Widget: Available Updates (Phase 2C)
 * Compares pinned container image tags and the Blueprint checkout against
 * cached GitHub releases with honest error/floating-tag reporting and 1-click
 * safe CLI update command copy.
 */

import { $, copyTextToClipboard } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";
import { state } from "../state.js";
import { renderOverview } from "./overview.js";

const updatesSubtitle = $("updates-subtitle");
const updatesSummaryBadge = $("updates-summary-badge");
const updatesMajorCallout = $("updates-major-callout");
const updatesTableWrap = $("updates-table-wrap");
const btnCheckUpdates = $("btn-check-updates");
const checkUpdatesSpinner = $("updates-check-spinner");
const checkUpdatesLabel = $("updates-check-label");

let lastUpdatesSignature = "";

function statusStamp(kind) {
  switch (kind) {
    case "up_to_date":
      return { cls: "badge-status-synced", label: "Up to Date", rowCls: "" };
    case "major":
      return { cls: "badge-status-error", label: "Major Version", rowCls: "row--minus" };
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

export function renderUpdates(data) {
  if (!data || !updatesTableWrap) return;
  state.updatesSnapshot = data;

  const rows = Array.isArray(data.rows) ? data.rows : [];
  const pending = Number(data.pending || 0);
  const majors = Number(data.majors || 0);

  if (updatesSubtitle) {
    const parts = [];
    if (data.checked_at_str) parts.push(`Last checked ${data.checked_at_str}`);
    else parts.push("Not checked against GitHub yet");
    parts.push(`${rows.length} tracked target${rows.length === 1 ? "" : "s"}`);
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
      updatesMajorCallout.textContent = `${majors} major version update${majors === 1 ? "" : "s"} detected — review upstream release notes before upgrading.`;
      updatesMajorCallout.hidden = false;
    } else {
      updatesMajorCallout.hidden = true;
    }
  }

  const sig = JSON.stringify(rows.map((r) => [r.container, r.current, r.latest, r.kind, r.reason, r.command]));
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

    const cmdBtnHtml = row.command && ["update", "rebuild", "major"].includes(row.kind)
      ? `<button type="button" class="btn-secondary btn-copy-update-cmd" data-cmd="${escapeHtml(row.command)}" aria-label="Copy update command for ${title}">Copy Cmd</button>`
      : `<span class="text-muted font-mono">${row.kind === "up_to_date" ? "Current" : "Manual"}</span>`;

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
          ${cmdBtnHtml}
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
          <th scope="col" class="actions-col">Update</th>
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
        ok ? "Paste in SSH to apply the compose update safely." : "Browser clipboard unavailable over plain HTTP.",
        ok ? "success" : "warning"
      );
    });
  });

  renderOverview();
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
}
