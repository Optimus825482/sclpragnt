// Bump this whenever app shell/CSS/JS asset graph changes so installed PWAs
// discard stale cached responses. The HTML document itself is network-first:
// Next.js emits content-hashed /_next/static/*.js|css filenames, so a fresh
// HTML response always references the newest assets and cache-busts itself.
// H-13: sürüm ELLE tutulmuyor; `.../sw.js?v=<BUILD_ID>` sorgusundan türetilir.
// Böylece yeni dağıtımda cache adı kendiliğinden değişir ve kurulu PWA eski
// shell'i sunmaya devam edemez.
const BUILD = new URL(self.location.href).searchParams.get("v") || "dev";
const CACHE = "scalper-agent-v4-shell-" + BUILD;
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

  // PWA kapalý olsa bile sesli bildirim: Android/Chrome ses dosyasý destekler,
  // iOS Safari vibrate ile destekler; her ikisini birden saðlýyoruz.
  var notifOpts = {
    body: data.body || data.message || "Yeni market alarmý",
    icon: "/icon.svg",
    badge: "/icon.svg",
    vibrate: [300, 150, 300, 150, 500, 150, 300],
    tag: data.tag || "scalper-alert",
    requireInteraction: true,
    renotify: true,
    silent: false,
    data: { url: data.url || "/alerts" }
  };
  // Android/Chrome: ses dosyasý (sound alaný)
  if (data.sound) notifOpts.sound = data.sound;
  // ML olaslýk varsa baþlýða ekle
  if (data.ml_hit_probability != null) {
    var prob = Math.round(Number(data.ml_hit_probability) * 100);
    notifOpts.body = "[ML %" + prob + "] " + (notifOpts.body || "");
  }
  event.waitUntil(self.registration.showNotification(data.title || "Scalper Agent alarmý", notifOpts));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = (event.notification.data && event.notification.data.url) || "/alerts";
  // 2026-09-16: eskiden her tıklama `clients.openWindow` ile YENİ SEKME açıyordu.
  // Doğrusu: açık bir pencere varsa onu ODAKLA ve hedef URL'e yönlendir; yoksa aç.
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        var client = list[i];
        if (new URL(client.url).origin === self.location.origin) {
          if ("navigate" in client) {
            return client.navigate(target).then(function (navigated) {
              return (navigated || client).focus();
            });
          }
          return client.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});

// PUSH-RESILIENCE (2026-09-16): tarayıcı aboneliği döndürürse (endpoint rotasyonu,
// PWA yeniden kurulumu) eski endpoint ölür ve backend ölü aboneliği temizledikten
// sonra push SESSİZCE susar. Bu olay o durumu yakalayıp yeni aboneliği backend'e
// yazar. NOT: Chrome bu olayı güvenilir tetiklemez → istemci tarafında açılışta
// `reconcilePushSubscription()` (lib/push.ts) ile birlikte çalışır; ikisi birlikte
// hem olayı destekleyen hem desteklemeyen tarayıcıları kapsar.
function swVapidKey() {
  try { return new URL(self.location.href).searchParams.get("vapid") || ""; } catch (_) { return ""; }
}

function urlBase64ToUint8Array(base64String) {
  var clean = base64String.trim().replace(/-/g, "+").replace(/_/g, "/");
  var padded = clean + "=".repeat((4 - (clean.length % 4)) % 4);
  var raw = atob(padded);
  var out = new Uint8Array(raw.length);
  for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function registerSubscription(subscription) {
  if (!subscription) return Promise.resolve();
  return fetch("/api/alerts/push-subscription", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(subscription.toJSON()),
  }).catch(function () { /* çevrimdışı: sonraki açılışta uzlaştırma yakalar */ });
}

self.addEventListener("pushsubscriptionchange", function (event) {
  var key = swVapidKey();
  if (!key) return;
  event.waitUntil(
    Promise.resolve(event.newSubscription).then(function (existing) {
      if (existing) return registerSubscription(existing);
      return self.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      }).then(registerSubscription);
    }).catch(function () { /* yeniden abone olunamadı: kullanıcı izni gerekebilir */ })
  );
});

function isDocumentRequest(request) {
  return request.destination === "document" || request.mode === "navigate";
}

// Next.js App Router'ın istemci-içi gezinme iskeleti (RSC payload) SÖZLEŞME DIŞI:
// bu istekler önbelleğe alınırsa bir kez yazılır, sonraki gezinmelerde BAYAT RSC
// döner → grafik eski sembolü (BTCTRY) gösterir, sonra görüntülenemez; yalnız tam
// yenileme düzeltir. Bu yüzden RSC istekleri service worker'dan ÇIKARILIR
// (ağa doğrudan gider; SW karışmaz).
function isRscRequest(request) {
  return request.method === "GET" &&
    (request.headers.get("RSC") === "1" ||
     request.headers.has("Next-Router-State-Tree"));
}

self.addEventListener("fetch", function (event) {
  const url = new URL(event.request.url);
  if (isRscRequest(event.request)) return;
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
        return cached || caches.match("/").then(function (shell) {
          // Çevrimdışı + hiçbir önbellek yoksa bile GEÇERLİ bir Response dön;
          // `respondWith(undefined)` "Failed to convert value to 'Response'"
          // fırlatır ve istemci-içi gezinmeyi kırar.
          return shell || new Response("offline", { status: 503, statusText: "offline" });
        });
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
      // Ağ hatasında `cached` yoksa `undefined` döndürme → SW TypeError vermesin.
      return cached || new Response("offline", { status: 503, statusText: "offline" });
    });
    return cached || network;
  }));
});
