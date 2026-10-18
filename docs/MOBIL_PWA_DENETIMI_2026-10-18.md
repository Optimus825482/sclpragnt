# Mobil ve PWA uyum denetimi — özet ve birleşik yol haritası (2026-10-18)

Kapsam: tüm sayfalar (özellikle grafik sayfaları), ortak kabuklar ve PWA kurulumu. Üç ayrı salt-okunur denetim yapıldı;
ayrıntılar bu dosyanın devamında (Bölüm A: grafik, Bölüm B: PWA, Bölüm C: diğer sayfalar). Hiçbir kaynak dosya değiştirilmedi.

**Sınır:** denetim kodu okuyarak yapıldı; gerçek cihazda, Lighthouse ile ya da çalışan oturumda ölçülmedi. Raporlarda "(varsayım)"
işaretli maddeler cihazda doğrulanmalıdır. Aşağıdaki P0 = kullanıcıyı engelleyen/yanlış çalışan, P1 = belirgin kalite sorunu, P2 = cila.

## Bu oturumda zaten düzeltilenler
- Yüzen "Asistan" düğmesi mobilde gizlendi, menüye taşındı; basit arayüz "Diğer" menüsü dokunuşla kapanıyor.
- Grafik zaman ekseni ve imleç Türkiye saatine (UTC+3) çevrildi.

## En kritik bulgular (birleşik, önem sırasıyla)

| # | Sorun | Nerede | Önem | Efor |
|---|---|---|---|---|
| 1 | **Mobilde Çıkış yok** (normal kullanıcı oturumu kapatamıyor): Çıkış ve kullanıcı adı yalnız `UserNav` içinde, o da `md:` altında gizli | `components/user/UserNav.tsx:13` | P0 | S |
| 2 | **Alarm bildirimi 404'e gidiyor**: varsayılan bağlantı `/alerts`, frontend'de böyle bir rota yok | `backend/app/alerting.py:80,129`, `public/sw.js:63,85` | P0 | S |
| 3 | **Yeni sürüm kurulu uygulamada fark edilmiyor**: SW her build'de `/sw.js?v=BUILD` ile kayıtlı, baytlar aynı kalıyor; sürüm kıyası ve `registration.update()` yok; ChunkLoadError tanınmıyor | `sw.js`, `error.tsx`, `global-error.tsx` | P0 | M |
| 4 | **iPhone push kurulumu tamamlanamıyor**: Safari kullanıcısına "Chrome kullanın" deniyor; Safari sekmesinde `PushManager` yok | `PushOnboardingModal.tsx:66,130`, `lib/push.ts:11-21` | P0 | M |
| 5 | **Grafik tablosu olası taşma**: `globals.css:523` mobilde her `table`'a `min-width:680px` veriyor; lightweight-charts kendini `<table>` ile kurduğu için fiyat ekseni kırpılabilir. Önce 360 px emülasyonda ölçülmeli | `globals.css:523` | P0 (doğrula) | S |
| 6 | **CSS sırası Tailwind sınıflarını eziyor**: `.input` / `.ui-button` katmansız ve `@tailwind utilities`'ten sonra; `text-base min-h-[48px]` yazan ~10 girdi gerçekte 14 px / 40 px (iOS odak zoom'u) | `globals.css:6,255,435` | P1 | S |
| 7 | **Açık temada kontrast ≈2,9:1**: `bg-neon-green/red` + `text-white` (Sat, tehlikeli onay, toast, birincil düğmeler) | çok sayıda bileşen | P1 | S |
| 8 | **WS aynı-mum güncellemesi `bars`'a yazılmıyor**: alt şerit RSI/MFI/OBV, basınç bandı ve "canlı" fiyat 60 sn'ye kadar bayat | `charts/page.tsx:771` | P1 | S |
| 9 | **WS, uygulama öne gelince/ağ dönünce hemen yeniden bağlanmıyor**; ölü soket ~60 sn açık sayılabiliyor; API isteklerinde zaman aşımı yok | `lib/liveSocket.ts` | P1 | S-M |
| 10 | **Asistan çekmecesi mobilde**: `bottom-16`, `z-[95]`, `vh`, safe-area yok; sidebar çekmecenin arkasında kalıyor; girdi 12 px | `ChartAssistantDrawer.tsx:170` | P1 | S-M |
| 11 | **Modallarda ortak eksikler**: `vh` (dvh değil), arka plan kaydırma kilidi yok, geri tuşu kapatmıyor, `useModalA11y` kullanılmıyor | grafik + users/monitoring/settings/audit | P1 | M-L |
| 12 | **Geniş tablolar yalnız yatay kayıyor** (Portföy, Binance TR emir/işlem, Kullanıcılar, MACD, daily-rising); Portföy için yazılmış mobil kart CSS'i hiçbir yerde kullanılmıyor | ilgili sayfalar | P1 | L |
| 13 | **Push teslimat kalitesi**: `ttl=0` (telefon kısa süre erişilemezse bildirim kaybolur), `Urgency` yok; bildirim ikonu SVG (Android desteklemez) | `alerting.py:90`, `sw.js:56-57` | P1 | S |
| 14 | **Gösterge yeniden kurma maliyeti**: `bars` her değişince tüm seriler/paneller sökülüp yeniden kuruluyor (technical-charts 60 sn ile sınırlı, charts/page.tsx değil) | `charts/page.tsx:1111-1120` | P1 | M-L |
| 15 | **Binance pozisyon grafiği dokunmatik güvenliği**: parmak kalkınca SL/TP gerçek emri onaysız gidebiliyor (admin sayfası `confirmBeforeSend` vermiyor) | `BinancePositionChartModal.tsx` + admin `/binance-tr` | P1 (güvenlik) | S |
| 16 | **Manifest/ikon**: `orientation: portrait-primary` yatay grafiği engelliyor; maskable ikon "any" ile aynı ve şeffaf köşeli; renkler gerçek zeminle uyumsuz | `public/manifest.webmanifest` | P1 | S |
| 17 | **Gizli panel/arka plan yükü**: Ayarlar'da 5 gizli alt panel yükleniyor; Portföy 5/15/30 sn poll; Sohbet yan paneli kapalıyken poll; Kullanıcı Sinyal Raporu 30 sn'de 1000 satır | ilgili sayfalar | P1 | M |
| 18 | **Dokunma hedefleri < 44 px** (aktif gösterge ✕ ≈12 px, pane ⚙/✕ ≈16 px, ayar dişlisi 32 px) ve **12 px altı yazı** (charts/page.tsx'te 36 yerde) | çok sayıda | P1-P2 | M |
| 19 | **iOS bildirimsiz push riski** (görünür sayfada push atlanırsa abonelik iptali; varsayım) ve ses için jestle açılan `AudioContext` yok | `sw.js`, push akışı | P1 | M |
| 20 | **Monitoring rozet satırları sarmıyor**, `overflow-x: clip` taşanı gizlediği için kesilen kısım kaydırılamıyor | `monitoring/page.tsx` | P1 | S-M |
| 21 | **İçerik tutarsızlığı**: sorumluluk reddi "gerçek para kullanılmaz" diyor, uygulama gerçek Binance TR emri veriyor; grafik altında hâlâ "mumlar UTC" yazıyor | `Disclaimer`, `charts/page.tsx:2263` | P1 / P2 | S |

## Önerilen uygulama sırası
1. **Hızlı kazanımlar (yarım gün, en yüksek getiri):** 1, 2, 5 (ölçüp), 6, 7, 16, 21.
2. **Güncelleme ve ağ dayanıklılığı:** 3, 9, 13, 4, 19 (PWA'nın "kurulu uygulama" deneyimini düzeltir).
3. **Grafik kalitesi:** 8, 10, 14, 15, 18.
4. **Ortak bileşenler (büyük refactor):** 11 (`<Modal>`/`<Sheet>`), 12 (`<ResponsiveTable>`), 17.
5. **Kalıcı güvence:** Playwright ile 360×640, 390×844, 430×932 (dikey ve yatay) taşma/modal sığma/z-index testleri; Lighthouse PWA; gerçek iPhone ve Android kontrol listesi.

---

# Bölüm A — Grafik sayfaları (ayrıntılı rapor)

# Grafik Sayfaları — Mobil (360–430 px, dokunmatik) ve PWA Uyum Denetimi

Kapsam: frontend/app/charts/{page.tsx, ChartAssistantDrawer.tsx, IndicatorPicker.tsx, IndicatorSettings.tsx, badgeMarkers.ts, chartShared.ts},
frontend/app/technical-charts/{page.tsx, MultiChartCard.tsx}, frontend/app/binance-tr/BinancePositionChartModal.tsx,
globals.css, layout.tsx, public/manifest.webmanifest, lib/{liveSocket.ts, useVisibleInterval.ts}, components/{BottomNav, user/UserBottomNav, user/AssistantFab, AppShell}.
Yöntem: salt-okunur kod incelemesi (+ lightweight-charts 5.2.0 dist kaynağına bakış). Çalışan uygulamada/cihazda ÖLÇÜM YAPILMADI; kod kanıtı olmayan çıkarımlar "(varsayım)" diye işaretli.
Ciddiyet: P0 = kullanılamaz/veri-para riski, P1 = belirgin mobil kusur, P2 = cila/erişilebilirlik. Efor: S < 0,5 gün, M 0,5–2 gün, L > 2 gün.

---------------------------------------------------------------------
## ÖZET
- Grafik sayfası mobilde temel olarak düşünülmüş (compact yükseklik hesabı, dikey sürüklemenin sayfa kaydırmasına bırakılması, pozisyon kart listesi, görünürlük-farkında polling). Eksikler ince ayar sınıfında değil, birkaç sistemik boşluk: (1) ortak Modal/Sheet davranışı yok (vh, kaydırma kilidi, klavye, geri tuşu, safe-area, a11y), (2) z-index/sabit konum envanteri yok, (3) dokunma hedefleri ve <12px yazı yaygın, (4) PWA yaşam döngüsü (WS uyanışı, orientation kilidi, overscroll) ele alınmamış, (5) iki yüksek riskli olası hata: LWC iç tablosuna uygulanan `table{min-width:680px}` ve WS aynı-mum güncellemesinin `bars`'a yazılmaması.
- Kullanıcının şikâyeti olan "yüzen Asistan düğmesi" mobilde menüye taşınmış (AssistantFab.tsx `hidden md:flex`, charts/page.tsx:2295) — düğme sorunu çözülmüş; ancak AÇILAN çekmece (ChartAssistantDrawer.tsx:170) hâlâ alt çubuklara, safe-area'ya ve sidebar'a binebilir (C1).

---------------------------------------------------------------------
## A. DÜZEN / YATAY TAŞMA / SABİT PX

**A1 (P0, olası — DOĞRULANMALI) Global `table { min-width: 680px }` lightweight-charts'ın iç `<table>`'ına da uygulanıyor.**
- Kanıt: globals.css:523 (`@media (max-width:768px)` içinde `table { min-width: 680px; }`). LWC 5.2 grafiği `<table>` ile kurar (node_modules/lightweight-charts/dist/lightweight-charts.development.mjs:10630) ve tabloya inline `width:<px>` verir (…:10719); kök `div.tv-lightweight-charts` `overflow:hidden` (…:10626). CSS `min-width` inline `width`'i ezer → ≤768 px'te tablo 680 px olur, fiyat ekseni hücresi sağa itilip kırpılabilir (fiyat ekseni/son fiyat etiketi görünmez, yanlış genişlik). Pane başlığı kodu da tabloya bağımlı (page.tsx:1073-1080).
- Doğrulama: mobil emülasyonda `document.querySelector('.tv-lightweight-charts table').getBoundingClientRect().width` ≈ 680 mi?
- Düzeltme: `.tv-lightweight-charts table { min-width: 0 !important; }` ya da global kuralı `.data-table, .table-scroll > table` ile sınırla. Efor: S.

**A2 (P1) `.chart-card > div:first-of-type { min-height: 22rem }` yanlış elemana denk geliyor.**
- Kanıt: globals.css:566. İlk `div`, "AÇIK OTONOM İŞLEM" şeridi (page.tsx:2037, `currentAutoTrade` varken) → mobilde şerit 352 px yüksekliğinde boş kutu olur; grafik kapsayıcısı (page.tsx:2084 `<div ref={containerRef}>`) bu kuraldan fayda görmez.
- Düzeltme: kapsayıcıya sınıf (`.chart-canvas-host`) verip seçiciyi ona bağla. Efor: S.

**A3 (P1) Grafik ilk ekranın altında kalıyor (tahmin).**
- Kanıt: grafik kartından önce sırayla: header (page.tsx:1664), portföy şeridi (1692, flex-wrap, 3 satıra çıkar), TF yönü şeridi (1700-1726; 7×58 px çip 360 px'te 2 satır, kaydırılabilir değil), sembol seçici/araç çubuğu (1728-1815), AKTİF çip satırı (1816-1840), radar bildirim kartı (≈1900-1965, mobilde 2 sütunlu 3 satır) veya ML tahmin kartı (1968-2030). Satır yüksekliklerinden toplam kaba ≈ 600–750 px (varsayım, ölçülmedi) → 360×640–390×844 ekranlarda grafik katlama çizgisinin altında.
- Düzeltme: mobilde sıra: sembol + TF (tek satır, yatay kaydırmalı) → grafik → (katlanır) bildirim/ML/portföy kartları; portföy şeridi tek satır kaydırmalı; TF yönü şeridi `overflow-x-auto flex-nowrap`. Efor: M.

**A4 (P2) Formasyon ipucu (tooltip) 256 px genişlikte ve `left` en fazla 360** — page.tsx:2122-2123 `w-64`, `Math.min(Math.max(x+16,12),360)`; 360 px ekranda sağdan taşıp `overflow-hidden` kartta kırpılır. Düzeltme: `min(x+16, containerWidth-264)`. Efor: S.

**A5 (P2) `.chart-toolbar` CSS grid'inde boş hücreler** — globals.css:549-556: `grid-template-columns: minmax(0,1fr) auto` + `.chart-intervals{grid-column:1/-1}`; ASİSTAN düğmesi satırın tek hücresinde kalıp yanında boşluk bırakıyor; CANLI rozeti/İNDİKATÖR/KAYDET alt satırlara dağılıyor (görsel dağınıklık, işlevsel bozukluk değil). Düzeltme: açık `grid-template-areas`. Efor: S.

**A6 (P1) technical-charts: açılır paneller taşıyor ve kart tarafından kırpılıyor.**
- technical-charts/page.tsx:478 `absolute left-0 … w-80` (320 px; düğme x≈100+ olduğundan 360 px ekranda sağa taşar); MultiChartCard.tsx:753 `w-64`, :842 `w-72 right-0`; kart kökü `overflow-hidden` (MultiChartCard.tsx:736) → paneller kart sınırında kırpılır.
- Düzeltme: <768 px'te `fixed inset-x-2 bottom-2` alt sayfa (bottom sheet) + arka plan; ya da panelleri `createPortal` ile body'ye al. Efor: M.

**A7 (P1) BinancePositionChartModal: sürükleme tutamaç kutusu 256 px.**
- BinancePositionChartModal.tsx:1787 `right-14 sm:right-16 … w-64 pointer-events-none`; TP/SL etiketleri `pointer-events-auto` (…:1812, 1836; ~110-140 px genişlik) → 360 px ekranda sağ ~%40 grafik yatay kaydırmayı çalar; TP ile SL yakınsa etiketler üst üste biner. "Pozisyonu kapat ✕" 28×28 px (…:1801, `h-7 w-7`) giriş çizgisinde, TP/SL etiketleriyle bitişik.
- Düzeltme: tutamaçları ≥44×44 px yap, çakışan etiketleri dikey kaydır (collision), ✕ düğmesini grafikten çıkarıp başlığa/alt çubuğa taşı. Efor: M.

---------------------------------------------------------------------
## B. DOKUNMA HEDEFLERİ ve DOKUNMA/SÜRÜKLEME ÇAKIŞMALARI

**B1 (P1) <44 px dokunma hedefleri (envanter).**

| Yer | Boyut (kod) |
|---|---|
| AKTİF çip "✕" — charts/page.tsx:1829 | çıplak metin düğmesi, ≈12-16 px, aria-label yok |
| Pane başlığı ⚙ / ✕ (DOM ile enjekte) — page.tsx:1087-1102 | font 11px, `padding:0 2px`, ≈16 px; birbirine 5 px; yanlış dokunuş göstergeyi siler |
| Grafik ayarları dişlisi — page.tsx:2140 | `h-8 w-8` = 32 px |
| ML ⟳ / YENİDEN DENE / "＋ EKLE" — page.tsx:1989, 1817 | `px-2 py-1 text-[11px]` ≈ 26 px |
| IndicatorSettings Toggle — IndicatorSettings.tsx:20-31 | 40×20 px, role/aria yok |
| Renk örnekleri — IndicatorSettings.tsx:177 | `w-5 h-5` = 20 px; `type=color` h-5 |
| IndicatorPicker ✕ — IndicatorPicker.tsx:294 | boyutsuz, aria-label yok; kategori çipleri `py-1` (:311) |
| Asistan 🧹 / ✕ — ChartAssistantDrawer.tsx:199, 206 | `p-1.5` ≈ 28 px; hızlı soru çipleri `py-1 text-[11px]` (:264) ≈ 26 px |
| Binance modal TF düğmeleri — BinancePositionChartModal.tsx:1518 | `px-2.5 py-1 text-[11px]` ≈ 26 px yükseklik |
| technical-charts başlık düğmeleri — page.tsx:340-372, MultiChartCard.tsx ~890-912 | `p-1`/`p-1.5` ≈ 24-28 px |

Olumlu: charts/page.tsx modal ✕ (min-h-11), mobil pozisyon KAPAT (min-h-11, :2245), `.chart-interval-button` 2.75 rem (globals.css:560), `.chart-toolbar > button` 2.75 rem.
- Düzeltme: `@media (pointer: coarse)` altında ortak `.hit` yardımcı sınıfı (`min-height/width:44px` ya da `::after{inset:-8px}` ile görünmez büyütme); pane başlık düğmelerini DOM yerine React portal'ı ile kur. Efor: M.

**B2 (olumlu / not) Grafik pan–sayfa kaydırma ayrımı doğru kurulmuş.** page.tsx:365-368 `handleScroll: { vertTouchDrag:false, horzTouchDrag:true }` → LWC 5.2'de dikey sürükleme sayfa kaydırmasına bırakılır, yatay sürükleme grafiği kaydırır (lightweight-charts.development.mjs:9075-9076, 9566-9567); `handleScale` verilmemiş = varsayılan (pinch açık). Aynı ayar MultiChartCard.tsx:445'te de var.
- Sınırlama (P2): fiyat ekseni ve zaman ekseni dokunmayla ölçeklenemiyor (…:9075, 10254 `treatVertTouchDragAsPageScroll: () => true`) → mobilde dikey zoom yok. Öneri: grafiğe "otomatik ölçek / sıfırla / +/-" mini düğmeleri. Efor: S–M.
- Not: LWC kendi `touch-action` CSS'ini koymuyor (dist'te yok); davranış JS'te `preventDefault` ile — yatay pan sırasında dikey kayma "sızabilir" (varsayım; cihazda dene). Kapsayıcıya `touch-action: pan-y pinch-zoom` eklemek bunu netleştirir.

**B3 (P1) Mobilde aşırı sıkışık mum yoğunluğu + rozet çakışması.**
- Kanıt: page.tsx:448 `limit=200` ve :477 `fitContent()` → ~330 px genişlikte mum başına ≈1,6 px (mum gövdesi seçilemez). badgeMarkers.ts:21-27: rozet sabit 28 px yükseklik, ≥44 px genişlik, 13 px kalın yazı, çakışma önleme yok → bar aralığı 2 px iken onlarca rozet üst üste biner (tek bulut).
- Düzeltme: `compact` ise ilk görünümde son 60–90 mum (`timeScale().setVisibleLogicalRange`), rozetleri `barSpacing < ~8` iken küçük nokta/ok olarak çiz ya da minimum yatay mesafe filtresi uygula. Efor: M.

**B4 (P2) Çift dokunma yakınlaştırma yalnız `button, a` için kapalı** — globals.css:49 `touch-action: manipulation` yalnızca düğme/bağlantıda; metin/kart alanlarında çift dokunma zoom'u çalışır. viewport'ta `maximumScale` yok (erişilebilirlik için doğru) → `html { touch-action: manipulation }` ekle. Efor: S.

**B5 (P1, PWA) Pull-to-refresh / overscroll yönetimi yok.** `overscroll-behavior` yalnız sidebar'da (globals.css:33). Android PWA'da sayfa en üstteyken (ör. technical-charts'ta grafikler üstte) aşağı sürükleme yenilemeyi tetikler ve grafik/durum kaybolur; modallarda scroll zinciri arka sayfayı kaydırır. Düzeltme: `html, body { overscroll-behavior-y: contain }` + kaydırılabilir iç alanlara `overscroll-behavior: contain`. Efor: S.

**B6 (P1, güvenlik) Dokunmatikte parmağı kaldırınca gerçek emir gidiyor (admin).**
- Kanıt: BinancePositionChartModal.tsx:1119-1121 (`if (… || confirmBeforeSend) return;` aksi halde `touchend` → `handleMouseUp` → `/api/binance/set-sl-tp`, `cancel_existing:true`). Kullanıcı kabuğu `confirmBeforeSend` geçiyor (components/user/binance/HoldingsCard.tsx:269) ama admin /binance-tr sayfası geçmiyor (binance-tr/page.tsx:2720-2733). Mobilde yanlışlıkla sürüklenen SL/TP çizgisi onaysız canlı emir değiştirir; `touchmove` `preventDefault` ile sayfayı da kilitler (…:1169-1172).
- Düzeltme: `window.matchMedia('(pointer: coarse)')` ise `confirmBeforeSend` zorunlu; ya da tutamaç için "uzun bas → sürükle" kollama. Efor: S.

---------------------------------------------------------------------
## C. YÜZEN/YAPIŞKAN ÖĞELER, Z-INDEX, SAFE-AREA

**C1 (P1) Asistan çekmecesi alt çubuk/safe-area/sidebar ile çakışıyor.**
- Kanıt: ChartAssistantDrawer.tsx:170 `fixed bottom-16 md:bottom-4 right-3 … z-[95] w-[94vw] sm:w-[440px] h-[580px] max-h-[75vh]`. Alt çubuklar: admin BottomNav z-40, yükseklik ≈ 44 px touch-target + py-1 + `max(0.35rem, env(safe-area-inset-bottom))` (BottomNav.tsx:24-26) → iPhone'da ≈ 90 px, `bottom-16` = 64 px → çekmece alt çubuğun üst kısmını örter; UserBottomNav z-30 (UserBottomNav.tsx:33). Çekmece sidebar (z-50) ve ☰ düğmesinin (z-40) üstünde (z-95): çekmece açıkken menüyü açınca menü çekmecenin ARKASINDA kalır. `bottom-16` ve `max-h-75vh` safe-area/dvh içermiyor.
- Kullanıcının şikâyetinin devamı: yüzen düğme kalktı ama "açılan pencere diğer öğelerin üstüne biniyor" sınıfı hâlâ var.
- Düzeltme: <768 px'te çekmeceyi tam ekran alt sayfa yap (`inset-x-0 bottom-0 h-[min(85dvh,640px)]`, `padding-bottom: env(safe-area-inset-bottom)`, arka plan karartma + kaydırma kilidi), z-index'i token'a bağla (C2). Efor: M.

**C2 (P1) z-index envanteri tutarsız (token yok).**
- Mevcut: topbar sticky z-20 (globals.css:34); mobil menü düğmesi z-40, BottomNav z-40, UserBottomNav z-30, sidebar z-50 / backdrop z-45; IndicatorPicker, IndicatorSettings, Binance modal, ConfirmDialog z-50 (aynı seviye: sidebar ile eşit); grafik ayarları + analiz modalı z-90; yüzen asistan z-80; çekmece z-95; bildirim modalı z-100; Radar log z-110; onboarding z-115; Disclaimer z-200; technical-charts tam ekran z-9998/9999 (MultiChartCard.tsx:739, page.tsx:326).
- Olası görsel hata (varsayım): grafik kartı `relative` fakat `isolation`/z-index yok → kart içi `z-20` (page.tsx:2134 geri sayım + dişli) ve `z-30` (page.tsx:2122 ipucu) aynı yığın bağlamında sticky topbar (z-20, DOM'da önce) ile yarışır; kaydırırken grafik üst bandın üstüne çıkabilir. Düzeltme: `.chart-card { isolation: isolate }`.
- Öneri: CSS değişkenleri `--z-nav:40; --z-drawer:60; --z-modal:90; --z-toast:200; --z-fullscreen:300` ve tüm değerleri buna bağla. Efor: S–M.

**C3 (P1) Safe-area kapsamı eksik.**
- Var: `.content-shell` top/bottom (globals.css:479, 597), BottomNav, UserBottomNav, mobil menü düğmesi (globals.css:555), `viewportFit: "cover"` (layout.tsx:40).
- Yok: tam ekran katmanlar — Binance modal (`h-[100dvh]`; başlık çentik/durum çubuğu altında kalabilir, `statusBarStyle` ayarı yok, varsayılan iOS davranışında sorun çıkmayabilir → varsayım), technical-charts `fixed inset-0` tam ekran (page.tsx:326, MultiChartCard.tsx:739), çekmece, bildirim modalları. `env(safe-area-inset-left/right)` projede hiç yok → iOS yatay modda çentik içeriği keser.
- Düzeltme: ortak `.safe-pad` yardımcıları (top/right/bottom/left) ve tam ekran katmanlara uygulama. Efor: S.

**C4 (P2) Tema rengi sabit.** layout.tsx:37-42 `themeColor: "#05080d"`; kullanıcı (açık tema) kabuğunda UserShell `data-theme=light` yapıyor ama `<meta name=theme-color>` güncellenmiyor → Android durum çubuğu koyu, içerik açık. Düzeltme: UserShell'de `meta[name=theme-color]` güncelle. Efor: S.

---------------------------------------------------------------------
## D. PENCERE / MODAL / ÇEKMECE / KLAVYE

**D1 (P1) `vh` kullanımı (mobil adres çubuğu/klavye).** Yalnız Binance modal `100dvh` (BinancePositionChartModal.tsx:1450). Diğerleri: analiz modalı `h-[92vh]` (charts/page.tsx:1844), grafik ayarları `max-h-[86vh]` (:1854), IndicatorPicker `max-h-[85vh]` (IndicatorPicker.tsx:291), IndicatorSettings `max-h-[90vh]` + iç `max-h-[60vh]` (IndicatorSettings.tsx:134, 147), çekmece `max-h-[75vh]` (Drawer:170), technical-charts `h-[calc(100vh-4rem)]` (page.tsx:327). `vh` = en büyük görünüm → adres çubuğu açıkken alt kısım ekran dışında kalır. (globals.css'te başka yerlerde `dvh` kullanılıyor — tutarsızlık.) Düzeltme: `dvh` + `vh` yedek, `max-h-[min(90dvh,…)]`. Efor: S.

**D2 (P1) Arka plan kaydırma kilidi yok.** Grafik modal/çekmeceleri (analiz, ayarlar, seçici, çekmece, Binance) `body` kaydırmasını kilitlemiyor; yalnız Sidebar.tsx:74 ve RadarScanLogModal.tsx:160 kilitliyor. Mobilde modal içi kaydırma bitince arkadaki sayfa kayar (scroll chaining), iOS lastik efekti. Çekmece mesaj listesi `overflow-y-auto` ama `overscroll-behavior` yok. Düzeltme: ortak `useBodyScrollLock(open)` + `overscroll-behavior: contain`. Efor: S.

**D3 (P1) Klavye ve iOS otomatik yakınlaştırma.**
- <16 px girdiler: Drawer girdisi `text-xs` (Drawer:287), IndicatorPicker arama `text-sm` + `autoFocus` (IndicatorPicker.tsx:300-304), IndicatorSettings sayı/select `text-sm` (IndicatorSettings.tsx:47, 65), chart-symbol-select `text-sm` (charts/page.tsx:1733, 1745), technical-charts sembol girdileri `text-xs` (page.tsx:394, MultiChartCard.tsx:774). iOS Safari odaklanınca sayfayı yakınlaştırır; standalone PWA'da geri alma zor. Sohbet sayfası bunu bilip 16 px yapmış (globals.css:511) — grafiklerde uygulanmamış.
- `autoFocus` (IndicatorPicker) mobilde modal açılır açılmaz klavyeyi açar; liste klavyenin altında kalır (`max-h-[85vh]` klavye sonrası küçülmez).
- Klavye ile yeniden boyutlanma: viewport meta'da `interactive-widget` yok (Android Chrome varsayılanı: yalnız görsel viewport küçülür) → `fixed bottom` çekmece girdisi klavyenin arkasında kalabilir (varsayım). Düzeltme: mobilde `input,select,textarea{font-size:16px}`, `autoFocus`'u coarse pointer'da kaldır, `visualViewport` ile çekmece alt konumunu ayarla ya da `interactive-widget=resizes-content`. Efor: S–M.

**D4 (P1, PWA) Geri tuşu modalı/çekmeceyi kapatmıyor.** Hiçbir grafik modal/çekmecesi `history.pushState` kullanmıyor (charts/ içinde popstate yok). Android standalone'da sistem geri tuşu modal yerine sayfayı terk eder. (Sayfa "← GERİ" düğmesi doğru: page.tsx:1668.) Düzeltme: ortak Sheet/Modal bileşeninde açılışta `pushState`, `popstate`'de kapat. Efor: S–M.

**D5 (P2) Erişilebilirlik.**
- `useModalA11y` var (lib/useModalA11y.ts; Binance, ConfirmDialog, BuyDialog vb. kullanıyor) ama charts/page.tsx modalleri (analiz :1843, ayarlar :1853), IndicatorPicker, IndicatorSettings ve Drawer kullanmıyor → odak tuzağı/Esc yok. Drawer `role="dialog"`/`aria-label`/`aria-live` taşımıyor (mesaj akışı ekran okuyucuya duyurulmuyor). IndicatorPicker ✕, AKTİF ✕, pane düğmeleri, IndicatorSettings Toggle (role="switch"/aria-checked yok; oysa charts/page.tsx:1862 ayarlar anahtarları doğru yapılmış) etiketsiz. technical-charts düğmeleri yalnız `title` ile (dokunmatikte görünmez). Durum bilgisi bazı yerlerde yalnız renkle (RSI/MFI bölgesi; TF yönü ok + renk — iyi).
- Düzeltme: ortak Modal/Sheet + `role="switch"` Toggle + etiketler. Efor: M.

**D6 (P1) Fullscreen API iPhone'da yok → hata.** technical-charts/page.tsx:117 ve MultiChartCard.tsx:404 `el.requestFullscreen().catch(...)` — iPhone Safari'de öğe için `requestFullscreen` tanımsız (varsayım; iPadOS'ta var) → `TypeError` fırlar, düğme sessizce çalışmaz. Düzeltme: özellik algılama + CSS ile `fixed inset-0 h-dvh` yedek tam ekran (safe-area'lı). Efor: S.

**D7 (P2) Analiz modalı `iframe`** (page.tsx:1846): iç içe kaydırma + `h-[92vh]`; iframe içinde ayrıca `min-h-screen overflow-y-auto` (AppShell.tsx embedded dalı). Mobilde iOS iframe kaydırması takılabilir. Öneri: mobilde iframe yerine rota ile tam sayfa açmak. Efor: S.

---------------------------------------------------------------------
## E. GRAFİK YÜKSEKLİĞİ ve YENİDEN BOYUTLANDIRMA

**E1 (P1) Piksel tabanlı, `window.innerHeight`'a bağlı yükseklik; ilk çizimde 600 px.**
- Kanıt: `chartHeightRef = useRef(TOTAL_HEIGHT)` = 600 (page.tsx ~164; chartShared.ts:21) → grafik ilk 600 px ile yaratılır (page.tsx:358), sonra ResizeObserver düzeltir (page.tsx:395-413) → mobilde kısa süreli yükseklik sıçraması/yerleşim kayması (CLS). Hesap `preferredChartHeight`/`computePaneLayout` (chartShared.ts:34-80) `innerHeight` kullanır ve RO kapsayıcıyı gözlediği için YALNIZ kapsayıcı GENİŞLİĞİ değişince yeniden hesaplar: adres çubuğu gizlenip `innerHeight` değişince, klavye/dvh değişince hesap güncellenmez (yükseklik kararlı kalır ama ekrana oransız olabilir). Yön değişimi genişliği değiştirdiği için tetikler (iyi). Yatay modda (ör. 844×390): `targetTotal` ≈ 359 px, `baseMin` 300 → grafik neredeyse tüm yüksekliği kaplar, alt paneller 108–136 px'e sıkışır (okunurluk riski).
- Eşik uyumsuzluğu: JS `compact = innerWidth < 768` (page.tsx:398, 1057) ↔ CSS `max-width: 768px` (globals.css:472) → tam 768 px'te CSS mobil, JS masaüstü hesabı. Düzeltme: tek `matchMedia('(max-width: 768px)')`.
- Düzeltme: yüksekliği CSS'le ver (`height: clamp(340px, 62dvh, 640px)`), RO yalnız boyutu uygulasın; `visualViewport` resize + `orientationchange` dinle; ilk karede `window.innerHeight`'tan başlat. Efor: M.

**E2 (P1, PWA) Manifest yönü kilitli.** public/manifest.webmanifest:7 `"orientation": "portrait-primary"` → Android'de kurulu uygulama yatay çevrilemez; grafik analizi için yatay en doğal mod. (iOS manifest `orientation`'ı yok sayar → iOS'ta yatay serbest; E1 yatay yerleşimi bu yüzden önemli.) Düzeltme: `"any"` (ya da alanı kaldır). Efor: S.

**E3 (P2) technical-charts mobil yerleşim.** `h-full min-h-[300px]` kartlar + `grid-rows-2` (page.tsx:304-307) — 4'lü şablonda mobil `grid-cols-1 grid-rows-2` → 4 kart için 2 açık + 2 örtük satır; dış kapsayıcı `h-[calc(100vh-4rem)]` (page.tsx:327) içeriği tutmuyor (kartlar taşıyor); admin kabuğunda üst bant + alt çubuk + `content-shell` dolgusu bu 4rem varsayımını bozuyor (varsayım: ek kaydırma). Düzeltme: mobilde tek sütun, kart başı `h-[60dvh]`, sayfa kaydırılabilir. Efor: M.

---------------------------------------------------------------------
## F. PERFORMANS ve CANLILIK

**F1 (P1) Her `bars` değişiminde tüm gösterge serileri/pane'ler söküp yeniden kuruluyor.**
- Kanıt: page.tsx:1111-1120 (`[instances]` ve `[bars]` efektleri; bağlanmada ikisi de çalışır = çift kurulum); buildLayout içinde tüm seri/pane silinir, `entry.calculate(bars)` ile gösterge baştan hesaplanır, pane başlıkları `requestAnimationFrame`'de DOM'a enjekte edilir (page.tsx:861-872, 1067-1110). `reloadKlines` her turda yeni dizi ile `setBars` çağırıyor, eşitlik kontrolü yok (page.tsx:465) → WS kapalıyken 10 sn'de, açıkken 60 sn'de (page.tsx:499) ve her yeni mumda tam yeniden kurulum. technical-charts'ta eşitlik kontrolü + yeniden kurma eşiği (60 sn) var (MultiChartCard.tsx:82, 475) — charts/page.tsx'te yok.
- Etki: orta seviye telefonlarda 14 gösterge × 200 mum eşzamanlı hesap + canvas/pane yeniden kurma → titreme, pil. Pane yükseklikleri `skipHeight=true` yolunda yeniden uygulanmıyor (page.tsx:1054-1067): yeni pane'ler varsayılan oranla doğar → her tazelemede kullanıcının ayarladığı yükseklikler sıfırlanıyor olabilir (varsayım — cihazda doğrula).
- Düzeltme: (a) `setBars` öncesi son mum zamanı+close+uzunluk karşılaştır; (b) tam yeniden kurma yalnız `instances`/sembol/TF değişiminde; yeni mumda yalnız son noktaları `series.update`; (c) hesapları `startTransition`/idle parçalara bölmek veya Web Worker. Efor: M–L.

**F2 (P2) Hesap ana iş parçacığında.** Gösterge `calculate` çağrıları eşzamanlı (page.tsx ~895); `strongCandlestickPatterns(bars)` aynı veri için iki ayrı efektte tekrar hesaplanıyor (page.tsx ~1272-1325). Ölçüm önerisi: DevTools Performance, 4× CPU throttle, Long Task > 50 ms var mı. Efor: S (ortak memo).

**F3 (P1, doğruluk) WS ile gelen aynı-mum güncellemesi `bars`'a yazılmıyor.**
- Kanıt: page.tsx:771 `const next = bar.time === last.time ? prev : [...prev.slice(-199), bar]; barsRef.current = next; setBars(next)` → aynı mumda `prev` aynen döner (son mumun close/high/low'u güncellenmez) ve React aynı referansla yeniden render etmez. Sonuç: `candleRef.update` canvas'ı canlı çizer ama `bars`'a bağlı her şey yeni mum ya da HTTP turuna (WS açıkken 60 sn) kadar bayat: alt şerit RSI/MFI/OBV (page.tsx:1617-1621; yorum "WS ile canlı tazelenir" diyor), alıcı/satıcı basıncı (:1604-1613), `monitorLivePrice` → "canlı" fiyat ve "HEDEFE ULAŞILDI" (page.tsx:1650-1655) 60 sn'ye kadar gecikebilir, Asistan'a giden `currentPrice` (page.tsx:2277).
- Düzeltme: son mumu yeni nesneyle değiştir (`[...prev.slice(0,-1), bar]`), yazımı rAF/250 ms ile throttle et. Efor: S.

**F4 (P1, PWA) WS uyanış/bağlantı yaşam döngüsü eksik.** lib/liveSocket.ts yalnız `onclose` + 15 sn'de bir kontrol / 45 sn sessizlik eşiği (liveSocket.ts:73-98); `visibilitychange`, `pageshow` (bfcache), `online` olayları yok. Arka plandan dönen mobil PWA'da soket "open" görünse de ölü olabilir; en kötü ≈ 60 sn donuk veri ve bu sürede HTTP yedek aralığı da 60 sn (page.tsx:499, `liveStatus==="open"`). (HTTP tazeleme görünür olunca anında çalışıyor — useVisibleInterval `runOnVisible` — bu yüzden mum akışı toparlanır; portföy/pozisyon WS mesajları gecikebilir.) Düzeltme: `visibilitychange→visible` ve `online`'da son mesaj yaşı > ~5 sn ise soketi kapat-yeniden aç ve `reloadKlines`/özetleri hemen çağır; HTTP aralığını `liveStatus` yerine "son WS mesaj yaşı"na bağla. Efor: S–M.

**F5 (P2) Görünürlük-farksız zamanlayıcılar.** `CountdownSec` kendi `setInterval(1000)`'ı (page.tsx:105), MultiChartCard `CardCandleCountdown` 250 ms `setInterval` ×4 kart (MultiChartCard.tsx:327), Binance modal 1 sn geri sayım (BinancePositionChartModal.tsx:566; 547'deki `document.hidden` korumalı). Arka planda tarayıcı kısıyor ama kuyrukta kalır. Düzeltme: `useVisibleInterval`'a geçir. Efor: S.

**F6 (P1) technical-charts mobilde varsayılan 4'lü ızgara.** page.tsx:83 `useState("grid4")`: telefonda 4 grafik alt alta, her biri 6 sn'de bir 300 mum çekiyor (MultiChartCard.tsx:713) ve 14 gösterge kurabiliyor → CPU/pil/veri. Düzeltme: <768 px'te varsayılan `single`, gizli kartların polling'ini durdur (IntersectionObserver). Efor: S–M.

**F7 (P2)** `subscribeCrosshairMove` her harekette `setState` (MultiChartCard.tsx:446-451, charts/page.tsx:1413-1427 `showPatterns` açıkken) — rAF ile throttle. Efor: S.

Olumlu: görünürlük-farkında polling'in büyük kısmı `useVisibleInterval` ile yapılmış (page.tsx:82, 351, 499, 572, 671-689, 715); geri sayım izole bileşende; `loadPersisted` try/catch'li.

---------------------------------------------------------------------
## G. OKUNABİLİRLİK / KONTRAST / TEMA

**G1 (P2) 12 px altı yazı yaygın.** Sayım (`text-[9..11px]`): charts/page.tsx 36 (22×10px, 13×11px, 1×9px), Binance modal 39 (13×10, 21×11, 5×9), MultiChartCard 21, technical-charts/page 14, IndicatorSettings 10, Drawer 4, Picker 2. Önemli veriler küçük puntoda: TF şeridi etiketi (page.tsx:1702, 1720), alt gösterge şeridi etiket/bölge/TF (:2113-2116), radar kartı alan etiketleri (:1930-1954), pozisyon kartı strateji satırı (:2233), CANLI/TAZELEMEDE rozeti (:1786), Asistan zaman damgası `text-[9px]`. Ayrıca `.topbar-kicker` .5rem, `.topbar-status` .52rem (globals.css mobil bloğu).
- Düzeltme: mobilde alt sınır 12 px (`--text-2xs: .75rem` token), veri alanlarını 12–14 px yap. Efor: M.

**G2 (P2) Kontrast ve tanımsız sınıflar.**
- IndicatorPicker.tsx:304 `placeholder-bunker-700` (#444875 / #0f1131 ≈ 2,1:1 — WCAG 4,5:1 altı; kendi hesabım); technical-charts `placeholder-bunker-600` ≈ 3,8:1. `text-bunker-muted` (#aeb2c7) koyu zeminde yeterli.
- Tailwind 3.4'te olmayan/yapılandırılmamış sınıflar sessizce etkisiz: Drawer'da `text-bunker-100/200/500` (tailwind.config'te yalnız 950–600 + muted), `rounded-bl-xs/br-xs`, `animate-in fade-in slide-in-from-bottom-5` (tailwindcss-animate yok; Binance modal da aynı), `backdrop-blur-xs` (Binance modal) → metin rengi/animasyon beklendiği gibi değil.
- Düzeltme: renk token'larını tamamla veya sınıfları kaldır. Efor: S.

**G3 (P2) Açık/koyu tema.** Grafik zemini temaya göre ayarlanıyor ve MutationObserver ile güncelleniyor (page.tsx:360, 373-383 — iyi). Ancak: SWATCH `#e5e7eb` (IndicatorSettings.tsx:16) beyaz zeminde görünmez; neon sarı gibi varsayılan renkler beyazda düşük kontrast; pane başlığı DOM'u sabit koyu (page.tsx:1087); technical-charts kendi `isDark` anahtarına sahip (uygulama temasından bağımsız, MultiChartCard.tsx ~392); Binance modal sabit koyu `#080b10` (kabul edilebilir). Efor: S.

**G4 (P2) Yanlış metin: "mumlar UTC".** page.tsx:2263 alt notu hâlâ "mumlar UTC" diyor; zaman ekseni İstanbul'a çevrildi → "mumlar Türkiye saati (UTC+3)". Efor: S.

---------------------------------------------------------------------
## H. ÜST KONTROLLER / SARMA

**H1 (P2)** `.chart-intervals` yatay kaydırılabilir ve gizli kaydırma çubuklu (globals.css:559-561) ama kaydırma ipucu yok; projede hazır `.tab-scroll-fade` var (globals.css ~590; monitoring/page.tsx:1153 kullanıyor) — burada kullanılmamış. TF yönü şeridi (page.tsx:1700) sarıyor (kaydırmıyor) ve mobilde 2 satır yer kaplıyor; AKTİF çipleri `flex-wrap` (iyi) ama çip + ✕ küçük (B1). Düzeltme: iki şeride `overflow-x-auto flex-nowrap tab-scroll-fade`. Efor: S.

**H2 (P2)** Basit modda (`!isAdvanced`) araç çubuğu yalnız sembol seçici; TF değişimi yalnız TF yönü şeridinden (page.tsx:1702-1726) — keşfedilebilirlik düşük ama çalışır.

---------------------------------------------------------------------
## I. PWA'YA ÖZGÜ

| # | Bulgu | Ciddiyet | Not |
|---|---|---|---|
| I1 | `orientation: portrait-primary` (manifest:7) | P1 | bkz. E2 |
| I2 | Overscroll/pull-to-refresh yönetimi yok | P1 | bkz. B5 |
| I3 | Modal/çekmece geri tuşu | P1 | bkz. D4 |
| I4 | `theme-color` sabit; açık temada uyumsuz | P2 | bkz. C4 |
| I5 | `maskable` ikon `any` ile aynı dosya (Icon-512.png, manifest:15-16) | P2 (varsayım) | maskable güvenli bölge uygulanmamışsa Android'de logo kırpılır; ayrı maskable PNG üret. |
| I6 | Uzun basma (context menu): Binance modal `onContextMenu` özel menü açıyor (BinancePositionChartModal.tsx:1744-1749, 1879-1882; Android uzun basma = contextmenu; `left: min(x, innerWidth-260)` 260 px'ten dar ekranda negatif) | P2 | Grafik sayfalarında `-webkit-touch-callout:none; user-select:none` kapsayıcıda yok (LWC kendi öğesinde `disableSelection` yapıyor); kartlarda metin seçimi/uzun basma menüsü çıkabilir. |
| I7 | `display_override`/`screenshots`/`shortcuts` yok | P2 | İsteğe bağlı. |
| I8 | Durum çubuğu: `black-translucent` kullanılmadığından `safe-area-inset-top` çoğunlukla 0 (varsayım) | bilgi | Tam ekran katmanlar yine de safe-area ile korunmalı (C3). |
| I9 | Service worker: HTML network-first, hashed asset cache (public/sw.js:172-209) | olumlu | |
| I10 | Çift dokunma zoom/`touch-action` | P2 | bkz. B4 |

---------------------------------------------------------------------
## Geliştirilmesi gereken kısımlar (öncelikli yol haritası, en çok 12)

1. **[P0-doğrula / S] LWC iç tablosuna `min-width:680px` kuralını durdur** (A1) ve `.chart-card > div:first-of-type` seçicisini düzelt (A2). Önce 360 px emülasyonda `.tv-lightweight-charts table` genişliğini ölç; sorun doğrulanırsa tek satırlık CSS düzeltmesi.
2. **[P1 / S] WS aynı-mum güncellemesini `bars`'a yaz** (F3, page.tsx:771) — alt şerit, basınç bandı, "canlı" fiyat ve hedefe-ulaşıldı bayatlığını giderir; yazımı 250 ms'e throttle et.
3. **[P1 / M] Ortak `Sheet/Modal` bileşeni**: `dvh`, kaydırma kilidi, `useModalA11y`, geri tuşu (`pushState/popstate`), safe-area (top/bottom/left/right), mobilde alt sayfa/tam ekran, 16 px girdi. Asistan çekmecesi, gösterge seçici/ayarları, grafik ayarları, analiz modalı buna taşınsın (C1, D1–D5). Z-index token tablosu ile birlikte (C2).
4. **[P1 / S–M] Asistan çekmecesini mobilde tam ekran/alt sayfa yap**; alt çubuk yüksekliği + safe-area'ya göre konumlandır; açıkken sidebar/menü çakışmasını kaldır (C1).
5. **[P1 / M] Dokunma hedefleri ≥44 px** (`pointer:coarse` yardımcı sınıfı): AKTİF ✕, pane ⚙/✕ (React portal'a taşı), ayar dişlisi, Toggle, renk örnekleri, çekmece/seçici düğmeleri, Binance TF/✕, technical-charts başlığı (B1).
6. **[P1 / M] Mobil ilk ekran düzeni**: sembol+TF → grafik → katlanır kartlar; TF şeridi/portföy şeridi tek satır kaydırmalı; compact'ta son 60–90 mum görünür + rozet seyreltme/küçültme (A3, B3, H1).
7. **[P1 / M–L] Gösterge yeniden kurma optimizasyonu**: aynı veriyi atla, yalnız son noktaları güncelle, tam yeniden kurmayı yapı değişimine bağla; pane yüksekliklerini yeniden uygula; ağır hesapları worker/idle'a taşı; çift mount-efektini kaldır (F1, F2, F7).
8. **[P1 / S–M] PWA yaşam döngüsü**: `visibilitychange/pageshow/online` ile WS yeniden bağlanma + anlık veri tazeleme; HTTP yedek aralığını son-mesaj-yaşına bağla; zamanlayıcıları `useVisibleInterval`'a geçir (F4, F5).
9. **[P1 / S] Manifest ve global CSS**: `orientation:"any"`, `html,body{overscroll-behavior-y:contain; touch-action:manipulation}`, `theme-color` temaya göre güncelleme, `input,select,textarea{font-size:16px}` (mobil), maskable ikon (E2, B4, B5, C4, D3, I5).
10. **[P1 / M] technical-charts mobil modu**: varsayılan `single`, açılır paneller alt sayfa, kartlarda `overflow` kırpmasını kaldır, Fullscreen API yedeği (CSS tam ekran + safe-area), gizli kartların polling'ini durdur (A6, D6, E3, F6).
11. **[P1 / S] Binance pozisyon grafiği dokunmatik güvenliği**: coarse pointer'da onay zorunlu (admin sayfası `confirmBeforeSend`), tutamaçlar ≥44 px ve çakışma önleme, ✕ düğmesini taşı (A7, B6).
12. **[P2 / M] Tipografi/kontrast/tema temizliği + test düzeneği**: 12 px alt sınır token'ı, placeholder kontrastı, tanımsız Tailwind sınıfları, açık tema renkleri, "mumlar UTC" metni (G1–G4); Playwright mobil emülasyon testleri (360×640, 390×844, 430×932 ve yatay; chart yüksekliği, taşma, modal sığma, z-index sırası) + Lighthouse PWA + gerçek iOS/Android kontrol listesi.

---------------------------------------------------------------------
### Doğrulama notları / sınırlar
- Hiçbir kaynak dosya değiştirilmedi, git komutu çalıştırılmadı; çalışan uygulamada ölçüm yapılmadı (oturum/AuthGate nedeniyle).
- "(varsayım)" işaretli maddeler: A3 yükseklik toplamı, C2 grafik-üstü-topbar bindirmesi, C3 iOS durum çubuğu, D3 klavye davranışı, D6 iPhone fullscreen, F1 pane yüksekliği sıfırlanması, I5 maskable. A1 kodla güçlü biçimde desteklenir ama görsel doğrulama gerekir.
- F3 (WS aynı-mum bayatlığı) mobil olmayan ama ilgili, masaüstünde de geçerli.


---

# Bölüm B — PWA kurulumu ve ortak kabuk (ayrıntılı rapor)

# PWA kurulumu ve ortak mobil kabuk denetimi — 2026-10-18

Kapsam: manifest, sw.js, ikonlar, layout metadata/viewport, globals.css mobil kuralları, AppShell/Sidebar/BottomNav/TopBar/PortfolioBand/AppLoader, Push/Notification modalları, RadarAlertModal, user kabuğu, nginx + next.config önbellek başlıkları, web push (backend `alerting.py` dahil), liveSocket. SALT OKUNUR: hiçbir kaynak dosya değiştirilmedi, git kullanılmadı.
Yöntem notu: üretim build'i (`.next`) yok ve cihaz/Lighthouse çalıştırılmadı; kodla kanıtlanabilen her şey `dosya:satır` ile verildi, doğrulanamayanlar **[VARSAYIM]** diye işaretli. Efor: S (<1 sa), M (yarım-1 gün), L (>1 gün). Yollar `frontend/` altındadır (aksi belirtilmedikçe).

## Hüküm

Temel iskelet sağlam: SW dar kapsamlı (yalnız navigasyon + `/_next/static`; API/RSC/WS'ye dokunmuyor), HTML network-first, sw.js `no-store`, `/_next/static` immutable, push için `pushsubscriptionchange` + açılışta sessiz uzlaştırma, `useVisibleInterval` ve tek paylaşımlı WS (heartbeat + backoff) var. Buna rağmen "kurulu PWA, her deploy sonrası yeni sürüm gelmeli" hedefi için **güncelleme mimarisinde yapısal bir açık** var (SW URL'si her build'de değişiyor; arka plandan dönen kurulu uygulama yeni sürümü hiç fark etmiyor), **alarm bildirimine dokununca 404'e gidiliyor**, iPhone için **onboarding yanlış yönlendiriyor** ve **iOS'ta sayfa açıkken bildirimsiz atlanan push abonelik iptaline yol açabilir**. Android'de push `ttl=0` + normal aciliyet olduğundan Doze'da bildirim kaybı olası.

Önem özeti: 3 adet P0 (S1, P1, I1), çok sayıda P1/P2 — aşağıda.

---

## 1. Manifest (`public/manifest.webmanifest`)

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| M1 | P1 | manifest:7 | `"orientation": "portrait-primary"` — Android'de kurulu PWA'yı dikey kilitler; **yatay grafik** (lightweight-charts) kullanılamaz, tablette (doğal yatay) uygulama dikeye zorlanır, ters dikey de engellenir. iOS bu alanı yok sayar (iPhone'da yatay dönüş serbest — bkz. V1). | `"orientation": "any"` (veya alanı kaldır). Dikey tercih ediliyorsa kilidi yalnız ihtiyaç duyan ekranda `screen.orientation.lock` ile uygula. | S |
| M2 | P1 | manifest:13-16 | Maskable ikon, "any" ikonla **aynı dosya** (`icons/Android/Icon-512.png`). Dosya RGBA ve **köşeleri şeffaf yuvarlatılmış kare** (görsel okundu). Maskable'da şeffaf köşeler launcher maskesinin içinde beyaz/siyah "çift köşe" bırakır. Glif güvenli bölge (merkez %80 daire) içinde kalıyor (en uzak nokta yarıçapın ~%92'si) — sorun yalnız şeffaflık/opaklık. | `icons/Android/maskable-512.png`: tam kaplamalı **opak** zemin (uygulama zemini) + aynı glif (%60 ölçek). "any" ikon yuvarlatılmış kalabilir. İsteğe bağlı `purpose:"monochrome"` (Android 13 temalı ikon). | S |
| M3 | P2 | manifest (yok) | `id` yok (kimlik `start_url`'e düşer; ileride start_url değişirse kurulu uygulama "yeni uygulama" sayılır). | `"id": "/"`. | S |
| M4 | P2 | manifest (yok) | `display_override`, `categories`, `shortcuts`, `screenshots`, `launch_handler`, `prefers_related_applications:false` yok. Android'de zengin kurulum arayüzü ve uzun-basış kısayolları yok. | `display_override:["standalone","minimal-ui"]`, `categories:["finance"]`, `shortcuts` (Portföy `/portfolio`, Radar `/monitoring`, Grafik `/charts`, Binance TR `/binance-tr`; 96px ikonlu), `screenshots` (≥1 dar + ≥1 wide), `launch_handler:{client_mode:"focus-existing"}` (Chromium: bildirim/kısayol açılışları mevcut pencereyi yeniden kullanır). | M |
| M5 | P1 | manifest:9-10, `app/layout.tsx:41`, `tailwind.config.ts:8`, `app/user-palette.generated.css:2` | **Renk uyumsuzluğu**: manifest `background_color/theme_color` = `#05080d`; uygulamanın gerçek koyu zemini `bunker-950 = #0f1131` (lacivert-mor); kullanıcı (light) kabuğunun zemini `#eef2fb`. Sonuç: Android'de durum çubuğu/sistem başlığı `#05080d`, sayfa farklı lacivert veya açık; açılış (splash) rengi ile ilk boyama arasında renk sıçraması. `viewport.themeColor` tek statik değer. | Koyu tema için hepsini `#0f1131`'e hizala. User (light) kabuğunda `UserShell` efektiyle `<meta name="theme-color">`'ı `#eef2fb`'ye çek, cleanup'ta geri al (Android standalone runtime meta değişimini izler). Manifest `theme_color`'ı en sık role göre seç. | S |
| M6 | P2 | manifest:2-4 | `name/description` "Paper Trading … public-data paper scalping terminal"; oysa uygulamada artık **gerçek Binance TR emri** var (`binance-tr`, user kabuğu) — ana ekran/başlık yanıltıcı olabilir. `short_name` "Scalper Agent" (13 karakter) ana ekranda kırpılır. | `short_name: "Scalper"`; açıklamayı güncelle. | S |
| M7 | P2 | `public/icons/iOS/Icon-{120,152,180}.png`, `icons/Android/*` | Tüm PNG'ler RGBA ve köşeleri şeffaf (180 px görseli okundu). iOS apple-touch-icon opak ister; şeffaf köşeler siyaha boyanır. 167 px (iPad Pro) ve 1024 yok. | iOS ikonlarını opak tam kare üret (iOS kendi maskesini uygular); 167 ekle. | S |

Doğru olanlar: `scope:"/"`, `start_url:"/"`, `lang:"tr"`, 192/512 PNG var, `display:"standalone"`, SVG `any`.

---

## 2. Service worker (`public/sw.js`, `app/lib/serviceWorker.ts`, `app/components/AppShell.tsx`)

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| S1 | **P0** | `app/lib/serviceWorker.ts:8-12,21-27`, `sw.js:8`, `AppShell.tsx:29-44` | **Güncelleme tetikleyicisi yalnızca "yeni HTML yükleniyor"a bağlı.** SW kaydı `/sw.js?v=<BUILD>` ile yapılıyor; tarayıcının kendi güncelleme denetimi (navigasyonda/24 saatte bir/`update()`) **kayıtlı eski URL'yi** (`?v=ESKİ`) getirir, baytlar aynı olduğundan yeni SW kurulmaz. Yeni SW yalnızca yeni build'in JS'i çalışıp `register('...?v=YENİ')` çağırınca gelir. Arka plandan dönen (askıdaki) kurulu uygulama — iOS'ta günlerce, Android'de saatlerce yaşar — **yeni deploy'u hiç fark etmez**: ne `visibilitychange` sürüm denetimi, ne `registration.update()`, ne periyodik build kontrolü var (repoda `build-id` yalnız `layout.tsx:53` meta'da yazılıyor, hiçbir yerde karşılaştırılmıyor — grep ile doğrulandı). `SW_VERSION` mesajı (AppShell:33) yalnızca **başka bir pencere/sekme** yeni SW'yi kurunca eski sayfayı yeniler; tek pencereli kurulu PWA için işe yaramaz. Sonuç: eski JS + yeni backend API uyumsuzluğu (gerçek emir ekranları dahil) sessiz kalır. | (a) SW URL'sini **sabit** yap (`/sw.js`); build bilgisini ve VAPID public key'i dosya içeriğine göm (ör. `app/sw.js/route.ts` ile üretip `Cache-Control: no-store` ver; veya prebuild adımı `__BUILD__` yerleştirsin). Böylece tarayıcının bayt-karşılaştırmalı güncellemesi ve `registration.update()` çalışır. (b) `AppShell`'de `visibilitychange→visible` + 10 dk periyodik: `registration.update()` **ve** küçük `/api/version` (veya `fetch('/',{cache:'no-store'})` içindeki `build-id` meta'sı) ile build kıyası; fark varsa "Yeni sürüm var — Yenile" şeridi (boştayken otomatik yenile; açık emir formu/modal varken zorlama). (c) `waiting` durumunu yakalayıp `controllerchange` ile tek seferlik reload. | M |
| S2 | P1 | `sw.js:20-25` (eski cache silme) + dağıtım | Deploy sonrası eski sayfa belleğinde duruyorken **tembel yüklenen chunk'lar** (`dynamic()` — `ChartAssistantDrawer`, `BinancePositionChartModal`, `IndicatorPicker`, admin sekmeleri) eski hash'le istenir: sunucu imajında yalnız yeni build var → 404; SW'nin eski cache'i de `activate`'te siliniyor (`key !== CACHE`) → ChunkLoadError. `app/error.tsx` / `app/global-error.tsx` ChunkLoadError'ı tanımıyor; ham hata + "TEKRAR DENE" gösteriyor (reset aynı eski chunk'ı yine ister). | `error.tsx`/`global-error.tsx`'e ChunkLoadError/`Loading chunk … failed` algısı: tek seferlik `location.reload()` (sessionStorage bayrağı). SW'de bir önceki build'in static cache'ini bir nesil daha tut. | S |
| S3 | P1 | `sw.js:172-193` | Navigasyon `fetch`'inde **zaman aşımı yok**: mobilde "lie-fi" (bağlantı var, veri yok) durumunda belge isteği onlarca sn asılı kalır, önbellek yedeği devreye girmez; uygulama açılışta beyaz ekranda bekler. Navigation preload da kapalı. | `Promise.race([fetch, timeout(4000)→cache])`; `registration.navigationPreload.enable()` + `event.preloadResponse` (SW başlatma gecikmesini de keser). | M |
| S4 | P1 | `sw.js:149-193` | `isDocumentRequest` **tüm** navigasyonları yakalar: `/api/...` indirme/yönlendirmeleri ve her URL varyantı (`?embedded=1`, `?symbol=…`) `cache.put` ile önbelleğe girer (anahtar = tam URL → sınırsız büyüme, deploy'a kadar temizlenmez); yanıt **başarılı olmasa da** (404/500/nginx 502-503 HTML'i) cache'lenir ve çevrimdışıyken o hata sayfası sunulur (`response.ok` kontrolü yok). `put` `waitUntil` içinde değil ve `.catch` yok → kota/Vary hatasında yakalanmamış reddetme. | `if (url.pathname.startsWith('/api/') \|\| url.pathname==='/ws') return;`; yalnız `response.ok && response.type==='basic'` olanı ve yalnız kabuk sayfalarını cache'le; `event.waitUntil(put.catch(()=>{}))`; eşleştirmede `ignoreSearch:true`. | S |
| S5 | P2 | `sw.js:10,14,188-192` | `SHELL = ["/", "/manifest.webmanifest", "/icon.svg"]` ön-önbelleği: manifest/icon fetch'te hiç servis edilmiyor (`sw.js:212` "SW karışmasın") → ölü yük. `addAll("/")` HTTP önbelleğinden bayat HTML alabilir; deploy anında 503 olursa `install` tümden reddedilir. Çevrimdışı yedek "/" **HTML'i** var ama JS chunk'ları yok (static cache yalnız o an istenenleri tutar) → çevrimdışı açılışta boş/bozuk sayfa; üstelik AuthGate `/api/auth/status` bekleyeceği için zaten işlevsiz; son çare `"offline"` düz metin 503. | Gerçek `offline.html` (statik, satır içi stil, "Bağlantı yok — Yeniden dene" Türkçe) ön-önbellekle ve navigasyon başarısızlığında onu dön. `new Request(u,{cache:'reload'})` ile ekle. | S |
| S6 | P2 | `sw.js:196-211` | `/_next/static/` için stale-while-revalidate: içerik-hash'li dosyada anlamsız (cache-first yeterli), her istekte arka plan fetch + çift depolama. | Cache-first. | S |
| S7 | P2 | `sw.js:20-25` ve `sw.js:225-233` | İki ayrı `activate` dinleyicisi (clients.claim iki kez). | Tek `activate`'te birleştir. | S |
| S8 | P2 | `sw.js:55,72` (+ yorum 52-53,65,67) | Fallback bildirim metinleri **mojibake**: `"Yeni market alarmý"`, `"Scalper Agent alarmý"` (baytlar `c3 bd` = U+00FD, bayt düzeyinde doğrulandı). Backend normalde başlık/gövde gönderdiği için nadir görünür. | UTF-8 olarak düzelt ("alarmı"). | S |
| S9 | P2 | `serviceWorker.ts:19-27` + `AppShell` (AuthGate'in çocuğu, `AuthGate.tsx:383-396`) | SW **yalnız giriş yapıldıktan sonra** kaydoluyor. Giriş ekranında (taze kurulumun en çok görüldüğü yer) SW yok; `beforeinstallprompt` daha geç/hiç gelmeyebilir; oturum yokken kurulu uygulama kendini güncelleyemez. | `useServiceWorker()`'i `layout.tsx` düzeyinde küçük bir client bileşenine taşı. | S |
| S10 | P2 | `sw.js:83-105` | Tıklama işleyicisi: (a) `client.navigate()` **tam sayfa yeniden yükleme** yapar (mobilde yavaş, durum kaybı) ve kontrol edilmeyen istemcide reddeder; reddetme yakalanmadığı için **tıklama hiçbir şey yapmaz** (focus da çağrılmaz). (b) İlk bulunan aynı-origin istemci seçiliyor (görünür olan değil). (c) `target` doğrulanmıyor (mutlak/harici URL → `navigate` reddi). | `client.focus()` önce; `postMessage({type:'NAVIGATE',url})` + AppShell'de `router.push` (SPA geçişi); `navigate` yalnız yedek ve `.catch(()=>clients.openWindow(target))`; `target`'ı `new URL(target,origin)` ile aynı-origin'e zorla. | M |

SW dayanıklılığında doğru olanlar: `respondWith(undefined)` koruması (`sw.js:191,209`), `isRscOrAppDataRequest` ayrımı (RSC bayat yanıt sorunu çözülmüş), yalnız GET + aynı origin; WS (`/ws`) SW'den geçmez; API istekleri `respondWith` almadığı için önbelleğe **girmez** (fetch/XHR `destination==""`).

---

## 3. Deploy sonrası bayat JS/CSS (`next.config.js`, `nginx/default.conf`, `Dockerfile`)

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| D1 | P2 | `nginx/default.conf:239-253` (özellikle 248) | `/_next/static/` bloğunda `add_header Cache-Control "public, max-age=31536000, immutable" always;` — `always` **hata yanıtlarına da** uygulanır: eski HTML'in istediği, artık var olmayan chunk için Next'in verdiği 404 (veya deploy anındaki 502/503) tarayıcıda/ara proxy'de **1 yıl** önbelleğe girebilir (404 varsayılan olarak önbelleğe alınabilir). Next zaten 200 yanıtlarına kendi immutable başlığını koyuyor. | `always`'ı kaldır ya da `map $upstream_status $static_cc { ~^2 "public, max-age=31536000, immutable"; default "no-store"; }` ile yalnız 2xx'e uygula. | S |
| D2 | P2 | `next.config.js:3-14,19-20` | `getBuildId()` `Date.now()` tabanlı ve modül yüklenirken hesaplanıyor; Docker build'de `.git` yok (context `./frontend`) → yalnız zaman damgası kalır (sorun değil). Ancak `next.config.js` ana süreç ve işçi süreçlerinde ayrı ayrı yüklenirse `generateBuildId` ile `NEXT_PUBLIC_BUILD_ID` farklı değer üretebilir — S1/SW sürüm kıyası bu eşitliğe dayanacak. **[VARSAYIM: doğrulayın]** | `BUILD_ID`'yi Dockerfile `ARG BUILD_ID` / Coolify `SOURCE_COMMIT` ile dışarıdan ver; `/api/version` veya `/build-id.txt` ekle. | S |
| D3 | P2 | `next.config.js:22-30` | Yalnız `/sw.js` için başlık var; `/manifest.webmanifest`, `/icons/*` Next varsayılanıyla (`public, max-age=0`) → her açılışta koşullu doğrulama; işlevsel, ama ikonlar için gereksiz gidiş-dönüş. | İkon/manifest için `public, max-age=86400, stale-while-revalidate=604800`. | S |
| D4 | P2 | `nginx/default.conf` (yok) | `Service-Worker-Allowed` gerekmiyor (sw.js kökte). `Content-Type`: Next `.webmanifest` için `application/manifest+json` veriyor (Next'in gömülü mime tablosunda var; canlıda `curl -I` ile doğrulanmadı). nginx'te `sw.js` için **güvence katmanı** yok — ileride CDN/Cloudflare öne eklenirse bayat SW riski. | Savunma derinliği: nginx'te `location = /sw.js` ve `= /manifest.webmanifest` için açık `Cache-Control`; CDN varsa `sw.js` bypass kuralı. | S |

Doğru olanlar: `sw.js` için `no-cache, no-store, must-revalidate` (`next.config.js:25-27`), `/_next/static` immutable (nginx + Next), HTML için `proxy_cache` yok, gateway'de `gzip` açık, build id her deploy'da değişiyor.

---

## 4. Viewport, safe-area, meta etiketleri (`app/layout.tsx`, `app/globals.css`)

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| V1 | P1 | `layout.tsx:40` + `UserShell.tsx:23-31`, `UserBottomNav.tsx:114`, `AppShell.tsx` | `viewportFit:"cover"` açık ama **yan safe-area hiç kullanılmıyor** (`safe-area-inset-left/right` repoda 0 kullanım). iPhone'da yatay dönüşte (iOS manifest orientation'ı yok sayar) içerik ve alt menü çentik/yan kenar altında kalır. Üst safe-area yalnız admin `.content-shell` (globals.css:479) için var; `UserShell` üstünde `pt-4` sabit. | Kabuk kapsayıcılara `padding-inline: max(1rem, env(safe-area-inset-left/right))`; `UserBottomNav`'a yan inset; `UserShell`'e `padding-top: env(safe-area-inset-top)`. Alternatif: `viewportFit` kaldırılsın (yatay kullanılmayacaksa). | S |
| V2 | P1 | `layout.tsx:34,53` | iOS için `apple-mobile-web-app-status-bar-style` / `apple-mobile-web-app-title` yok (yorum 34 bilinçli kaçınma). iOS ≥16.4 manifest `display`'i dikkate alıyor, ancak durum çubuğu stili varsayılan (açık/beyaz çubuk) — koyu uygulamada açık çubuk; ana ekran etiketi `<title>`/`name`'den türer ("Scalper Agent V4 — Paper Trading" kırpılır) **[VARSAYIM]**. | `<meta name="apple-mobile-web-app-title" content="Scalper">`; `black-translucent` seçilirse üst safe-area padding **zorunlu** (V1). Koyu/açık role bağlı olduğundan `default` + runtime theme-color (M5) daha güvenli. | S |
| V3 | P2 | `layout.tsx` (yok) | `formatDetection:{telephone:false}` yok: iOS uzun rakam dizilerini (fiyat/miktar) **telefon numarası** gibi bağlantılaştırabilir. `interactiveWidget` yok: Android Chrome ≥108 varsayılanı `resizes-visual` — klavye açılınca `100dvh` küçülmez, `position:fixed`/sticky alt öğeler (chat composer, BottomNav) klavyenin arkasında kalabilir **[VARSAYIM: cihazda doğrula]**. | `metadata.formatDetection = {telephone:false}`; chat/emir formu sayfalarında `interactiveWidget:'resizes-content'` ya da `visualViewport` ile kaydırma. | S |
| V4 | P1 | `globals.css:255` (`.input` = `text-sm`, 14px), `globals.css:382` (`.portfolio-filter input … .72rem`) | **iOS odak yakınlaştırması**: 16px altı `input/select/textarea` iOS Safari/standalone'da odakta sayfayı **yakınlaştırır** ve kendiliğinden geri küçültmez. Yalnız `.chat-composer textarea` 16px (511). Giriş formu (`AuthGate.tsx:374-375`) ve emir miktarı/fiyatı girişleri etkilenir. | `@media (max-width:768px){ input,select,textarea{font-size:16px} }`. | S |
| V5 | P1 | `globals.css` `html/body` (yok) | **Çekerek yenileme / overscroll kontrolü yok** (`overscroll-behavior` yalnız `.app-sidebar`'da, globals.css:33; repoda `touch-action` yalnız `button,a{manipulation}`). Android Chrome standalone'da sayfa başında aşağı sürükleme tam yeniden yükleme yapar → grafik pan'ı sırasında yanlışlıkla yenileme, WS yeniden kurulur, emir formundaki durum kaybolur. **[VARSAYIM: LWC canvas dokunma davranışı cihazda test edilmeli]** | `html,body{overscroll-behavior-y:none}` (veya `contain`) + grafik konteynerine uygun `touch-action`. **Uyarı**: iOS standalone'da zaten PTR yok; Android'de kapatınca elle yenileme yolu kalmaz → S1(b)'deki "Yenile" şeridi / üst çubukta yenile düğmesi ekle. | S |
| V6 | P2 | `AppShell.tsx:50,53,55`, `UserShell.tsx:23`, `AuthGate.tsx:85`; `technical-charts/page.tsx:327`; çok sayıda `max-h-[90vh]` modal | `min-h-screen` (= `100vh`): mobil tarayıcı sekmesinde adres çubuğu yüzünden taşar; standalone'da sorun yok. `h-screen` (Sidebar:110) `.app-sidebar{height:100dvh}` tarafından zaten ezilmiş. | `min-h-dvh` / `max-h-[90dvh]` (Tailwind ≥3.4 destekler). | S |
| V7 | P2 | `AppShell.tsx:55`, `globals.css:478` | `<main className="… overflow-y-auto">` + yapışkan `TopBar` (`.topbar{position:sticky}` main içinde): `overflow-y:auto` olan `main` yüksekliği sınırlı değilse kaydırma kutusu olur ama kaymaz → `sticky` belge kaydırmasına bağlanmaz; mobilde `main{overflow-x:clip}` ile birleşiyor. Sabit hamburger (`.mobile-menu-button` fixed z-40, 44px) kaydırmada içeriğin üzerine biner. **[VARSAYIM — cihazda doğrula]** | `main`'den `overflow-y-auto`'yu kaldır (belge kaydırsın) ya da kabuğu `h-dvh` + iç kaydırma yap. Hamburger'i TopBar içine al. | M |

Doğru olanlar: `touch-action:manipulation` (çift dokunma gecikmesi/zoom yok, `globals.css:49`), `-webkit-tap-highlight-color:transparent` (48), `.touch-target` 44px, alt navigasyonda `env(safe-area-inset-bottom)` (`BottomNav.tsx:272`, `UserBottomNav.tsx:114`), `100dvh` kullanan sohbet/sidebar alanları, `prefers-reduced-motion` desteği, `userScalable` kısıtlanmamış, `lang="tr"`, `body{overflow-x:clip}` gerekçesi yorumlu.

---

## 5. Kurulum istemi ve onboarding (`PushOnboardingModal.tsx`, `lib/push.ts`, `Sidebar.tsx`, `AuthGate.tsx`)

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| I1 | **P0** | `PushOnboardingModal.tsx:66,160-166,130-131`, `lib/push.ts:11-21` | **iPhone'da yanlış yönlendirme.** `detectBrowser()` iPhone Safari için `"safari"`, iOS Chrome (CriOS) için de `"safari"` döndürür; modal `!== "chrome"` ise ilk adım olarak "**Chrome önerilir… lütfen Chrome kullanın**" gösterir — iOS'ta doğru tarayıcı **Safari**'dir (ana ekrana ekleme + push yalnız Safari'den eklenen/standalone uygulamada). Aynı akışta iOS'ta "ANLADIM" (214) ile `notify` adımına geçilince `ensurePushSubscription` → `"PushManager" in window` Safari sekmesinde **yok** → `push_yok` → "**Chrome ile açmayı deneyin**" (130-131). iPhone kullanıcısı için kurulum akışı çıkmaz sokak. | iOS'ta (`/iphone\|ipad\|ipod/` veya `MacIntel && maxTouchPoints>1`) `browser_warn`'u atla; Safari değilse "Safari'de aç" uyarısı; standalone değilken `notify` adımına **geçme** — adım adım talimat (Paylaş simgesi çizimi) göster + "iOS 16.4+ gerekir" kontrolü; `push_yok` mesajını iOS için "Ana ekrana ekleyip oradan açın" yap. | M |
| I2 | P1 | `PushOnboardingModal.tsx:36-41`, `Sidebar.tsx:57-67` | `beforeinstallprompt` yalnız bileşen **bağlandığında** (oturum açıldıktan sonra) dinleniyor. Olay sayfa yüklenirken bir kez atılır; giriş öncesi atıldıysa kaçırılır → kullanıcı "Chrome menüsünden kur" metnine düşer. Sidebar yalnız admin kabuğunda var; **user kabuğunda kalıcı "Uygulamayı yükle" girişi yok** (yalnız tek seferlik modal; `UserSettings` Bildirim sekmesinde de yok). | Olayı `layout.tsx`'te erken (modül düzeyinde) yakalayıp singleton/context'te sakla (tek `prompt()` hakkı); `appinstalled` ile temizle; User Ayarları'na ve menüye kalıcı "Uygulamayı yükle" ekle. | M |
| I3 | P2 | `PushOnboardingModal.tsx:99-101` | `prompt()` sonrası `userChoice` okunmuyor; kullanıcı **reddetse de** akış `notify` adımına geçiyor. Zaten kuruluysa (Android'de aynı uygulama tarayıcı sekmesinde açıldı) `beforeinstallprompt` gelmez ve "menüden yükle" talimatı yanlış olur. | `const {outcome} = await prompt.userChoice`; `navigator.getInstalledRelatedApps?.()` ile kurulu algıla ("Uygulama kurulu — ana ekrandan aç"). | S |
| I4 | P2 | `PushOnboardingModal.tsx:49,79-82` | "BİR DAHA GÖSTERME" `localStorage` anahtarı **Android'de tarayıcı ile kurulu PWA arasında paylaşılır**: kurulum adımında "bir daha gösterme" denirse kurulu PWA'da bildirim izni adımı hiç gelmez (kalan yol yalnız User Ayarları > Bildirimler, `UserSettings.tsx:170`). iOS'ta depolama ayrı. | "Gösterme" bayrağını adıma göre ayır (`install` ve `notify` ayrı anahtarlar). | S |
| I5 | P2 | `NotificationPermissionModal.tsx:40-42,18-19` | `vapid_yok` da "Bu tarayıcı Web Push desteklemiyor" olarak gösteriliyor (oysa yapılandırma eksikliği — `PushOnboardingModal` ayrımı doğru yapıyor). iPadOS Safari "Macintosh" UA'sı nedeniyle `isMobileDevice()` false → masaüstü modalı gelir, iPad ana ekran akışı yok. | Mesajı ayır; iPadOS algısı ekle. | S |
| I6 | P2 | `Sidebar.tsx:98,220-229` | Admin kabuğu: yükleme düğmesi olay yoksa **disabled** ("YÜKLEME İÇİN TARAYICI MENÜSÜ") — işlevsiz buton; render sırasında `navigator.userAgent` okunuyor (225); `installed` state'i set ediliyor ama kullanılmıyor. | iOS'ta düğmeyi gizle/talimat göster; talimatı I1 ile ortak bileşene al. | S |

Doğru olanlar: `reconcilePushSubscription` açılışta **izin istemiyor** (`push.ts`), `pushsubscriptionchange` + yeniden abonelik, VAPID anahtarı uzunluk doğrulaması (65 bayt), `NEXT_PUBLIC_VAPID_PUBLIC_KEY` Dockerfile/compose build-arg olarak geçiyor (anahtar yoksa `vapid_yok` ile dürüst hata), `requestPermission` kullanıcı jestinin içinde çağrılıyor, DisclaimerModal (z-200) ile onboarding (z-115) sıralaması doğru.

---

## 6. Web push akışı (`public/sw.js`, `backend/app/alerting.py`, `backend/app/routers/monitoring.py`)

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| P1 | **P0** | `backend/app/alerting.py:80,129`, `public/sw.js:63,85` | **Alarm push'unun varsayılan derin bağlantısı `/alerts` — bu rota yok** (`frontend/app/alerts` yok, `find app -ipath "*alerts*"` boş; `next.config.js`'te rewrite/redirect yok; user menüsünde "Bildirimler" `legacy`/gizli). `deliver_alert_push` payload'ında `url or "/alerts"` (129) ve `_evaluate_single_rule` çağrısı url vermiyor → her fiyat/yüzde alarmı bildirimine dokunan kullanıcı **404 "Sayfa bulunamadı"** ekranına düşer. SW fallback'i de `/alerts`. Testler (`tests/test_notification_audit_fixes.py:177`, `test_push_only_notifications.py:203`) bu değeri sabitlemiş. (Radar push'ları `/charts?symbol=…` kullanıyor — doğru.) | Backend varsayılanını mevcut bir rotaya çevir (alarmda sembol varsa `/charts?symbol=…`, yoksa `/monitoring` veya `/`), SW fallback'ini `/` yap, testleri güncelle. Geçici: Next'te `/alerts` → `/notifications` redirect. | S |
| P2 | P1 | `public/sw.js:37-52,83-90` | **iOS'ta bildirimsiz push riski**: sayfa görünür+odaklıyken push **bildirim gösterilmeden** atlanıyor (mükerrer önleme). Chrome/Android görünür pencere varken bildirimsiz push'a izin verir; **WebKit (iOS/iPadOS) `userVisibleOnly` ihlalinde aboneliği iptal eder** **[VARSAYIM: WebKit politikası; eşik cihazda doğrulanmalı]**. Uygulama açıkken radar sık tetiklendiğinden iPhone'da abonelik sessizce ölebilir; `reconcilePushSubscription` açılışta yeniden kurar ama "kapalıyken bildirim gelmiyor" şikayeti buradan doğar. | iOS'ta `skipWhenPageVisible`'ı devre dışı bırak (platform bilgisini istemciden IDB/`postMessage` ile ilet) ve çift sesi, bildirimi `silent:true`+`renotify:false` göstererek çöz. | M |
| P3 | P1 | `backend/app/alerting.py:90-92` | `webpush(...)` çağrısında `ttl` ve `headers` verilmiyor: **pywebpush 2.4.0 varsayılanı `ttl=0`** (doğrulandı: `.venv/Lib/site-packages/pywebpush/__init__.py:404`), `Urgency` başlığı yok, `timeout=None`. `ttl=0` = "anında teslim edilemiyorsa at": telefon Doze/uçak modu/kapsama dışıyken kısa süreliğine bile erişilemezse radar bildirimi **kaybolur**; normal aciliyette Android Doze'da gecikir. Gönderim abonelik başına **sıralı** ve zaman aşımsız (askıda bir uç nokta tüm turu bloke eder). | `ttl` = bildirimin anlamlı kaldığı süre (300–900 sn; `horizon_minutes` ile hizala), `headers={"Urgency":"high","Topic": tag}`, `timeout=10`, sınırlı paralel `asyncio.gather`. | S |
| P4 | P1 | `public/sw.js:56-57` | Bildirim `icon:"/icon.svg"` ve `badge:"/icon.svg"`: Chrome Android bildirim ikonunda **SVG desteklemez** → varsayılan/boş ikon; `badge` Android'de **tek renkli şeffaf PNG** (96×96) olmalı, aksi halde gri varsayılan. iOS badge'i yok sayar. | `icon:"/icons/Android/Icon-192.png"`, yeni `icons/badge-96.png` (beyaz glif/şeffaf). | S |
| P5 | P2 | `sw.js:58-66`, `alerting.py:81` | `data.sound` / `"sound": "/alarm.wav"`: Notification `sound` özelliği hiçbir tarayıcıda yok ve `/alarm.wav` dosyası `public/`'te **yok** (ölü kod). `requireInteraction:true` Android'de yok sayılır, masaüstünde bildirimi kalıcı yapar. `vibrate` iOS'ta yok. Android bildirim **kanalı** web'den kontrol edilemez. `navigator.setAppBadge` hiç kullanılmıyor (kurulu PWA'da okunmamış sayısı için iOS ≥16.4 ve Android destekler). | Ölü alanları temizle; push'ta `setAppBadge(n)`, açılışta `clearAppBadge`. | S |
| P6 | P2 | `app/components/RadarAlertModal.tsx:11-41` | Alarm sesi her olayda **yeni `AudioContext`** açıyor, `resume()` ve kullanıcı jestiyle "kilit açma" yok: iOS Safari/standalone'da jestsiz oluşturulan context `suspended` kalır → WS ile gelen radar modalı **sessiz** açılır; push de görünür sayfada atlandığı için (P2) kullanıcı **hiç ses duymaz**. Arka plandan dönüşte context yine askıda. | Tek paylaşımlı context; ilk `pointerdown/touchend`'de `resume()`; her çalmada `ctx.state!=='running'` ise `resume()`; Android için `navigator.vibrate`. | S |
| P7 | P2 | `alerting.py:76`, `monitoring.py:347-375` | Push **tüm aboneliklere** gidiyor (`usernames=None`); sessiz saat **global** (`get_user_notification_settings` tek satır; `time.localtime()` — `TZ=Europe/Istanbul` ile doğru). Çok kullanıcılı yapıda her kullanıcıya her radar bildirimi gidiyor, kişisel sessiz saat yok. Sessiz saat mantığı kendi içinde doğru (gece sarma destekli, ertelemeli kuyruk `maxlen=100`, bayatlayanı düşürme). | Kullanıcı bazlı tercih (sessiz saat + kategori) — ürün kararı. | L |
| P8 | P2 | `sw.js:114-146` | `pushsubscriptionchange` Chrome'da güvenilmez (yorumda da yazılı). VAPID anahtarı SW URL sorgusundan (`?vapid=`) okunuyor — S1 ile URL sabitlenirse anahtar dosyaya gömülmeli. | S1 ile birlikte. | S |

Doğru olanlar: sessiz saatte push erteleme + süresi dolanı düşürme, mükerrer endpoint temizliği (`p256dh` ile), ölü abonelik (404/410) temizliği, push-test uç noktası zinciri katman katman teşhis ediyor, tıklamada açık pencereyi odaklama (yeni sekme yağmuru yok), açılışta izin istemeyen sessiz uzlaştırma.

---

## 7. Ortak mobil kabuk ve gezinme

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| K1 | P1 | `app/lib/liveSocket.ts:161-176` | **Arka plandan dönüşte WS toparlanması yavaş**: `visibilitychange`/`online`/`pageshow` dinleyicisi yok (repoda `online` olayı hiç dinlenmiyor). Mobil OS soketi öldürünce `onclose` gelmeyebilir; heartbeat 45 sn sessizlik + 15 sn kontrol aralığı = ~60 sn'ye kadar yalancı "CANLI"; sonra backoff (2-32 sn). Yeniden bağlanınca **kaçırılan alarm/radar olayları için telafi yok** (modal yalnız canlı olayda açılır). | `visibilitychange→visible` / `online` / `pageshow(persisted)`: `reconnectAttempt=0`, hemen bağlan; sessizlik >10 sn ise soketi kapat-aç; yeniden bağlanınca `/api/monitoring/notifications` ile son N olayı çekip bayat olmayanları göster. | M |
| K2 | P2 | `app/charts/ChartAssistantDrawer.tsx:170` (`bottom-16`), `UserShell.tsx:30` (`pb-24`), `UserBottomNav.tsx:114` | Asistan çekmecesi `bottom-16` (64 px) sabit; iPhone'da alt menü ≈ 52 px + `safe-area-inset-bottom` (≈34 px) → çekmece alt menüyü ~20-25 px kapatır. `pb-24` (96 px) ≈ alt menü + safe-area sınırında. Admin `BottomNav` benzer. | `bottom: calc(4rem + env(safe-area-inset-bottom))`; içerik alt boşluğu `calc(5.5rem + env(...))`. | S |
| K3 | P2 | `Sidebar.tsx:69-81,110`, `globals.css:474` | Kapalı çekmece yalnız `translateX(-105%)` ile gizli: **odaklanabilir/ekran okuyucuya açık** (`inert`/`aria-hidden`/`visibility` yok); odak tuzağı/başlangıç odağı yok. `body{overflow:hidden}` iOS Safari'de kaydırmayı her sürümde kilitlemez. Geri tuşu: Android'de çekmece/modal açıkken geri **sayfadan çıkar** (history girdisi yok) — kurulu PWA'da en sık yapılan hata. | Kapalıyken `inert` + `visibility:hidden` (gecikmeli); açılışta `history.pushState` + `popstate` ile geri tuşu kapatsın (`useModalA11y`'ye ekle); kaydırma kilidi için `overscroll-behavior:contain` + `position:fixed` tekniği. | M |
| K4 | P2 | `UserBottomNav.tsx:143-170` | `role="menu"` var ama ok tuşu gezintisi/roving tabindex yok (ARIA menu kalıbı eksik); `w-44` sabit, `max-h` yok → çok öğede küçük ekranda üstten taşar. | `max-h-[70dvh] overflow-y-auto`; ya tam menü kalıbı ya da basit `aria-expanded` liste. | S |
| K5 | P2 | `backend/app/main.py:522-531`, `backend/app/security.py:200-216` | Oturum `max_age=43200` (12 sa, kayan değil) + `SameSite=Strict` + **tam User-Agent'a bağlı**: kurulu PWA'da günde ≥1 yeniden giriş; Chrome/iOS sürüm güncellemesi UA'yı değiştirdiği anda oturum düşer (yaklaşık 4 haftada bir sürpriz çıkış). `scalper:auth-expired` olayında push uzlaştırması sessizce 401 alır. Güvenlik tercihi — yalnız "kurulu uygulama" deneyimi açısından not. | UA parmak izini platform/aile düzeyine gevşet; kayan oturum / "Bu cihazda hatırla" 30 gün. | M |
| K6 | P2 | `TopBar.tsx:41` | "CANLI PUBLIC DATA" **statik metin** — WS durumunu yansıtmıyor (`useLiveStatus` var); kesintide yanıltıcı. | `useLiveStatus` ile bağla. | S |
| K7 | P2 | `UserShell.tsx:13-21`, `layout.tsx:51` | `html` sunucuda `class="dark"`; User kabuğu `data-theme="light"`'ı **etkiden sonra** (`useEffect`) koyuyor → light kullanıcıda ilk karede koyu zemin sıçraması (FOUC). Admin "basit görünüm"e geçişte de aynı. | `useLayoutEffect` ya da `<head>`'e rol/`localStorage`'a göre temayı boyamadan önce ayarlayan küçük satır-içi script; `theme-color` ile eş zamanlı (M5). | S |

---

## 8. Performans ve veri (mobil ağ)

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| F1 | P2 | `app/binance-tr/BinancePositionChartModal.tsx:515`, `app/components/user/binance/HoldingsCard.tsx:97`, `app/components/CombinedPaperPanel.tsx:124`, `app/reports/CombinedRisingTab.tsx:266` | Görünürlük-farkında olmayan `setInterval` yoklamaları: derinlik 5 sn, ticker 5 sn, 60 sn'lik REST yedekleri sekme arka plandayken de kurulu (mobil OS çoğunu dondurur ama masaüstü PWA'da çalışır; dönüşte birikim). Ayrıca `charts/page.tsx:105,586` her saniye tam sayfa yeniden çizimi tetikleyen `setCountdown`/`setNow` (2300 satırlık bileşen — pil/CPU). WS `tickers` zaten istemcide eleniyor (iyi). | `useVisibleInterval`'e geçir; saniyelik sayaçları ayrı alt bileşene al (`UserBinance` `Freshness` iyi örnek). | S |
| F2 | P2 | `package.json` (lightweight-charts, oakscriptjs, lightweight-charts-indicators, react-markdown + remark-gfm) | Üretim build'i olmadığından paket boyutu **ölçülemedi [VARSAYIM]**: `charts/page.tsx` (2304 satır), `binance-tr/page.tsx` (2744), `monitoring/page.tsx` (1894); `IndicatorPicker/Settings`, `ChartAssistantDrawer` `dynamic()` ile bölünmüş (iyi). Lighthouse'ta beklenen: yüksek TBT/JS yürütme (orta sınıf Android), LCP'de ardışık gecikme (HTML → JS → `/api/auth/status` → ilk içerik; AuthGate kimlik durumunu istemciden alıyor). | `next build` "First Load JS" + `@next/bundle-analyzer`; `react-markdown`'ı `dynamic()` ile ertele; ilk boyamada giriş iskeleti göster. | M |
| F3 | P2 | `layout.tsx:11-15` | 4 Google font ailesi (`Poppins` 2, `Inter` 3, `IBM Plex Sans` 4, `JetBrains Mono`) ≈ 10+ font dosyası, çoğu kabukta kullanılmıyor (`font-sans` = Plex, Inter yedek). `next/font` self-host olduğundan render-blocking değil ama ilk yük/cache şişer. | Kullanılmayan ağırlık/aileleri grep'le doğrulayıp kaldır. | S |

---

## 9. Erişilebilirlik ve tema

| # | Önem | Yer | Bulgu | Düzeltme | Efor |
|---|------|-----|-------|----------|------|
| A1 | P2 | `PushOnboardingModal.tsx:152`, `NotificationPermissionModal.tsx:70` | `role="dialog" aria-modal` var ama `useModalA11y` (odak tuzağı/Escape/odak iadesi) **kullanılmıyor** (kullananlar: binance-tr, BuyDialog, ConfirmDialog, UserRadar, monitoring…). Modal açıkken odak arka sayfada. `RadarAlertModal` kendi tuzağını yazmış (iyi) — ortak hook'a geçirilebilir. | `useModalA11y` ekle. | S |
| A2 | P2 | `globals.css` (`.topbar-kicker .5rem`, `.pband-label .52rem`, `text-[10px]`), `.input::placeholder rgb(100 116 139)` (256) | 8 px etiketler ve ≈3.8:1 kontrastlı placeholder (WCAG 4.5:1 altı); px sabit boyutlar. | Taban 11-12 px, placeholder daha açık. | S |
| A3 | P2 | `globals.css:8-9`, `layout.tsx:51` | Tema: `color-scheme:dark` + `html.dark` sabit; gerçek mekanizma `data-theme="light"` (rol/admin görünümü). OS `prefers-color-scheme` hiç izlenmiyor (bilinçli olabilir). `tailwind.config.ts`'te `darkMode` yok ve `dark:` kullanımı yok (sorun yok). | Ürün kararı: sistem temasını izleme seçeneği (PWA'da OS karanlık/açık geçişi beklentisi). | M |
| A4 | P2 | geneli | Odak göstergesi yalnız `.ui-button/.ui-tabs/.input` (`globals.css:468`); `Link`/alt menü/üst menü bağlantılarında özel `:focus-visible` yok. Hareket azaltma desteği iyi. | Genel `a:focus-visible, button:focus-visible{outline:…}`. | S |

---

## Kodla doğrulanan / varsayım ayrımı

- **Doğrulandı (kodda)**: S1 (SW URL'si build'e bağlı; repoda `update()`/sürüm kıyası yok — grep), S3-S4, P1 (`/alerts` rotası yok; `alerting.py:80,129`), P3 (`pywebpush 2.4.0 ttl=0`, kütüphane kaynağından), P4, I1 (`detectBrowser` mantığı), V1 (`safe-area-inset-left/right` 0 kullanım), V4, V5, K1 (`online` dinleyicisi yok), M1-M2 (ikon görselleri okundu), S8 (bayt düzeyinde mojibake), K5.
- **Varsayım / cihazda doğrulanmalı**: P2 (iOS bildirimsiz push → abonelik iptali), V3 (Android klavye davranışı), V5 (LWC dokunma/PTR etkileşimi), V7 (sticky TopBar), V2 (iOS ana ekran etiketi), D2 (build-id eşitliği), F2 (paket boyutu — build alınmadı), M5/K7 (görsel sıçrama).
- **Başlıklar**: `next.config.js` yalnız `/sw.js` için başlık veriyor; manifest `Content-Type`'ı Next mime tablosundan çıkarıldı — canlı sunucuya `curl -I` ile doğrulanmadı.

---

## Geliştirilmesi gereken kısımlar (öncelikli yol haritası)

1. **[P0, S] Bildirim derin bağlantısını düzelt**: `alerting.py:80,129` ve `sw.js:63,85` varsayılan `/alerts` → var olan rota (alarmda `/charts?symbol=…`); geçici Next redirect; ilgili testleri güncelle. (P1)
2. **[P0, M] iPhone onboarding'ini düzelt**: iOS'ta "Chrome önerilir"/"Chrome ile açın" mesajlarını kaldır; Safari → Paylaş → Ana Ekrana Ekle talimatı, standalone değilken push adımına geçme, iOS ≥16.4 kontrolü. (I1)
3. **[P0, M] Güncelleme mimarisini onar**: SW URL'sini sabitle (build + VAPID dosyaya gömülü), `visibilitychange`/periyodik `registration.update()` + build kıyası, "Yeni sürüm var — Yenile" şeridi, ChunkLoadError'da otomatik tek-seferlik reload, eski static cache'i bir nesil tut. (S1, S2, P8)
4. **[P1, S] Push teslimat kalitesi**: `ttl` (300-900 sn) + `Urgency:high` + `Topic` + `timeout` + paralel gönderim; PNG `icon` ve tek renkli `badge`; ölü `sound`/`/alarm.wav` temizliği. (P3, P4, P5)
5. **[P1, M] iOS bildirimsiz-push riskini gider ve sesi güvenilir kıl**: iOS'ta görünür sayfada da (sessiz) bildirim göster; paylaşılan, jestle açılan `AudioContext` + `resume()`. (P2, P6)
6. **[P1, M] WS toparlanması**: `visibilitychange/online/pageshow` ile anında yeniden bağlan, kaçırılan olayları REST ile telafi et. (K1)
7. **[P1, S] Mobil form ve gezinme sertleştirmesi**: giriş alanları ≥16 px (iOS odak zoom'u), `overscroll-behavior-y:none` + grafikte `touch-action`, yan/üst `safe-area` (`viewportFit:cover` kullanılıyorsa zorunlu), `min-h-dvh`. (V1, V4, V5, V6)
8. **[P1, S] Manifest ve ikon düzeltmeleri**: `orientation:"any"`, opak tam kaplamalı maskable ikon, `id`, renkleri `#0f1131` ile hizala + User kabuğunda runtime `theme-color`, `short_name`, iOS ikonlarını opaklaştır, `apple-mobile-web-app-title`. (M1, M2, M3, M5, M6, M7, V2)
9. **[P1, M] SW navigasyon sağlamlığı**: `/api` hariç tutma, yalnız `ok` yanıtı cache'le, 4 sn ağ zaman aşımı + `navigationPreload`, gerçek `offline.html`, SW'yi layout düzeyinde kaydet. (S3, S4, S5, S9)
10. **[P2, M] Kurulum deneyimi**: `beforeinstallprompt`'u erken yakala, User kabuğunda/ayarlarda kalıcı "Uygulamayı yükle", `userChoice`/`getInstalledRelatedApps`, "bir daha gösterme" bayraklarını adıma göre ayır, manifest `shortcuts`/`screenshots`/`categories`/`launch_handler`. (I2, I3, I4, M4)
11. **[P2, M] Kabuk davranışı**: kapalı çekmeceye `inert`, Android geri tuşunu modal/çekmeceye bağla (history), bildirim tıklaması → SPA yönlendirme (`postMessage`+`router.push`), asistan çekmecesi/alt menü safe-area hizası, `TopBar` durumunu `useLiveStatus`'a bağla, tema FOUC'u. (K2, K3, K6, K7, S10)
12. **[P2, M] Oturum, nginx ve performans**: kurulu uygulama için kayan oturum + UA parmak izini gevşet; nginx `always` başlığını yalnız 2xx'e daralt, `sw.js`/manifest için savunma başlıkları; yoklamaları `useVisibleInterval`'e taşı; `next build` bundle analizi + font ağırlıklarını azalt. (K5, D1, D4, F1, F2, F3)

Not: Bu denetim yalnızca okuma yapmıştır; hiçbir kaynak dosya değiştirilmemiş, git komutu çalıştırılmamıştır. Tek yazılan dosya bu rapordur.


---

# Bölüm C — Diğer sayfalar (ayrıntılı rapor)

# Mobil / PWA Denetimi: Grafik Dışı Sayfalar (salt-okunur)

Kapsam: `frontend/app` altında Grafik hariç tüm sayfalar, kullanıcı (basit) arayüz bileşenleri ve kabuklar. Hedef cihaz: 360-430 px dokunmatik, kurulu PWA.
Yöntem: yalnızca kod okuma + derlenmiş CSS sırası kontrolü (`.next/dev/static/chunks/*.css`). Tarayıcıda çalıştırılmadı; kanıtı koddan çıkmayan her şey **(varsayım)** diye işaretli.
Hiçbir kaynak dosya değiştirilmedi, git kullanılmadı. Satır numaraları `~` ile başlıyorsa yaklaşıktır.

Ciddiyet: **P0** = kullanıcı bir işi hiç yapamıyor / veri-para riski. **P1** = mobilde belirgin kullanım veya güvenlik sorunu. **P2** = cila, tutarlılık, erişilebilirlik.
Efor: **S** < 2 saat, **M** yarım-1 gün, **L** 1-3 gün.

---

## 0. Özet (en kritik 8 bulgu)

1. **P0 - Kullanıcı arayüzünde mobilde Çıkış yok.** `UserNav` (kullanıcı adı + Çıkış) `hidden md:block` (`components/user/UserNav.tsx:13`); `UserBottomNav`, `UserSettings`, `ProfilePanel` içinde `logout` çağrısı yok (tüm repoda `logout` yalnızca `Sidebar.tsx:210` ve `UserNav.tsx:36`). Telefondaki normal kullanıcı oturumu kapatamaz, hangi hesapta olduğunu göremez.
2. **P1 - CSS katman sırası yüzünden Tailwind sınıfları ezilir.** `@tailwind utilities` en üstte (`globals.css:6`), `.input` (`:255`) ve `.ui-button` (`:435`) sonra, katmansız tanımlı. Derlenmiş CSS'te `.text-base` (ofset 77266) `.input`'tan (115575) önce geliyor. Sonuç: `input ... text-base min-h-[48px]` yazılan ~10 yerde gerçek değer **14 px / 40 px**. iOS'ta odaklanınca otomatik zoom, hedef 44 px altında.
3. **P1 - Açık temada "koyu yeşil/kırmızı zemin + text-white" birleşimi ≈2.9:1 kontrast.** `user-theme.generated.css:105` `.text-white` açık temada koyu mürekkebe (11 18 32) çevriliyor; `bg-neon-green` (4 108 78) ve `bg-neon-red` (185 28 28) ise koyu kalıyor. Etkilenenler: **Sat** düğmesi (`HoldingsCard.tsx:254`), tehlikeli onay "Evet, sat / iptal et / sil" (`ConfirmDialog.tsx:46`), toast (`UserBinance.tsx:244`), UserRadar / UserSettings birincil düğmeleri.
4. **P1 - Geniş tablolar kart görünümsüz.** Portföy (4 tablo), Binance TR açık emirler (10 sütun) ve işlem defteri, kullanıcı / olay / veritabanı / MACD / daily-rising / mtf tabloları yalnız yatay kaydırma; global `table { min-width: 680px }` (`globals.css:523`). Portföy için yazılmış `.portfolio-mobile-trades` / `.portfolio-history-table-wrap` CSS'i hiçbir TSX'te kullanılmıyor (ölü kod).
5. **P1 - Arka plan / gizli panel yükü.** Ayarlar'da 5 alt panel `hidden` sınıfıyla ama **mount + fetch** ediliyor (`settings/page.tsx:660-681`; yükleme: `:1201,:1479,:1573,:1725,:1836`); Portföy 5 sn + 15 sn + 30 sn poll (`portfolio/page.tsx:285-287`); Sohbet 3 sn + 5 sn poll, yan panel mobilde kapalıyken de (`chat/page.tsx:565,567`); Kullanıcı Sinyal Raporu 30 sn'de bir **1000 satır** (`UserSignalReport.tsx:77`).
6. **P1 - PWA dayanıklılığı.** `liveSocket.ts` görünürlük / `online` olayı dinlemiyor; `apiRequest` zaman aşımı yok; SW yeni sürümde açık sayfayı otomatik `location.reload()` ediyor (`AppShell.tsx:33-38`), açık emir penceresi varken sayfa yenilenebilir.
7. **P1 - Push akışı iOS'ta yanlış yönlendiriyor.** `detectBrowser()` iOS Safari'yi "safari" sayıyor (`lib/push.ts:12-20`), `PushOnboardingModal.tsx:66` Chrome olmayan her tarayıcıya "Chrome önerilir" gösteriyor. iPhone'da Web Push yalnız Safari'den "Ana Ekrana Ekle" ile çalıştığı için bu kullanıcıyı yanlış yöne iter. Ayrıca SW varsayılan bildirim URL'si `/alerts` (`sw.js:63,85`; backend `app/alerting.py:80,129`), bu rota yok (404).
8. **P1 - Monitoring (Radar) satırları dar ekranda kesiliyor.** Rozet satırları `flex items-center gap-2.5` + `shrink-0` rozetler, sarma yok (`monitoring/page.tsx:1349-1383`, `:1745-1770`); `body/main { overflow-x: clip }` taşanı gizlediği için kesilen içerik kaydırılamaz.

---

## 1. Genel desenler (tekrar eden sorunlar)

| # | Desen | Kanıt | Ciddiyet | Öneri | Efor |
|---|---|---|---|---|---|
| G1 | **Özel sınıflar utility'leri eziyor** (katmansız CSS `@tailwind utilities`'ten sonra) | `globals.css:6` vs `:255` (`.input`: `min-h-10 text-sm`) ve `:435` (`.ui-button`: `min-height:2.5rem`). Etkilenen: BuyCard:210/245/260/265, BuyDialog:253/309, UserRisk:100/135, HistoryCard:44 (input); NotificationCard:45/78, UserSettings:288 (`ui-button` + `min-h-[44px]` = 40 px) | P1 | `.input`, `.ui-button`, `.card` vb. bileşen sınıflarını `@layer components {}` içine al; ayrıca `@media (pointer:coarse){ .ui-button{min-height:44px} .input,select,textarea{font-size:16px;min-height:44px} }` | S |
| G2 | **iOS odak zoom'u (<16 px girdi)** | `.input` 14 px; monitoring filtreleri `text-xs` (`monitoring/page.tsx:1268,1275,1286`); mtf-scanner `text-xs` (`mtf-scanner/page.tsx:394-420`); settings sayısal girdiler `w-28/w-24 ... text-sm` (`settings/page.tsx:930,945,960,1294`); chat textarea `text-sm` (`chat/page.tsx:~1148`) ve `.chat-composer textarea{font-size:16px}` (`globals.css:511`) **ölü kural** (sayfa `chat-composer-section` kullanıyor, `.chat-composer` yok); UserSettings API anahtarı `text-sm` (`:143,:154`); giriş formu `.input` | P1 | G1'deki tek global kural hepsini kapatır; chat textarea'ya `text-base` | S |
| G3 | **Dokunma hedefi < 44 px** | `.ui-button` 40 px, `.ui-tabs button` 40 px (`globals.css:435,:462`); ✕ kapatma düğmeleri 14-24 px: users:61, monitoring (detay ve eşik modalı), Sidebar:237, binance-tr modalları; `px-2 py-1` mini düğmeler: page.tsx:142/157, monitoring:1074, MaBuySignals:370-371, mtf-scanner filtre düğmeleri; Sidebar kapat `w-8 h-8` (`Sidebar.tsx:122`) | P1 | `pointer:coarse` altında min 44 px; ✕ için ortak `IconButton` (44x44) | M |
| G4 | **Küçük font:** `text-[8px/9px]` 31, `text-[10px]` 275, `text-[11px]` 240 kullanım; TopBar kicker/status 8-8.3 px (`globals.css:481-483`); `eyebrow` 12 px | tüm sayfalar (en çok binance-tr 73, monitoring 41, reports 35, settings 33) | P2 | Mobilde alt sınır 11-12 px; kritik değerleri (fiyat, K/Z, durum) 12 px altına düşürme | M |
| G5 | **Tablo-yalnız-kaydırma** (kart görünümü yok, sembol sütunu yapışkan değil) | portfolio (557/660/725/769), binance-tr açık emirler `:1841` + işlem defteri `:1958`, HistoryCard `:61` (`min-w-[640px]`), users, audit-logs, database, macd-monitor (632/820/966/1041), daily-rising (404/451/526/583/665), mtf-scanner `:459`, reports (10+ tablo) | P1 | Ortak `<ResponsiveTable>`: `<md` kart, `md+` tablo (RadarScanLogModal / MaBuySignals deseni zaten iyi); en azından ilk sütunu `sticky left-0` yap | L |
| G6 | **`overflow-x: clip` taşmayı gizliyor** | `globals.css:24,:479` | P1 | 360/390/430 genişlikte `scrollWidth > clientWidth` yakalayan Playwright testi ekle (kesilen içerik şu an sessiz) | M |
| G7 | **`title=` ile verilen kritik bilgi** (dokunmatikte yok) | 239 `title=`; UserRadar:163/214, NotificationCard (olasılık/başabaş/net hedef), HoldingsCard:223/231/238/241 (maliyet bilinmiyor, net K/Z), monitoring LLM kanıt/tuzak (`:1769`), macd-monitor sütun açıklamaları, RadarScanLog rozet nedeni | P1 | Dokunma ile açılan `<InfoTip>` (popover) veya satır içi küçük açıklama | M |
| G8 | **Modal tutarsızlığı** | `useModalA11y` (odak tuzağı / Esc) iyi ama **kaydırma kilidi yok** (yalnız Sidebar:69-81 ve RadarScanLogModal:159-163 `body.overflow=hidden` yapıyor); `max-h-[90vh]/[92vh]` 10+ yerde (iOS adres çubuğunda taşar), `dvh` yalnız chat-modal, portfolio-detail, BinancePositionChartModal; alt-sheet'lerde safe-area yok (`ConfirmDialog.tsx:27`, `BuyDialog.tsx:261`); `interactiveWidget` yok (`layout.tsx:36-41`) (varsayım: Android klavye alt sheet'i örter). Hook'suz / role'süz modallar: users (2), monitoring skor eşiği (`:1808`), settings backfill (5, `:1046-1115`), Sidebar bildirimleri (`:233`), Disclaimer / PushOnboarding / NotificationPermission (role var, tuzak yok) | P1 | `<Modal>` bileşeni: portal + scroll lock + `dvh` + `pb-[env(safe-area-inset-bottom)]` + `useModalA11y`; tüm modalları buna taşı | L |
| G9 | **Native `confirm/alert`** | 21 çağrı: settings 14 (`:322,350,378,384,391,405,417,431,445,459,507,1856`...), CombinedPaperPanel, FeeModeCard, LlmManagement, binance-tr:1182 ("Tümünü iptal et") | P2 | Gerçek para / geri alınamaz işlemler için ortak onay penceresi (ConfirmDialog zaten var) | M |
| G10 | **Açık tema kontrastı** | bkz. Özet #3; ayrıca `placeholder-bunker-700` (≈1.7:1, settings sembol araması), `text-bunker-muted/70` 11 px "BİR DAHA GÖSTERME" | P1 | `text-white` yerine açık temada `--u-brand-text`; `bg-neon-*` + `text-white` birleşimi için özel kural | S |
| G11 | **Polling:** çoğu `useVisibleInterval` (iyi). İstisnalar: audit-logs:153 (kendi interval, `load` her filtre değişiminde yeniden kuruluyor, görünür olunca anında yenilemiyor), portfolio:285-312, CombinedPaperPanel:124 ve CombinedRisingTab:266 (60 sn, gizliyken de), daily-rising Countdown:132 (1 sn, gizliyken de), UserBinance Freshness:26 (1 sn, gizliyken de), monitoring `RelativeTime` her satırda ayrı interval (~30 adet, `:357-359`), symbol-analysis 5 sn (`:75`), UserBinance'te `usePortfolioSummary` mobilde gereksiz ikinci kaynak (`:148`) | P1/P2 | Tüm interval'ları `useVisibleInterval`'e taşı; zaman etiketleri için tek paylaşımlı "tick" context'i | M |
| G12 | **Semantik / erişilebilirlik** | iç içe `<main>` (audit-logs:193, users:162, database:117, portfolio:453, MaBuySignals, ProfilePanel) AppShell'in `<main>`'i içinde; tıklanan `div` satırlar (monitoring:1345) klavye/odak yok; admin/page.tsx:192 `aria-selected` var ama `role="tab"` yok; `th onClick` sıralama (binance-tr:~1990) klavyeye kapalı | P2 | `<main>` yalnız AppShell'de; satırlara `role="button" tabIndex=0` veya gerçek `<button>/<Link>` | M |
| G13 | **Tam sayfa yenileme veren `<a href>`** | `daily-rising/page.tsx:421,471,543,603,685` ve `settings/page.tsx:1130`; PWA'da gezinme yavaş, SW/WS sıfırlanır | P1 | `<Link>` / `SymbolLink` | S |
| G14 | **Tema / ilk boyama** | `themeColor` sabit koyu (`layout.tsx:41`), kullanıcı arayüzü açık tema; `data-theme` `useEffect` içinde (`UserShell.tsx:6-13`); `useAdminView` başlangıcı "advanced" (`adminView.ts:17`) -> Basit görünümdeki yönetici açılışta bir an yönetici kabuğunu (Sidebar + API istekleri) mount ediyor | P2 | `themeColor` için `media` çifti veya `<meta name=theme-color>` dinamik güncelle; seçimi `localStorage`'dan ilk render'da oku / inline script ile `data-theme` | S |

---

## 2. Kabuk, PWA ve ortak katman

| # | Sorun | Dosya:satır | Ciddiyet | Öneri | Efor |
|---|---|---|---|---|---|
| K1 | Mobil kullanıcı arayüzünde **Çıkış yok**, kullanıcı adı yok, mobilde üst çubuk / portföy bandı yok (`pband-lg hidden md:block`) | UserNav.tsx:13,36; UserShell.tsx:28 | **P0** | UserSettings > Profil sekmesine "Oturumu kapat" + kullanıcı adı kartı; alt menü "Diğer" listesine "Çıkış" | S |
| K2 | SW sürüm değişince **otomatik `location.reload()`**: açık alım/satım onayı, yazılmış form kaybolabilir | AppShell.tsx:33-38; sw.js:206-217 | P1 | "Yeni sürüm hazır - Yenile" şeridi; açık modal / kirli form varken ertele | M |
| K3 | WS: `visibilitychange` / `online` / `pageshow` yok; arka plandan dönüşte ölü soket ancak 45 sn eşik + 15 sn kontrol + 2-30 sn geri çekilme sonra fark ediliyor. 45 sn mesaj gelmezse (tickers sayılmıyor) sağlıklı soket de kapatılıyor (varsayım: backend sessiz kaldığı anlarda yeniden bağlanma döngüsü) | lib/liveSocket.ts:73-98,161-176 | P1 | Görünür olunca ve `online` olayında hemen yeniden bağlan + REST tazele; backend'den ping mesajı iste | M |
| K4 | `apiRequest` zaman aşımı / iptal yok; zayıf ağda yükleniyor ekranı sonsuz | lib/api.ts:24-37 | P1 | `AbortSignal.timeout(15000)` varsayılanı; çevrimdışı banner | S |
| K5 | SW: HTML yanıtları **durumuna bakılmadan** önbelleğe yazılıyor (404/500 dahil); ağ-önce strateji zaman aşımsız (varsayım: yavaş ağda soğuk açılış uzun bekler); çevrimdışı ekranı yok | sw.js:178-197 | P2 | `response.ok` kontrolü, 3-4 sn ağ zaman aşımı, basit çevrimdışı sayfa | S |
| K6 | Bildirim varsayılan URL `/alerts` -> rota yok (404); metinlerde **bozuk karakter** ("alarmý", çift UTF-8) | sw.js:55,63,72,85; backend/app/alerting.py:80,129 | P1 (URL) / P2 (metin) | `/` veya `/monitoring` yap; dosyayı UTF-8 yeniden yaz ("alarmı") | S |
| K7 | Bildirim ikonu / rozeti SVG (`/icon.svg`); Android bildirim çubuğunda SVG desteklenmez (varsayım) | sw.js:54-57 | P2 | 192 px PNG icon + tek renkli PNG badge | S |
| K8 | Push onboarding: iOS Safari'ye "Chrome önerilir"; iPadOS UA "Macintosh" olduğu için `isMobileDevice()` false -> masaüstü akışı; `BİR DAHA GÖSTERME` kalıcı, sonradan geri açma yolu yalnız UserSettings > Bildirim | lib/push.ts:12-28; PushOnboardingModal.tsx:66,205-207 | P1 | iOS'ta Chrome uyarısını atla; doğrudan "Paylaş > Ana Ekrana Ekle" ve standalone sonrası izin; iPadOS için `maxTouchPoints>1` | S |
| K9 | Manifest: `orientation: portrait-primary` (tablet/yatay kilit), `id` / `shortcuts` / `screenshots` yok, maskable ikon "any" ile aynı dosya (varsayım: güvenli alana uymuyor, kırpılır) | public/manifest.webmanifest | P2 | `orientation: any`, `id`, `shortcuts` (Radar, Binance TR), ayrı maskable PNG | S |
| K10 | Sidebar (yönetici): mobil kapat `w-8 h-8`; kapalıyken ekran dışı bağlantılar odaklanabilir (`inert` / `aria-hidden` yok); bildirim penceresi `max-h-[90vh]` + `[75vh]`, odak tuzağı / kaydırma kilidi yok; `PortfolioBand` mobilde hiç yok -> yönetici telefonda toplam değer / K-Z göremez | Sidebar.tsx:110,122,233-239; PortfolioBand.tsx:100-112 | P2 | Mobilde sidebar'a `inert`, kapat 44 px, mobil için tek satırlık kompakt portföy özeti | M |
| K11 | BottomNav (yönetici) iyi (safe-area var, `pb-[4.75rem]`); ama Ana sayfadaki "Hızlı Modül" kartları aynı 4 hedefin tekrarı; Toast'lar `fixed top-5` safe-area'sız (binance-tr:1236, UserBinance:244) | BottomNav.tsx:70-71; page.tsx:171 | P2 | Toast `top: max(1rem, env(safe-area-inset-top))`; ana sayfada mobil için kartları kaldır / özet yap | S |
| K12 | UserBottomNav: "Diğer" açılır listesi `bottom-full` ve yükseklik sınırsız (yatay modda 7 öğe x 44 px taşar); etiketler 12 px | UserBottomNav.tsx:63 | P2 | `max-h-[60dvh] overflow-auto` | S |
| K13 | RadarAlertModal `z-120`, açık alım/satım penceresinin (z-50) üstüne biniyor ve odağı çalıyor; ses `AudioContext` iOS'ta kullanıcı jesti olmadan sessiz kalır (varsayım) | globals.css:646; RadarAlertModal.tsx:11-41,177-211 | P2 | Emir penceresi açıkken uyarıyı kuyruğa al / küçük şerit; ilk dokunuşta AudioContext "unlock" | M |
| K14 | AuthGate: kullanıcı adı `autoFocus` (PWA açılışında klavye fırlar), `autoCapitalize/autoCorrect` yok; doğrulama sırasında "Oturum açın" başlığı görünüyor | AuthGate.tsx:85-97 | P2 | `autoFocus` kaldır, `autoCapitalize="none" autoCorrect="off"`, doğrulama sırasında yalnız loader | S |
| K15 | DisclaimerModal metni "yalnızca kağıt (paper) ticaret, gerçek para kullanılmaz" diyor; oysa uygulamada gerçek Binance TR emri veriliyor. İçerik / hukuki tutarsızlık; ayrıca odak tuzağı yok, "BİR DAHA GÖSTERME" 11 px düşük kontrast | DisclaimerModal.tsx:76-79,97-103 | P1 (içerik) | Metni gerçek işlem açıkken güncelle; 44 px hedef | S |
| K16 | `global-error.tsx` `100vh`, satır içi stil, tema yok | global-error.tsx:11 | P2 | `min-height:100dvh` | S |

---

## 3. Sayfa bazında bulgular

### 3.1 `/` Ana sayfa (`app/page.tsx`; kullanıcı: `UserHome`)

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Yönetici ana sayfası: mod düğmesi ve "YENİDEN DENE" `text-[10px]/[11px] px-2 py-1` (~24 px yükseklik) | page.tsx:142,157 | P1 | `ui-button` + 44 px | S |
| "OTONOM İŞLEM" değeri `${trades} · ${±₺tutar}` 2 sütunda 1.35 rem içinde sarabilir (varsayım) | page.tsx:164-166 | P2 | Değeri iki satıra böl (adet / tutar) | S |
| Her `signal` WS mesajı 3 REST isteği tetikliyor + 15 sn poll (yoğun sinyalde istek fırtınası) | page.tsx:100-110 | P2 | 1-2 sn debounce | S |
| Hızlı modül kartları BottomNav'ın tekrarı; "Son aktivite" iç kaydırma (`max-h-40`) sayfa kaydırmasıyla çakışır | page.tsx:171-248,285 | P2 | Mobilde kartları gizle, aktiviteyi sınırsız göster | S |
| UserHome: izleme şeridinde "×" düğmesi `w-9` (36 px) ve bağlantıya bitişik, onaysız siler | FavoritesStrip.tsx:66 | P2 | 44 px, onay / geri al | S |
| UserHome: iyi - 15 sn `useVisibleInterval`, hata / boş / yükleniyor durumları var, kartlarda 44 px hedefler | UserHome.tsx:17-31 | (iyi) | - | - |

### 3.2 `/admin` (`admin/page.tsx`)

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 8 sekme yatay kaydırma çubuğu: iyi (`touch-target`, `no-scrollbar`), ama kaydırılabildiğine dair ipucu yok (`tab-scroll-fade` kullanılmamış) | :176-199 | P2 | `tab-scroll-fade` | S |
| `aria-selected` var, `role="tab"` / `tablist` yok | :192 | P2 | Rolleri ekle | S |
| Her sekme kendi `<main>`'ini ve başlığını getiriyor (çift başlık, çift `main`) | database / audit / users | P2 | Gömülü modda başlık / main'i gizle | M |
| Sekme içeriği `dynamic` + `ssr:false`: iyi (hafif); Chat sekmesi `calc(100dvh - 8.25rem)` ile iç içe kaydırma (varsayım) | :10-80; globals.css:51 | P2 | Gömülüyken sabit yükseklik kullanma | S |

### 3.3 `/audit-logs`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 8 sütunlu tablo yalnız yatay kaydırma, kart yok | :227-269 | P1 | Kart görünümü (zaman, kullanıcı, eylem, detay) | M |
| Kendi `setInterval` (30 sn): `load` bağımlılığı yüzünden her filtre / yazım değişiminde yeniden kuruluyor; sekmeye dönünce hemen yenilemiyor | :153-159 | P2 | `useVisibleInterval(load,30000)` | S |
| Filtre çubuğu: iki `select !w-auto` + 2 girdi + 2 düğme sarar; girdiler 14 px; `FİLTRELE` düğmesi gereksiz (yazım zaten otomatik) | :214-225 | P2 | Filtreleri açılır panele al | M |
| Silme modalı: `max-h-[90vh]`, kaydırma kilidi / odak tuzağı / Esc yok; `type="number"` `inputMode` yok; liste hatası modal içinde de görünüyor | :283-300 | P2 | `<Modal>` bileşeni | S |
| "Eski Kayıtları Temizle" kırmızı düğme başlıkla aynı satırda, 40 px | :202 | P2 | Ayrı satır / menü | S |

### 3.4 `/binance-tr` (yönetici; kullanıcı: `UserBinance` + kartlar)

Yönetici sayfası (`binance-tr/page.tsx`, 2744 satır):

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Pozisyon kartları (sm altı) iyi; ama **Grafik / SL-TP / Sat** üç düğme `h-10` (40 px), `gap-1.5` (6 px) - gerçek paralı "Sat" yan yana, yanlış dokunuş riski | ~:1625-1655 | **P1** | Sat'ı ayrı satıra / ayrı renk blok al, 44-48 px, aralık >=12 px | S |
| **Bekleyen emirler** 10 sütunlu tablo, "İptal" işlem sütunu en sağda (kaydırmadan görünmez); kart yok | :1841-1900 | **P1** | Kart görünümü: sembol, yön, tip, miktar, fiyat + büyük İptal | M |
| İşlem defteri 8 sütun, `th onClick` sıralama (klavye yok), kart yok | :1958-2000 | P1 | Kart görünümü + sıralama seçici | M |
| "Tümünü iptal et" native `window.confirm` | :1182 | P1 | ConfirmDialog (kaç emir, hangi semboller) | S |
| 4 modal `useModalA11y` ile (iyi) ama `max-h-[90vh]`, kaydırma kilidi yok; ✕ ~16 px; "ONAYLA - SAT" `text-xs py-2`; SL/TP mod seçici `py-1.5 text-xs` | :2068-2140,2341-2470,2479-2640 | P1 | Ortak `<Modal>`, 48 px birincil düğme | M |
| `BinancePositionChartModal`: tam ekran `100dvh` + dokunmatik sürükleme (`touch-none`, `touchmove passive:false`) iyi; ama kapat / İptal / Güncelle 38 px; 1 sn geri sayım sayacı gizliyken de çalışıyor | BinancePositionChartModal.tsx:1450,1729-1740,566 | P2 | 44 px; `useVisibleInterval` | S |
| Girdiler `input ... text-sm` (14 px) -> iOS zoom | :2403 | P1 | G1 | S |
| KPI başlıkları 9-11 px, `FeeModeCard` mobilde `max-w-sm` | :1351-1410 | P2 | G4 | S |

Kullanıcı arayüzü (`UserBinance` + `components/user/binance/*`):

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| **Sat** ve tehlikeli onay düğmeleri açık temada koyu zemin + koyu yazı (≈2.9:1) | HoldingsCard.tsx:254; ConfirmDialog.tsx:46 | P1 | G10 | S |
| Girdi gerçek yükseklik 40 px / font 14 px (G1): tutar, SL, RR | BuyCard.tsx:210-265 | P1 | G1 | S |
| İşlem geçmişi 8 sütun `min-w-[640px]` yatay kaydırma | HistoryCard.tsx:61 | P1 | Coin bazlı kart (alış / satış / sonuç) | M |
| ConfirmDialog alt sheet: yükseklik sınırı yok (uzun içerik / uyarı kutusu + klavye), safe-area yok, kaydırma kilidi yok | ConfirmDialog.tsx:27,34 | P1 | `max-h-[85dvh] overflow-y-auto pb-[env(safe-area-inset-bottom)]` | S |
| Toast `top-3` safe-area'sız, `text-white` açık temada koyu (kontrast) | UserBinance.tsx:244 | P1 | G10 + `top` safe-area | S |
| `Freshness` 1 sn interval gizliyken de; `usePortfolioSummary` mobilde ikinci REST/WS kaynağı | UserBinance.tsx:26,148 | P2 | `useVisibleInterval`; kaynağı `settings`ten öğren | S |
| Coin arama önerileri `onBlur` 150 ms gecikmeli; mobilde klavye açıkken liste (max-h-60) alt menü / klavyeyle çakışabilir (varsayım) | BuyCard.tsx:208,213 | P2 | `scrollIntoView`, `max-h` dvh | S |
| İyi: idempotent `client_order_id`, belirsiz emir akışı, 48 px düğmeler, `inputMode="decimal"` | BuyCard / HoldingsCard | (iyi) | - | - |

### 3.5 `/chat`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Mesaj kutusu `text-sm` 14 px (iOS zoom); mobil 16 px kuralı ölü (`.chat-composer` sınıfı kullanılmıyor) | chat/page.tsx:~1148; globals.css:510-512 | P1 | `text-base` | S |
| Mobilde Enter = gönder; yeni satır için Shift+Enter ipucu mobilde anlamsız | chat/page.tsx:~1155 | P2 | `pointer:coarse` ise Enter yeni satır, yalnız düğmeyle gönder | S |
| Mesaj alanı yapışkan değil: mobilde `chat-page` yükseklik auto, composer sayfa akışında (uzun sohbette en alta kaydırmak gerekiyor; sticky kural ölü sınıfta) | globals.css:98-104,510 | P1 | Composer `sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))]` (BottomNav üstü) | M |
| 3 sn araç log + 5 sn yan panel poll'u, yan panel mobilde kapalıyken de çalışıyor | chat/page.tsx:565,567 | P1 | `controlsOpen` değilken durdur | S |
| Ses / aksiyon düğmeleri `text-xs px-2 py-1` (~26 px); `webkitSpeechRecognition` iOS PWA'da çalışmaz (varsayım) | chat/page.tsx:~1085-1110 | P2 | 44 px; destek yoksa mikrofonu gizle | S |

### 3.6 `/daily-rising`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 5 tablo `overflow-x-auto`, 8+ sütun, kart yok | :404,451,526,583,665 | P1 | G5 | L |
| Sembol bağlantıları `<a href>` -> tam sayfa yenileme | :421,471,543,603,685 | P1 | `SymbolLink` | S |
| Üst blok `flex-col items-end` (geri sayım + tarama düğmesi sağa yaslı); Countdown 1 sn interval gizliyken de | :130-133,~335-345 | P2 | Mobilde `items-stretch`; `useVisibleInterval` | S |
| 30 sn yoklama gizlilik duyarlı (iyi) | :269-279 | (iyi) | - | - |

### 3.7 `/database`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Tablo seçilince sonuç **aşağıda** açılıyor, ekran kaymıyor; kullanıcı tablo listesinde kalıyor | :146-150,165 | **P1** | Seçimde `scrollIntoView` veya mobilde iki ekranlı (liste -> detay) akış | S |
| `max-h-[70vh]` liste + `max-h-[65vh]` iç içe iki kaydırma alanı | :145,189 | P2 | Sayfa kaydırmasına bırak, sticky başlık | S |
| CSV / SQL indirme: blob + `a.download` (iOS PWA standalone'da güvenilmez, varsayım) | :83-105 | P2 | `navigator.share` dosya veya yeni sekmede aç | M |
| Yarışan yanıt koruması yok (hızlı tablo değişiminde eski yanıt yenisini ezebilir) | :47-63 | P2 | Sıra numarası (audit-logs:104 deseni) | S |

### 3.8 `/ma-buy-signals` (`MaBuySignals.tsx`)

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| İyi: `<md` kart listesi, sıralama düğmeleri, 30 sn görünürlük duyarlı yenileme | :342-378 | (iyi) | - | - |
| Sıralama düğmeleri `px-2 py-1` (~26 px); 5 `select/input` filtre satırı 14 px | :370-371,308-325 | P2 | 44 px; filtreleri açılır panele | S |
| Kart listesi sayfalamasız (sunucu kırpıyor ama yüzlerce kart olabilir) | :373-377 | P2 | "Daha fazla göster" | S |

### 3.9 `/macd-monitor`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 4 tablo; ana tablo her zaman yüzlerce sembol satırı (sanallaştırma / sayfalama yok), çok sütun | :632-760,820,966,1041 | P1 | Kart / kompakt liste + sayfalama | L |
| Sütun açıklamaları yalnız `title` (GÜÇ, SIÇRAMA, ERKEN) | :656-660 | P1 | G7 | M |
| Arama kutusu `w-56` sabit, 14 px | :621 | P2 | `w-full sm:w-56` | S |
| Poll 30 sn + 60 sn görünürlük duyarlı (iyi) | :353-354 | (iyi) | - | - |

### 3.10 `/monitoring` (Radar & Hız Avcısı; kullanıcı: `UserRadar`)

Yönetici sayfası:

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Aday satırı rozet şeridi sarmıyor (sembol + mod + "4'lü Teyit (Master Surge)" + ML%) `shrink-0`; `overflow-x: clip` ile kesilir | :1349-1383 | **P1** | `flex-wrap`, rozetleri ikinci satıra al | S |
| Son bildirim satırı (YENİ, sembol, hedef, skor, LLM) tek satır, sarma yok; LLM kanıt / tuzak yalnız `title` | :1745-1770 | **P1** | `flex-wrap`; LLM gerekçesini genişleyen satır yap | S |
| Üst KPI kartları sekme düğmeleriyle aynı işi yapıyor (iki kez 4 hedef): mobilde ilk ekranın yarısı | :1074-1130 vs :1153-1210 | P2 | Mobilde KPI'yi tek satır özet yap | S |
| Filtreler `text-xs py-1.5` (≈30 px, 12 px font), temizle "✕" ~12 px | :1263-1290 | P1 | G1-G3 | S |
| Skor eşiği modalı: `role=dialog` yok, odak tuzağı yok, `autoFocus` sayısal girdi (klavye), ✕ küçük, `vh` | :1808-1895 | P1 | `<Modal>` | S |
| Aday satırı `div onClick` (klavye yok), "Grafik" `min-h-[36px]` | :1345,:1447 | P2 | `<button>` / 44 px | S |
| Her satırda `RelativeTime` ayrı interval (~30 adet) | :357-359 | P2 | Ortak tick | M |
| Detay modalı `useModalA11y` ile iyi; `max-h-[90vh]`, ✕ ~24 px | :504-600 | P2 | G8 | S |

`RadarScanLogModal` (yönetici): mobil tam ekran + kart görünümü + `MAX_RENDER_ROWS` + kaydırma kilidi **iyi örnek**. Küçük: ✕ ve YENİLE 40 px (`ui-button`), arama girdisi 14 px, `Otomatik` onay kutusu 16 px (`:244-251,:322`) - P2.

`UserRadar` (kullanıcı):

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| "Grafikte gör" ve aktif sekme `bg-neon-green text-white` açık temada kontrast ≈2.9:1 | UserRadar.tsx:222,342 | P1 | G10 | S |
| Olasılık / skor açıklamaları `title` | :150,163,210,214 | P1 | G7 | M |
| Detay penceresi alt sheet: safe-area yok, kaydırma kilidi yok, yükseklik sınırı yok | :183-235 | P2 | `<Modal>` | S |
| İyi: sekmeler 44 px, kart + 44 px detay düğmesi, `useVisibleInterval` + WS gecikmeli yenileme, boş / hata durumları | :239-368 | (iyi) | - | - |

### 3.11 `/mtf-scanner` (yalnız yönetici)

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Kapsam `select` `onChange` anında tüm çiftleri tarıyor ("Tüm Çiftler" ağır) - yanlışlıkla dokunma maliyeti yüksek | :394-400 | P1 | Ayrı "Tara" düğmesi / onay | S |
| Girdi / select `text-xs` (iOS zoom), filtre düğmeleri `py-1.5` | :370-420 | P1 | G1-G3 | S |
| Tablo 9+ sütun (zaman dilimleri sütunu geniş), kart yok | :459-480 | P1 | G5 | L |
| "Grafik" 4'lü ekrana gidiyor (mobilde 4 canlı grafik ağır, varsayım) | :~480 | P2 | Mobilde tek grafiğe yönlendir | S |

### 3.12 `/notifications` (kullanıcı: `UserNotifications`)

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Yönetici (gelişmiş) görünümde sayfa çıkmaz sokak: tek satır metin, bağlantı yok | notifications/page.tsx:9 | P2 | Radar sayfasına link / yönlendirme | S |
| 200 kartın hepsi tek seferde render (sanallaştırma / "daha fazla" yok) | UserNotifications.tsx:78-88,115-132 | P2 | 25'er sayfalama (UserSignalReport deseni) | S |
| Olasılık açıklaması `title`; filtre değişince eski satırlar yükleme bitene kadar görünür (`setLoaded(false)` ama `rows` temizlenmiyor) | :53,103 | P2 | `setRows([])` | S |
| İyi: mobil kart / masaüstü tablo ayrımı, 44 px filtreler, 30 sn görünürlük duyarlı yenileme | :94-166 | (iyi) | - | - |

### 3.13 `/portfolio`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 4 tablo (açık otonom 8 sütun, ana hesap, geçmiş...) yalnız yatay kaydırma, sembol sütunu yapışkan değil; hazırlanmış mobil kart CSS'i kullanılmıyor | portfolio/page.tsx:557,660,725,769; globals.css:~381-400 | **P1** | `.portfolio-mobile-trades` kartlarını bağla | M |
| 5 sn + 15 sn + 30 sn poll, WS açıkken bile; ayrıca `liveStatus!=="open"` iken 15 sn daha | :285-287,312 | P1 | WS canlıyken 30-60 sn'ye düşür; `useVisibleInterval` | S |
| Başlık alanında "● CANLI" 10 px rozet, "Yenile" ui-button 40 px | :466-472 | P2 | G3 | S |
| Üst sekmeler `grid-cols-2` 12 px metin, uzun etiket ("Kombine Paper (5.000 ₺)") iki satıra sarar | :477-486 | P2 | Kısalt | S |
| CombinedPaperPanel 60 sn `setInterval` gizliyken de çalışır; native confirm | CombinedPaperPanel.tsx:124,129 | P2 | G9, G11 | S |

### 3.14 `/profile` (`ProfilePanel`; kullanıcıda Ayarlar > Profil)

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Kullanıcı görünümünde `router.replace` + `null` -> kısa boş ekran | profile/page.tsx:12-15 | P2 | `redirect()` / yükleniyor göstergesi | S |
| "Hızlı erişim" kartı mobil menüyle çakışıyor; kullanıcı menüsünde olmayan `/portfolio` bağlantısı da var | ProfilePanel.tsx:160-168 | P2 | Kullanıcıda gizle | S |
| "Arayüz Modu" `select` 14 px, `Wrap` `main` iç içe | :175-191,75 | P2 | G1, G12 | S |
| **Çıkış / oturum bilgisi yok** (bkz. K1) | - | P0 | Buraya ekle | S |
| Şifre alanları: `autoComplete` doğru, `required/minLength` var (iyi) | :107-143 | (iyi) | - | - |

### 3.15 `/reports` (yönetici; kullanıcı: `UserSignalReport`)

Yönetici:

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 10+ `table-compact` tablo; bazıları `max-h-[300-360px]` ile **iç içe dikey + yatay kaydırma** (parmak kaydırması sayfaya geçmez) | reports/page.tsx:441,478,1473,1530 | P1 | Dikey sınırı mobilde kaldır | S |
| Yoğun veri yükü (500 bildirim, 300 sembol, 100 işlem) tek seferde; mobilde sayfalama yok | :147,1148,1329 | P2 | Sayfalama / lazy sekme | M |
| Alt sekme çubuğu `py-1.5 text-xs` (~30 px) | :1412-1428 | P2 | G3 | S |

`UserSignalReport` (kullanıcı):

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 30 sn'de bir `limit=1000` bildirim indiriliyor (mobil veri / pil) | UserSignalReport.tsx:77,84 | P1 | Özet + ilk 50; "daha fazla" ile sayfalı çek, poll'u 60-120 sn | M |
| Yüklenirken boş durum ("Bu süzgece uyan bildirim yok") yanıltıcı; KPI'lar "-" | :134,161 | P2 | Skeleton | S |
| İyi: kart / tablo ayrımı, 44 px düğmeler, ilerleme çubuğuna `aria-label` | :105-111,165-185 | (iyi) | - | - |

### 3.16 `/risk` (`UserRisk`)

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Girdiler `text-base min-h-[44px]` yazılı ama G1 nedeniyle 14 px / 40 px | UserRisk.tsx:100,135 | P1 | G1 | S |
| Yönetici görünümünde sayfa tek satır metin (bağlantısız) | risk/page.tsx:8 | P2 | Link | S |
| Yükleme hatasında "Tekrar dene" `ui-button-secondary` ama `.ui-button` tabanı yok (stil eksik olabilir, varsayım) | :79 | P2 | `ui-button ui-button-secondary` | S |
| İyi: `range` 44 px, `type=number inputMode=decimal`, Kaydet düğmesi sayfa sonunda ama sayfa kısa | :89-104,141-147 | (iyi) | - | - |

### 3.17 `/settings` (yönetici; kullanıcı: `UserSettings`)

Yönetici (2080 satır):

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 5 alt panel (Radar, Bildirim, Chat, Otonom Paper, MACD) `hidden` ile **hep mount**; her biri açılışta ayrı fetch; ayrıca 60 sn x2 poll (top-gainer, aktivite) | settings/page.tsx:660-681,163,203,1201,1479,1573,1725,1836 | **P1** | Yalnız aktif sekmeyi mount et; poll'ları sekmeye bağla | M |
| Birden çok bağımsız KAYDET (üstte genel, her panelde ayrı); üstteki uzun sayfada kaybolur, yapışkan kayıt çubuğu yok | :618,1315,1768 | P1 | Yapışkan "Kaydet" çubuğu + kirli durum uyarısı | M |
| 14 native `confirm/alert` (sıfırlama, yedek, backfill...) | :322-507,1856 | P1 | ConfirmDialog | M |
| 5 backfill modalı: `role` / Esc / odak tuzağı yok, `max-h-[80vh]`, 3-4 sütunlu istatistik şeritleri 360 px'te sıkışık | :1046-1120 | P1 | `<Modal>` | M |
| 37 `type=number` sabit genişlikli (`w-16/20/24/28`), `py-1.5 text-sm` (≈34 px, 14 px) | :930-960,1294,1643-1647 | P1 | G1-G3, tam genişlik mobilde | M |
| `select` ile Açık/Kapalı (`"1"/"0"`) 20+ yerde; mobilde açılır liste yerine anahtar daha hızlı | :1766-2062 | P2 | Toggle bileşeni | M |
| PostgreSQL yedeği blob indirme (iOS PWA'da güvenilmez, varsayım) | :569-600 | P2 | Veritabanı sayfasıyla ortak çözüm | M |
| Sekme çubuğu 9 sekme yatay kaydırma, kaydırma ipucu yok | :641-660 | P2 | `tab-scroll-fade` | S |

`UserSettings`:

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| **Çıkış yok** (K1) | UserSettings.tsx | P0 | Ekle | S |
| Birincil düğmeler `bg-neon-green text-white` açık temada kontrast ≈2.9:1 | :160,208 | P1 | G10 | S |
| Binance API anahtar girdileri `text-sm` 14 px (iOS zoom); `autoCorrect` yok | :133-156 | P1 | `text-base`, `autoCorrect="off"` | S |
| Bildirim bölümü: iOS'ta "tarayıcı desteklemiyor" nedeni anlatılmıyor (PWA kurulu değil); "Ana Ekrana Ekle" yönlendirmesi / uygulama kurulumu yok | :170-216 | P1 | `isStandalonePwa()` / iOS durumuna göre talimat + kurulum düğmesi | M |
| `denied` durumunda cihaza özel yönerge yok | :196 | P2 | Android / iOS adımları | S |
| İyi: 44 px anahtarlar (`role=switch`), sekme `role=tab`, `?tab=` desteği | :47-58,246-265 | (iyi) | - | - |

### 3.18 `/symbol-analysis`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Sayfa açılışında ve **her sembol değişiminde LLM yorumu otomatik** istenir (token / maliyet, mobil veri) | symbol-analysis/page.tsx:95-99 | P2 | Manuel düğme veya önbellek | S |
| 5 sn `useVisibleInterval` + `r.ok` kontrolsüz `r.json()`; hata `error` temizlenmiyor | :66-75 | P2 | `getJSON`, poll 15 sn | S |
| `Tabs` 7 zaman dilimi (40 px düğmeler, yatay kaydırma var); sembol `select max-w-40` 14 px | :113-116 | P2 | G1, G3 | S |
| Gömülü mod (`?embedded=1`) `min-h-screen` | AppShell.tsx:49 | P2 | `dvh` | S |

### 3.19 `/system-health`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| Genel olarak iyi: `useVisibleInterval` 10 sn + WS, 2 sütunlu kartlar, hata şeridi, 44 px yenile düğmesi | system-health/page.tsx:19-62 | (iyi) | - | - |
| Hata durumunda değerler "-" kalıyor, son başarılı zaman damgası yok | :22,47-54 | P2 | "son güncelleme" etiketi | S |

### 3.20 `/users`

| Sorun | Kanıt | Cs. | Öneri | Efor |
|---|---|---|---|---|
| 6 sütunlu tablo yatay kaydırma; **DÜZENLE / SİL** en sağda, `!min-h-9` (36 px), 8 px aralık, kaydırmadan görünmez | users/page.tsx:178-205 | **P1** | Kart (kullanıcı, rol, durum + 44 px düğmeler), SİL ayrı satır | M |
| Modal ✕ ~16 px; rol düğmeleri `py-2`; odak tuzağı / Esc / kilit yok; `autoFocus` kullanıcı adı | :56-90 | P1 | `<Modal>` | S |
| Kullanıcı adı alanında `autoCapitalize` / `autoComplete="off"` yok; bildirim zamanlayıcısı temizlenmiyor | :65,139-142 | P2 | Ekle | S |
| Silme onayı `max-h-[90vh]`, geri alınamaz işlem için tek dokunuşlu sonuç | :92-114 | P2 | Kullanıcı adını yazdır | S |

---

## 4. Kullanıcı arayüzü bileşenleri: kısa değerlendirme

| Bileşen | Durum | Not |
|---|---|---|
| `UserShell` / `UserBottomNav` | Çıkış yok (K1); alt menü safe-area'lı (iyi); "Diğer" açılır liste sınırsız yükseklik (K12); kök `min-h-screen` yerine `dvh` | UserShell.tsx, UserBottomNav.tsx:63 |
| `UserHome` + `NotificationCard` + `FavoritesStrip` | 44 px hedefler çoğunlukla iyi (yalnız `.ui-button` 40 px, G1); `title` bilgileri (G7); "×" 36 px | NotificationCard.tsx:45,152 |
| `UserNotifications` | İyi kart / tablo ayrımı; sayfalama yok | bkz. 3.12 |
| `UserRadar` | Kontrast (G10), `title`, alt sheet | bkz. 3.10 |
| `UserBinance` + kartlar | İşlevsel olarak olgun; G1 / G10 / geçmiş tablosu / ConfirmDialog | bkz. 3.4 |
| `UserRisk` | G1 | bkz. 3.16 |
| `UserSettings` | Çıkış yok, kontrast, anahtar girdisi 14 px, iOS bildirim yönergesi | bkz. 3.17 |
| `UserSignalReport` | 1000 satır / 30 sn | bkz. 3.15 |
| `KpiStrip` | Ana sayfadan kaldırılmış (kullanılmıyor); kodu temizle | KpiStrip.tsx |

---

## 5. Olumlu bulgular (korunmalı)

- `useVisibleInterval` yaygın ve doğru kullanılmış; `useModalA11y` odak tuzağı / Esc / odak iadesi sağlıyor.
- Alt gezinme çubukları `env(safe-area-inset-bottom)` kullanıyor; içerik `pb-24` / `4.75rem + safe-area` boşluğu bırakıyor.
- `RadarScanLogModal`, `MaBuySignals`, `UserNotifications`, `UserSignalReport` mobil-önce kart / tablo ayrımı için referans örnek.
- Gerçek paralı akışlarda idempotent emir kimliği, belirsiz emir uyarısı, onay penceresi (BuyCard / HoldingsCard).
- Hata / boş / yükleniyor durumları çoğu sayfada ayrı ele alınmış; `auth-expired` olayıyla giriş ekranına dönüş çalışıyor.

---

## 6. Geliştirilmesi gereken kısımlar (öncelikli yol haritası, en çok 15)

| Sıra | İş | Kapsadığı bulgular | Ciddiyet | Efor |
|---|---|---|---|---|
| 1 | **Kullanıcı mobilinde Çıkış + hesap bilgisi** (Ayarlar > Profil ve "Diğer" menüsü) | K1 | P0 | S |
| 2 | **CSS katman düzeltmesi + dokunmatik tabanı:** bileşen sınıflarını `@layer components`'e taşı; `pointer:coarse` altında girdi 16 px / 44 px, `.ui-button` 44 px | G1, G2, G3 | P1 | S |
| 3 | **Açık tema kontrast düzeltmesi** (`bg-neon-*` + `text-white` birleşimleri; Sat / tehlikeli onay / toast) ve placeholder kontrastı | G10 | P1 | S |
| 4 | **Ortak `<Modal>` bileşeni:** portal, kaydırma kilidi, `dvh`, safe-area, `useModalA11y`; users / monitoring / settings / audit / Sidebar / ConfirmDialog / BuyDialog taşınır | G8 | P1 | L |
| 5 | **`<ResponsiveTable>` ve öncelikli sayfalar:** Portföy (hazır CSS'i bağla), Binance TR açık emirler + işlem defteri + HistoryCard, Kullanıcılar, Olay kayıtları | G5 | P1 | L |
| 6 | **PWA ağ dayanıklılığı:** WS'i görünür / online olayında yeniden bağla, `apiRequest` zaman aşımı, SW yenileme için "Yeni sürüm" şeridi (otomatik reload yok), SW HTML önbelleğinde `ok` kontrolü | K2, K3, K4, K5 | P1 | M |
| 7 | **Push / iOS akışı:** iOS Safari için "Ana Ekrana Ekle" öncelikli akış (Chrome uyarısını kaldır), iPadOS algılama, Ayarlar > Bildirim'de kurulum / izin yönergeleri, `/alerts` URL'si ve SW metin kodlaması düzeltmesi, PNG bildirim ikonu | K6, K7, K8 | P1 | S-M |
| 8 | **Gizli panel ve arka plan yükünü kes:** Ayarlar'da yalnız aktif sekme mount, Chat yan panel poll'u, Portföy poll'larını WS'e göre azalt, Kullanıcı Sinyal Raporu sayfalı yükleme, kalan `setInterval`'leri `useVisibleInterval`'e taşı | G11 | P1 | M |
| 9 | **Monitoring satır / rozet taşmaları ve filtreleri:** `flex-wrap`, LLM gerekçesi için dokunmayla açılan satır, filtre alanları 44 px / 16 px | monitoring bulguları, G7 | P1 | S-M |
| 10 | **Dokunma hedefi turu:** ✕ düğmeleri (ortak `IconButton`), mini düğmeler (`px-2 py-1`), Binance TR yönetici sayfasında Sat / SL-TP / Grafik ayrımı | G3, binance-tr | P1 | M |
| 11 | **`title` tooltip yerine dokunmatik `InfoTip`:** olasılık / başabaş, net K/Z, LLM kanıtı, MACD sütunları | G7 | P1 | M |
| 12 | **Sohbet mobil düzeni:** composer yapışkan (BottomNav üstünde), 16 px girdi, mobilde Enter = yeni satır, sesli giriş desteği kontrolü | 3.5 | P1 | M |
| 13 | **Ayarlar mobil kullanımı:** yapışkan Kaydet çubuğu + kirli durum uyarısı, native confirm/alert'leri ConfirmDialog'a taşı, Açık/Kapalı `select`lerini anahtara çevir | 3.17, G9 | P1/P2 | M-L |
| 14 | **Veritabanı sayfası mobil akışı** (liste -> detay), indirme alternatifi (paylaş / yeni sekme), `daily-rising` `<a>` -> `Link`, `mtf-scanner` kapsam `select`i anında taramasın | 3.7, 3.6, 3.11, G13 | P1/P2 | S-M |
| 15 | **Otomasyon ve cila:** 360/390/430 genişlikte `scrollWidth` taşma testi (Playwright), `themeColor` / FOUC ve `useAdminView` ilk render düzeltmesi, iç içe `<main>` temizliği, manifest (`orientation`, `id`, `shortcuts`, maskable PNG), Disclaimer metin tutarlılığı | G6, G12, G14, K9, K15 | P1/P2 | M |

Önerilen sıra: 1-3 (yarım gün, en yüksek getiri), sonra 6-8 (PWA / yük), 4-5 (büyük refactor), kalanlar.
