/**
 * Widget: Troubleshoot Runner & Contextual How-To Guides (Phase 4F)
 * Runs live `/api/troubleshoot` health checks with plain-word explanations and
 * opens short step-by-step How-To guides linked directly from dashboard cards.
 */

import { $, copyTextToClipboard } from "../shared/dom.js";
import { ENDPOINTS } from "../config.js";
import { escapeHtml } from "../shared/formatters.js";
import { closeModal, openModal } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";

const HOWTO_GUIDES = {
  restore_backup: {
    title: "How to Restore a Backup",
    subtitle: "Recover Immich photos, database dumps, and media settings from off-site storage.",
    actionView: "backups",
    actionLabel: "Open Backups View",
    steps: [
      {
        title: "Verify your remote backup archive first",
        detail: "In Backups, click 'Run Restore Test' (or pick a cloud remote) to confirm decryption keys and archive readability.",
      },
      {
        title: "Stop Immich containers before replacing the database",
        detail: "Go to Apps -> Managed Containers and stop immich_server and immich_machine_learning so writes pause cleanly.",
      },
      {
        title: "Pull the latest DB dump and memories directory",
        detail: "Use `rclone copy <remote>:Immich_Backup/database /tmp/restore-db` over SSH, restore PostgreSQL (`psql`), then sync missing originals back to your Memories folder.",
        cmd: "rclone lsjson gdrive:Immich_Backup/database --max-depth 1",
      },
      {
        title: "Start Immich and check face sidecars",
        detail: "Restart the Immich containers from Apps and confirm recent photos and library stats match in Backups -> Photo Library.",
      },
    ],
  },
  add_tv: {
    title: "How to Add an Android TV",
    subtitle: "Pair a new Google TV / Mi Box / Shield for automated APK updates.",
    actionView: "tvs",
    actionLabel: "Open TVs View",
    steps: [
      {
        title: "Enable Developer Options & Network Debugging on the TV",
        detail: "Open TV Settings -> System -> About -> click Android TV OS build 7 times -> go to Developer Options and turn on Network / ADB debugging.",
      },
      {
        title: "Scan your LAN or enter the TV's static IP",
        detail: "Open TVs -> Add a TV -> click 'Scan LAN' to discover port 5555 devices or enter the TV's IP address directly.",
      },
      {
        title: "Accept the 'Always allow from this computer' prompt on the TV screen",
        detail: "When Control Hub connects for the first time, look at your TV screen, tick 'Always allow', and select Allow.",
      },
      {
        title: "Save with a friendly room nickname",
        detail: "Pick the detected model/brand, give it a nickname (for example Living Room TV), and save to include it in automated syncs.",
      },
    ],
  },
  add_indexer: {
    title: "How to Add a Search Indexer",
    subtitle: "Link Prowlarr indexers so Radarr and Sonarr can find releases automatically.",
    actionView: "apps",
    actionLabel: "Open Media Indexers",
    steps: [
      {
        title: "Open Prowlarr Indexer Health in Apps",
        detail: "Go to Apps -> Media Pipeline & Indexer Health and check whether any configured indexers show warnings or errors.",
      },
      {
        title: "Click 'Pick Indexers' or 'Test Indexers'",
        detail: "Use Prowlarr's built-in indexer wizard from Control Hub to add an indexer without editing raw XML files.",
      },
      {
        title: "Use FlareSolverr only for Cloudflare-protected sites",
        detail: "If an indexer returns anti-bot errors, check that the `flaresolverr` container is running in Apps and linked in Prowlarr.",
      },
      {
        title: "Confirm Radarr & Sonarr Prowlarr sync",
        detail: "After adding an indexer, run 'Test Indexers' in Control Hub to confirm Prowlarr synced cleanly to Radarr and Sonarr.",
      },
    ],
  },
  free_space: {
    title: "How to Free Up Disk Space Safely",
    subtitle: "Reclaim space without breaking active hardlinks or deleting backed-up media.",
    actionView: "system",
    actionLabel: "Open Storage Cleanup",
    steps: [
      {
        title: "Inspect real folder usage first",
        detail: "Check System -> Storage Breakdown, Cleanup & Disk Health to see whether Movies, TV Shows, Torrents, or Photos grew fastest.",
      },
      {
        title: "Run built-in Safe Cleanup candidates",
        detail: "Use the Safe Storage Cleanup table to purge rotated qBittorrent logs or remove torrents that already finished seeding (hardlinked copies in /data/media stay safe).",
      },
      {
        title: "Avoid duplicate copies across mounts",
        detail: "Run Troubleshoot to confirm Torrents and Media share the same filesystem device (`/data`), ensuring zero-copy hardlinks.",
      },
      {
        title: "Remove watched large 4K remuxes if needed",
        detail: "Delete unneeded movies/shows directly inside Jellyfin or Radarr/Sonarr rather than raw `rm` so tracking metadata stays clean.",
      },
    ],
  },
  tailscale_https: {
    title: "Remote HTTPS Access via Tailscale",
    subtitle: "Reach Control Hub securely from your phone over encrypted HTTPS.",
    actionView: "system",
    actionLabel: "Open Network Card",
    steps: [
      {
        title: "Enable MagicDNS & HTTPS Certificates in Tailscale Admin",
        detail: "In your Tailscale Admin Console -> DNS page, switch on MagicDNS and click Enable HTTPS under HTTPS Certificates.",
      },
      {
        title: "Publish Control Hub with one Tailscale Serve command",
        detail: "Run `sudo tailscale serve --bg 7575` on your server via SSH. Control Hub automatically keeps cookies Secure behind Tailscale HTTPS.",
        cmd: "sudo tailscale serve --bg 7575",
      },
      {
        title: "Sign in on your phone's Tailscale app",
        detail: "Install Tailscale on iOS or Android, sign in to the same tailnet, and open the `https://<node>.<tailnet>.ts.net` URL shown in your Network card.",
      },
    ],
  },
};

function navigateToView(viewName) {
  if (!viewName) return;
  const link = document.querySelector(`#hub-nav [data-view-link="${viewName}"]`);
  if (link) {
    link.click();
  } else {
    window.location.hash = `#/${viewName}`;
  }
}

export function openHowToGuide(guideKey, triggerEl = null) {
  const modal = $("howto-guide-modal");
  const titleEl = $("howto-modal-title");
  const subEl = $("howto-modal-subtitle");
  const bodyEl = $("howto-modal-body");
  const jumpBtn = $("btn-howto-jump");
  if (!modal || !bodyEl) return;

  const guide = HOWTO_GUIDES[guideKey] || HOWTO_GUIDES.restore_backup;
  if (titleEl) titleEl.textContent = guide.title;
  if (subEl) subEl.textContent = guide.subtitle;

  const navBtns = modal.querySelectorAll("[data-howto-select]");
  navBtns.forEach((btn) => {
    const active = btn.getAttribute("data-howto-select") === guideKey;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  });

  if (jumpBtn) {
    jumpBtn.textContent = guide.actionLabel || "Open View";
    jumpBtn.dataset.jumpView = guide.actionView || "overview";
  }

  bodyEl.innerHTML = `
    <ol class="howto-steps-list">
      ${guide.steps.map((step, idx) => `
        <li class="howto-step-card">
          <div class="howto-step-head">
            <span class="howto-step-num font-mono">${idx + 1}</span>
            <strong>${escapeHtml(step.title)}</strong>
          </div>
          <p class="howto-step-detail">${escapeHtml(step.detail)}</p>
          ${step.cmd ? `
            <div class="howto-cmd-row">
              <code class="font-mono">${escapeHtml(step.cmd)}</code>
              <button type="button" class="btn-secondary btn-howto-copy-cmd" data-cmd="${escapeHtml(step.cmd)}">Copy</button>
            </div>
          ` : ""}
        </li>
      `).join("")}
    </ol>
  `;

  bodyEl.querySelectorAll(".btn-howto-copy-cmd").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const ok = await copyTextToClipboard(btn.getAttribute("data-cmd") || "");
      showToast(
        ok ? "Command Copied" : "Copy Blocked",
        ok ? "Paste this command into SSH on your server." : "Clipboard blocked on this origin.",
        ok ? "success" : "warning"
      );
    });
  });

  openModal(modal, triggerEl);
}

function renderTroubleshootReport(data) {
  const summaryBox = $("troubleshoot-summary-pills");
  const listEl = $("troubleshoot-checks-list");
  if (!listEl) return;

  const okN = Number(data.ok_count || 0);
  const warnN = Number(data.warn_count || 0);
  const failN = Number(data.fail_count || 0);

  if (summaryBox) {
    summaryBox.innerHTML = `
      <span class="badge badge-ok font-mono">${okN} Healthy</span>
      <span class="badge ${warnN ? "badge-warn" : "badge-neutral"} font-mono">${warnN} Warning${warnN === 1 ? "" : "s"}</span>
      <span class="badge ${failN ? "badge-danger" : "badge-neutral"} font-mono">${failN} Issue${failN === 1 ? "" : "s"}</span>
    `;
  }

  const checks = Array.isArray(data.checks) ? data.checks : [];
  if (!checks.length) {
    listEl.innerHTML = '<div class="empty-state">No diagnostic checks returned.</div>';
    return;
  }

  listEl.innerHTML = checks.map((chk) => {
    let badgeCls = "badge-ok";
    let statusTxt = "Healthy";
    if (chk.status === "fail") {
      badgeCls = "badge-danger";
      statusTxt = "Action Needed";
    } else if (chk.status === "warn") {
      badgeCls = "badge-warn";
      statusTxt = "Warning";
    }
    const steps = Array.isArray(chk.fix_steps) ? chk.fix_steps : [];
    const stepsHtml = steps.length
      ? `<ul class="troubleshoot-fix-list">${steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`
      : "";
    const jumpHtml = chk.action_view
      ? `<button type="button" class="btn-secondary btn-troubleshoot-jump" data-view="${escapeHtml(chk.action_view)}">${escapeHtml(chk.action_label || "Open View")}</button>`
      : "";

    return `
      <article class="panel troubleshoot-item troubleshoot-${escapeHtml(chk.status || "ok")}">
        <div class="troubleshoot-item-head">
          <div>
            <span class="badge badge-neutral">${escapeHtml(chk.category || "Host")}</span>
            <strong>${escapeHtml(chk.title || chk.id)}</strong>
          </div>
          <span class="badge ${badgeCls}">${statusTxt}</span>
        </div>
        <p class="troubleshoot-summary-line">${escapeHtml(chk.summary || "")}</p>
        <p class="troubleshoot-explain">${escapeHtml(chk.explanation || "")}</p>
        ${stepsHtml}
        ${jumpHtml ? `<div class="troubleshoot-item-actions">${jumpHtml}</div>` : ""}
      </article>
    `;
  }).join("");

  listEl.querySelectorAll(".btn-troubleshoot-jump").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetView = btn.getAttribute("data-view");
      closeModal($("troubleshoot-modal"));
      navigateToView(targetView);
    });
  });
}

async function runTroubleshootDiagnostics() {
  const listEl = $("troubleshoot-checks-list");
  const rerunBtn = $("btn-troubleshoot-rerun");
  if (listEl) listEl.innerHTML = '<div class="empty-state">Running live health checks across storage, containers, indexers, backups, network, and sleep guard&hellip;</div>';
  if (rerunBtn) rerunBtn.disabled = true;

  try {
    const res = await fetch(ENDPOINTS.troubleshoot);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderTroubleshootReport(data);
  } catch (err) {
    if (listEl) {
      listEl.innerHTML = `<div class="inline-callout is-danger">Could not complete troubleshoot scan: ${escapeHtml(err.message)}</div>`;
    }
  } finally {
    if (rerunBtn) rerunBtn.disabled = false;
  }
}

export function openTroubleshootModal(triggerEl = null) {
  const modal = $("troubleshoot-modal");
  if (!modal) return;
  openModal(modal, triggerEl);
  runTroubleshootDiagnostics();
}

export function setupHelpDrawer() {
  const tsModal = $("troubleshoot-modal");
  const openTsBtn = $("btn-open-troubleshoot");
  const closeTsBtn = $("troubleshoot-modal-close");
  const dismissTsBtn = $("troubleshoot-modal-dismiss");
  const rerunBtn = $("btn-troubleshoot-rerun");
  const openGuidesFromTsBtn = $("btn-troubleshoot-open-guides");

  if (openTsBtn) {
    openTsBtn.addEventListener("click", () => openTroubleshootModal(openTsBtn));
  }
  if (closeTsBtn && tsModal) closeTsBtn.addEventListener("click", () => closeModal(tsModal));
  if (dismissTsBtn && tsModal) dismissTsBtn.addEventListener("click", () => closeModal(tsModal));
  if (rerunBtn) rerunBtn.addEventListener("click", () => runTroubleshootDiagnostics());
  if (openGuidesFromTsBtn && tsModal) {
    openGuidesFromTsBtn.addEventListener("click", () => {
      closeModal(tsModal);
      openHowToGuide("restore_backup", openTsBtn);
    });
  }

  const guideModal = $("howto-guide-modal");
  const closeGuideBtn = $("howto-modal-close");
  const dismissGuideBtn = $("howto-modal-dismiss");
  const jumpGuideBtn = $("btn-howto-jump");

  if (closeGuideBtn && guideModal) closeGuideBtn.addEventListener("click", () => closeModal(guideModal));
  if (dismissGuideBtn && guideModal) dismissGuideBtn.addEventListener("click", () => closeModal(guideModal));
  if (jumpGuideBtn && guideModal) {
    jumpGuideBtn.addEventListener("click", () => {
      const targetView = jumpGuideBtn.dataset.jumpView || "overview";
      closeModal(guideModal);
      navigateToView(targetView);
    });
  }

  if (guideModal) {
    guideModal.querySelectorAll("[data-howto-select]").forEach((btn) => {
      btn.addEventListener("click", () => {
        openHowToGuide(btn.getAttribute("data-howto-select"), btn);
      });
    });
  }

  document.addEventListener("click", (ev) => {
    const trigger = ev.target && ev.target.closest ? ev.target.closest("[data-howto-guide]") : null;
    if (!trigger) return;
    ev.preventDefault();
    openHowToGuide(trigger.getAttribute("data-howto-guide") || "restore_backup", trigger);
  });
}
