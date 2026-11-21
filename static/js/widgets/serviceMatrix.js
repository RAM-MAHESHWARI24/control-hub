/**
 * Widget: Service Matrix & Container Logs
 * Renders compact 56px service rows for actually installed containers/services,
 * updates filter counts dynamically, removes fake ping figures, and manages inline logs.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { COCKPIT_BASE_URL, DOZZLE_BASE_URL, ENDPOINTS, HOSTNAME } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";

const servicesGrid = $("services-grid");
const serviceFilters = $("service-filter-group");
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
const dozzleIframe = $("dozzle-iframe");

let activeLogServiceId = null;
let activeLogServiceName = null;
let activeLogDockerId = null;

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

function getBrandLogoImg(serviceId) {
  const iconPath = BRAND_ICON_MAP[serviceId] || "/img/icons/jellyfin.svg";
  return `<img src="${iconPath}" alt="" class="brand-logo-img" loading="lazy" />`;
}

function updateFilterCounts(services) {
  if (!serviceFilters) return;
  const counts = { all: services.length, media: 0, ingest: 0, system: 0 };
  services.forEach((svc) => {
    const cat = svc.category || "system";
    if (cat in counts) counts[cat] += 1;
  });
  const labels = {
    all: `All (${counts.all})`,
    media: `Media (${counts.media})`,
    ingest: `Ingest (${counts.ingest})`,
    system: `System (${counts.system})`,
  };
  serviceFilters.querySelectorAll(".svc-filter-btn").forEach((btn) => {
    const key = btn.getAttribute("data-filter");
    if (key in labels) btn.textContent = labels[key];
  });
}

function updateOptionalToolLinks(dozzleInstalled, cockpitInstalled) {
  state.dozzleInstalled = Boolean(dozzleInstalled);
  state.cockpitInstalled = Boolean(cockpitInstalled);

  if (openDozzleFullBtn) {
    openDozzleFullBtn.style.display = state.dozzleInstalled ? "inline-flex" : "none";
    openDozzleFullBtn.href = DOZZLE_BASE_URL;
  }
  if (logViewToggle) {
    logViewToggle.style.display = state.dozzleInstalled ? "inline-flex" : "none";
  }
  if (dozzleModalExtLink) {
    dozzleModalExtLink.style.display = state.dozzleInstalled ? "inline-flex" : "none";
  }
  if (footerDozzleLink) {
    footerDozzleLink.style.display = state.dozzleInstalled ? "inline-flex" : "none";
    footerDozzleLink.href = DOZZLE_BASE_URL;
  }
  if (footerCockpitLink) {
    footerCockpitLink.style.display = state.cockpitInstalled ? "inline-flex" : "none";
    footerCockpitLink.href = COCKPIT_BASE_URL;
  }
}

export async function fetchServices() {
  if (!servicesGrid) return;
  try {
    const res = await fetch(ENDPOINTS.servicesStatus);
    if (!res.ok) return;
    const data = await res.json();
    const services = data.services || [];

    updateOptionalToolLinks(data.dozzle_installed, data.cockpit_installed);
    updateFilterCounts(services);

    const onlineCount = services.filter((s) => s.is_up).length;
    setCardSummary(
      "services-matrix",
      services.length
        ? `Apps: ${onlineCount}/${services.length} online`
        : (data.docker_available === false ? "Apps: Docker unavailable" : "Apps: None installed")
    );

    if (services.length === 0) {
      const msg = data.docker_available === false
        ? `Docker daemon unavailable${data.docker_error ? `: ${escapeHtml(data.docker_error)}` : "."}`
        : "No homelab containers detected on this host.";
      servicesGrid.innerHTML = `<div class="ops-empty-state">${msg}</div>`;
      return;
    }

    const currentFilter = state.activeServiceFilter || "all";

    servicesGrid.innerHTML = services.map((svc) => {
      const isUp = Boolean(svc.is_up);
      const badgeClass = isUp ? "online" : "stopped";
      const badgeText = isUp ? "Online" : (svc.state || "Stopped");
      const category = svc.category || "system";
      const isVisible = currentFilter === "all" || currentFilter === category;
      const protocol = svc.port === 9090 ? "https:" : "http:";
      const targetUrl = `${protocol}//${HOSTNAME}:${svc.port}`;
      const safeName = escapeHtml(svc.name);
      const safeStatus = escapeHtml(svc.status || badgeText);

      return `
        <div class="service-row tile-${escapeHtml(svc.id)}" id="tile-${escapeHtml(svc.id)}" data-category="${escapeHtml(category)}" style="display: ${isVisible ? "flex" : "none"};">
          <div class="service-row-main">
            <span class="status-dot-sm ${badgeClass}" aria-hidden="true"></span>
            <div class="service-row-icon" aria-hidden="true">${getBrandLogoImg(svc.id)}</div>
            <div class="service-row-info">
              <div class="service-row-title-line">
                <span class="service-row-name">${safeName}</span>
                <span class="tile-port font-mono">:${svc.port}</span>
              </div>
              <span class="service-row-desc">${safeStatus}</span>
            </div>
          </div>

          <div class="service-row-actions">
            <span class="tile-badge ${badgeClass}">${escapeHtml(badgeText)}</span>
            <a href="${targetUrl}" target="_blank" rel="noopener" class="btn-tile-launch" id="btn-launch-${escapeHtml(svc.id)}" aria-label="Open ${safeName} on port ${svc.port}">
              Open <span aria-hidden="true">&nearr;</span>
            </a>
            ${svc.id !== "cockpit" ? `
              <button type="button" class="btn-tile-logs" data-log-id="${escapeHtml(svc.id)}" data-log-name="${safeName}" data-docker-id="${escapeHtml(svc.docker_id || "")}" aria-label="View logs for ${safeName}">
                Logs
              </button>
              <button type="button" class="btn-tile-restart" id="btn-restart-${escapeHtml(svc.id)}" data-restart-id="${escapeHtml(svc.id)}" data-restart-name="${safeName}" aria-label="Restart ${safeName}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="micro-icon" aria-hidden="true">
                  <polyline points="23 4 23 10 17 10"></polyline>
                  <polyline points="1 20 1 14 7 14"></polyline>
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                </svg>
                <span>Restart</span>
              </button>
            ` : ""}
          </div>
        </div>
      `;
    }).join("");

    servicesGrid.querySelectorAll(".btn-tile-logs").forEach((btn) => {
      btn.onclick = () => openContainerLogs(btn.dataset.logId, btn.dataset.logName, btn.dataset.dockerId, btn);
    });
    servicesGrid.querySelectorAll(".btn-tile-restart").forEach((btn) => {
      btn.onclick = () => restartContainer(btn.dataset.restartId, btn.dataset.restartName);
    });

    state.servicesLoadedOnce = true;
  } catch (err) {
    console.error("Error fetching services:", err);
  }
}

export async function openContainerLogs(containerId, containerName, dockerId, triggerEl = null) {
  activeLogServiceId = containerId;
  activeLogServiceName = containerName;
  activeLogDockerId = dockerId || containerId;

  if (dozzleModalTitle) dozzleModalTitle.textContent = `${containerName} Logs`;
  if (containerModalSubPath) {
    const shortId = dockerId ? ` (${dockerId.slice(0, 12)})` : "";
    containerModalSubPath.textContent = `Container: ${containerId}${shortId} • Live Tail`;
  }

  const effectiveDozzleId = dockerId || containerId;
  const dozzleUrl = `${DOZZLE_BASE_URL}/container/${effectiveDozzleId}`;
  if (dozzleModalExtLink) dozzleModalExtLink.href = dozzleUrl;

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
  } else {
    if (btnLogTabNative) btnLogTabNative.classList.remove("active");
    if (btnLogTabDozzle) btnLogTabDozzle.classList.add("active");
    if (containerNativeLogView) containerNativeLogView.style.display = "none";
    if (containerDozzleIframeView) containerDozzleIframeView.style.display = "block";
    if (containerNativeFooter) containerNativeFooter.style.display = "none";

    const effectiveDozzleId = activeLogDockerId || activeLogServiceId;
    const dozzleUrl = `${DOZZLE_BASE_URL}/container/${effectiveDozzleId}`;
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
    const res = await fetch(ENDPOINTS.serviceLogs(activeLogServiceId, 120));
    const data = await res.json();
    if (containerModalLogContent) {
      containerModalLogContent.textContent = data.logs || "No log output recorded yet.";
      containerModalLogContent.scrollTop = containerModalLogContent.scrollHeight;
    }
  } catch (err) {
    if (containerModalLogContent) {
      containerModalLogContent.textContent = `Error fetching logs: ${err.message}`;
    }
  }
}

export async function restartContainer(containerId, containerName) {
  const btn = $(`btn-restart-${containerId}`);
  if (btn) btn.disabled = true;
  showToast("Restarting Container", `Sending restart signal to ${containerName}...`, "⟳", 4000);

  try {
    const res = await fetch(ENDPOINTS.serviceRestart(containerId), { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Container Restarted", `${containerName} restarted successfully.`, "✅", 4000);
      await fetchServices();
    } else {
      showToast("Restart Failed", data.error || "Failed to restart container", "⚠️", 5000);
    }
  } catch (err) {
    showToast("Restart Error", err.message, "⚠️", 5000);
  } finally {
    if (btn) btn.disabled = false;
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
    const filterBtns = serviceFilters.querySelectorAll(".svc-filter-btn");
    filterBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        filterBtns.forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-pressed", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-pressed", "true");
        state.activeServiceFilter = btn.getAttribute("data-filter") || "all";
        if (servicesGrid) {
          servicesGrid.querySelectorAll(".service-row").forEach((tile) => {
            tile.style.display =
              state.activeServiceFilter === "all" || tile.getAttribute("data-category") === state.activeServiceFilter
                ? "flex"
                : "none";
          });
        }
      });
    });
  }

  if (btnLogTabNative) btnLogTabNative.addEventListener("click", () => switchLogTab("native"));
  if (btnLogTabDozzle) btnLogTabDozzle.addEventListener("click", () => switchLogTab("dozzle"));
  if (containerModalRefresh) containerModalRefresh.addEventListener("click", refreshContainerLog);
}
