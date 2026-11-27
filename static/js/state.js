/**
 * Control Hub - Central Reactive State
 */

export const state = {
  // Active workspace view: "overview" | "apps" | "backups" | "tvs" | "system"
  activeView: "overview",

  // Theme preference: "dark" | "light" | "system"
  themePreference: "dark",

  // Connection truthfulness tracker
  consecutivePollFailures: 0,
  lastSuccessfulPollAt: 0,

  // Background visibility-aware interval timers
  realtimeTimers: {
    fast: null,
    medium: null,
  },

  // Host metadata & active role ("owner" | "family")
  authRole: "owner",
  hostname: "",
  hubPort: window.location.port || "7575",
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  tzAbbr: "",

  // Module availability (dynamically hides unused views)
  modules: {
    backups: true,
    tvs: true,
    sleepGuard: true,
    indexers: false,
  },

  // Sleep Guard
  sleepInstalled: true,
  sleepEnabled: true,
  sleepSkipActive: false,
  sleepStateMode: "default",
  sleepSecondsRemaining: 0,
  sleepLabel: "Checking...",

  // Bandwidth & Unit Toggle
  currentUnit: "mbs", // "mbs" (MB/s) or "mbps" (Mbps)
  lastLanTotalMbs: 0.0,
  lastLanRxMbs: 0.0,
  lastLanTxMbs: 0.0,
  lanHistory: [],
  lanPeakMbs: 0.0,
  lastSpeedtest: null,

  // Torrents & Storage ops (shared with Overview activity & confirmation dialogs)
  torrentsPaused: false,
  torrentsActiveCount: 0,
  torrentsDlMbs: 0.0,
  torrentsStatus: "unknown",
  activeJellyfinStreams: 0,
  activeSmbClients: 0,
  storageTotalIoMbs: 0.0,

  // Vitals snapshot for Overview KPIs
  vitals: null,

  // Services
  servicesLoadedOnce: false,
  servicesList: [],
  activeServiceFilter: "all",
  serviceSearchQuery: "",
  includeOtherContainers: false,
  dozzleInstalled: false,
  dozzlePort: 8888,
  cockpitInstalled: false,

  // Available Updates (Phase 2C)
  updatesSnapshot: null,

  // Backup Sync Toast & Overview snapshot
  backupSnapshot: null,
  userInitiatedSync: false,
  lastSyncCompletionToastTime: 0,

  // TV snapshot
  tvSnapshot: null,

  // Alerts snapshot
  alertsSnapshot: null,

  // Netplan pending confirmation snapshot
  netplanPending: null,

  // Indexers banner state
  indexersNeedsSetup: false,
};
