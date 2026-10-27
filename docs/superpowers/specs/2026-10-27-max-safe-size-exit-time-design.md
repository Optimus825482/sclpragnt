# Maksimum güvenli alım tutarı + tahmini süre / çıkış zamanı — tasarım

Tarih: 2026-10-27 · Durum: kullanıcı onayı bekliyor

## 1. Niyet ve neden

Kullanıcı sistemin yükseliş bildirimine (radar, yükseliş, MA BUY) göre Binance TR'de alım yapıyor. Alım tutarını
şu an rastgele seçiyor. Asıl amacı: **mümkün olan en kısa sürede en az %3 NET kârla işlemden çıkmak.**

Tetikleyen olay: 175.000 TL'lik DODO alımından sonra fiyat %11 düştü, 6 saat sonra toparlandı. İnceleme gösterdi ki
alımın fiyata etkisi ~%0,3'tü (24s hacim 73M TRY); düşüş alımdan değil piyasadan geldi. Yine de kullanıcı her
bildirimde şunu bilmek istiyor:

1. Bu sembolde %3 net kârla çıkabilmek için **en fazla ne kadar** alabilirim (alımım fiyatı itmesin, çıkışta
   defter beni taşıyabilsin)?
2. +%3'e **tahminen ne kadar sürede** ulaşır?
3. **Çıkış zamanı** ne (saat olarak)?
4. Süre dolarsa ne yapmalıyım?

Ek kullanıcı kararları (birebir):
- Push bildirimi ile uygulama içi bildirim **aynı içerikte** olmalı; uygulama içi bildirim ve aksiyonlar push'taki
  değerlere göre hareket etmeli.
- **Otonom (paper) işlemler** de aynı değerlere göre ayarlanmalı.
- Gerçek parayla yapılan alımda çıkış zamanı gelip hedef tutmadıysa sistem **otomatik satış YAPMAZ**, yalnızca
  "çıkış zamanı geldi" push'u gönderir.
- "Süre dolarsa ne yapılsın" kuralı: kullanıcı "en mantıklı olan neyse" dedi → aşağıdaki kural benim (Claude) kararım.

## 2. Hedefler / hedef olmayanlar / anti-hedefler

**Hedefler**
- Tek bir hesaplanmış "işlem planı" (trade plan) her bildirime eklenir ve TÜM yüzeyler aynı planı kullanır: push
  metni, uygulama içi radar modalı, bildirim listesi kartı, "Alım yap" diyaloğu, otonom paper.
- Plan, canlı emir defteri + 24s hacim + geçmiş sinyal istatistiklerinden hesaplanır.

**Hedef olmayanlar**
- Gerçek hesapta otomatik çıkış/satış (kullanıcı reddetti).
- Sinyal üretme mantığının (radar skor, MA kesişimi vb.) değiştirilmesi.
- Binance Global defterini sizing'e katmak (yalnız TR'de işlem yapılıyor; Global bilgi amaçlı kaldı).

**Anti-hedefler (çalışsa bile başarısızlık sayılır)**
- Push ile uygulama içi ekranın farklı rakam göstermesi.
- Plan hesaplaması yüzünden bildirimin gecikmesi/düşmesi (plan hesaplanamazsa bildirim yine gider, plan alanları
  "hesaplanamadı" olarak işaretlenir).
- Yeterli geçmiş verisi olmayan kaynakta uydurma süre göstermek (az örnekte "veri yetersiz" yazılır).
- Gerçek hesapta kullanıcı onayı olmadan emir.

## 3. Hesaplama (benim kararlarım; eşikler ayarlanabilir config olmalı)

### 3.1 Net %3 hedef → brüt hedef fiyat
- `fee_rate`: sistemin mevcut gerçek komisyon oranı (trade_plan/open_position'daki `fee_rate` kaynağı).
- Brüt hedef % = net hedef (3,0) + giriş kayması + çıkış kayması + 2 × komisyon.
- Sinyalin kendi `target_pct`'si brüt hedeften büyükse sinyalinki kullanılır.
- Kayma değerleri, aşağıda bulunan maksimum tutar için hesaplanan gerçek kaymalardır.

### 3.2 Maksimum güvenli tutar (TRY) = aşağıdakilerin EN KÜÇÜĞÜ
1. **Giriş:** Binance TR ask kademeleri (REST `depth`, limit 100) boyunca süpürmede ortalama kayma ≤ %0,2.
2. **Çıkış:** Brüt hedef fiyatın −%1 altına kadar değil; **mevcut** best bid'den −%1 içindeki bid toplamı × 0,4
   (düşüşte piyasa yapıcı emir çeker varsayımı).
3. **Hacim:** 24s TRY hacminin %2'si.
- Sonuç kullanıcıya yuvarlanmış gösterilir (ör. 1.000 TL'ye).
- Bu tutarda brüt hedef > %8 çıkıyorsa veya tutar `MIN_PARTIAL_ORDER_TRY` altındaysa plan
  "%3 net bu defterde gerçekçi değil" uyarısı taşır.

### 3.3 Tahmini süre ve çıkış zamanı (geçmiş veriden)
- Kova (bucket): kaynak + zaman dilimi (radar / yükseliş-türü / MA BUY-TF).
- Geçmişteki her bildirim için 1m mumlar tekrar oynatılarak **brüt +%3,6'ya (sabit, istatistik amaçlı) ilk
  ulaşma dakikası** ve o ana kadarki en büyük düşüş (MAE) hesaplanır. Pencere: 24 saat.
- Kova istatistikleri: isabet oranı, süre P50 / P75, kazanan sinyallerde hedeften önceki MAE'nin P80'i, örnek sayısı.
- **Tahmini süre** = P50. **Çıkış zamanı** = bildirim zamanı + P75.
- **Stop** = giriş × (1 − kazananların MAE P80'i), en az %2, en çok %10 (bkz. §6.1).
- Kovada < 30 örnek varsa süre/stop yerine "veri yetersiz" + sistem varsayılanları (otonom için mevcut ayarlar).
- İstatistikler periyodik (ör. günde bir) yeniden hesaplanıp tabloya yazılır; bildirim anında yalnız okunur.

### 3.4 "Süre dolarsa" kuralı
Çıkış zamanında hedef tutmadıysa:
- Net PnL ≥ 0 → **"çık"** (kârda/başabaşta sat).
- Net PnL < 0 → **"stop seviyesine kadar bekle"**; stop zaten emir olarak yerinde.
- Çıkış zamanı + (P75 kadar ek süre) sonunda hâlâ açıksa → **"çık"**.

## 4. Yüzeyler

### 4.1 Push + uygulama içi bildirim (aynı içerik)
- Üç bildirim kurucusu (`monitoring._build_notification`, `monitoring._build_rising_notification`,
  `ma_buy_notify.build_notification` / `_build_profile_notification`) zarfa ortak bir `trade_plan` nesnesi ekler:
  `max_amount_try`, `entry_ref_price`, `target_price`, `target_gross_pct`, `target_net_pct` (3),
  `stop_price`, `stop_pct`, `eta_minutes` (P50), `exit_at` (epoch), `hit_rate`, `sample_n`, `warnings`.
- Mesaj metni plandan üretilir (tek fonksiyon), ör.:
  `KITETRY | Maks: 40.000 TL | Hedef 6,22 (+%3 net) | ~35 dk (geçmişte %62) | Çıkış 20:45'e kadar | Stop 5,82`
- Radar modalı (`frontend/app/components/RadarAlertModal.tsx`) ve `NotificationCard.tsx` bu alanları gösterir;
  push'taki metin ile aynı rakamlar.

### 4.2 "Alım yap" diyaloğu (push aksiyonu + uygulama içi)
- `BuyDialog` bildirimin `trade_plan`'ı ile açılır: tutar = min(maks güvenli tutar, boş TRY), stop ve hedef dolu,
  OCO işaretli. Kullanıcı değiştirebilir.
- Push aksiyonu URL'si (`/?buy=SYM&buy_price=...`) bildirim kimliğini de taşır; `QuickBuyFromUrl` planı
  bildirim kimliğinden çeker.
- Gerçek alımda stop/hedef mevcut OCO akışıyla (`open_position.place_order`, `sl_pct` + `rr`) kurulur:
  `sl_pct` = plan stop %, `rr` = brüt hedef % / stop %.

### 4.3 Gerçek pozisyon için "çıkış zamanı geldi" push'u
- Bildirimden açılan gerçek alımın `order_requests` kaydına `notification_key` ve `exit_at` yazılır.
- Zamanlayıcı `exit_at`'te pozisyon hâlâ açıksa (OCO tetiklenmemişse) §3.4 kuralına göre push gönderir:
  "KITETRY çıkış zamanı geldi: şu an +%1,2 net → çık" gibi. Emir GÖNDERMEZ.
- Ek-süre sonunda ikinci ve son push.

### 4.4 Otonom paper
- `order_value` = min(mevcut bakiye-yüzdesi tutarı, `max_amount_try`).
- Hedef = plan brüt hedef; bu işlemler için **hedefte satış açık** (genel `AUTO_PAPER_TP_PRIMARY_ENABLED`
  ayarından bağımsız).
- Stop = plan stop; `max_hold_minutes` = çıkış zamanına kalan + ek süre; §3.4 kuralı süre dolduğunda otomatik
  uygulanır (paper'da otomatik çıkış serbest).
- Plan "veri yetersiz" ise mevcut otonom ayarları aynen kullanılır.

## 5. Kısıtlar
- Binance TR REST ağırlık/limit koruması (`binance_tr_public` throttle) kullanılmalı; depth çağrısı bildirim
  başına bir kez.
- Push gecikmemeli: plan hesaplaması zaman aşımlı (ör. 2 sn), aşılırsa plan'sız gönderilir.
- Kullanıcı commit/deploy'u kendisi yapar; değişiklikler commit'lenmeden bırakılır.

## 6. Okuyucu kontrolünden sonra verilen kararlar (Claude'un kararları, kullanıcı itiraz edebilir)

1. **Gerçek alımda OCO:** Plan kaynaklı emirler `place_order`'a stop % ve hedef % değerlerini AYRI ayrı geçirir
   (`rr` türetilmez). `RR` 1–5 sınırı bu emirlere uygulanmaz. Stop üst sınırı %15 değil **%10** olur
   (`trade_plan.SL_PCT` sınırıyla aynı); §3.3'teki "en çok %15" buna göre %10 okunur.
2. **Yüzdeler gerçek dolum fiyatına uygulanır.** Net %3 dolum fiyatına göre ölçülür. Push'taki hedef/stop fiyatları
   `entry_ref_price` üzerinden gösterilen referanstır; diyalog ve OCO aynı YÜZDELERİ dolum fiyatına uygular.
3. **Geçmiş popülasyon:** Yalnız gerçekten push'u gitmiş sinyaller (radar: `monitoring_notifications`; yükseliş:
   `rising_alerts`, kova alanı `kind` + `tf`; MA BUY: `ma_buy_signals` `push_ok=true`, kova `timeframe`).
   Geriye bakış **60 gün**. 1m mumlar Binance TR REST `klines` ile mevcut throttle altında, artımlı (yalnız yeni
   bildirimler) çekilir; ilk doldurma arka planda yavaş yürür.
4. **Gerçek pozisyon "hâlâ açık" mı:** OCO emir listesinin durumu REST ile sorgulanır (OCO tetiklenmediyse açık).
   Coin bakiyesi alınan miktarın %50'sinin altına düştüyse kullanıcı elle satmış sayılır → push gönderilmez.
   Gerçek alımda `exit_at` = **dolum zamanı** + P75 (bildirim zamanı değil). Net PnL dolum fiyatına göre
   (`order_requests.result.avg_price`).
5. **Plan bildirim anında dondurulur** ve bildirim kaydıyla saklanır; push, modal, liste ve diyalog aynı rakamı
   gösterir. Diyalog açıldığında canlı fiyat `entry_ref_price`'tan %1'den fazla saptıysa uyarı bandı gösterir
   (rakamlar değişmez).
6. **Paper:** Plan işlemlerinde mevcut güvenlik çıkışları (rejim, LLM ikinci göz, bayat fiyat) AYNEN kalır.
   ATR stop genişletmesi plan işlemlerinde kapalıdır (profil işlemleriyle aynı). `order_value` = mevcut
   çarpanlar (ör. `regime_mult`) uygulandıktan sonraki tutar ile `max_amount_try`'nin küçüğü.
7. **İstatistikler planın gerçek brüt hedefi için** hesaplanır (sabit %3,6 değil): kova başına birkaç eşik
   (ör. 3,6 / 5 / 8 / 10) saklanır, plan en yakın üst eşiği kullanır.

8. **(Kullanıcı kararı, 2026-10-27)** Sinyalin kendi hedefi brüt hedeften (net %3) yüksekse (ör. MA BUY H4 %10)
   **sinyalin hedefi ve profilin çıkış kuralları kalır**: profil stop'u, iz süren stop ve tutma süresi plan
   stop'u/çıkış zamanının yerine geçer; net %3 yalnız ALT SINIRdır. Bu sinyallerde tahmini süre/çıkış zamanı yine
   §6.7'deki eşik istatistiğinden (sinyal hedefine en yakın üst eşik) gösterilir; maksimum güvenli tutar
   hesaplaması aynen uygulanır. Profil hedefi 3,6'nın altında olan sinyaller (ör. MA BUY 1m/5m) brüt hedefe yükseltilir.

## 7. İnşa edene bırakılanlar
- Tablo/migration adları ve şeması, istatistik işinin zamanlanması, mesajın tam biçimi ve emoji'ler,
  frontend yerleşimi, config anahtar adları, testlerin yapısı.
