// Service worker. Served from /sw.js (root scope) with __VERSION__ replaced.
//
// - Static assets: cache-first, precached on install, old caches removed on activate.
// - Pages: always from the network, so pantry data is never stale. If the network
//   is down, show the cached offline page instead.
"use strict";

const VERSION = "__VERSION__";
const CACHE = "pantry-" + VERSION;
const OFFLINE_URL = "/offline";
const PRECACHE = [
  OFFLINE_URL,
  "/static/app.css?v=" + VERSION,
  "/static/app.js?v=" + VERSION,
  "/static/vendor/htmx.min.js?v=" + VERSION,
  "/static/icons/icon-192.png",
  "/static/icons/favicon-32.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith("pantry-") && key !== CACHE).map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

function offlineResponse() {
  return caches.match(OFFLINE_URL).then((cached) => cached || new Response("Offline", { status: 503 }));
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      }))
    );
    return;
  }

  // Full page loads, and hx-boost page swaps (HX-Boosted header), fall back offline.
  const isPage = request.mode === "navigate" || request.headers.get("HX-Boosted") === "true";
  if (isPage) {
    event.respondWith(fetch(request).catch(offlineResponse));
  }
  // Everything else (e.g. the add preview) goes straight to the network.
});
