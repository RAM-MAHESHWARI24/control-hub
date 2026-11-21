/**
 * Widget: Nightly Google Drive Sync (Noodle Gallery Cloud Backup)
 * Renders honest backup status, 4-stage sync stepper, library telemetry,
 * log viewer modal, and breakdown modal. Never renders invented fallback numbers.
 */

import { $, setCardSummary } from "../shared/dom.js";
import { state } from "../state.js";
import { ENDPOINTS } from "../config.js";
import { openModal, registerModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";

const backupStatusBadge = $("backup-status-badge");
const backupSchedule = $("backup-schedule");
const backupLastTime = $("backup-last-time");
const backupDbSize = $("backup-db-size");
const backupRemoteMirror = $("backup-remote-mirror");
const backupStatusMsg = $("backup-status-msg");
const backupModalSubPath = $("backup-modal-sub-path");
const libraryModalSubPath = $("library-modal-sub-path");

const btnSyncCard = $("btn-sync-card");
const cardSyncSpinner = $("card-sync-spinner");
const cardSyncIcon = $("card-sync-icon");
const cardSyncLabel = $("card-sync-label");

const btnViewBackupLog = $("btn-view-backup-log");
const backupLogModal = $("backup-log-modal");
const backupModalClose = $("backup-modal-close");
const backupModalDismiss = $("backup-modal-dismiss");
const backupModalRefresh = $("backup-modal-refresh");
const backupLogContent = $("backup-log-content");
const modalSyncDot = $("modal-sync-dot");
const modalSyncBanner = $("modal-sync-banner");
const syncStatusIndicator = $("sync-status-indicator");
const modalSyncBannerText = $("modal-sync-banner-text");
const syncLiveTag = $("sync-live-tag");
const btnModalTriggerSync = $("btn-modal-trigger-sync");
const modalSyncSpinner = $("modal-sync-spinner");
const modalSyncIcon = $("modal-sync-icon");
const modalSyncBtnText = $("modal-sync-btn-text");

// Summary Strip
const btnOpenLibraryDetails = $("btn-open-library-details");
const libValDisk = $("lib-val-disk");
const libValGdrive = $("lib-val-gdrive");
const libValAssets = $("lib-val-assets");
const libValFaces = $("lib-val-faces");

// Library Modal
const immichLibraryModal = $("immich-library-modal");
const immichModalClose = $("immich-modal-close");
const immichModalDismiss = $("immich-modal-dismiss");
const immichModalRefresh = $("immich-modal-refresh");
const modalLibDisk = $("modal-lib-disk");
const modalLibDiskLabel = $("modal-lib-disk-label");
const modalLibGdriveUsed = $("modal-lib-gdrive-used");
const modalLibGdriveFree = $("modal-lib-gdrive-free");
const modalLibGdrivePct = $("modal-lib-gdrive-pct");
const modalLibGdriveBar = $("modal-lib-gdrive-bar");
const modalLibDbDump = $("modal-lib-db-dump");
const modalLibTotalAssets = $("modal-lib-total-assets");
const modalLibPhotos = $("modal-lib-photos");
const modalLibVideos = $("modal-lib-videos");
const modalLibNamedPeople = $("modal-lib-named-people");
const modalLibUnhiddenPeople = $("modal-lib-unhidden-people");
const modalLibNamedAssets = $("modal-lib-named-assets");
const modalLibFaceInstances = $("modal-lib-face-instances");

const stepFace = $("step-face");
const stepDump = $("step-dump");
const stepRclone = $("step-rclone");
const stepVerify = $("step-verify");
const stepConn1 = $("step-conn-1");
const stepConn2 = $("step-conn-2");
const stepConn3 = $("step-conn-3");

function formatTb(gb) {
  if (typeof gb !== "number" || Number.isNaN(gb)) return "Unknown";
  return `${(gb / 1024).toFixed(2)} TB`;
}

function updateSyncUiState(syncing) {
  if (btnSyncCard) {
    btnSyncCard.disabled = syncing;
    btnSyncCard.classList.toggle("is-syncing", syncing);
    if (cardSyncSpinner) cardSyncSpinner.style.display = syncing ? "inline-block" : "none";
    if (cardSyncIcon) cardSyncIcon.style.display = syncing ? "none" : "inline-block";
    if (cardSyncLabel) cardSyncLabel.textContent = syncing ? "Syncing..." : "Sync Now";
  }

  if (btnModalTriggerSync) {
    btnModalTriggerSync.disabled = syncing;
    btnModalTriggerSync.classList.toggle("is-syncing", syncing);
    if (modalSyncSpinner) modalSyncSpinner.style.display = syncing ? "inline-block" : "none";
    if (modalSyncIcon) modalSyncIcon.style.display = syncing ? "none" : "inline-block";
    if (modalSyncBtnText) modalSyncBtnText.textContent = syncing ? "Syncing Noodle Gallery..." : "Sync Noodle Gallery Now";
    if (modalSyncBanner) modalSyncBanner.classList.toggle("is-syncing", syncing);
    if (syncLiveTag) syncLiveTag.style.display = syncing ? "inline-block" : "none";
    if (modalSyncBannerText) {
      modalSyncBannerText.textContent = syncing
        ? "Backup active: Exporting face XMP sidecars, dumping database, and syncing photos..."
        : "Ready to sync Noodle Gallery (Faces, DB Dump & Photos) to Google Drive.";
    }
  }
}

function renderBackupStepper(currentStage, status) {
  const steps = [
    { elem: stepFace, num: 1 },
    { elem: stepDump, num: 2 },
    { elem: stepRclone, num: 3 },
    { elem: stepVerify, num: 4 },
  ];
  const connectors = [stepConn1, stepConn2, stepConn3];
  const isSyncing = status === "syncing";
  const isError = status === "error";
  const isSynced = status === "synced";

  steps.forEach(({ elem, num }) => {
    if (!elem) return;
    const circle = elem.querySelector(".step-circle");

    if (isError && currentStage === num) {
      elem.className = "step-item step-error";
      if (circle) circle.textContent = "✕";
    } else if (isSyncing) {
      if (num < currentStage) {
        elem.className = "step-item step-done";
        if (circle) circle.textContent = "✓";
      } else if (num === currentStage) {
        elem.className = "step-item step-active";
        if (circle) circle.innerHTML = `<span class="step-spin" aria-hidden="true">⟳</span>`;
      } else {
        elem.className = "step-item";
        if (circle) circle.textContent = `${num}`;
      }
    } else if (isSynced && currentStage >= num) {
      elem.className = "step-item step-done";
      if (circle) circle.textContent = "✓";
    } else if (isError && num < currentStage) {
      elem.className = "step-item step-done";
      if (circle) circle.textContent = "✓";
    } else {
      elem.className = "step-item";
      if (circle) circle.textContent = `${num}`;
    }
  });

  connectors.forEach((conn, idx) => {
    if (!conn) return;
    const precedingStepNum = idx + 1;
    if (isSynced && currentStage >= 4) {
      conn.className = "step-connector connector-done";
    } else if ((isSyncing || isError) && precedingStepNum < currentStage) {
      conn.className = "step-connector connector-done";
    } else {
      conn.className = "step-connector";
    }
  });
}

export async function fetchBackupStatus() {
  try {
    const res = await fetch(ENDPOINTS.backupStatus);
    if (!res.ok) return;
    const data = await res.json();

    const status = data.status || "unknown";
    const isSyncing = Boolean(data.is_syncing || status === "syncing");
    const isError = status === "error";
    const isSynced = status === "synced";
    const stage = Number(data.current_stage || 0);

    updateSyncUiState(isSyncing);
    renderBackupStepper(stage, isSyncing ? "syncing" : status);

    if (backupStatusBadge) {
      if (isSyncing) {
        backupStatusBadge.className = "badge-status-syncing";
        backupStatusBadge.textContent = "Syncing";
      } else if (isError) {
        backupStatusBadge.className = "badge-status-error";
        backupStatusBadge.textContent = "Attention Needed";
      } else if (isSynced) {
        backupStatusBadge.className = "badge-status-synced";
        backupStatusBadge.textContent = "Verified";
      } else {
        backupStatusBadge.className = "badge-status-unknown";
        backupStatusBadge.textContent = "Not Verified";
      }
    }

    if (backupSchedule && data.schedule) backupSchedule.textContent = data.schedule;
    if (backupLastTime) backupLastTime.textContent = data.last_sync || "Never";
    if (backupDbSize) backupDbSize.textContent = data.db_size || "Unknown";
    if (backupRemoteMirror) backupRemoteMirror.textContent = data.gdrive_remote || "Not configured";
    if (backupStatusMsg) backupStatusMsg.textContent = data.message || data.reason || "No backup run yet";

    if (backupModalSubPath) {
      const logPart = data.log_file || "Unknown";
      const remotePart = data.gdrive_remote || "Not configured";
      backupModalSubPath.textContent = `Log: ${logPart} • Remote: ${remotePart}`;
    }
    if (libraryModalSubPath) {
      const memDir = data.memories_dir || "Unknown";
      const remotePart = data.gdrive_remote || "Not configured";
      libraryModalSubPath.textContent = `Local: ${memDir} • Remote: ${remotePart}`;
    }

    // Summary Strip (honest values only)
    if (libValDisk) {
      libValDisk.textContent = data.disk_size || "Unknown";
      libValDisk.title = data.disk_reason || "";
    }
    if (libValGdrive) {
      if (typeof data.gdrive_used_gb === "number" && typeof data.gdrive_total_gb === "number") {
        libValGdrive.innerHTML = `${data.gdrive_used_gb} GB <span class="text-dim">/ ${formatTb(data.gdrive_total_gb)}</span>`;
        libValGdrive.title = "";
      } else {
        libValGdrive.textContent = "Unknown";
        libValGdrive.title = data.gdrive_reason || "Drive quota unavailable";
      }
    }
    if (libValAssets) {
      if (typeof data.total_assets === "number") {
        const photosTxt = typeof data.photos_count === "number" ? ` (${(data.photos_count / 1000).toFixed(1)}k photos)` : "";
        libValAssets.innerHTML = `${Number(data.total_assets).toLocaleString()}<span class="text-dim">${photosTxt}</span>`;
        libValAssets.title = "";
      } else {
        libValAssets.textContent = "Unknown";
        libValAssets.title = data.assets_reason || "Database unavailable";
      }
    }
    if (libValFaces) {
      if (typeof data.assets_with_named_faces === "number") {
        const peopleTxt = typeof data.named_people === "number" ? ` (${data.named_people} people)` : "";
        libValFaces.innerHTML = `${Number(data.assets_with_named_faces).toLocaleString()}<span class="text-dim">${peopleTxt}</span>`;
        libValFaces.title = "";
      } else {
        libValFaces.textContent = "Unknown";
        libValFaces.title = data.assets_reason || "Database unavailable";
      }
    }

    setCardSummary(
      "backup-section",
      data.last_sync
        ? `Backup: ${status} · ${data.last_sync}${data.db_size ? `, ${data.db_size}` : ""}`
        : `Backup: ${data.reason || "No run yet"}`
    );

    if (modalSyncDot) {
      modalSyncDot.className = isSyncing ? "modal-dot dot-syncing" : (isError ? "modal-dot dot-error" : (isSynced ? "modal-dot dot-live" : "modal-dot"));
    }
    if (syncStatusIndicator) {
      syncStatusIndicator.className = isSyncing ? "sync-status-indicator sync-running" : "sync-status-indicator sync-idle";
    }

    const nowTs = Date.now();
    if (state.userInitiatedSync && !isSyncing && !isError && isSynced) {
      if (nowTs - state.lastSyncCompletionToastTime > 300000) {
        state.lastSyncCompletionToastTime = nowTs;
        state.userInitiatedSync = false;
        showToast(
          "Cloud Sync Complete",
          `Noodle Gallery synced (${data.last_sync || "just now"}).`,
          "☁️"
        );
      }
    }
  } catch (err) {
    console.error("Error fetching backup status:", err);
  }
}

export async function triggerBackupSync() {
  updateSyncUiState(true);
  state.userInitiatedSync = true;

  try {
    const res = await fetch(ENDPOINTS.backupSync, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Cloud Sync Started", "Mirroring Noodle Gallery photos and PostgreSQL dump...", "☁️");
      await fetchBackupStatus();
      openBackupLogModal(btnViewBackupLog);
    } else {
      showToast("Sync Busy", data.message || "Backup is already executing...", "⚠️");
      await fetchBackupStatus();
    }
  } catch (_) {
    showToast("Error", "Could not trigger backup", "❌");
    updateSyncUiState(false);
  }
}

export async function openBackupLogModal(triggerEl = null) {
  if (!backupLogModal) return;
  openModal(backupLogModal, triggerEl);
  await refreshBackupLog();
}

export async function refreshBackupLog() {
  if (!backupLogContent) return;
  backupLogContent.textContent = "Fetching backup log lines...";
  try {
    const res = await fetch(ENDPOINTS.backupLog);
    const data = await res.json();
    if (backupModalSubPath && data.log_file) {
      backupModalSubPath.textContent = `Log: ${data.log_file}`;
    }
    backupLogContent.textContent = data.log || "No log content returned.";
    backupLogContent.scrollTop = backupLogContent.scrollHeight;
  } catch (_) {
    backupLogContent.textContent = "Error loading backup log file.";
  }
}

export async function openImmichLibraryModal(triggerEl = null) {
  if (!immichLibraryModal) return;
  openModal(immichLibraryModal, triggerEl);
  await fetchLibraryStats(false);
}

export async function fetchLibraryStats(force = false) {
  try {
    const url = force ? `${ENDPOINTS.libraryStats}?refresh=true` : ENDPOINTS.libraryStats;
    const res = await fetch(url);
    const data = await res.json();

    const gdrive = data.gdrive || null;
    const assets = data.assets || null;

    if (modalLibDiskLabel && data.memories_dir) {
      modalLibDiskLabel.textContent = `Local Folder (${data.memories_dir})`;
    }
    if (modalLibDisk) modalLibDisk.textContent = data.disk_size || (data.disk_reason || "Unknown");

    if (gdrive && typeof gdrive.used_gb === "number") {
      if (modalLibGdriveUsed) modalLibGdriveUsed.textContent = `${gdrive.used_gb} GB`;
      if (modalLibGdriveFree) modalLibGdriveFree.textContent = formatTb(gdrive.free_gb);
      if (modalLibGdrivePct) modalLibGdrivePct.textContent = `${gdrive.used_percent}% of ${formatTb(gdrive.total_gb)}`;
      if (modalLibGdriveBar) modalLibGdriveBar.style.width = `${Math.min(100, gdrive.used_percent || 0)}%`;
    } else {
      if (modalLibGdriveUsed) modalLibGdriveUsed.textContent = "Unknown";
      if (modalLibGdriveFree) modalLibGdriveFree.textContent = "Unknown";
      if (modalLibGdrivePct) modalLibGdrivePct.textContent = data.gdrive_reason || "Drive quota unavailable";
      if (modalLibGdriveBar) modalLibGdriveBar.style.width = "0%";
    }

    if (modalLibDbDump) {
      modalLibDbDump.textContent = data.db_dump_size
        ? `${data.db_dump_size} (pg_dumpall)`
        : (data.db_dump_reason || "No dump yet");
    }

    if (assets && typeof assets.total_assets === "number") {
      const total = assets.total_assets;
      const photos = assets.photos_count || 0;
      const videos = assets.videos_count || 0;
      const photoPct = total > 0 ? ((photos / total) * 100).toFixed(1) : "0.0";
      const videoPct = total > 0 ? ((videos / total) * 100).toFixed(1) : "0.0";

      if (modalLibTotalAssets) modalLibTotalAssets.textContent = Number(total).toLocaleString();
      if (modalLibPhotos) modalLibPhotos.textContent = `${Number(photos).toLocaleString()} (${photoPct}%)`;
      if (modalLibVideos) modalLibVideos.textContent = `${Number(videos).toLocaleString()} (${videoPct}%)`;

      if (modalLibNamedPeople) modalLibNamedPeople.textContent = `${assets.named_people ?? 0} people`;
      if (modalLibUnhiddenPeople) modalLibUnhiddenPeople.textContent = `${Number(assets.unhidden_people ?? 0).toLocaleString()} recognized`;
      if (modalLibNamedAssets) modalLibNamedAssets.textContent = `${Number(assets.assets_with_named_faces ?? 0).toLocaleString()} assets`;
      if (modalLibFaceInstances) modalLibFaceInstances.textContent = `${Number(assets.total_face_instances ?? 0).toLocaleString()} detections`;
    } else {
      const reason = data.assets_reason || "Database unavailable";
      [modalLibTotalAssets, modalLibPhotos, modalLibVideos, modalLibNamedPeople, modalLibUnhiddenPeople, modalLibNamedAssets, modalLibFaceInstances]
        .forEach((el) => {
          if (el) {
            el.textContent = "Unknown";
            el.title = reason;
          }
        });
    }
  } catch (err) {
    console.error("Error loading library stats:", err);
  }
}

export function setupBackupSync() {
  registerModal(backupLogModal, { closeButtons: [backupModalClose, backupModalDismiss] });
  registerModal(immichLibraryModal, { closeButtons: [immichModalClose, immichModalDismiss] });

  if (btnSyncCard) btnSyncCard.addEventListener("click", triggerBackupSync);
  if (btnModalTriggerSync) btnModalTriggerSync.addEventListener("click", triggerBackupSync);
  if (btnViewBackupLog) btnViewBackupLog.addEventListener("click", () => openBackupLogModal(btnViewBackupLog));
  if (backupModalRefresh) backupModalRefresh.addEventListener("click", refreshBackupLog);

  if (btnOpenLibraryDetails) btnOpenLibraryDetails.addEventListener("click", () => openImmichLibraryModal(btnOpenLibraryDetails));
  if (immichModalRefresh) immichModalRefresh.addEventListener("click", () => fetchLibraryStats(true));
}
