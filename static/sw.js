/**
 * Control Hub Service Worker (Phase 4B)
 * Caches app shell assets and keeps last-known GET API snapshots available
 * when the server sleeps or the phone temporarily loses connectivity.
 */

const SHELL_CACHE = "hub-shell-v1";
const API_CACHE = "hub-api-snapshot-v1";

const SHELL_ASSETS = [
  "/",
  "/manifest.webmanifest",
  "/img/icons/hub-app.svg",
  "/img/icons/ui-sprite.svg"
];

const CACHEABLE_API_PREFIXES = [
  "/api/system/vitals",
  "/api/services/status",
  "/api/backup/status",
  "/api/sleep/status",
  "/api/alerts",
  "/api/network/speed"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE && k !== API_CACHE)
          .map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/")) {
    const canSnapshot = CACHEABLE_API_PREFIXES.some((p) => url.pathname.startsWith(p));
    if (!canSnapshot) return;

    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(API_CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
          }
          return res;
        })
        .catch(() => caches.match(req).then((cached) => cached || new Response(
          JSON.stringify({ status: "offline", offline_cached: false, message: "Server offline or sleeping" }),
          { status: 503, headers: { "Content-Type": "application/json" } }
        )))
    );
    return;
  }

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && (req.mode === "navigate" || url.pathname.startsWith("/css/") || url.pathname.startsWith("/js/") || url.pathname.startsWith("/fonts/") || url.pathname.startsWith("/img/"))) {
          const copy = res.clone();
          caches.open(SHELL_CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
        }
        return res;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match("/")))
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow("/#/overview");
      return undefined;
    })
  );
});
