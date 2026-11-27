/**
 * Widget: Media Pipeline Operations (Phase 3A Slice 2)
 * Displays Prowlarr indexer health & fix hints, Seerr pending requests with
 * approve/decline, Radarr/Sonarr 7-day calendar & missing items, and Jellyfin
 * library scan + recently added titles.
 */

import { $ } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { showToast } from "../shared/toast.js";

const mediaHubPanel = $("media-hub-panel");
const mediaHubSummary = $("media-hub-summary");
const mediaHubBody = $("media-hub-body");
const btnTestIndexers = $("btn-media-test-indexers");
const btnScanJellyfin = $("btn-media-scan-jellyfin");
const familyRecentMedia = $("family-recent-media");
const familyRequestsBody = $("family-requests-body");
const familyMediaSummary = $("family-media-summary");

let activeTab = "indexers";
let lastData = { indexers: null, media: null };

function renderFamilyOverview() {
  if (!familyRecentMedia || !familyRequestsBody) return;
  const media = lastData.media || {};
  const recent = Array.isArray(media?.library?.jellyfin?.recent) ? media.library.jellyfin.recent : [];
  const reqs = Array.isArray(media?.requests?.items) ? media.requests.items : [];
  if (familyMediaSummary) {
    familyMediaSummary.textContent = `${recent.length} recent addition${recent.length === 1 ? "" : "s"} · ${reqs.length} pending request${reqs.length === 1 ? "" : "s"}`;
  }
  familyRecentMedia.innerHTML = recent.length
    ? recent.map((it) => `<span class="well toolbar-stat font-mono">${escapeHtml(it.name)}${it.year ? ` (${escapeHtml(it.year)})` : ""}</span>`).join("")
    : `<span class="text-muted">No recent Jellyfin additions yet.</span>`;
  familyRequestsBody.innerHTML = reqs.length
    ? `<ol class="trail audit-trail-list">${reqs.map((r) => `
        <li class="audit-trail-item">
          <span class="audit-trail-label">${escapeHtml(r.title)} (${escapeHtml(r.type || "media")})</span>
          <span class="audit-trail-meta">${escapeHtml(r.requested_by || "Family")} · ${escapeHtml(r.waiting_reason || "Pending")}</span>
        </li>
      `).join("")}</ol>`
    : `<span class="text-muted">No pending Seerr requests right now.</span>`;
}

function renderTabContent() {
  renderFamilyOverview();
  if (!mediaHubBody) return;
  const isFamily = state.authRole === "family";
  if (isFamily && activeTab === "indexers") {
    activeTab = "library";
    mediaHubPanel?.querySelectorAll(".media-hub-tab").forEach((b) => {
      b.setAttribute("aria-selected", String(b.dataset.tab === activeTab));
    });
  }
  const ix = lastData.indexers;
  const media = lastData.media;

  if (mediaHubSummary) {
    const reqs = Array.isArray(media?.requests?.items) ? media.requests.items.length : 0;
    if (isFamily) {
      const recentCount = Array.isArray(media?.library?.jellyfin?.recent) ? media.library.jellyfin.recent.length : 0;
      mediaHubSummary.textContent = `${recentCount} recent title${recentCount === 1 ? "" : "s"} · ${reqs} pending request${reqs === 1 ? "" : "s"}`;
    } else {
      const failing = Number(ix?.failing || 0);
      mediaHubSummary.textContent = `${ix?.total || 0} indexers (${failing} failing) · ${reqs} pending request${reqs === 1 ? "" : "s"}`;
    }
  }

  if (activeTab === "indexers") {
    if (!ix || ix.installed === false) {
      mediaHubBody.innerHTML = `<div class="empty-state">Prowlarr API key not configured; add PROWLARR_API_KEY in control-hub.env to monitor indexer health.</div>`;
      return;
    }
    if (!ix.reachable) {
      mediaHubBody.innerHTML = `<div class="inline-callout is-warning">Prowlarr is not reachable right now.</div>`;
      return;
    }
    const items = Array.isArray(ix.indexers) ? ix.indexers : [];
    if (!items.length) {
      mediaHubBody.innerHTML = `<div class="empty-state">No indexers configured in Prowlarr yet.</div>`;
      return;
    }
    mediaHubBody.innerHTML = `
      <table class="service-ledger">
        <thead>
          <tr>
            <th scope="col">Indexer</th>
            <th scope="col">Tier</th>
            <th scope="col">Health</th>
            <th scope="col">Diagnostic</th>
          </tr>
        </thead>
        <tbody>
          ${items.map((r) => `
            <tr class="service-row">
              <td><span class="service-row-name">${escapeHtml(r.name)}</span></td>
              <td class="font-mono">${escapeHtml(r.privacy || r.protocol || "")}</td>
              <td><span class="${r.healthy ? "badge-status-synced" : "badge-status-error"}">${r.healthy ? "Healthy" : "Failing"}</span></td>
              <td>${escapeHtml(r.fix_hint || "Passing checks")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
    return;
  }

  if (activeTab === "requests") {
    const req = media?.requests;
    if (!req?.configured) {
      mediaHubBody.innerHTML = `<div class="empty-state">Set SEERR_API_KEY in control-hub.env to approve or decline Seerr requests here.</div>`;
      return;
    }
    const items = Array.isArray(req.items) ? req.items : [];
    if (!items.length) {
      mediaHubBody.innerHTML = `<div class="empty-state">${req.error ? escapeHtml(req.error) : "No pending Seerr requests."}</div>`;
      return;
    }
    mediaHubBody.innerHTML = `
      <table class="service-ledger">
        <thead>
          <tr>
            <th scope="col">Title</th>
            <th scope="col">Requested By</th>
            <th scope="col">State</th>
            <th scope="col" class="actions-col">Decision</th>
          </tr>
        </thead>
        <tbody>
          ${items.map((r) => `
            <tr class="service-row">
              <td><span class="service-row-name">${escapeHtml(r.title)}</span> <span class="font-mono text-muted">${escapeHtml(r.type)}</span></td>
              <td>${escapeHtml(r.requested_by)}</td>
              <td>${escapeHtml(r.waiting_reason)}</td>
              <td class="actions-col">
                ${isFamily ? `<span class="badge">Read-only</span>` : `
                <button type="button" class="btn-primary btn-req-decide" data-req-id="${escapeHtml(r.id)}" data-decision="approve">Approve</button>
                <button type="button" class="btn-ghost btn-req-decide" data-req-id="${escapeHtml(r.id)}" data-decision="decline">Decline</button>
                `}
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
    mediaHubBody.querySelectorAll(".btn-req-decide").forEach((btn) => {
      btn.addEventListener("click", () => decideRequest(btn.dataset.reqId, btn.dataset.decision, btn));
    });
    return;
  }

  if (activeTab === "calendar") {
    const cal = media?.calendar;
    if (!cal?.configured) {
      mediaHubBody.innerHTML = `<div class="empty-state">Set RADARR_API_KEY or SONARR_API_KEY in control-hub.env to show upcoming 7-day releases.</div>`;
      return;
    }
    const items = Array.isArray(cal.items) ? cal.items : [];
    if (!items.length) {
      mediaHubBody.innerHTML = `<div class="empty-state">No movies or episodes scheduled in the next 7 days.</div>`;
      return;
    }
    mediaHubBody.innerHTML = `
      <table class="service-ledger">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Type</th>
            <th scope="col">Release</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          ${items.map((c) => `
            <tr class="service-row">
              <td class="font-mono">${escapeHtml(c.date || "--")}</td>
              <td class="font-mono">${escapeHtml(c.kind || "")}</td>
              <td>${escapeHtml(c.title)}</td>
              <td><span class="${c.has_file ? "badge-status-synced" : "badge-status-pending"}">${c.has_file ? "On Disk" : "Upcoming"}</span></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
    return;
  }

  // Library tab (Jellyfin recent + Arr wanted)
  const lib = media?.library || {};
  const jf = lib.jellyfin || {};
  const recent = Array.isArray(jf.recent) ? jf.recent : [];
  const wanted = Array.isArray(lib.wanted) ? lib.wanted : [];
  if (!jf.configured && !lib.wanted_configured) {
    mediaHubBody.innerHTML = `<div class="empty-state">Set JELLYFIN_API_KEY / RADARR_API_KEY / SONARR_API_KEY to browse recent media, missing items, and library scan tools.</div>`;
    return;
  }
  const recentHtml = recent.length
    ? recent.map((it) => `<span class="well toolbar-stat font-mono">${escapeHtml(it.name)}${it.year ? ` (${escapeHtml(it.year)})` : ""}</span>`).join("")
    : `<span class="text-muted">${jf.configured ? "No recent items returned." : "JELLYFIN_API_KEY not configured."}</span>`;
  const wantedHtml = wanted.length
    ? wanted.map((it) => `<span class="well toolbar-stat font-mono">${escapeHtml(it.title)}</span>`).join("")
    : `<span class="text-muted">${lib.wanted_configured ? "No missing/wanted items." : "Set RADARR_API_KEY / SONARR_API_KEY to track wanted items."}</span>`;
  mediaHubBody.innerHTML = `
    <div class="panel"><h3>Recently Added (Jellyfin)</h3><div class="tv-crud-actions">${recentHtml}</div></div>
    <div class="panel"><h3>Missing &amp; Wanted (*Arr)</h3><div class="tv-crud-actions">${wantedHtml}</div></div>
  `;
}

async function decideRequest(reqId, decision, btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.mediaRequestDecision(reqId, decision), { method: "POST" });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast("Request Updated", `Request #${reqId} ${decision}d.`, "success");
      await fetchMediaHub();
    } else {
      showToast("Request Failed", data.error || "Seerr declined the change.", "warning");
    }
  } catch (_) {
    showToast("Error", "Could not reach Control Hub.", "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

export async function fetchMediaHub() {
  if (!mediaHubPanel && !familyRecentMedia) return false;
  try {
    const isFamily = state.authRole === "family";
    const [ixRes, mediaRes] = await Promise.allSettled([
      isFamily ? Promise.resolve(null) : fetch(ENDPOINTS.indexersHealth),
      fetch(ENDPOINTS.mediaOverview),
    ]);
    if (ixRes.status === "fulfilled" && ixRes.value && ixRes.value.ok) {
      lastData.indexers = await ixRes.value.json();
    }
    if (mediaRes.status === "fulfilled" && mediaRes.value && mediaRes.value.ok) {
      lastData.media = await mediaRes.value.json();
    }
    renderTabContent();
    return true;
  } catch (_) {
    return false;
  }
}

export function setupMediaHub() {
  if (!mediaHubPanel) return;
  mediaHubPanel.querySelectorAll(".media-hub-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      activeTab = tab.dataset.tab || "indexers";
      mediaHubPanel.querySelectorAll(".media-hub-tab").forEach((b) => {
        b.setAttribute("aria-selected", String(b === tab));
      });
      renderTabContent();
    });
  });

  if (btnTestIndexers) {
    btnTestIndexers.addEventListener("click", async () => {
      btnTestIndexers.disabled = true;
      btnTestIndexers.textContent = "Testing...";
      try {
        const res = await fetch(ENDPOINTS.indexersTestAll, { method: "POST" });
        const data = await res.json();
        if (res.ok) {
          showToast("Indexer Test Complete", "Prowlarr connectivity check finished.", "success");
          await fetchMediaHub();
        } else {
          showToast("Test Failed", data.error || "Prowlarr testall failed.", "warning");
        }
      } catch (_) {
        showToast("Error", "Could not reach Prowlarr.", "danger");
      } finally {
        btnTestIndexers.disabled = false;
        btnTestIndexers.textContent = "Test Indexers";
      }
    });
  }

  if (btnScanJellyfin) {
    btnScanJellyfin.addEventListener("click", async () => {
      btnScanJellyfin.disabled = true;
      try {
        const res = await fetch(ENDPOINTS.mediaJellyfinScan, { method: "POST" });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast("Jellyfin Scan Started", data.message || "Library scan queued.", "success");
        } else {
          showToast("Scan Unavailable", data.error || "Configure JELLYFIN_API_KEY in control-hub.env.", "info");
        }
      } catch (_) {
        showToast("Error", "Could not reach Control Hub.", "danger");
      } finally {
        btnScanJellyfin.disabled = false;
      }
    });
  }
}
