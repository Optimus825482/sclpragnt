// Bump this whenever app shell/CSS/JS asset graph changes so installed PWAs
// discard stale cached responses. The HTML document itself is network-first:
// Next.js emits content-hashed /_next/static/*.js|css filenames, so a fresh
// HTML response always references the newest assets and cache-busts itself.
const CACHE = "scalper-agent-v4-shell-13";
const SHELL = ["/", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE).then(function (cache) {
    return cache.addAll(SHELL);
  }).then(function () {
    return self.skipWaiting();
  }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (key) { return key !== CACHE; }).map(function (key) {
      return caches.delete(key);
    }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = { title: "Scalper Agent", body: event.data ? event.data.text() : "Yeni alarm" }; }
  event.waitUntil(self.registration.showNotification(data.title || "Scalper Agent alarmı", {
    body: data.body || data.message || "Yeni market alarmı",
    icon: "/icon.svg",
    badge: "/icon.svg",
    vibrate: [180, 80, 180, 80, 280],
    tag: data.tag || "scalper-alert",
    data: { url: data.url || "/alerts" }
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data?.url || "/alerts"));
});

function isDocumentRequest(request) {
  return request.destination === "document" || request.mode === "navigate";
}

self.addEventListener("fetch", function (event) {
  const url = new URL(event.request.url);
  const eligible = event.request.method === "GET" &&
    url.origin === self.location.origin && !url.pathname.startsWith("/api/");
  if (!eligible) return;

  if (isDocumentRequest(event.request)) {
    // HTML: network-first. Always try the server so users get the newest
    // app shell and hashed JS/CSS; fall back to cache only when offline.
    event.respondWith(fetch(event.request).then(function (response) {
      const copy = response.clone();
      caches.open(CACHE).then(function (cache) { return cache.put(event.request, copy); });
      return response;
    }).catch(function () {
      return caches.match(event.request).then(function (cached) {
        return cached || caches.match("/");
      });
    }));
    return;
  }

  // Static assets (_next hashed JS/CSS, images, manifest): stale-while-revalidate.
  event.respondWith(caches.match(event.request).then(function (cached) {
    const network = fetch(event.request).then(function (response) {
      if (response && response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then(function (cache) { return cache.put(event.request, copy); });
      }
      return response;
    }).catch(function () {
      return cached;
    });
    return cached || network;
  }));
});
