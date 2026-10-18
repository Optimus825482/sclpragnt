// SERVICE WORKER ŞABLONU — tarayıcıya `/sw.js` olarak `app/sw.js/route.ts` üzerinden,
// derleme kimliği ve VAPID anahtarı GÖMÜLEREK sunulur (bkz. app/lib/swRender.ts).
//
// NEDEN GÖMME? (2026-10-18, mobil/PWA denetimi S1)
// Eskiden SW `/sw.js?v=<BUILD>` adresiyle kaydediliyordu; her deploy'da yalnız
// sorgu değişiyor, dosya baytları aynı kalıyordu. Tarayıcının kendi güncelleme
// denetimi (`registration.update()`, açılışta, 24 saatte bir) KAYITLI eski URL'yi
// çeker; baytlar aynı olduğundan yeni SW hiç kurulmazdı. Şimdi URL SABİT (`/sw.js`)
// ve dosyanın İÇİNDE her build'de değişen `BUILD` sabiti var → bayt farkı →
// tarayıcı yeni SW'yi kendiliğinden kurar.
//
// Derleme zamanında şu iki jeton değiştirilir (tırnaklarıyla birlikte). Şablon
// ham haliyle de geçerli JavaScript'tir.
var BUILD = "__SW_BUILD__";
var VAPID_KEY = "__SW_VAPID__";

var CACHE_PREFIX = "scalper-agent-v4-shell-";
var CACHE = CACHE_PREFIX + BUILD;
var SHELL_URL = "/";
// Ağ bu süre içinde yanıt vermezse (bağlantı var, veri yok — "lie-fi") ve
// önbellekte sayfa varsa önbellek sunulur; ağ isteği arka planda sürer.
var NAV_TIMEOUT_MS = 4000;

function noop() {}

function offlineResponse() {
  return new Response("offline", { status: 503, statusText: "offline" });
}

// Navigasyon önbelleği yalnız yol (pathname) ile anahtarlanır: `?symbol=…`
// gibi sorgu varyantları sınırsız girdi üretmesin. Sayfalar istemcide çizilir;
// sorgu zaten tarayıcıdan okunur.
function navCacheKey(url) {
  return new Request(url.origin + url.pathname);
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      // Deploy anında "/" 503 dönebilir: ön-önbellek hatası kurulumu düşürmesin.
      return cache.add(new Request(SHELL_URL, { cache: "reload" })).catch(noop);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

// Tek `activate`: eski kabuk önbelleklerini temizle (önceki build'in önbelleğini
// BİR NESİL daha tut: deploy sonrası eski sayfa bellekteyken tembel chunk isterse
// 404 yerine önbellekten alınabilsin), istemcileri devral, sürümü bildir.
self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      var mine = keys.filter(function (key) { return key.indexOf(CACHE_PREFIX) === 0; });
      var previous = mine.filter(function (key) { return key !== CACHE; }).slice(-1);
      var keep = [CACHE].concat(previous);
      return Promise.all(keys.filter(function (key) {
        return key.indexOf(CACHE_PREFIX) === 0 && keep.indexOf(key) === -1;
      }).map(function (key) { return caches.delete(key); }));
    }).then(function () {
      return self.clients.claim();
    }).then(function () {
      return self.clients.matchAll({ type: "window" });
    }).then(function (list) {
      // Sayfa kendi derleme kimliğiyle kıyaslar; farklıysa "Yeni sürüm var"
      // şeridini gösterir (OTOMATİK YENİLEME YOK: açık emir penceresi kaybolmasın).
      list.forEach(function (client) {
        try { client.postMessage({ type: "SW_VERSION", build: BUILD }); } catch (_) { /* yok say */ }
      });
    })
  );
});

self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = { title: "Scalper Agent", body: event.data ? event.data.text() : "Yeni alarm" }; }

  // MÜKERRER BİLDİRİM ÖNLEMİ (2026-09-17): uygulama ODAKLI ve GÖRÜNÜR bir
  // pencereyle açıksa sayfa kendi modal + sesini zaten gösteriyor (WS
  // `monitoring_alert`); OS push'u da göstermek AYNI bildirimi iki kez
  // duyurur (modal sesi + bildirim sesi/titreşimi). Bu durumda push'u
  // sessizce atla — sayfa kapanırsa/arka plana geçerse push yine gösterilir.
  var skipWhenPageVisible = function () {
    return clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        var c = list[i];
        try {
          if (new URL(c.url).origin === self.location.origin && c.visibilityState === "visible" && c.focused) {
            return true;
          }
        } catch (_) { /* url çözülemedi: sayfayı gösterilen saymayalım */ }
      }
      return false;
    });
  };

  var show = function () {
    // PWA kapalı olsa bile sesli bildirim: Android/Chrome ses dosyası destekler,
    // iOS Safari vibrate ile destekler; her ikisini birden sağlıyoruz.
    var notifOpts = {
      body: data.body || data.message || "Yeni market alarmı",
      icon: "/icon.svg",
      badge: "/icon.svg",
      vibrate: [300, 150, 300, 150, 500, 150, 300],
      tag: data.tag || "scalper-alert",
      requireInteraction: true,
      renotify: true,
      silent: false,
      data: { url: data.url || "/monitoring" }
    };
    // Android/Chrome: ses dosyası (sound alanı)
    if (data.sound) notifOpts.sound = data.sound;
    // ML olasılık varsa başlığa ekle
    if (data.ml_hit_probability != null) {
      var prob = Math.round(Number(data.ml_hit_probability) * 100);
      notifOpts.body = "[ML %" + prob + "] " + (notifOpts.body || "");
    }
    return self.registration.showNotification(data.title || "Scalper Agent alarmı", notifOpts);
  };

  event.waitUntil(
    skipWhenPageVisible().then(function (pageVisible) {
      if (pageVisible) return; // sayfa zaten modal ile duyurdu
      return show();
    })
  );
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = (event.notification.data && event.notification.data.url) || "/monitoring";
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
            }).catch(function () {
              // Kontrol edilmeyen istemcide navigate reddedilir: tıklama sessiz kalmasın.
              return clients.openWindow(target);
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
// VAPID anahtarı artık URL sorgusundan değil, derleme zamanında dosyaya gömülür.
function swVapidKey() {
  return VAPID_KEY && VAPID_KEY.indexOf("__SW_") !== 0 ? VAPID_KEY : "";
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

function isStaticAssetRequest(request) {
  return request.method === "GET" &&
    new URL(request.url).pathname.startsWith("/_next/static/");
}

// Next.js App Router'ın istemci-içi gezinme iskeleti (RSC payload) ve diğer
// uygulama fetch'leri (API dışı) service worker'dan ÇIKARILIR. Çok geniş bir
// `eligible` kuralı RSC'yi bir kez önbelleğe alıp sonraki gezinmelerde BAYAT
// yanıt döndürüyordu → grafik eski sembolü (BTCTRY) gösteriyor, sonra navigasyon
// bozuluyor; yalnız tam yenileme düzeltiyordu. Bu yüzden SW yalnızca şunlara bakar:
//   (1) document/navigation → network-first (4 sn zaman aşımı), çevrimdışı shell fallback
//   (2) /_next/static/*    → cache-first (içerik-hash'li, değişmez)
// Geri kalan HER ŞEY (RSC, API, manifest, ikon dışı GET) ağa doğrudan gider.
function isRscOrAppDataRequest(request) {
  return request.method === "GET" &&
    (request.headers.get("RSC") === "1" ||
     request.headers.has("Next-Router-State-Tree"));
}

// Başarılı, aynı-origin, yönlendirmesiz yanıt mı? Hata sayfaları (404/500/nginx
// 502-503 HTML'i) önbelleğe GİRMEMELİ: çevrimdışıyken kullanıcıya hata sayfası
// sunulurdu. Yönlendirilmiş yanıt da navigasyona geri verilemez.
function isCacheableNavigation(response) {
  return !!response && response.ok && response.type === "basic" && !response.redirected;
}

function putInCache(event, key, response) {
  var work = caches.open(CACHE).then(function (cache) { return cache.put(key, response); }).catch(noop);
  // Yanıt dönüldükten sonra gelen ağ cevabında `waitUntil` geçersiz olabilir.
  try { event.waitUntil(work); } catch (_) { /* iş yine de sürer */ }
}

function handleNavigation(event) {
  var request = event.request;
  var key = navCacheKey(new URL(request.url));
  var network = fetch(request);
  network.then(function (response) {
    if (isCacheableNavigation(response)) putInCache(event, key, response.clone());
  }, noop);
  var timeout = new Promise(function (resolve) {
    setTimeout(function () { resolve(null); }, NAV_TIMEOUT_MS);
  });
  return Promise.race([network, timeout]).then(function (response) {
    if (response) return response;
    // Zaman aşımı: önbellekte sayfa varsa onu sun; yoksa ağı beklemeye devam et.
    return caches.match(key).then(function (cached) { return cached || network; });
  }).catch(function () {
    return caches.match(key).then(function (cached) {
      return cached || caches.match(new Request(self.location.origin + SHELL_URL));
    }).then(function (shell) {
      // `respondWith(undefined)` istemci-içi gezinmeyi kırar: HER ZAMAN geçerli Response dön.
      return shell || offlineResponse();
    });
  });
}

self.addEventListener("fetch", function (event) {
  var request = event.request;
  var url = new URL(request.url);
  if (isRscOrAppDataRequest(request)) return;
  if (url.origin !== self.location.origin) return;
  if (request.method !== "GET") return;
  // API ve WebSocket yolları (indirme/yönlendirme navigasyonları dahil) SW'ye hiç girmez.
  if (url.pathname.indexOf("/api/") === 0 || url.pathname === "/ws") return;

  if (isDocumentRequest(request)) {
    event.respondWith(handleNavigation(event));
    return;
  }

  if (isStaticAssetRequest(request)) {
    // Hash'li statik dosya: cache-first. Önceki build'in önbelleği de aranır
    // (caches.match tüm önbelleklere bakar) → deploy sonrası eski sayfanın tembel chunk'ı çalışır.
    event.respondWith(caches.match(request).then(function (cached) {
      if (cached) return cached;
      return fetch(request).then(function (response) {
        if (response && response.ok) putInCache(event, request, response.clone());
        return response;
      }).catch(offlineResponse);
    }));
    return;
  }

  // Diğer her şey (RSC, manifest, ikon, API-dışı GET): SW karışmasın.
});
