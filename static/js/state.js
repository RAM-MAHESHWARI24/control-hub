/**
 * Control Hub - Central Reactive State
 */

export const state = {
  // Background visibility-aware interval timers
  realtimeTimers: {
    fast: null,
    medium: null
  },

  // Host Timezone
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  tzAbbr: "",

  // Sleep Guard
  sleepSkipActive: false,
  sleepSecondsRemaining: 0,

  // Bandwidth & Unit Toggle
  currentUnit: "mbs", // "mbs" (MB/s) or "mbps" (Mbps)
  lastWanDlMbs: 0.0,
  lastWanUpMbs: 0.0,
  lastLanTotalMbs: 0.0,
  lastLanRxMbs: 0.0,
  lastLanTxMbs: 0.0,

  // Sparkline History
  wanHistory: [],
  lanHistory: [],
  wanPeakMbs: 0.0,
  lanPeakMbs: 0.0,

  // Torrents
  torrentsPaused: false,

  // Services
  servicesLoadedOnce: false,
  activeServiceFilter: "all",
  dozzleInstalled: false,
  cockpitInstalled: false,

  // Backup Sync Toast Debouncing
  userInitiatedSync: false,
  lastSyncCompletionToastTime: 0
};
