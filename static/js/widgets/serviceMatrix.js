/**
 * Widget: Service Matrix & Container Controls / Logs
 * Keyed zero-flicker rows, real Docker health & published ports, search + category
 * + custom-container toggle, confirmation guard for streaming/ingest restarts/stops,
 * and searchable/copyable inline logs modal.
 */

import { $, confirmAction, copyTextToClipboard, setCardSummary, uiIcon } from "../shared/dom.js";
import { state } from "../state.js";
import { COCKPIT_BASE_URL, ENDPOINTS, HOSTNAME } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { renderOverview } from "./overview.js";

const servicesGrid = $("services-grid");
const serviceFilters = $("service-filter-group");
const btnFilterOther = $("btn-filter-other");
const serviceSearchInput = $("service-search-input");
const includeOtherWrap = $("include-other-wrap");
const chkIncludeOther = $("chk-include-other");
const includeOtherLabel = $("include-other-label");

const openDozzleFullBtn = $("open-dozzle-full-btn");
const footerDozzleLink = $("footer-dozzle-link");
const footerCockpitLink = $("footer-cockpit-link");

const dozzleModal = $("dozzle-modal");
const dozzleModalTitle = $("dozzle-modal-title");
const containerModalSubPath = $("container-modal-sub-path");
const logViewToggle = $("log-view-toggle");
const btnLogTabNative = $("btn-log-tab-native");
const btnLogTabDozzle = $("btn-log-tab-dozzle");
const dozzleModalExtLink = $("dozzle-modal-ext-link");
const dozzleModalClose = $("dozzle-modal-close");
const containerNativeLogView = $("container-native-log-view");
const containerDozzleIframeView = $("container-dozzle-iframe-view");
const containerModalLogContent = $("container-modal-log-content");
const containerModalRefresh = $("container-modal-refresh");
const containerModalDismiss = $("container-modal-dismiss");
const containerNativeFooter = $("container-native-footer");
const containerLogFilter = $("container-log-filter");
const containerLogFilterBar = $("container-log-filter-bar");
const containerLogCopy = $("container-log-copy");
const dozzleIframe = $("dozzle-iframe");

let activeLogServiceId = null;
let activeLogServiceName = null;
let activeLogDockerId = null;
let rawContainerLogText = "";
let lastServicesSignature = "";

const GUARDED_SERVICES = new Set(["jellyfin", "immich_server", "qbittorrent", "immich_postgres"]);

const BRAND_ICON_MAP = {
  jellyfin: "/img/icons/jellyfin.svg",
  seerr: "/img/icons/seerr.svg",
  immich_server: "/img/icons/immich.svg",
  sonarr: "/img/icons/sonarr.svg",
  radarr: "/img/icons/radarr.svg",
  prowlarr: "/img/icons/prowlarr.svg",
  bazarr: "/img/icons/bazarr.svg",
  qbittorrent: "/img/icons/qbittorrent.svg",
  dozzle: "/img/icons/dozzle.svg",
  byparr: "/img/icons/byparr.svg",
  cockpit: "/img/icons/cockpit.svg",
};

function getBrandLogoHtml(serviceId) {
  const iconPath = BRAND_ICON_MAP[serviceId];
  if (iconPath) {
    return `<img src="${iconPath}" alt="" class="brand-logo-img" loading="lazy" />`;
  }
  return uiIcon("box");
}

function dozzleUrlBase() {
  return `http://${HOSTNAME}:${state.dozzlePort || 8888}`;
}

function updateFilterCounts(services) {
  if (!serviceFilters) return;
  const counts = { all: services.length, media: 0, ingest: 0, system: 0, other: 0 };
  services.forEach((svc) => {
    const cat = svc.category || "system";
    if (cat in counts) counts[cat] += 1;
  });
  if (btnFilterOther) btnFilterOther.hidden = counts.other === 0;
  const labels = {
    all: `All (${counts.all})`,
    media: `Media (${counts.media})`,
    ingest: `Ingest (${counts.ingest})`,
    system: `System (${counts.system})`,
    other: `Other (${counts.other})`,
  };
  serviceFilters.querySelectorAll("[data-filter]").forEach((btn) => {
    const key = btn.getAttribute("data-filter");
    if (key in labels) btn.textContent = labels[key];
  });
}

function updateOptionalToolLinks(dozzleInstalled, cockpitInstalled, dozzlePort) {
  state.dozzleInstalled = Boolean(dozzleInstalled);
  state.cockpitInstalled = Boolean(cockpitInstalled);
  if (dozzlePort) state.dozzlePort = dozzlePort;
  const dUrl = dozzleUrlBase();

  if (openDozzleFullBtn) {
    openDozzleFullBtn.style.display = state.dozzleInstalled ? "inline-flex" : "none";
    openDozzleFullBtn.href = dUrl;
  }
  if (logViewToggle) {
    logViewToggle.style.display = state.dozzleInstalled ? "inline-flex" : "none";
  }
  if (dozzleModalExtLink) {
    dozzleModalExtLink.style.display = state.dozzleInstalled ? "inline-flex" : "none";
  }
  if (footerDozzleLink) {
    footerDozzleLink.style.display = state.dozzleInstalled ? "inline-flex" : "none";
    footerDozzleLink.href = dUrl;
  }
  if (footerCockpitLink) {
    footerCockpitLink.style.display = state.cockpitInstalled ? "inline-flex" : "none";
    footerCockpitLink.href = COCKPIT_BASE_URL;
  }
}

function serviceVisualBadge(svc) {
  if (svc.health === "unhealthy") return { cls: "unhealthy", label: "Unhealthy" };
  if (svc.health === "starting") return { cls: "starting", label: "Starting" };
  if (svc.is_up) return { cls: "online", label: svc.health === "healthy" ? "Healthy" : "Online" };
  if (svc.scheduled) return { cls: "scheduled", label: "Scheduled Off" };
  return { cls: "stopped", label: svc.state || "Stopped" };
}

function applyClientFilters() {
  if (!servicesGrid) return;
  const filterCat = state.activeServiceFilter || "all";
  const q = (state.serviceSearchQuery || "").trim().toLowerCase();
  servicesGrid.querySelectorAll(".service-row").forEach((row) => {
    const cat = row.dataset.category || "system";
    const hay = row.dataset.search || "";
    const matchCat = filterCat === "all" || cat === filterCat;
    const matchSearch = !q || hay.includes(q);
    row.hidden = !(matchCat && matchSearch);
  });
}

function renderServiceRows(services, dockerAvailable, dockerError) {
  if (!servicesGrid) return;
  if (services.length === 0) {
    lastServicesSignature = "";
    const msg = dockerAvailable === false
      ? `Docker daemon unavailable${dockerError ? `: ${escapeHtml(dockerError)}` : "."}`
      : "No homelab containers detected on this host.";
    servicesGrid.innerHTML = `<div class="empty-state">${msg}</div>`;
    return;
  }

  const sig = JSON.stringify(services.map((s) => [s.id, s.state, s.health, s.status, s.port, s.is_up, s.has_web_ui, s.image, s.restart_count, s.version]));
  if (sig === lastServicesSignature && servicesGrid.querySelector(".service-row")) {
    applyClientFilters();
    return;
  }
  lastServicesSignature = sig;

  let tbody = servicesGrid.querySelector("tbody.service-ledger-body");
  if (!tbody) {
    servicesGrid.innerHTML = `
      <table class="service-ledger">
        <thead>
          <tr>
            <th scope="col">Service</th>
            <th scope="col">Group</th>
            <th scope="col" class="num-col">Port</th>
            <th scope="col">Health</th>
            <th scope="col" class="actions-col">Actions</th>
          </tr>
        </thead>
        <tbody class="service-ledger-body"></tbody>
      </table>
    `;
    tbody = servicesGrid.querySelector("tbody.service-ledger-body");
  }

  // Keyed patching to avoid disrupting hover/focus during 15s polling
  const existing = new Map();
  tbody.querySelectorAll(".service-row[data-service-id]").forEach((el) => {
    existing.set(el.dataset.serviceId, el);
  });

  const seenIds = new Set();
  services.forEach((svc) => {
    seenIds.add(svc.id);
    const { cls: badgeClass, label: badgeText } = serviceVisualBadge(svc);
    const category = svc.category || "system";
    const catLabel = category.charAt(0).toUpperCase() + category.slice(1);
    const hasUi = svc.has_web_ui !== false && Boolean(svc.port);
    const protocol = svc.port === 9090 ? "https:" : "http:";
    const targetUrl = hasUi ? `${protocol}//${HOSTNAME}:${svc.port}` : null;
    const safeName = escapeHtml(svc.name);
    const statusParts = [svc.status || badgeText];
    if (Number(svc.restart_count) > 0) {
      statusParts.push(`${svc.restart_count} restart${svc.restart_count === 1 ? "" : "s"}`);
    }
    if (svc.version) {
      statusParts.push(`v${svc.version}`);
    } else if (svc.image && svc.image !== "systemd") {
      const shortImg = svc.image.includes("/") ? svc.image.split("/").pop() : svc.image;
      statusParts.push(shortImg);
    }
    const safeStatus = escapeHtml(statusParts.join(" · "));

    let row = existing.get(svc.id);
    if (!row) {
      row = document.createElement("tr");
      row.className = `service-row tile-${svc.id}`;
      row.id = `tile-${svc.id}`;
      row.dataset.serviceId = svc.id;
      tbody.appendChild(row);
    }

    row.dataset.category = category;
    row.dataset.search = `${svc.name} ${svc.id} ${svc.description || ""} ${svc.image || ""}`.toLowerCase();

    const isRunning = svc.state === "running";
    const actionBtnsHtml = svc.id !== "cockpit" ? `
      <button type="button" class="btn-secondary btn-tile-logs" data-log-id="${escapeHtml(svc.id)}" data-log-name="${safeName}" data-docker-id="${escapeHtml(svc.docker_id || "")}" aria-label="View logs for ${safeName}">
        Logs
      </button>
      ${isRunning ? `
        <button type="button" class="btn-ghost btn-tile-restart" id="btn-restart-${escapeHtml(svc.id)}" data-action="restart" data-svc-id="${escapeHtml(svc.id)}" data-svc-name="${safeName}" aria-label="Restart ${safeName}">
          ${uiIcon("refresh")}
          <span>Restart</span>
        </button>
        <button type="button" class="btn-ghost btn-tile-stop" id="btn-stop-${escapeHtml(svc.id)}" data-action="stop" data-svc-id="${escapeHtml(svc.id)}" data-svc-name="${safeName}" aria-label="Stop ${safeName}">
          <span>Stop</span>
        </button>
      ` : `
        <button type="button" class="btn-secondary btn-tile-restart" id="btn-start-${escapeHtml(svc.id)}" data-action="start" data-svc-id="${escapeHtml(svc.id)}" data-svc-name="${safeName}" aria-label="Start ${safeName}">
          ${uiIcon("play")}
          <span>Start</span>
        </button>
      `}
    ` : "";

    row.innerHTML = `
      <td class="ledger-cell-service">
        <div class="service-row-main">
          <span class="status-dot-sm ${badgeClass}" aria-hidden="true"></span>
          <div class="service-row-icon" aria-hidden="true">${getBrandLogoHtml(svc.id)}</div>
          <div class="service-row-info">
            <span class="service-row-name">${safeName}</span>
            <span class="service-row-desc">${safeStatus}</span>
          </div>
        </div>
      </td>
      <td class="ledger-cell-group">${escapeHtml(catLabel)}</td>
      <td class="ledger-cell-port num-col">
        ${svc.port ? `<span class="tile-port font-mono">:${svc.port}</span>` : `<span class="tile-port font-mono">Internal</span>`}
      </td>
      <td class="ledger-cell-health">
        <span class="tile-badge ${badgeClass}">${escapeHtml(badgeText)}</span>
      </td>
      <td class="ledger-cell-actions actions-col">
        <div class="service-row-actions">
          ${hasUi ? `
            <a href="${targetUrl}" target="_blank" rel="noopener" class="btn-tile-launch" id="btn-launch-${escapeHtml(svc.id)}" aria-label="Open ${safeName} on port ${svc.port}">
              Open ${uiIcon("external")}
            </a>
          ` : ""}
          ${actionBtnsHtml}
        </div>
      </td>
    `;
  });

  existing.forEach((node, id) => {
    if (!seenIds.has(id)) node.remove();
  });

  tbody.querySelectorAll(".btn-tile-logs").forEach((btn) => {
    btn.onclick = () => openContainerLogs(btn.dataset.logId, btn.dataset.logName, btn.dataset.dockerId, btn);
  });
  tbody.querySelectorAll("[data-action]").forEach((btn) => {
    btn.onclick = () => performContainerAction(btn.dataset.svcId, btn.dataset.svcName, btn.dataset.action, btn);
  });

  applyClientFilters();
}

export async function fetchServices() {
  try {
    const res = await fetch(ENDPOINTS.servicesStatus(state.includeOtherContainers));
    if (!res.ok) return false;
    const data = await res.json();
    const services = data.services || [];

    state.servicesList = services;
    state.servicesLoadedOnce = true;

    if (includeOtherWrap) {
      const otherCount = Number(data.other_count || 0);
      includeOtherWrap.hidden = otherCount === 0 && !state.includeOtherContainers;
      if (includeOtherLabel && otherCount > 0) {
        includeOtherLabel.textContent = `Show ${otherCount} other container${otherCount === 1 ? "" : "s"}`;
      }
    }

    updateOptionalToolLinks(data.dozzle_installed, data.cockpit_installed, data.dozzle_port);
    updateFilterCounts(services);

    const onlineCount = services.filter((s) => s.is_up).length;
    setCardSummary(
      "services-matrix",
      services.length
        ? `${onlineCount}/${services.length} online`
        : (data.docker_available === false ? "Docker unavailable" : "No containers installed")
    );

    renderServiceRows(services, data.docker_available, data.docker_error);
    renderOverview();
    return true;
  } catch (err) {
    console.error("Error fetching services:", err);
    return false;
  }
}

function renderFilteredLog() {
  if (!containerModalLogContent) return;
  const q = (containerLogFilter ? containerLogFilter.value : "").trim().toLowerCase();
  if (!q) {
    containerModalLogContent.textContent = rawContainerLogText || "No log output recorded yet.";
  } else {
    const matched = (rawContainerLogText || "").split("\n").filter((ln) => ln.toLowerCase().includes(q));
    containerModalLogContent.textContent = matched.length
      ? matched.join("\n")
      : `No log lines matching "${q}".`;
  }
  containerModalLogContent.scrollTop = containerModalLogContent.scrollHeight;
}

export async function openContainerLogs(containerId, containerName, dockerId, triggerEl = null) {
  activeLogServiceId = containerId;
  activeLogServiceName = containerName;
  activeLogDockerId = dockerId || containerId;
  if (containerLogFilter) containerLogFilter.value = "";

  if (dozzleModalTitle) dozzleModalTitle.textContent = `${containerName} Logs`;
  if (containerModalSubPath) {
    const shortId = dockerId ? ` (${dockerId.slice(0, 12)})` : "";
    containerModalSubPath.textContent = `Container: ${containerId}${shortId} · Live Tail`;
  }

  const effectiveDozzleId = dockerId || containerId;
  if (dozzleModalExtLink) dozzleModalExtLink.href = `${dozzleUrlBase()}/container/${effectiveDozzleId}`;

  switchLogTab("native");
  if (dozzleModal) openModal(dozzleModal, triggerEl);
  await refreshContainerLog();
}

export function switchLogTab(tab) {
  const useDozzle = tab === "dozzle" && state.dozzleInstalled;
  if (!useDozzle) {
    if (btnLogTabNative) btnLogTabNative.classList.add("active");
    if (btnLogTabDozzle) btnLogTabDozzle.classList.remove("active");
    if (containerNativeLogView) containerNativeLogView.style.display = "block";
    if (containerDozzleIframeView) containerDozzleIframeView.style.display = "none";
    if (containerNativeFooter) containerNativeFooter.style.display = "flex";
    if (containerLogFilterBar) containerLogFilterBar.style.display = "flex";
  } else {
    if (btnLogTabNative) btnLogTabNative.classList.remove("active");
    if (btnLogTabDozzle) btnLogTabDozzle.classList.add("active");
    if (containerNativeLogView) containerNativeLogView.style.display = "none";
    if (containerDozzleIframeView) containerDozzleIframeView.style.display = "block";
    if (containerNativeFooter) containerNativeFooter.style.display = "none";
    if (containerLogFilterBar) containerLogFilterBar.style.display = "none";

    const effectiveDozzleId = activeLogDockerId || activeLogServiceId;
    const dozzleUrl = `${dozzleUrlBase()}/container/${effectiveDozzleId}`;
    if (dozzleIframe && (!dozzleIframe.src || dozzleIframe.src === "about:blank" || !dozzleIframe.src.includes(effectiveDozzleId))) {
      dozzleIframe.src = dozzleUrl;
    }
  }
}

export async function refreshContainerLog() {
  if (!activeLogServiceId) return;
  if (containerModalLogContent) {
    containerModalLogContent.textContent = `Streaming tail logs for ${activeLogServiceName}...`;
  }
  try {
    const res = await fetch(ENDPOINTS.serviceLogs(activeLogServiceId, 200));
    const data = await res.json();
    rawContainerLogText = data.logs || "";
    renderFilteredLog();
  } catch (err) {
    rawContainerLogText = "";
    if (containerModalLogContent) {
      containerModalLogContent.textContent = `Error fetching logs: ${err.message}`;
    }
  }
}

export async function performContainerAction(containerId, containerName, action = "restart", triggerEl = null) {
  if (action === "stop" || (GUARDED_SERVICES.has(containerId) && action === "restart")) {
    let activeWarning = "";
    if (containerId === "jellyfin" && state.activeJellyfinStreams > 0) {
      activeWarning = `${state.activeJellyfinStreams} active Jellyfin stream(s) will be interrupted immediately.`;
    } else if (containerId === "immich_server" && state.activeJellyfinStreams > 0) {
      activeWarning = "Stopping the photo server interrupts any open gallery uploads or mobile backups.";
    } else if (containerId === "qbittorrent" && state.torrentsActiveCount > 0) {
      activeWarning = `${state.torrentsActiveCount} active torrent(s) are currently transferring.`;
    } else if (containerId === "immich_postgres") {
      activeWarning = "Stopping or restarting PostgreSQL temporarily disconnects photo library queries and backups.";
    }
    const ok = await confirmAction({
      title: `${action === "stop" ? "Stop" : "Restart"} ${containerName}?`,
      message: `This will ${action} the '${containerId}' container immediately.`,
      warning: activeWarning,
      confirmLabel: action === "stop" ? `Stop ${containerName}` : `Restart ${containerName}`,
      danger: action === "stop" || Boolean(activeWarning),
      triggerEl,
    });
    if (!ok) return;
  }

  if (triggerEl) triggerEl.disabled = true;
  const verb = action === "start" ? "Starting" : (action === "stop" ? "Stopping" : "Restarting");
  showToast(`${verb} Container`, `Sending ${action} command to ${containerName}...`, "info", 3500);

  try {
    const res = await fetch(ENDPOINTS.serviceAction(containerId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast("Container Updated", data.message || `${containerName} ${action}ed.`, "success", 3800);
      lastServicesSignature = "";
      await fetchServices();
    } else {
      showToast("Action Failed", data.error || `Failed to ${action} container`, "danger", 5000);
    }
  } catch (err) {
    showToast("Action Error", err.message, "danger", 5000);
  } finally {
    if (triggerEl) triggerEl.disabled = false;
  }
}

export function setupServiceMatrix() {
  registerModal(dozzleModal, {
    closeButtons: [dozzleModalClose, containerModalDismiss],
    onClose: () => {
      if (dozzleIframe) dozzleIframe.src = "about:blank";
    },
  });

  if (serviceFilters) {
    const filterBtns = serviceFilters.querySelectorAll("[data-filter]");
    filterBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        filterBtns.forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-pressed", "true");
        state.activeServiceFilter = btn.getAttribute("data-filter") || "all";
        applyClientFilters();
      });
    });
  }

  if (serviceSearchInput) {
    serviceSearchInput.addEventListener("input", () => {
      state.serviceSearchQuery = serviceSearchInput.value || "";
      applyClientFilters();
    });
  }

  if (chkIncludeOther) {
    chkIncludeOther.addEventListener("change", () => {
      state.includeOtherContainers = chkIncludeOther.checked;
      lastServicesSignature = "";
      fetchServices();
    });
  }

  if (containerLogFilter) containerLogFilter.addEventListener("input", renderFilteredLog);
  if (containerLogCopy) {
    containerLogCopy.addEventListener("click", async () => {
      const text = containerModalLogContent ? containerModalLogContent.textContent : "";
      const ok = await copyTextToClipboard(text);
      showToast(ok ? "Logs Copied" : "Copy Failed", ok ? "Container log tail copied to clipboard." : "Could not copy logs.", ok ? "success" : "warning");
    });
  }

  if (btnLogTabNative) btnLogTabNative.addEventListener("click", () => switchLogTab("native"));
  if (btnLogTabDozzle) btnLogTabDozzle.addEventListener("click", () => switchLogTab("dozzle"));
  if (containerModalRefresh) containerModalRefresh.addEventListener("click", refreshContainerLog);
}
