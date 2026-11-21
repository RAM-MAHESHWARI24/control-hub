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
const backupSection = $("backup-section");
const backupHealth = $("backup-health");
const backupHealthTitle = $("backup-health-title");
const backupHealthDetail = $("backup-health-detail");
const backupNextRun = $("backup-next-run");
const backupPreflight = $("backup-preflight");
const backupHistory = $("backup-history");
const backupHistoryCount = $("backup-history-count");
const backupRetention = $("backup-retention");
const mediaBackup = $("media-backup");
const mediaBackupBadge = $("media-backup-badge");
const mediaBackupLine = $("media-backup-line");
const mediaBackupMsg = $("media-backup-msg");
const btnMediaBackupRun = $("btn-media-backup-run");
const restoreTest = $("restore-test");
const restoreTestText = $("restore-test-text");
const btnRestoreTestRun = $("btn-restore-test-run");
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
    if (cardSyncLabel) cardSyncLabel.textContent = syncing ? "Backing up..." : "Run backup now";
  }

  if (btnModalTriggerSync) {
    btnModalTriggerSync.disabled = syncing;
    btnModalTriggerSync.classList.toggle("is-syncing", syncing);
    if (modalSyncSpinner) modalSyncSpinner.style.display = syncing ? "inline-block" : "none";
    if (modalSyncIcon) modalSyncIcon.style.display = syncing ? "none" : "inline-block";
    if (modalSyncBtnText) modalSyncBtnText.textContent = syncing ? "Backing up..." : "Run backup now";
    if (modalSyncBanner) modalSyncBanner.classList.toggle("is-syncing", syncing);
    if (syncLiveTag) syncLiveTag.style.display = syncing ? "inline-block" : "none";
    if (modalSyncBannerText) {
      modalSyncBannerText.textContent = syncing
        ? "Backup running: the log below refreshes every few seconds."
        : "Runs the same backup as the nightly job: pre-flight, face tags, database dump, photo mirror.";
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

const BADGES = {
  syncing: ["badge-status-syncing", "Running"],
  synced: ["badge-status-synced", "Verified"],
  error: ["badge-status-error", "Failed"],
  stale: ["badge-status-error", "Stale"],
  interrupted: ["badge-status-error", "Interrupted"],
  unknown: ["badge-status-unknown", "Not run yet"],
};

const OUTCOME_TEXT = { synced: "Succeeded", error: "Failed" };

function formatDuration(seconds) {
  if (typeof seconds !== "number" || seconds < 0) return null;
  if (seconds < 60) return `${seconds} s`;
  const m = Math.floor(seconds / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function renderHealth(health, data) {
  const stateName = health ? health.state : (data.status || "unknown");
  if (backupHealth) backupHealth.dataset.state = stateName;
  if (backupSection) backupSection.classList.toggle("is-alert", Boolean(health && health.is_red));

  if (backupHealthTitle) {
    let title;
    if (!health) title = data.reason || data.message || "No backup run recorded yet";
    else if (health.state === "syncing") title = "Backup running";
    else if (health.state === "synced") title = `Last good backup ${health.age || ""}`.trim();
    else if (health.state === "unknown") title = "No backup run yet";
    else title = health.message;
    backupHealthTitle.textContent = title;
  }
  if (backupHealthDetail) {
    let detail = "";
    if (health && !["synced", "unknown", "syncing"].includes(health.state)) {
      detail = health.last_good ? `Last good backup ${health.age}.` : "No good backup recorded yet.";
    }
    backupHealthDetail.textContent = detail;
  }
  if (backupNextRun) backupNextRun.textContent = (health && health.next_run) || data.schedule || "Not scheduled";

  // Pre-flight: list the checks only when one of them failed.
  if (backupPreflight) {
    backupPreflight.replaceChildren();
    const checks = (health && health.preflight && health.preflight.checks) || [];
    const show = checks.some((c) => !c.ok) && health.state !== "syncing";
    if (show) {
      checks.forEach((c) => {
        const li = el("li", c.ok ? "preflight-ok" : "preflight-fail");
        li.append(el("span", "preflight-mark", c.ok ? "OK" : "Failed"), el("span", "preflight-name", c.name), el("span", "preflight-detail", c.detail));
        backupPreflight.append(li);
      });
    }
    backupPreflight.hidden = !show;
  }

  if (backupHistory) {
    backupHistory.replaceChildren();
    const runs = (health && health.history) || [];
    runs.forEach((run) => {
      const ok = run.outcome === "synced";
      const li = el("li", `backup-run ${ok ? "run-ok" : "run-fail"}`);
      const top = el("div", "backup-run-top");
      top.append(el("span", "backup-run-outcome", OUTCOME_TEXT[run.outcome] || run.outcome || "Unknown"), el("span", "backup-run-when font-mono", run.when || ""));
      const facts = [];
      if (run.dump_size) facts.push(`dump ${run.dump_size}`);
      if (typeof run.files === "number") facts.push(`${run.files} files${run.moved ? ` (${run.moved})` : ""} uploaded`);
      const dur = formatDuration(run.duration_s);
      if (dur) facts.push(dur);
      li.append(top);
      if (facts.length) li.append(el("div", "backup-run-facts", facts.join(" · ")));
      if (!ok && run.message) li.append(el("div", "backup-run-msg", run.message));
      backupHistory.append(li);
    });
    if (!runs.length) backupHistory.append(el("li", "backup-run", "No runs recorded yet."));
    if (backupHistoryCount) backupHistoryCount.textContent = runs.length ? `(${runs.length})` : "";
  }

  if (backupRetention) {
    const ret = health && health.retention;
    if (ret && typeof ret.kept === "number") {
      const next = ret.next_delete || [];
      backupRetention.textContent = `Drive keeps ${ret.kept} database dumps (the newest nightly ones plus the first of each month). `
        + `The last run deleted ${ret.deleted_last_run}; the next run deletes ${next.length ? next.join(", ") : "none"}.`;
    } else {
      backupRetention.textContent = "Retention has not run yet.";
    }
  }
}

function renderRestoreTest(info, last) {
  if (!restoreTest) return;
  const installed = Boolean(info && info.installed);
  restoreTest.hidden = !installed && !last;
  if (restoreTest.hidden) return;
  restoreTest.dataset.state = info && info.running ? "running" : (last ? (last.ok ? "ok" : "fail") : "none");
  let text;
  if (info && info.running) {
    text = "running now (download, restore into a throwaway database, count)...";
  } else if (last) {
    text = last.ok
      ? `passed ${last.when || ""}: ${Number(last.restored).toLocaleString()} photos and videos restored from ${last.dump_file}`
      : `FAILED ${last.when || ""}: ${last.message}`;
  } else {
    text = "not run yet";
  }
  if (info && info.next && !(info && info.running)) text += ` · next ${info.next}`;
  if (restoreTestText) restoreTestText.textContent = text;
  if (btnRestoreTestRun) {
    btnRestoreTestRun.hidden = !installed;
    btnRestoreTestRun.disabled = Boolean(info && info.running);
  }
}

async function runRestoreTest() {
  if (btnRestoreTestRun) btnRestoreTestRun.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.backupRestoreTest, { method: "POST" });
    const data = await res.json();
    showToast(data.success ? "Restore test started" : "Not started", data.message || "", data.success ? "🧪" : "⚠️");
  } catch (_) {
    showToast("Not started", "The Control Hub did not answer.", "❌");
  } finally {
    setTimeout(fetchBackupStatus, 2000);
  }
}

function renderMediaBackup(media) {
  if (!mediaBackup) return;
  mediaBackup.hidden = !media;
  if (!media) return;
  const [cls, label] = BADGES[media.state] || BADGES.unknown;
  if (mediaBackupBadge) {
    mediaBackupBadge.className = cls;
    mediaBackupBadge.textContent = label;
  }
  if (mediaBackupLine) {
    const parts = [];
    parts.push(media.last_good ? `Last good: ${media.last_good} (${media.age})` : "No good run yet");
    if (media.archive_size) parts.push(media.archive_size);
    if (media.next_run) parts.push(`next ${media.next_run}`);
    mediaBackupLine.textContent = parts.join(" · ");
  }
  if (mediaBackupMsg) {
    const show = media.is_red || media.state === "syncing";
    mediaBackupMsg.hidden = !show;
    mediaBackupMsg.textContent = show ? (media.state === "syncing" ? "Backing up the media apps' settings..." : media.message) : "";
  }
  if (btnMediaBackupRun) {
    btnMediaBackupRun.hidden = !media.can_run;
    btnMediaBackupRun.disabled = media.state === "syncing";
  }
  if (backupSection && media.is_red) backupSection.classList.add("is-alert");
}

async function runMediaBackup() {
  if (btnMediaBackupRun) btnMediaBackupRun.disabled = true;
  try {
    const res = await fetch(ENDPOINTS.backupMediaRun, { method: "POST" });
    const data = await res.json();
    showToast(data.success ? "Media backup started" : "Not started", data.message || "", data.success ? "☁️" : "⚠️");
  } catch (_) {
    showToast("Not started", "The Control Hub did not answer.", "❌");
  } finally {
    setTimeout(fetchBackupStatus, 2000);
  }
}

let logPollTimer = null;

function syncLogPolling(isSyncing) {
  const modalOpen = Boolean(backupLogModal) && backupLogModal.style.display !== "none";
  if (isSyncing && modalOpen && !logPollTimer) {
    logPollTimer = setInterval(() => {
      if (document.hidden) return;
      if (!backupLogModal || backupLogModal.style.display === "none") {
        clearInterval(logPollTimer);
        logPollTimer = null;
        return;
      }
      refreshBackupLog(true);
      fetchBackupStatus();
    }, 3000);
  } else if ((!isSyncing || !modalOpen) && logPollTimer) {
    clearInterval(logPollTimer);
    logPollTimer = null;
    if (modalOpen) refreshBackupLog(true);
  }
}

export async function fetchBackupStatus() {
  try {
    const res = await fetch(ENDPOINTS.backupStatus);
    if (!res.ok) return;
    const data = await res.json();

    const health = data.health || null;
    const status = health ? health.state : (data.status || "unknown");
    const isSyncing = Boolean(data.is_syncing || status === "syncing");
    const isError = ["error", "stale", "interrupted"].includes(status);
    const isSynced = status === "synced";
    const stage = Number(data.current_stage || 0);

    updateSyncUiState(isSyncing);
    renderBackupStepper(stage, isSyncing ? "syncing" : (status === "error" || status === "interrupted" ? "error" : status));
    renderHealth(health, data);
    renderMediaBackup(data.media || null);
    renderRestoreTest(data.restore || null, (health && health.restore_test) || null);
    syncLogPolling(isSyncing);

    if (backupStatusBadge) {
      const [cls, label] = BADGES[isSyncing ? "syncing" : status] || BADGES.unknown;
      backupStatusBadge.className = cls;
      backupStatusBadge.textContent = label;
    }

    if (backupLastTime) backupLastTime.textContent = (health && health.last_good) || "None yet";
    if (backupDbSize) backupDbSize.textContent = data.db_size || "Unknown";
    if (backupRemoteMirror) backupRemoteMirror.textContent = data.gdrive_remote || "Not configured";
    if (backupStatusMsg) {
      // The health box already states the outcome; this line only narrates a run in progress.
      backupStatusMsg.textContent = isSyncing ? (data.message || "Backup running...") : "";
      backupStatusMsg.hidden = !isSyncing;
    }

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
      health && health.last_good
        ? `Backup: ${(BADGES[status] || BADGES.unknown)[1].toLowerCase()} · last good ${health.age}${data.db_size ? `, ${data.db_size}` : ""}`
        : `Backup: ${(health && health.message) || data.reason || "No run yet"}`
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
          "Backup finished",
          `Photo backup verified (${(health && health.last_good) || data.last_sync || "just now"}).`,
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
      showToast("Backup started", "Pre-flight checks first, then face tags, database dump and photo mirror.", "☁️");
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
  await fetchBackupStatus();
}

export async function refreshBackupLog(quiet = false) {
  if (!backupLogContent) return;
  const atBottom = backupLogContent.scrollHeight - backupLogContent.scrollTop - backupLogContent.clientHeight < 40;
  if (!quiet) backupLogContent.textContent = "Fetching backup log lines...";
  try {
    const res = await fetch(ENDPOINTS.backupLog);
    const data = await res.json();
    if (backupModalSubPath && data.log_file) {
      backupModalSubPath.textContent = `Log: ${data.log_file}`;
    }
    backupLogContent.textContent = data.log || "No log content returned.";
    if (!quiet || atBottom) backupLogContent.scrollTop = backupLogContent.scrollHeight;
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
  if (btnMediaBackupRun) btnMediaBackupRun.addEventListener("click", runMediaBackup);
  if (btnRestoreTestRun) btnRestoreTestRun.addEventListener("click", runRestoreTest);
  if (btnModalTriggerSync) btnModalTriggerSync.addEventListener("click", triggerBackupSync);
  if (btnViewBackupLog) btnViewBackupLog.addEventListener("click", () => openBackupLogModal(btnViewBackupLog));
  if (backupModalRefresh) backupModalRefresh.addEventListener("click", refreshBackupLog);

  if (btnOpenLibraryDetails) btnOpenLibraryDetails.addEventListener("click", () => openImmichLibraryModal(btnOpenLibraryDetails));
  if (immichModalRefresh) immichModalRefresh.addEventListener("click", () => fetchLibraryStats(true));
}
