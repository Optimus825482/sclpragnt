# Frontend kod denetimi — 2026-10-18

Kapsam: `frontend/app/**` (öncelik: `components/user/**`, `lib/usePortfolioSummary.ts`, `lib/liveSocket.ts`, `lib/useVisibleInterval.ts`, `lib/tradeApi.ts`, `charts/**`). Salt okuma; hiçbir dosya değiştirilmedi, commit yapılmadı.
Not: `UserBinance.tsx`, `HoldingsCard.tsx` ve `usePortfolioSummary.ts` başka bir ajan tarafından değiştiriliyor; bu dosyalardaki satır numaraları ±20 kayabilir (bulgular okuma anındaki sürüme göre).

## Hüküm

Kod tabanı genel olarak olgun: emir yolu (idempotent `client_order_id`, `sendLock` ref'i, 45 sn zaman aşımı, "durum belirsiz" akışı), polling'in `useVisibleInterval` ile sekme-farkında olması, REST-seq korumaları ve `null` ≠ 0 disiplini sağlam. `npm run typecheck` temiz, `vitest` 277/277 geçiyor. Buna rağmen 15 doğrulanmış bulgu var; en önemlileri: (1) gerçek parayla ilgili bir idempotency boşluğu (satış "belirsiz" sonrası pencere yeniden açılınca oran %100'e dönüp yeni kimlikle gönderiliyor), (2) `/charts` sayfasında WS ile gelen otonom pozisyonların `status` alanının olmaması yüzünden panel/SL-TP çizgilerinin ~1 sn sonra kaybolması, (3) canlı fiyat kaynağının (WS `watch_prices`) kullanıcının izleme/favori sembollerini kapsamaması ve WS "taze" olduğu sürece yedek yoklamanın hiç çalışmaması. ESLint yerelde çalışmıyor çünkü `node_modules` eksik (bağımlılıklar package.json + lockfile'da tanımlı; yalnızca `npm ci` gerekiyor).

## Özet tablo

| # | Önem | Dosya:satır | Sorun | Çözüm |
|---|------|-------------|-------|-------|
| 1 | Yüksek | `components/user/binance/HoldingsCard.tsx` ~250, ~110, ~279 | Belirsiz satış sonrası pencere kapatılıp yeniden açılınca oran `%100`'e sıfırlanıyor; "Aynı emri tekrar gönder" yazıyor ama niyet anahtarı değiştiği için YENİ kimlikle %100 satış gidiyor | `uncertain` state'ine `chip`+`qty` koy; yeniden açılışta chip'i oradan geri yükle |
| 2 | Yüksek | `charts/page.tsx` 760-777 (+628, 1111, 1250, 1979) | WS `portfolio` ile gelen otonom pozisyon nesnelerinde `status` yok; `p.status === "open"` filtreleri ilk WS mesajından sonra hep boş → "açık otonom işlem" paneli ve SL/TP çizgileri kayboluyor | WS map'ine `status: "open"` ekle |
| 3 | Yüksek | `lib/useWatchPrices.ts` 16, 34 (+ `backend/app/watch_prices.py` 14-24) | WS `watch_prices` yalnızca son 20 bildirim + 7 günlük yükselenleri kapsıyor; WS taze (<15 sn) olduğu sürece yedek REST yoklaması atlanıyor → izleme/favori/radar sembollerinin fiyatı "—"; eski fiyat süresiz donuk kalıyor | Eksik sembolleri WS tazeliğinden bağımsız yokla; sembol başına zaman damgası tut, bayatı gösterme |
| 4 | Orta | `components/user/binance/UncertainOrderNotice.tsx` 27 (ve 15-16 yorumlar) | Dosya çift-kodlanmış (mojibake): kullanıcıya `SorgulanÄ±yorâ€¦` yazısı çıkıyor — tam da "emir durumu belirsiz" ekranında | Dosyayı UTF-8 olarak yeniden yaz (`"Sorgulanıyor…"`) |
| 5 | Orta | `components/user/binance/BuyCard.tsx` 133-137, 309-314, 89-93 | Başarılı alımdan sonra `plan` temizlenmiyor; "Onayla ve al" aktif kalıyor, kimlik sıfırlandığı için bir tık + onayla AYNI tutarda ikinci gerçek alım yapılabiliyor (eski fiyat/senaryo ile); `openConfirm` başarı mesajını da siliyor | Başarıdan sonra `setPlan(null)`; ya da planı "kullanıldı" diye kilitle |
| 6 | Orta | `components/user/binance/BuyCard.tsx` 66-87 | `buildPlan`'da istek sırası/iptal yok: istek uçarken sembol/tutar değişirse (`invalidate()` planı siler) eski yanıt gelip `setPlan` ile yanlış sembolün planını gösteriyor | `seq` ref'i (BuyDialog'daki gibi) veya `AbortController` |
| 7 | Orta-Düşük | `lib/liveSocket.ts` 68 | `COMMISSION_RE = /"commission_pct"s*:s*(...)/` — `\s` yerine `s` yazılmış; backend `json.dumps` varsayılan `": "` ile yayınlıyor → regex gerçek mesajda hiç eşleşmiyor (node ile doğrulandı) | `/"commission_pct"\s*:\s*([0-9.eE+-]+)/` |
| 8 | Orta | `components/user/UserBinance.tsx` ~70-73, `UserSettings.tsx` 76-88 | `/api/binance/settings` geçici hata verirse `configured:false` varsayılıyor → hesap bölümü gizleniyor, "anahtar ekle" gösteriliyor, polling duruyor, yeniden deneme yok | Hata durumunu `settings` içinden ayır (`error` state), tekrar dene düğmesi + otomatik retry |
| 9 | Orta | `components/user/UserRadar.tsx` 262, 322-325 | `error = !sRes.ok && !hRes.ok` — yalnız biri başarısızsa hata bayrağı kalkmıyor; `watch` hiç yüklenmediyse sonsuza dek "Yükleniyor…" | Sekme başına hata durumu tut |
| 10 | Orta | `components/PortfolioBand.tsx` 72-75; `UserBinance.tsx` Freshness `role="status"` (~31) | Sürekli değişen değerler `aria-live="polite"` bölgede: bant 2 sn'de bir, "Güncellendi N sn önce" metni her saniye ekran okuyucuya okunur | Canlı bölgeyi kaldır/`aria-live="off"`; yalnız durum geçişlerini (bayat/hata) duyur |
| 11 | Orta (perf) | `charts/page.tsx` 688, 760-777 | `useLiveMessages` tip filtresi olmadan abone: `wantsAllTypes` açılıyor, `binance_price` (büyük) her saniye JSON.parse ediliyor; ayrıca her `portfolio` mesajı 3 state'i yeniden kurup 2200 satırlık sayfanın tamamını ~1 Hz render ediyor | Tip listesi ver; portföy/pozisyon state'ini ayrı alt bileşene al veya eşitlik kontrolü yap |
| 12 | Düşük-Orta | `components/RadarAlertModal.tsx` 21-34 | Her osilatörün `ended` olayı `context.close()` çağırıyor: ilk nota (0,14 sn) bitince context kapanıyor → 2. ve 3. nota çalmıyor; kalan 2 `close()` reddedilmiş Promise (unhandled rejection) | Yalnız son notada kapat ve `context.close().catch(()=>{})` |
| 13 | Düşük-Orta | `lib/useModalA11y.ts` Escape bloğu; `RadarAlertModal.tsx` 176-204 | Escape'te `stopPropagation()` aynı hedefteki (document-capture) diğer dinleyicileri durdurmaz; iki modal birlikte açıkken (ör. BuyDialog + radar uyarısı) Esc ikisini birden kapatır, Tab tuzakları odağı birbirinden çalar. `ConfirmDialog` Esc'i `busy` iken de kapatıyor | Global modal yığını (yalnız en üstteki işler) / `stopImmediatePropagation`; Esc'te `busy` kontrolü |
| 14 | Orta-Düşük | `HistoryCard.tsx` 19-30; `UserNotifications.tsx` 63-75, 102/132; `RecentNotifications.tsx` 53; `lib/useWatchPrefs.ts` 105-126 | (a) Gün/filtre değişince eski yanıt yenisini ezebilir (seq yok), önceki günün verisi yeni başlıkla görünür; (b) liste anahtarları `…-${i}` içerdiği için yeni bildirim gelince tüm kartlar yeniden mount olur (odak kaybı); (c) eşzamanlı iki `commit`'te hata rollback'i diğerinin iyimser değişikliğini siler, sunucuda sıra bozulabilir | seq/AbortController; anahtar = `id ?? symbol-detected_at`; `commit`'leri kuyruğa al |
| 15 | Düşük | bkz. detay | Toplu küçük kusurlar: `AuthGate.logout` ağ hatasında yakalanmamış reddedilme + sunucuda oturum açıkken "çıkış yapıldı" görünümü; `authValue` memo'su işe yaramıyor; alt menü `<details>` rota değişince kapanmıyor; coin önerisi klavye ile seçilemiyor; ondalık nokta/virgül tutarsızlığı; `parseTrNumber("1.500")=1,5`; UserRisk eski hata mesajı kalıyor | detayda |

## Ayrıntılar

### 1. HoldingsCard: belirsiz satış sonrası oran kilidi kayboluyor (Yüksek)
`HoldingsCard.tsx` (okuma anında 110, 250, 271, 279):
```tsx
const cid = intentId(intent.current, sellIntentKey(asset, chip, chip === 100 ? 0 : qty));
...
onClick={() => { setTarget(h); setChip(100); setDone(null); setError(""); setLookup(""); }}   // Sat düğmesi
...
disabled={uncertainHere || sending}   // chip düğmeleri
```
Senaryo: %50 sat → yanıt zaman aşımı → `UncertainOrderError` → `uncertain={asset,cid}`, pencere açık, chip'ler kilitli. Kullanıcı "Vazgeç"/Esc ile kapatıp satırdaki "Sat"a tekrar basar: `setChip(100)` oranı %100 yapar, chip'ler `uncertainHere` yüzünden kilitli, pencere "oran kilitli; aynı emir kimliğiyle tekrar gönderilir" ve "Aynı emri tekrar gönder" yazar. Oysa `sellIntentKey(asset,100,0) !== sellIntentKey(asset,50,qty)` → `intentId` yeni kimlik üretir ve `quantity:null` (tümü) gönderilir. İlk %50 emri aslında borsada dolmuşsa kalan bakiyenin tamamı satılır; UI'ın verdiği "aynı emir" sözü yanlıştır. Çözüm: `uncertain` nesnesine `chip` ve `qty` ekle; "Sat" tıklanınca `uncertain.asset === h.asset` ise `setChip(uncertain.chip)`.

### 2. Charts: WS otonom pozisyonlarında `status` yok (Yüksek)
`charts/page.tsx:760-777`: WS `auto_paper_positions` şu alanlarla map'leniyor: `id, symbol, side, entry_price, current_price, quantity, take_profit, stop_loss, entry_time, notification_*` — `status` yok. Tüketiciler:
```tsx
628:  autoPaperPositions.find((p) => p.symbol === symbol && p.status === "open")   // currentAutoTrade → panel (1979)
1111: const autoPos = autoPaperPositions.find((p) => p.symbol === symbol && p.status === "open");   // SL/TP çizgileri
1250: const hasOpenAutoTrade = autoPaperPositions.some(... p.status === "open")
```
REST (`/api/auto-paper/trades?status=open`, 30 sn'de bir) `status:"open"` taşır; fakat WS portföy mesajı ~1 sn'de bir state'i `status`'suz nesnelerle değiştirir. Sonuç: açık otonom işlemin paneli/çizgileri sayfa açıldıktan ~1 sn sonra düşer (WS açıkken). Backend yalnız açık işlemleri yolladığı için (`runtime.py:301-325`) `status: "open"` eklemek doğru ve yeterli.

### 3. `useWatchPrices` kapsama boşluğu (Yüksek)
```ts
// useWatchPrices.ts
34: if (Date.now() - lastWsAt.current < SILENCE_MS) return;   // WS taze ise yoklama YOK
```
Backend `watch_prices.py`: semboller yalnızca `list_monitoring_notifications(limit=20)` + `list_daily_rising(days=7)` birleşimi (cap 50), tüm kullanıcılar için ortak. `UserHome` ise `recent + prefs.pinned + prefs.favorites` sembollerini istiyor; `UserRadar` izleme listesi ve 30 satırlık geçmiş de aynı hook'u kullanıyor. Bu kümenin dışındaki semboller WS'de hiç gelmez, WS taze olduğu için REST yedeği de çalışmaz → "CANLI —", `PctChange` "—", `notificationStatus` canlı fiyatsız. Ayrıca `prices` içinde sembol başına zaman damgası olmadığından WS'den bir kez gelmiş fiyat, sembol yayından düştüğünde bile "canlı" diye donuk kalır (ve `hit`/`gone` durumları buna göre hesaplanır). Ek olarak `.slice(0, 50)` (satır 16) 70'e varabilen listeyi sessizce keser; her WS mesajı `setPrices({...cur,...next})` ile eşitlik kontrolü olmadan yeni nesne üretir (3 sn'de bir tüm Ana Sayfa yeniden render).
Çözüm: `missing = key sembolleri − son WS mesajındaki semboller` için, WS tazeliğinden bağımsız 5 sn'lik REST yoklaması; `prices` değerlerine `at` ekle; değer değişmediyse `cur` döndür.

### 4. UncertainOrderNotice mojibake (Orta)
`UncertainOrderNotice.tsx:27`:
```tsx
{lookupBusy ? "SorgulanÄ±yorâ€¦" : "Durumu sorgula"}
```
Dosya çift-UTF-8 kodlanmış (yorumlar da bozuk). Başka hiçbir `app/**` dosyası etkilenmemiş (grep ile tarandı). Çözüm: dosyayı doğru UTF-8 ile yeniden yaz.

### 5. BuyCard: başarıdan sonra ikinci alım kapısı (Orta)
`BuyCard.tsx:133-137` başarıda `resetIntent` + `setConfirmOpen(false)` + `setResult(...)` yapıyor; `plan` kalıyor, `Onayla ve al` (`disabled={!liveEnabled || blocked || lockedByUncertain}`) açık. `openConfirm` (89-93) yeni kimlik üretir ve `setResult(null)` ile "Pozisyon açıldı" bilgisini siler. İki bilinçli dokunuşla aynı tutarda ikinci gerçek alım mümkün; plandaki fiyat/senaryo eski. (BuyDialog bu sorunu yaşamıyor: yeniden açılışta planı sıfırlıyor.) Çözüm: başarı/202 sonrası `setPlan(null)`.

### 6. BuyCard: bayat plan yanıtı (Orta)
```tsx
75: const r = await call<TradePlanResponse>("POST", "/api/binance/trade-plan", body);
76: setPlanBusy(false);
82: setPlan(r.body);
```
`invalidate()` (input `onChange`) planı siler ama uçuştaki isteği geçersiz kılmaz; yanıt gelince kutuda BTC yazarken ADA planı görünür ve `rrText/slText` da ona göre yazılır. Onay penceresi `plan.symbol`'ü açıkça yazdığı için kullanıcı fark edebilir, ama arayüz tutarsız. `BuyDialog.runPlan` zaten `seq` ref'i ile doğru çözmüş.

### 7. `COMMISSION_RE` (Orta-Düşük)
`liveSocket.ts:68`: `/"commission_pct"s*:s*([0-9.eE+-]+)/`. `\s` yazılacakken `s` kalmış. `ws_runtime.py:76` `json.dumps(..., ensure_ascii=False)` varsayılan ayraçlarla (`": "`) yayınlar. `node` ile: `{"commission_pct": 0.1}` → `null`; `{"commission_pct":0.1}` → eşleşir. Etki: hiçbir dinleyici `portfolio` istemiyorsa (ör. mobilde bant yok, yalnız Radar açık) ön-eleme dalı komisyonu hiç senkronlayamaz; net K/Z varsayılan %0,15 ile hesaplanır (HoldingsCard `/api/config` ile kısmen telafi ediyor).

### 8. `settings` hatasında "bağlı değil" (Orta)
`UserBinance.tsx:70-73`:
```tsx
const r = await call<Settings>("GET", "/api/binance/settings");
if (r.ok) setSettings(r.body);
else setSettings({ configured: false, sell_enabled: false, sell_source: "panel" });
```
5xx/ağ hatası = "anahtar yok": hesap kartları gizlenir, `BuyCard` "Ayarlar'dan anahtarını ekle" der, `ConnectionCard` "kayıtlı değil / anahtar ekle", `configured` false olduğundan 10 sn'lik yoklama durur ve hiçbir yerde yeniden deneme yok (yalnızca mount'ta + `onChanged`). `UserSettings.BinanceSection.check` (76-88) aynı kalıp: ağ hatasında "Anahtar kayıtlı değil" gösterir. Çözüm: `settingsError` durumu + "Tekrar dene"; hata durumunda configured'ı değiştirme.

### 9. UserRadar kısmi hata (Orta)
`UserRadar.tsx:262`: `setError(!sRes.ok && !hRes.ok)`. `/api/monitoring/state` 500 verip `/notifications` başarılıysa `watch` `null` kalır, `error` false → `items == null` dalı (322-325) sonsuza dek "Yükleniyor…" yazar. Tersi durumda eski veri sessizce bayat kalır. Çözüm: `watchError/historyError` ayrı tut, sekme içinde göster.

### 10. aria-live gürültüsü (Orta, erişilebilirlik)
`PortfolioBand.tsx:72-75`: `role="status" aria-live="polite"` kapsayıcı tüm bant değerlerini içeriyor; `usePortfolioSummary` WS yenilemesini 2 sn ile sınırlıyor (yorum "gürültüyü azaltmak için") ama 2 sn'de bir bütün bandın okunması hâlâ kullanılamaz. `UserBinance.Freshness` (`role="status"`, her saniye metin değişiyor: "Güncellendi 5 sn önce"). Çözüm: sürekli sayaç/değerler için canlı bölge kullanma; yalnız "veri bayatladı / hata" geçişini duyur.

### 11. Charts performansı (Orta)
`charts/page.tsx:688` `useLiveMessages(useCallback(...), deps)` — ikinci argüman (tip listesi) yok → `liveSocket.recomputeWanted` `wantsAllTypes=true` yapar, `rawWantsAnyType` ön-elemesi devre dışı kalır ve her `binance_price` (309 sembol) JSON.parse edilir. Ek olarak `portfolio` mesajında (≈1 Hz) `setLivePortfolio`, `setPositions`, `setAutoPaperPositions` hepsi yeni referansla çağrılıyor → 2248 satırlık `ChartsPage` her saniye yeniden render. (`CandleCountdown`/`CountdownSec` izolasyonu yapılmış ama asıl kaynak bu.) Çözüm: `["kline","portfolio","trade_updated","signal","reset","llm_position_management","portfolio_reconciled"]`; pozisyon tablosunu ayrı memo bileşene taşı. `BinancePositionChartModal.tsx:942` (HoldingsCard'dan kullanılıyor) için de abonelik tiplerini doğrula (okumada ikinci argüman görmedim). Ayrıca kline işleyicisinde (`718`) her mesajda `applyOptions({priceFormat})`; `742` aynı mum için `prev` döndürdüğünden `bars` state'i (indikatörlerin girdisi) canlı mumu HTTP turuna (WS açıkken 60 sn) kadar bayat tutar.

### 12. Radar ses efekti (Düşük-Orta)
`RadarAlertModal.tsx:33`: `oscillator.addEventListener("ended", () => context.close());` döngü içinde, her nota için. İlk nota `now+0.14+0.02`'de bitince context kapanır; 2. nota (0,14 sn) ve 3. nota (0,28 sn) çalmaz. `close()` kapalı context'te reddedilen Promise döner, `try/catch` async hatayı yakalamaz (2 adet unhandled rejection). Çözüm: yalnız son osilatörde kapat ve `.catch(() => {})`.

### 13. Modal yığını (Düşük-Orta)
`useModalA11y` ve `RadarAlertModal` ayrı ayrı `document` capture dinleyicisi ekliyor; `event.stopPropagation()` aynı düğümdeki diğer dinleyicileri durdurmaz (`stopImmediatePropagation` gerekir). BuyDialog/ConfirmDialog açıkken radar uyarısı gelirse: Esc ikisini birden kapatır; Tab'da iki tuzak birbirinin odağını çalar. `ConfirmDialog` arka plan tıklamasını `busy` iken engelliyor ama Esc'i engellemiyor (gönderim sürerken pencere kapanır; sonuç yine işlenir, ama "Gönderiliyor…" ekranı kaybolur). `FOCUSABLE_SELECTOR` içinde `display:none` öğeler elenmiyor (yorum "görünür olanlar" diyor) ve `button:not([disabled])` iki kez yazılı.

### 14. Bayat yanıt, indeks anahtarı, rollback yarışı (Orta-Düşük)
- `HistoryCard.tsx:19-30`: `load` gün değişince yeniden oluşuyor ama istek sırası yok; `data` temizlenmediği için yükleme sırasında önceki günün satırları/PnL'i yeni tarih başlığı altında görünür.
- `UserNotifications.tsx:63-75`: aynı kalıp (filtre değişimi), ayrıca `hit` filtresi yalnızca son 200 satırdan istemci tarafında süzülüyor (daha eski başarılı bildirimler listelenmez).
- Anahtarlar: `RecentNotifications.tsx:53` `` `${id ?? symbol}-${detected_at}-${i}` ``, `UserNotifications.tsx:102,132` — `i` yüzünden 15 sn'lik yoklamada başa yeni kayıt eklenince tüm kartlar yeniden mount olur (odaktaki düğme düşer, DOM yeniden kurulur).
- `useWatchPrefs.commit` (105-126): `prev` commit başına yakalanıyor; iki hızlı değişiklikte ilkinin hatası ikincisini de siler; PUT'lar sırasız varırsa sunucuda son yazan kazanır. İlk `GET ui-prefs` yanıtı (83-95) kullanıcının iyimser değişikliğini ezebilir ve `r.ok` kontrolü yok.

### 15. Düşük öncelikli küçük kusurlar
- `AuthGate.tsx:64-78` `logout`: `try { await apiRequest(logout) } finally { ... }` catch yok → ağ hatasında yakalanmamış Promise reddi (`void logout?.()`), `finally` içindeki `refresh` de düşerse yerel olarak "çıkış" gösterilir ama HttpOnly çerez geçerli kalır. `authValue` (80) `logout` her render yeniden oluştuğu için `useMemo` boşa; `useCallback` gerekir. `login` (56) `body.detail` dizi gelirse `[object Object]` mesajı.
- `UserBottomNav.tsx:34-45`: "Diğer" `<details>` bir bağlantıya tıklanınca/rota değişince kapanmıyor, dışa tıklayınca da kapanmıyor.
- `BuyCard.tsx:200` `onBlur={() => setTimeout(() => setShowSuggest(false), 150)}`: Tab ile öneri düğmesine geçince 150 ms sonra liste unmount olur, odak kaybolur → klavye kullanıcısı öneri seçemez; `role="option"` içinde düğme, `aria-selected` hep false, ok tuşu yok.
- Ondalık ayracı tutarsızlığı: `UserRadar.tsx:150,154,188` (`toFixed` → nokta), `UserNotifications.tsx:110,136` (`%${r.target_pct}` ham), `UserSignalReport.tsx` (`%{r.target_pct ?? "—"}` → "%—", `{r.horizon_minutes ?? "—"} dk` → "— dk"); oysa `PctChange`/`NotificationCard` virgül kullanıyor.
- `tradeUi.parseTrNumber("1.500")` → `1.5` (virgül yoksa nokta ondalık sayılır); TL tutarı alanında "1.500" yazan kullanıcı ₺1,50 alır (güvenli yönde ama şaşırtıcı).
- `UserRisk.tsx:23-25,148`: ilk yükleme hatasındaki `message` "Tekrar dene" başarılı olsa da `ready` görünümünde kırmızı uyarı olarak kalır.
- `tradeApi.call` (`lib/tradeApi.ts`) zaman aşımsız: `trade-plan`, `protect`, `order-status` asılı kalırsa `planBusy`/`protectBusy`/`lookupBusy` sonsuz sürer (yalnız emir POST'ları `postJsonGuarded` ile 45 sn'lik sınıra sahip).
- `useAdminView`: admin "simple" görünümünde ilk render `advanced` → `AdminHome` bir an mount olup admin isteklerini başlatır, sonra `UserHome`'a geçer.
- `charts/page.tsx:273-274`: `localStorage.setItem` try/catch'siz (gizli mod/kota → efekt hatası). Display kaydı için 600 ms'lik zamanlayıcı unmount'ta iptal ediliyor (yorum "flush" diyor) → son değişiklik kaybolabilir.

## Doğru çalıştığı doğrulananlar

- `liveSocket.ts`: tekil soket, aboneler dolunca bağlanma/boşalınca kapatma, üstel geri çekilme + jitter, yarı-açık bağlantı için 45 sn sessizlik gözetimi, `onclose`/`socket !== instance` korumaları, tip filtreli ön-eleme; 4401'de yeniden bağlanmama (giriş ekranı çocukları unmount ettiği için tekrar girişte yeniden abone olunur — takılı kalma yok).
- `useLiveMessages`: dinleyici ref'te, `typesKey` ile kararlı abonelik (inline fonksiyon aboneliği koparmıyor).
- `useVisibleInterval`: gizliyken durur, görünür olunca hemen çalışır, temizlik doğru, `cbRef` ile bayat closure yok.
- `usePortfolioSummary`: REST `seq` koruması, `mountedRef`, debounce zamanlayıcısı unmount'ta temizleniyor, `null` ≠ 0 sözleşmesi, REST tabanından yeniden hesap (birikimli hata yok), hata durumunda eski veri + `stale` bayrağı. (Küçük not: 2 sn'lik kısma `lastWsRenderRef` son tiki "trailing" olarak göstermez; bir sonraki tik/REST'e kadar bekler.)
- `UserBinance`: pozisyon/emir için ayrı `seq/applied` yarış koruması, tick'lerin `heldRef` ile süzülmesi, `livePrices` REST sonrası sıfırlanması, hatada "eski veri" uyarıları, `toast` zamanlayıcı temizliği.
- Emir güvenliği: `sendLock` ref'i + `sending` state, niyet-anahtarlı `client_order_id`, 202/5xx/408/504 için "belirsiz" akışı (aynı kimlik), tanımlı reddetmede kimlik sıfırlama (`orderIntent.isDefinitiveReject`), `floorQty` aşağı kesme, minimum notional kontrolü, `UncertainOrderError` ile zaman aşımı; BuyDialog planı `seq` ile ve `dirty` kapısıyla koruyor, yeniden açılışta planı sıfırlıyor. Pozisyon kapatma modalı (`BinancePositionChartModal`) de idempotent kimlik kullanıyor ve kullanıcı arayüzünde `confirmBeforeSend` ile sürükle-bırak otomatik gönderimini kapatıyor.
- `api.ts`: tüm GET'ler `no-store`, çerez tabanlı oturum (localStorage'da token yok), 401'de `scalper:auth-expired` (login POST hariç; backend 401'i yalnız kimlik doğrulamada üretiyor), `getJSON` hata gövdesini taşıyor. `fetchAllPages` döngüsü ilerleme garantili.
- `pnl.ts` / `tradeUi.ts` / `userUi.ts`: `null` sözleşmesi, net K/Z formülü (iki bacak komisyon), `fmtSignedTry`/`fmtPct` tr-TR, yüzde matematiği (`pctChange`, `slPctFromPrice`, `rrFromPrices`) birim testli.
- `useModalA11y` temel işlevi: açılışta odak, Tab tuzağı, kapanışta odak iadesi; `ConfirmDialog` ilk odağı güvenli öğeye (Vazgeç/oran düğmeleri) veriyor.
- `PortfolioBand` yalnızca masaüstünde mount (mobilde istek/WS yok); `RegimeBanner` kaldırılması temiz (kalan referans yok).
- `AssistantFab`/`ChartAssistantDrawer`: `AbortController` ile durdurma, SSE ayrıştırıcıda `NaN→null` temizliği, `done/error` terminal olay kontrolü.
- Tüm `setInterval`/`setTimeout` kullanımlarında (kullanıcı arayüzü) temizlik var (tek istisna BuyCard `onBlur` zamanlayıcısı; React 18'de zararsız).

## Derleme hijyeni

- **ESLint**: `package.json` devDependencies `eslint ^9.39.0` ve `eslint-config-next 16.3.0` tanımlı; `package-lock.json` bunları içeriyor (`eslint 9.39.5`). `npm ls` her ikisini `UNMET DEPENDENCY` gösteriyor — yani eksik olan paket tanımı değil, yerel `node_modules` kurulumu. Çözüm: `cd frontend && npm ci`. `eslint.config.mjs` ~400 ihlali `warn`'a indirmiş (`no-explicit-any`, `react-hooks/refs` vb.); kurulumdan sonra `react-hooks/refs` uyarıları özellikle `BuyDialog.tsx:65` (`latest.current = …` render sırasında) ve benzerlerinde çıkacak.
- **React sürümü**: kurulu `react 18.3.1` / `@types/react ^18` (görevde "React 19 dönemi" denmişti; kod React 18 ile uyumlu).
- **`any`**: `app/**` içinde (test hariç) ~199 kullanım; kritik yollarda: `UserHome.tsx:19` (`getJSON<any>`), `charts/page.tsx:688` (WS mesajı `any`), `charts/page.tsx:135-151` (`forecast`, `positions`, `binanceHoldings`), `ChartAssistantDrawer.tsx:137`, `RadarAlertModal.tsx:12,144`, `BinancePositionChartModal` (`err: any`). Emir yolu (`orderSafety`, `BuyCard`, `HoldingsCard`, `tradeApi`) `any`'siz.
- **console**: `console.log` yok; `console.debug` `BinancePositionChartModal.tsx:912,1004`; `console.warn/error` `charts/page.tsx` (kline) — kasıtlı.
- **Ölü kod**: `components/user/KpiStrip.tsx` (hiçbir yerden import edilmiyor; `UserHome` yorumu "duruyor" diyor), `settings/SystemHealthTab.tsx` (import eden yok). `RegimeBanner` temizlenmiş.

## Komut çıktıları

- `npm run typecheck` (`next typegen && tsc --noEmit --incremental false`): **exit 0**, hata yok ("Types generated successfully").
- `npx vitest run`: **15 test dosyası, 277 test — hepsi geçti** (exit 0, ~2,7 sn). Dosyalar: userUi (36), pnl (27), format (19), entryLevels (7), signalReport (14), useWatchPrefs (6), orderSafety (32), userPalette (8), buyDialogMath (11), orderIntent (13), tradeUi (41), usePortfolioSummary (13), chartShared (4), serviceWorker (4), signals (42). Not: koşu sonrası diğer ajan `lib/binanceSeed.test.ts` ekledi; bu dosya koşuya dahil değil.
- `npx eslint`: çalıştırılamadı (`node_modules/eslint` yok, yukarıya bak).
