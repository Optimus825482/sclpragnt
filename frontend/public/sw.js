const CACHE = "scalper-agent-v4-shell-3";
const SHELL = ["/", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE).then(function (cache) {
    return cache.addAll(SHELL);
  }).then(function () {
    return self.skipWaiting();
  }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", function (event) {
  const url = new URL(event.request.url);
  const eligible = event.request.method === "GET" &&
    url.origin === self.location.origin && !url.pathname.startsWith("/api/");
  if (!eligible) return;
  event.respondWith(fetch(event.request).then(function (response) {
    const copy = response.clone();
    caches.open(CACHE).then(function (cache) {
      return cache.put(event.request, copy);
    });
    return response;
  }).catch(function () {
    return caches.match(event.request).then(function (cached) {
      return cached || caches.match("/");
    });
  }));
});
