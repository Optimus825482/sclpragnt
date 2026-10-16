# Kullanıcı Binance TR işlem deneyimi + Risk Merkezi — Tasarım

Tarih: 2026-10-16 · Durum: kullanıcı incelemesi bekliyor (yön ve kararlar sohbette alındı)

## 1. Amaç ve başarı ölçütü
Basit arayüzdeki kullanıcı, kendi Binance TR API anahtarını Ayarlar'a girince **gecikmesiz ve güvenli** biçimde al/sat yapabilir;
bakiyesini ve işlem geçmişini görür. Alım öncesi sistem sembole özel bir **risk/ödül (RR) planı** önerir, iyi/kötü senaryoyu
TL olarak gösterir; kullanıcı onaylarsa pozisyon açılır ve **OCO (SL+TP)** emri otomatik Binance TR'ye gönderilir.
Başarı: (a) çift emir, tutar hatası ve veri sızıntısı yok; (b) onaydan emre gecikme ölçülebilir ve düşük;
(c) kullanıcı jargon olmadan 3 dokunuşta işlem yapar.

## 2. Alınan kararlar (kullanıcı)
- **Risk Merkezi** ayrı bir sayfa: açılacak pozisyonlar için **serbest bakiyeden en fazla kullanılacak % (tek emir)** ve **standart RR** seçimi.
- Sembol seçilince sembolün **snapshot verisi LLM ile paylaşılır**; LLM günlük yükseliş/trend durumunu da dikkate alıp **sembole özel RR** önerir.
  Alım kartında önerilen RR, **kötü senaryo** (SL) ve **iyi senaryo** (TP) sonucu TL olarak gösterilir. Kullanıcı onaylarsa pozisyon açılır,
  ardından **OCO (SL+TP)** Binance TR'ye gönderilir. Kullanıcı isterse **manuel RR** girer; sistem yine dinamik öneri sunar.
- Basit sayfada emir türleri: **Piyasa + Limit + SL/TP**.
- Canlı işlem açma: **yazı yazdırmadan**, onay penceresinde **düğmeyle**.
- Teslimat: **3 ayrı PR, sırayla**.

## 3. Güvenlik ilkeleri (gerçek para)
1. LLM **yalnız öneri** üretir (SL %, RR, gerekçe). Emir vermez. Çıktısı **doğrulanır ve kenetlenir** (şema, SL %0,5–10, RR 1–5);
   geçersiz/zaman aşımı/LLM yok → **kural tabanlı yedek** (ATR'ye dayalı) kullanılır ve kullanıcıya "otomatik hesap" diye belirtilir.
2. Her gerçek emir **kullanıcı onayı** ister (önizleme özeti + "Onayla" düğmesi). Onay istemcide üretilen **`client_order_id`** ile gelir.
3. **Çift emir koruması:** aynı `client_order_id` ikinci kez emir üretmez; belirsiz sonuç (zaman aşımı/5xx) **202 UNKNOWN** döner,
   arayüz önce `order-status` ile sorgular, körlemesine yeniden denemez.
4. **Tutar sınırı:** tek emir ≤ `serbest TRY bakiyesi × max_position_pct` (Risk Merkezi). Aşım sunucuda reddedilir (UI'a güvenilmez).
5. **Veri izolasyonu:** tüm önbellekler API anahtarına/kullanıcıya özel (PR #10'daki sızıntı düzeltmesi bu işin ön koşuludur).
6. API anahtarı **kayıtta borsada doğrulanır** (`account/spot`); gizli anahtar geri gösterilmez; **silme** uç noktası eklenir.
7. Canlı işlem varsayılan **kapalı**; anahtar doğrulanınca kullanıcı onay penceresindeki düğmeyle açar. Kapatmak tek dokunuştur.
8. Gerçek emir testleri yok: tüm testler sahte borsa katmanıyla; uçtan uca deneme yerel **sahte Binance TR sunucusuna** karşı yapılır.

## 4. PR 1 — Arka uç: güvenli emir, risk ve plan
**Veri:** migration `017_user_risk_settings.sql`: `user_risk_settings(user_id PK → users, max_position_pct DOUBLE DEFAULT 20, default_rr DOUBLE DEFAULT 2.0, updated_at)`.
Doğrulama: `max_position_pct` 1–100, `default_rr` 1–5.

**Uç noktalar (hepsi oturumlu kullanıcı, kendi verisi):**
| Uç nokta | Amaç |
|---|---|
| `GET/PUT /api/binance/risk` | Risk Merkezi ayarları |
| `POST /api/binance/trade-plan` | `{symbol, amount_try?, amount_pct?, rr_mode:"auto"\|"manual", rr?, sl_pct?}` → fiyat, tahmini miktar, komisyon, SL/TP fiyatı, RR, **kötü/iyi senaryo TL**, sınır/filtre uyarıları, öneri kaynağı (`llm`\|`kural`) ve kısa gerekçe. Emir göndermez. |
| `POST /api/binance/open-position` | `{plan, client_order_id}` → (1) tutar sınırı + filtre + taze bakiye doğrulaması, (2) piyasa alım (`quoteOrderQty`), (3) `order detail` ile **gerçekleşen miktar**, (4) OCO satış (SL+TP). Yanıt: `{bought, protection: "placed"\|"failed", ...}`; OCO başarısızsa **korumasız uyarısı** + `POST /api/binance/protect` ile yeniden deneme. |
| `POST /api/binance/order` (mevcut) | Limit/SL/TP gibi diğer emirler; arayüz artık bunu kullanır. |
| `GET /api/binance/order-status` (mevcut) | Belirsiz sonuç sorgusu. |
| `GET /api/binance/symbol-info?symbol=` | En az tutar, adım, fiyat adımı (istemci doğrulaması ve önizleme). |
| `DELETE /api/binance/keys` | Anahtar silme (+ kullanıcı akışını durdurma). |
| `POST /api/binance/user-stream/start` | Dolum akışını sayfa açılınca başlatır (Pozisyonlar'a bağımlılığı kaldırır). |

**Plan hesabı (saf, testli):** `plan = f(price, atr_pct, rr, sl_pct, fee_rate, qty, filters)`:
SL = giriş × (1 − sl_pct); TP = giriş × (1 + sl_pct × rr); kötü senaryo = −(giriş−SL)×qty − komisyonlar; iyi senaryo = +(TP−giriş)×qty − komisyonlar;
miktar LOT_SIZE adımına, fiyatlar tick'e yuvarlanır. Komisyon `account/spot`'taki oranlardan.

**LLM önerisi:** Girdi: mevcut `calculate_snapshot` çıktısı (fiyat, ATR %, RSI, çok zaman dilimli trend uyumu, 24s değişim, hacim). Çıktı (JSON): `{sl_pct, rr, kisa_gerekce}`.
Aktif LLM sağlayıcısı kullanılır; 6 sn zaman aşımı; sembol başına 60 sn önbellek. **Yedek kural:** `sl_pct = clamp(1.5 × ATR%_15dk, 0.8, 6)`, `rr = default_rr`.

**Hız:** emir yoluna ayrı (öncelikli) eşzamanlılık yuvası; sembol filtreleri açılışta ısıtılır; emirde taze bakiye; alım web push'u yanıttan ayrılır;
sunucu bağlantı yeniden kullanımı ölçülüp (TLS el sıkışma maliyeti) uygulanır; hedef: onaydan borsaya gönderime kadar **sunucu tarafı < 300 ms** (borsa gecikmesi hariç), ölçüm log'lanır.

## 5. PR 2 — Basit arayüz: "Binance TR" ve "Risk Merkezi"
Menü: `binance` ("Binance TR") ve `risk` ("Risk Merkezi") eklenir (frontend `MENU_ITEMS`, backend `MENU_IDS`).
**Binance TR sayfası (mobil öncelikli, canlı renk paleti):**
1. Üstte **bakiye kartı** (toplam değer, serbest TL, günlük kâr/zarar) + "canlı işlem: açık/kapalı" durumu.
2. **Al / Sat** kartı: sembol arama → seçilince fiyat ve **plan kartı** (önerilen RR, kötü/iyi senaryo TL, komisyon, kaynak: yapay zekâ/otomatik) →
   tutar (TL veya % çipleri, Risk Merkezi sınırı gösterilir) → "Planı değiştir" (manuel RR/SL) → **Onayla** → ilerleme (alım → koruma emri) → sonuç.
   Satış: eldeki coin seç, % çipleri, onay özeti.
3. **Açık emirler:** tek dokunuşla iptal. 4. **Geçmiş:** gün filtreli işlem listesi + kâr/zarar. 5. **Bağlantı:** API anahtarı kaydet/doğrula/sil, canlı işlem düğmesi.
**Risk Merkezi sayfası:** "Bir pozisyonda serbest bakiyemin en fazla %…'sini kullan" (kaydırıcı+sayı), "Standart RR" (1:1,5 / 1:2 / 1:3 + özel), kısa açıklamalar.
Sayılar `tr-TR`, jargon yok (OCO yerine "otomatik zarar durdur ve kâr al").

## 6. PR 3 — Mevcut yönetici Binance TR sayfası
Yeni güvenli uçlara geçiş (idempotent alım/satım, plan/önizleme), 2.542 satırlık bileşeni parçalara bölme, render optimizasyonu
(fiyat akışında yalnız etkilenen satır), bayat USD yedeğinin (sabit 38) kaldırılması, tutarlı sayı biçimi, sessiz yutulan hataların görünür kılınması,
"gerçek satış" etiketinin gerçek anlamına (alış/satış/SL-TP) düzeltilmesi.

## 7. Kapsam dışı / riskler
- Bu belge **yatırım tavsiyesi sunmaz**; arayüzde "öneri, garanti değildir" notu bulunur.
- Binance TR **test emri uç noktası sunmuyor**; doğrulama bizim katmanımızdadır. Gizli uç noktalar (`/api/v3/*` kamu verisi, global yedek adresler) ayrı bir sertleştirme işi olarak not edilir.
- OCO tek başarısızlıkta kullanıcı korumasız kalabilir: bu yüzden açık uyarı + tek dokunuş yeniden deneme + (ileride) otomatik yeniden deneme.
- LLM sağlayıcısı yoksa tüm akış kural tabanlı çalışır.

## 8. Test ve doğrulama
- Birim: plan hesabı (SL/TP/komisyon/yuvarlama), LLM çıktı doğrulama/kenetleme, risk sınırı, `client_order_id` tekrarı, belirsiz sonuç (202), kullanıcı izolasyonu.
- Entegrasyon: sahte Binance TR sunucusu (yerel) ile alım→dolum→OCO akışı, OCO başarısızlığı, kısmi dolum.
- Arayüz: vitest (saf yardımcılar), tarayıcıda gözle kontrol (mobil/masaüstü), sahte sunucuya karşı. **Gerçek emir gönderilmez.**
- Gecikme: onaydan gönderime süre log'lanır ve test eşiği vardır.

## 9. Teslimat sırası
PR #10 (sızıntı) → **PR 1** (arka uç) → **PR 2** (basit sayfa + Risk Merkezi) → **PR 3** (yönetici sayfası).
