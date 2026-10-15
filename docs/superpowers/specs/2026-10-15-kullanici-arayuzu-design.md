# Kullanıcı Arayüzü (light tema) — Tasarım

Tarih: 2026-10-15 · Durum: kullanıcı incelemesi bekliyor (tasarım sohbette onaylandı)

## 1. Amaç ve başarı ölçütü
`role = user` hesapları, admin arayüzünden ayrı, **light temalı, sade ve hızlı anlaşılır** bir arayüz görür.
Admin mevcut koyu arayüzünü aynen korur. Başarı: kullanıcı ana sayfada son bildirimlerini, canlı % değişimlerini
ve başarı KPI'larını ilk bakışta görür; Radar sayfasında yalnız üç kavram vardır (Isınanlar, İzlemedekiler,
Bildirim gönderilenler).

Kapsam kararları (kullanıcı): menü 8 öğe; göster/gizle tercihi DB'de; yükselme tablosu WebSocket ile canlı;
Radar sadeleşir; **Aşama 2 (Portföy, Grafik, Raporlar, Profil light'a) bu işe dahil**; API key/secret girişi
mevcut şifreli altyapıya bağlanır.

## 2. Rol ayrımı ve tema
- `AppShell.tsx`: `useAuth().role === "admin"` → mevcut kabuk. Aksi → yeni `UserShell`
  (`app/components/user/`: `UserShell`, `UserNav`, `UserBottomNav`).
- `layout.tsx` `<html className="dark">` ve `viewport.themeColor` sabit; rol belli olunca `data-theme="light"`
  istemci tarafında `<html>`'e yazılır (kullanıcı), admin için `dark` kalır. Giriş ekranı koyu kalır
  (rol girişten önce bilinmez); girişten sonra tema değişir.
- Light tema = `[data-theme="light"]` altında CSS değişkenleri + mevcut `bunker-*`/`neon-*` sınıflarının
  yeniden eşlenmesi (`app/user-theme.css`). Böylece Aşama 2 sayfaları yeniden yazılmadan light görünür;
  sorunlu yerler tek tek düzeltilir. Admin sayfalarına dokunulmaz.
- Rol kontrolü yalnız görünüm içindir; yetki zaten backend'de (`require_admin`). Kullanıcı admin
  sayfasına URL ile girse mevcut `RequireAdmin` korur.

## 3. Menü (8 öğe) ve göster/gizle
Ana Sayfa, Bildirimler, Radar, Portföy, Grafik, Raporlar, Profil, Ayarlar.
- Ana Sayfa ve Ayarlar gizlenemez.
- Tercih DB'de: migration `015_user_ui_prefs.sql` → `user_ui_prefs(user_id PK → users ON DELETE CASCADE,
  hidden_menu TEXT NOT NULL DEFAULT '[]', updated_at DOUBLE PRECISION)`.
- Uçlar: `GET/PUT /api/profile/ui-prefs` (oturumdaki kullanıcı; yalnız bilinen menü kimlikleri kabul edilir,
  Ana Sayfa/Ayarlar reddedilir). Frontend ilk yüklemede localStorage önbelleğini gösterir, DB'den gelince eşitler.
- Mobil: alt gezinti (4 öğe + "Menü").

## 4. Ana Sayfa
Üstten alta:
1. **KPI şeridi:** Bugünkü başarı %, toplam başarı % (ve her birinin değerlendirilen sayısı).
   Kaynak `GET /api/reports/notifications` (`breakdown`/`overall`; `evaluated=0` → "Henüz ölçülmedi").
   Radar kesimi (2026-10-15 22:30) uygulanır; bu yüzden ilk saatlerde veri azdır, bu açıkça yazılır.
2. **Yükselme adayları (canlı):** `GET /api/daily-rising/live` ilk yük + canlı fiyat güncellemeleri.
   Sütunlar: sembol, bildirim fiyatı, canlı fiyat, % değişim (renk + ok), hedef tavan, durum.
3. **Son 5 bildirim:** `GET /api/monitoring/notifications` → `history` (gönderilmiş olanlar,
   `sent_via_push` önceliği; ilk 5). Sütunlar: zaman (göreli + saat), sembol, bildirim fiyatı, canlı fiyat, % değişim.

### Canlı fiyat (WebSocket)
Mevcut `binance_price` WS yayını yalnız cüzdan varlıkları içindir. Yeni yayın:
- Backend döngüsü `watch_prices_loop` (main.py, `binance_price_tick_loop` desenini izler): her ~3 sn,
  **tüm kullanıcılar için tek** sembol birleşimini (son 20 bildirim + `daily-rising/live` sembolleri, ≤50)
  `_batch_prices` ile çekip `{"type":"watch_prices","data":{"prices":{SYM:price},"time":epoch}}` yayınlar.
  Bağlı kullanıcı yoksa döngü boşta bekler (gereksiz Binance çağrısı yok).
- Frontend `useLiveMessages(["watch_prices"])`. WS 15 sn sessiz kalırsa `GET /api/market-tickers`
  yoklamasına düşer (kopukluk yedeği).
- % değişim = (canlı − bildirim fiyatı) / bildirim fiyatı × 100, istemcide; fiyat yoksa "—".

## 5. Bildirimler sayfası
`GET /api/reports/notifications` (limit 200). Sütunlar: gönderim zamanı, sembol, bildirim fiyatı, hedef %,
ufuk (dk), **Sonuç** (Hedefe ulaştı / Kısmen / Ulaşmadı / Bekliyor / Ölçülemedi), pencere bitişi
(`detected_at + ufuk`; bekleyenlerde geri sayım). Filtre: Bugün / Tümü / Yalnız hedefe ulaşanlar.
Durum eşlemesi: TAMAMEN BAŞARILI→Hedefe ulaştı, KISMİ→Kısmen, BAŞARISIZ→Ulaşmadı,
BEKLİYOR→Bekliyor, ÖLÇÜLEMEDİ→Ölçülemedi. Mobilde satırlar kart olur.

## 6. Radar sayfası (sadeleşmiş)
Kullanıcı görünümü `/monitoring` içinde rol dalı olarak render edilir (adres değişmez, admin görünümü aynı).
Yalnız **üç sekme**, kullanıcı dilinde:

| Sekme | Kaynak (`/api/monitoring/state`, `/notifications`) | Anlamı |
|---|---|---|
| Isınanlar | `warm` | Yükselişe hazırlanan, henüz izlemeye alınmamış |
| İzlemedekiler | `watchlist` | Sistemin izlemeye aldığı |
| Gönderilen bildirimler | `history` | Bildirim olarak gönderilenler |

Her satır: sembol, tek cümlelik durum, fiyat, hedef %, güven rozeti (Yüksek/Orta/Düşük — skor eşiklerinden),
canlı % (yukarıdaki WS). Kaldırılanlar: Adaylar, Pulse, tarama döngüsü kartları, ML/konfluans/ATR/R-R
çipleri, eşik düzenleme, tarama/sıfırlama düğmeleri, push sağlık çipleri. Detay penceresi sade: neden
önerildi (1-2 cümle), hedef, ufuk, grafik bağlantısı. Satır ve detay bileşenleri `monitoring/page.tsx`'ten
`app/components/radar/` altına çıkarılır (admin sayfası da kullanır, davranış değişmez).

## 7. Ayarlar (kullanıcı)
- Menü göster/gizle (§3), bildirim izni/ses. Tema seçeneği yok (YAGNI).
- **Binance TR API key/secret:** mevcut `user_binance_keys` (Fernet, migration 005) ve mevcut kaydet/sil uçları
  kullanılır; yeni tablo/şifreleme yok. Secret yazma-yalnızdır, kayıttan sonra yalnız "kayıtlı" ve son 4 hane
  gösterilir; loglara/yanıta düz yazılmaz. `real_sell_enabled` varsayılan kapalı, ayrı açık onayla açılır.
- Mevcut `/settings` admin sayfası (RequireAdmin) kullanıcıya açılmaz; kullanıcı ayarları kendi bileşenidir
  (`app/components/user/UserSettings.tsx`) ve `/settings` rol dalıyla render edilir.

## 8. Aşama 2 — diğer sayfalar light'a
Portföy, Grafik, Raporlar, Profil: §2'deki tema katmanıyla light görünür; sonra sayfa sayfa taranır
(kontrast, grafik renkleri, tablo satırları, modal). Raporlar'da kullanıcıya yalnız kullanıcı-seviyesi sekmeler
(Performans Özeti, Sinyal & Hedef Başarısı); admin sekmeleri gizli kalır. Grafik kütüphanesi renkleri tema
değişkenine bağlanır.

## 9. Öneriler (kapsam dışı, değerlendirme için)
Sembol favorileri (`user_favorites` mevcut) ile "Favorilerim" süzgeci; bildirim sessiz saatleri;
günlük özet kartı ("bugün X bildirim, Y hedefe ulaştı"); ilk girişte 3 adımlık tanıtım.

## 10. Test ve doğrulama
- Backend: `ui-prefs` uçları (geçersiz kimlik, gizlenemez öğe, kullanıcı izolasyonu), `watch_prices` sembol
  birleşimi (≤50, tekrarsız) ve bağlı kullanıcı yokken boşta kalma; migration 015 pg17'de uygulanır.
- Frontend (vitest, node ortamı): saf yardımcılar — % değişim, durum eşlemesi, pencere bitişi, menü süzgeci,
  rol→kabuk seçimi. `npm run typecheck`, `npm run lint`.
- Elle: iki hesapla (admin/user) tarayıcıda; 375 px ve masaüstü; WS koparıp yoklama yedeği; ekran görüntüleriyle kontrast.
- Güvenlik: secret hiçbir yanıtta/loglarda yok; kullanıcı başka kullanıcının tercihlerini/anahtarını okuyamaz.

## 11. Uygulama sırası
1. Tema katmanı + `UserShell` + rol dalı (admin değişmez). 2. `user_ui_prefs` migration + uçlar + menü.
3. `watch_prices` yayını + istemci kancası. 4. Ana Sayfa. 5. Bildirimler. 6. Radar (bileşen çıkarma + sade sayfa).
7. Kullanıcı Ayarları (+ API key). 8. Aşama 2 sayfa taraması. 9. Doğrulama ve ekran görüntüleri.
