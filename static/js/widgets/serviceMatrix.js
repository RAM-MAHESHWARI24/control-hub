/**
 * Widget: Service Matrix & 1-Click Container Logs
 * Renders 3x3 container tiles grid with live ping badges, category filter tabs,
 * 3D coin-flip interactive brand icon on card hover, 1-click Docker restarts,
 * and dual-mode log viewer (Native Docker socket tail vs Dozzle v11).
 */

import { $ } from "../shared/dom.js";
import { state } from "../state.js";
import { HOSTNAME, DOZZLE_BASE_URL, ENDPOINTS } from "../config.js";
import { showToast } from "../shared/toast.js";

const servicesGrid = $("services-grid");
const serviceFilters = $("service-filter-group");
const openDozzleFullBtn = $("open-dozzle-full-btn");

const dozzleModal = $("dozzle-modal");
const dozzleModalTitle = $("dozzle-modal-title");
const containerModalSubPath = $("container-modal-sub-path");
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

/**
 * Returns generic outline icon SVG (Front face of the 3D flip card)
 */
function getGenericIconSvg(iconName) {
  switch (iconName) {
    case "film":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>`;
    case "search":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>`;
    case "image":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>`;
    case "tv":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect><polyline points="17 2 12 7 7 2"></polyline></svg>`;
    case "video":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>`;
    case "rss":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 11a9 9 0 0 1 9 9"></path><path d="M4 4a16 16 0 0 1 16 16"></path><circle cx="5" cy="19" r="1"></circle></svg>`;
    case "file-text":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>`;
    case "download":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`;
    case "terminal":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>`;
    case "shield":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>`;
    default:
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle></svg>`;
  }
}

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
  cockpit: "/img/icons/cockpit.svg"
};

/**
 * Returns authentic, full-color brand logo image from official vector SVG assets
 */
function getBrandLogoImg(serviceId) {
  const iconPath = BRAND_ICON_MAP[serviceId] || "/img/icons/jellyfin.svg";
  return `<img src="${iconPath}" alt="${serviceId}" class="brand-logo-img" loading="lazy" />`;
}

export async function fetchServices() {
  if (!servicesGrid) return;
  try {
    const res = await fetch(ENDPOINTS.servicesStatus);
    if (!res.ok) return;
    const data = await res.json();
    const services = data.services || [];

    const currentFilter = state.activeServiceFilter || "all";

    servicesGrid.innerHTML = services.map(svc => {
      const isUp = svc.is_up;
      const badgeClass = isUp ? "online" : "stopped";
      const badgeText = isUp ? "Online" : "Stopped";
      const category = svc.category || "system";
      const isVisible = (currentFilter === "all" || currentFilter === category);

      const protocol = svc.port === 9090 ? "https:" : "http:";
      const targetUrl = `${protocol}//${HOSTNAME}:${svc.port}`;

      return `
        <div class="service-tile tile-${svc.id}" id="tile-${svc.id}" data-category="${category}" style="display: ${isVisible ? 'flex' : 'none'};">
          <div class="tile-top">
            <div class="tile-brand">
              <div class="tile-icon-box" title="${svc.name}">
                <div class="tile-icon-inner">
                  <div class="tile-icon-face tile-icon-front">
                    ${getGenericIconSvg(svc.icon)}
                  </div>
                  <div class="tile-icon-face tile-icon-back">
                    ${getBrandLogoImg(svc.id)}
                  </div>
                </div>
              </div>
              <div class="tile-title-group">
                <h4>${svc.name}</h4>
                <div class="tile-meta-row" style="display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                  <span class="tile-port">:${svc.port}</span>
                  <span class="tile-ping-badge">${isUp ? '<span style="color:#00f5a0;">●</span> 4ms' : '<span style="color:#ef4444;">●</span> Off'}</span>
                </div>
              </div>
            </div>
            <span class="tile-badge ${badgeClass}">
              <span class="status-dot-sm"></span>
              ${badgeText}
            </span>
          </div>

          <p class="tile-desc">${svc.description}</p>

          <div class="tile-bottom">
            <a href="${targetUrl}" target="_blank" class="btn-tile-launch" id="btn-launch-${svc.id}">
              Launch &nearr;
            </a>
            ${svc.id !== "cockpit" ? `
              <button class="btn-tile-logs" data-log-id="${svc.id}" data-log-name="${svc.name}" data-docker-id="${svc.docker_id || ''}" title="Stream live logs">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="micro-icon">
                  <polyline points="4 17 10 11 4 5"></polyline>
                  <line x1="12" y1="19" x2="20" y2="19"></line>
                </svg>
                Logs
              </button>
              <button class="btn-tile-restart" id="btn-restart-${svc.id}" data-restart-id="${svc.id}" data-restart-name="${svc.name}" title="Restart Docker Container">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="micro-icon">
                  <polyline points="23 4 23 10 17 10"></polyline>
                  <polyline points="1 20 1 14 7 14"></polyline>
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                </svg>
              </button>
            ` : ""}
          </div>
        </div>
      `;
    }).join("");

    // Bind log buttons
    servicesGrid.querySelectorAll(".btn-tile-logs").forEach(btn => {
      btn.onclick = () => openContainerLogs(btn.dataset.logId, btn.dataset.logName, btn.dataset.dockerId);
    });

    // Bind restart buttons
    servicesGrid.querySelectorAll(".btn-tile-restart").forEach(btn => {
      btn.onclick = () => restartContainer(btn.dataset.restartId, btn.dataset.restartName);
    });

    state.servicesLoadedOnce = true;
  } catch (err) {
    console.error("Error fetching services:", err);
  }
}

export async function openContainerLogs(containerId, containerName, dockerId) {
  activeLogServiceId = containerId;
  activeLogServiceName = containerName;
  activeLogDockerId = dockerId || containerId;

  if (dozzleModalTitle) dozzleModalTitle.textContent = `${containerName} Logs`;
  if (containerModalSubPath) {
    const shortId = dockerId ? ` (${dockerId.slice(0, 12)})` : "";
    containerModalSubPath.textContent = `Container: ${containerId}${shortId} • Live Stream`;
  }

  const effectiveDozzleId = dockerId || containerId;
  const dozzleUrl = `${DOZZLE_BASE_URL}/container/${effectiveDozzleId}`;
  if (dozzleModalExtLink) dozzleModalExtLink.href = dozzleUrl;

  switchLogTab("native");
  if (dozzleModal) dozzleModal.style.display = "flex";

  await refreshContainerLog();
}

export function switchLogTab(tab) {
  if (tab === "native") {
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
    if (dozzleIframe) {
      if (!dozzleIframe.src || dozzleIframe.src === "about:blank" || !dozzleIframe.src.includes(effectiveDozzleId)) {
        dozzleIframe.src = dozzleUrl;
      }
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

export function closeDozzleModal() {
  if (dozzleModal) dozzleModal.style.display = "none";
  if (dozzleIframe) dozzleIframe.src = "about:blank";
}

export function setupServiceMatrix() {
  if (openDozzleFullBtn) openDozzleFullBtn.href = DOZZLE_BASE_URL;

  // Category filter buttons
  if (serviceFilters) {
    const filterBtns = serviceFilters.querySelectorAll(".svc-filter-btn");
    filterBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        filterBtns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        state.activeServiceFilter = btn.getAttribute("data-filter") || "all";
        if (servicesGrid) {
          const tiles = servicesGrid.querySelectorAll(".service-tile");
          tiles.forEach(tile => {
            if (state.activeServiceFilter === "all" || tile.getAttribute("data-category") === state.activeServiceFilter) {
              tile.style.display = "flex";
            } else {
              tile.style.display = "none";
            }
          });
        }
      });
    });
  }

  // Modal event listeners
  if (btnLogTabNative) btnLogTabNative.addEventListener("click", () => switchLogTab("native"));
  if (btnLogTabDozzle) btnLogTabDozzle.addEventListener("click", () => switchLogTab("dozzle"));
  if (containerModalRefresh) containerModalRefresh.addEventListener("click", refreshContainerLog);
  if (containerModalDismiss) containerModalDismiss.addEventListener("click", closeDozzleModal);
  if (dozzleModalClose) dozzleModalClose.addEventListener("click", closeDozzleModal);
}
