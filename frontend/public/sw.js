// Bump this whenever app shell/CSS changes so installed PWAs discard stale assets.
const CACHE = "scalper-agent-v4-shell-5";
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
