/**
 * ServerFF Control Hub - Frontend Configuration
 * Dynamic Hostname resolution (ensures LAN, Tailscale, ZeroTier all work flawlessly)
 */

export const HOSTNAME = window.location.hostname || "localhost";
export const DOZZLE_BASE_URL = `http://${HOSTNAME}:8888`;

export const ENDPOINTS = {
  sleepStatus: "/api/sleep/status",
  sleepToggle: "/api/sleep/toggle",
  sleepShiftTonight: "/api/sleep/shift-tonight",
  sleepSchedulePermanent: "/api/sleep/schedule-permanent",
  networkSpeed: "/api/network/speed",
  speedtestLatest: "/api/speedtest/latest",
  speedtestRun: "/api/speedtest/run",
  activeDownloads: "/api/downloads/active",
  torrentsToggle: "/api/torrents/toggle-all",
  backupStatus: "/api/backup/status",
  backupSync: "/api/backup/sync",
  backupLog: "/api/backup/log",
  libraryStats: "/api/backup/library-stats",
  systemVitals: "/api/system/vitals",
  storageOps: "/api/storage/operations",
  cronStatus: "/api/cron/status",
  cronLog: (id) => `/api/cron/log/${id}`,
  cronRun: (id) => `/api/cron/run/${id}`,
  servicesStatus: "/api/services/status",
  serviceRestart: (id) => `/api/services/restart/${id}`,
  serviceLogs: (id, tail = 100) => `/api/services/logs/${id}?tail=${tail}`,
  tvUpdaterStatus: "/api/tv-updater/status",
  tvUpdaterDeploy: "/api/tv-updater/deploy",
  tvUpdaterSyncUpstream: "/api/tv-updater/sync-upstream",
  tvUpdaterInstallApp: "/api/tv-updater/install-app",
  tvUpdaterLog: "/api/tv-updater/log",
  tvUpdaterPushIncoming: "/api/tv-updater/push-incoming",
  configCurrent: "/api/config/current",
  configUpdate: "/api/config/update",
  configVerifyHardlink: "/api/config/verify-hardlink",
  configPorts: "/api/config/ports",
  configGenerateSecrets: "/api/config/generate-secrets",
  configAiDiagnostics: "/api/config/ai-diagnostics",
  configNetplanPreview: "/api/config/netplan-preview",
  configNetplanApply: "/api/config/netplan-apply"
};
