// Service Worker for Scripts Remote Control PWA
// Strictly caches public static UI assets only; NEVER caches authenticated API responses or private HTML.

const CACHE_NAME = "remote-control-shell-v1";
const STATIC_ASSETS = [
  "/",
  "/static/index.html",
  "/static/style.css",
  "/static/app.js",
  "/static/manifest.json",
  "/static/icon.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // STRICT RULE: Never cache or intercept API endpoints or state mutations
  if (url.pathname.startsWith("/api/") || event.request.method !== "GET") {
    return; // Pass through to network directly
  }

  // Network-first for static shell assets with cache fallback
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});
