/**
 * ServerFF Control Hub - Central Reactive State
 */

export const state = {
  // Telemetry Refresh Stream Mode: "hover" (Eco/Hover-Only) vs "realtime" (Real-Time All)
  streamMode: localStorage.getItem("serverff_stream_mode") || "hover",
  
  // Background interval timers
  realtimeTimers: {
    speedo: null,
    vitals: null,
    sleep: null,
    backup: null,
    cron: null,
    services: null
  },

  // Sleep Guard
  sleepSkipActive: false,
  sleepSecondsRemaining: 0,

  // Bandwidth & Unit Toggle
  currentUnit: "mbs", // "mbs" (MB/s) or "mbps" (Mbps)
  lastWanDlMbs: 10.9,
  lastWanUpMbs: 11.2,
  lastLanTotalMbs: 0.0,
  lastLanRxMbs: 0.0,
  lastLanTxMbs: 0.0,

  // Sparkline History
  wanHistory: [],
  lanHistory: [],
  wanPeakMbs: 10.9,
  lanPeakMbs: 0.0,

  // Torrents
  torrentsPaused: false,

  // Services
  servicesLoadedOnce: false,
  activeServiceFilter: "all",

  // Backup Sync Toast Debouncing
  userInitiatedSync: false,
  lastSyncCompletionToastTime: 0
};
