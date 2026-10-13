# Odak UI — sadeleştirilmiş açık tema panel

Scalper Agent V4 (mevcut `frontend/`) için **alternatif, sadeleştirilmiş arayüz**.
Tasarım isteğinden yola çıkarak (`tasarım 1.png` → "ODAK AI TRADER") inşa edildi;
GERÇEK backend uçlarına bağlıdır, sahte/statik veri içermez.

## Neden ayrı bir dizin/uygulama

Mevcut `frontend/` koyu temalı (bunker + neon yeşil) ve tek kabuk (Sidebar + TopBar)
üzerine kurulu. Bu tasarım ise **açık tema + mavi vurgu + tek üst menü** istiyor.
Var olan 30+ sayfayı ve koyu tema sözleşmesini bozmadan denemek için ayrı bir Next.js
uygulaması olarak kuruldu. İkisi aynı backend'e bağlanır ve **yan yana** çalışabilir.

## Sadeleştirme kararları (tasarım incelemesinden)

Görsel, iki vision modeliyle çapraz doğrulandı; **üç ortak sorun** vardı ve burada
bilinçli olarak düzeltildi:

| Tespit | Bu arayüzde çözüm |
|---|---|
| **Çift navigasyon** (üst menü + sol sidebar aynı linkleri tekrarlıyor) | Sol sidebar YOK; navigasyon yalnızca tek üst menüde (`TopNav.tsx`). |
| **Renk/hiyerarşi gürültüsü** (her blokta doygun yeşil, maviyle çakışıyor) | Vurgu rengi MAVİ (`#0066ff`). Yeşil/kırmızı YALNIZCA K/Z verisi için. |
| **Aşırı yoğunluk** (tek ekranda 6+ bölge) | Sistem durumu tek şeride indi (`StatusStrip`); kart/tablo/detay üç net bölge. |

Ek sapma: tasarımdaki **sahte AL/SAT emir formu konmadı** — sistem paper-only'dir.
Yerine seçili adayın gerçek alanlarını gösteren bir detay paneli (`CandidateDetail`)
ve gerçek işlem için mevcut panelin Binance TR sayfasına bağlantı eklendi.

## Entegrasyon modeli (CORS'suz)

Tarayıcı `/api/...` isteklerini **bu uygulamanın kendi origin'ine** yapar; Next.js
sunucusu bunları `BACKEND_ORIGIN`'e proxy'ler (`next.config.js` → `rewrites`). Böylece:

- **CORS yapılandırması gerekmez** (proxy sunucu-sunucu; tarayıcı çapraz köken görmez),
- oturum cookie'si (`scalper_session`, aynı-origin) bu origin'de saklanır ve çalışır.

Not: cookie same-origin olduğu için backend'in CORS origin listesine bu portu eklemek
GEREKMEZ. Yalnızca backend ayakta olmalıdır.

## Çalıştırma

```bash
cd frontend-odak
npm install
# Backend varsayılan http://127.0.0.1:8004 (docker-compose). Farklıysa:
#   BACKEND_ORIGIN=http://host:8004 npm run dev
npm run dev      # http://localhost:3055
```

Üretim: `npm run build && npm start` (port 3055). Docker imajı: `Dockerfile`.

## Kapsam (bu sürüm)

Sayfalar:
- `/` — **Fırsatlar**: aday kartları (gerçek `/api/daily-rising/state`), seçili aday
  detayı, portföy şeridi, açık pozisyon tablosu,
- `/positions` — açık pozisyonlar + risk özeti (`/api/positions`, `/api/risk/summary`),
- `/strategies` — promosyon hattı (`/api/strategy/pipeline`).

Veri kaynakları (hepsi gerçek, mevcut backend):
`/api/daily-rising/state`, `/api/monitoring/state`, `/api/dashboard/summary`,
`/api/portfolio/summary`, `/api/positions`, `/api/risk/summary`, `/api/strategy/pipeline`,
`/api/system/health` ve `WS /ws` (canlı tazeleme).

**Bilinçli kapsam dışı:** push bildirimleri, PWA/service-worker, uyarı modalları,
grafik sayfaları, admin/veritabanı, LLM/chat, Binance TR emir formu (mevcut panelde).
Bunlar gerekirse aynı kalıplarla eklenebilir.

## Doğrulama

- `npm run typecheck` → temiz
- `npm run build` → temiz (bkz. commit mesajı)
