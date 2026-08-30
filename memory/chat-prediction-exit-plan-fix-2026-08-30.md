---
name: chat-prediction-exit-plan-fix-2026-08-30
description: Canlı sunucuda eski bug'lı kod çalışıyordu; exit planı bağlanması +
  arayüz açık pozisyon listesi düzeltmeleri, doğrulama sonuçları
metadata:
  node_type: memory
  type: project
  originSessionId: sess_972ecfe3-4776-4d00-89d2-06fd556c8b00
---

2026-08-30: Kullanıcı canlı sunucudan gelen CHAT_PREDICTION loglarını paylaştı
(ZKTRY/MOVRTRY/NILTRY saniyeler içinde system_stop_loss). Teşhis: sunucu 29 Ağu
d8ba8e9 öncesi bug'lı kodu çalıştırıyordu (stop, fiyat BE eşiğine ulaşmadan
girişin üstüne çekiliyordu). Çözüm: sunucuda git pull + backend restart.
Lokal DB aynı imzayı gösteriyordu (paylaşılan Postgres: DATABASE_URL).

Aynı gün ek düzeltmeler ([[scalper-v4-fixes-2026-08-25]] devamı):

1. **Exit planı bağlanması (analyzer.py)**: open_position, CHAT_PREDICTION için
   caller'ın TP/SL/hold parametrelerini sessizce atıyor, %2.5 stop + 4 saat
   hold kullanıyordu. Artık: plan parametreleri verilirse (chat tahmin otomatı:
   TP %0.8/SL %0.5/900 sn) birebir uygulanır (system_take_profit_price,
   velocity_max_hold_sec, exit modeli "chat_replay_plan"); verilmezse (otonom
   hız avcısı) sabit TP yok, BE + ATR trailing merdiveni koşar.
   _manage_open_position'a "chat_plan_take_profit" ve "chat_plan_max_hold"
   çıkışları eklendi (max_hold_ ön eki bilinçli yok ki 24 saatlik timeout
   re-entry bloğu tetiklenmesin). Hold fallback'i kalıcı entry_context'ten
   okunur (restart sonrası da çalışır).

2. **Arayüz açık pozisyon listesi**: Ana sayfa (page.tsx) tablosu yalnızca WS
   portfolio'ya bağlıydı ve loadRestPositions tanımlı ama çağrılmıyordu — WS
   kopunca liste boşalıyordu. Artık REST 15 sn taban + WS override
   (displayPositions memo). Charts (charts/page.tsx) fetchPositions, res.ok
   kontrolü olmadan `positions || []` ile listeyi sıfırlıyordu; WS portfolio
   handler'ı da aynı şekilde. Her ikisi artık yalnızca gerçek dizi verisinde
   güncelliyor, hata durumunda mevcut liste korunuyor.

Doğrulama: py_compile temiz; venv ile 195 test = baseline ile birebir aynı
(failures=3, errors=3 — dotenv/psycopg ortam kaynaklı, pre-existing; kök
python312'de dotenv eksik olduğundan 86 error, venv şart). npm run build
EXIT 0 (20 sayfa). Not: pytest yok, unittest kullan (memory'deki ortam notu).

Sunucuya dağıtım hatırlatması: analyzer.py + iki frontend dosyası değişti;
sunucuda pull sonrası backend restart + frontend build gerekli.

**6 saatlik replay (30 Ağu 19:32, motor: `backend/work/chat_replay_6h.py`):**
Journal passes=True adayları (son 6h, M5 tarama başına en iyi) + Binance TR
1m klines (DB'deki historical_candles 6h penceresi boş — API'den çekildi,
historical_candles son verisi 00:52'de kalıyor, retention/gap-backfill
çalışmıyor olabilir → ayrı inceleme kalemi). 36 işlem, 300 TL/adet.
Sonuçlar: eski bug'lı -36,30 · yeni planlı -39,95 · plansız -81,55 ·
plan(BE yok) -54,05 (9 TP) · hepsi negatif. İçgörüler:
(1) Journal MFE'si (65% TP'ye ulaşır) path-independent — gerçek bar yolunda
stop önce vuruluyor, gerçek TP oranı %25'e düşüyor.
(2) Yeni merdiven tasarım gibi çalışıyor: bug'lı modelde tam stop -8,55 TL
(±%2,5) olan 7 işlem, yeni planda -2,55 TL'ye indi; ama BE arm aynı bar
uygulanınca TP'li işlem sayısı 0'a düşüyor (BE floor +0,50 TL'de kesiyor).
(3) Ekonomik kök sorun: 300 TL emirde çift taraf maliyet 1,05 TL (brüt TP'nin
%44'ü); net TP 1,35 TL vs net stop -2,55 TL → gereken win oranı %65,
gerçek %25-31. TP/SL/cost oranı düzeltilmeden çıkış modeli farkı ikincil.
Öneri: TP'yi %0,8→%1,2-1,5 arasına çekmek veya emir büyüklüğünü büyütmek
(oransal değil ama minimum-net-floor'u oranla küçültür) veya aday
filtresini sıkılaştırmak.

**Tur 3 (30 Ağu 20:00):** Kullanıcı canlı sunucuda `/api/positions` 500
gönderdiğini bildirdi (log ekte). Kök: `ValueError: Out of range float
values are not JSON compliant` — pozisyon alanlarında NaN/±Inf, starlette
`json.dumps(allow_nan=False)` tüm yanıtı düşürüyor; per-position try/except
bunu yakalayamıyor (hata serileştirmede). WS portfolio da aynı veriyi
taşıyor → panel her yerde boş. Düzeltme: `_json_safe_positions()` (main.py,
recursif NaN/Inf→None) /api/positions + ws_broadcast_loop'a eklendi.
NaN kaynağı muhtemelen WS kline ticker yolu (market_data.py:553, `close`
değeri filtresiz) veya entry_context teknik göstergeleri; sınırda temizlik
her iki yolu da koruyor.

**Yeni çıkış merdiveni (kullanıcı kontratı):** TP %0,8→%2,0 (config),
+%1 kâr görülünce stop = giriş×(1+%0,01)+giriş komisyonu payı (kâr
garantisi), sonrasında dinamik trailing stop = tepe×(1-%0,5) (yalnız
yukarı). Config yeni alanlar: VELOCITY_TRAIL_GAP_PCT=0.5,
VELOCITY_PROFIT_LOCK_PCT=0.01. Analyzer'da eski BE-arm+ATR-trailing bloğu
bununla değiştirildi (velocity_trailing_armed kaldırıldı,
velocity_protection_armed artık +%1 kilidi işaretliyor).

6h replay (37 işlem): eski bug'lı -53,90 · yeni merdiven **-53,27** ·
eski merdiven (BE+TP0.8) -54,70 · plansız -98,88. Yeni merdiven
kâr-kilidi işlemlerinde +2,2..+6,0 TL kazandırıyor (eski bug'lıda aynı
işlemler +0,5'te kesiliyordu), 1 işlem 15 dk max_hold'da +0,10 ile kapandı.
Ama yine negatif: 6h penceresinde girişlerin büyük kısmı +%1'e bile
ulaşamıyor (MFE %0.0 olan çok). Pencere küçük — 24-72h replay şart.

**24h replay (30 Ağu 20:30, onaylanan final ayar):** 85 işlem. Yeni
merdiven -72,83 (kazanan 19 işlem +70,56 / kaybeden 28 işlem -68,85);
bug'lı -12,66 (71 işlem +0,50 komisyon-rakibi kapanış — yanıltıcı "en
iyi"); plansız -101,51. Eşik taraması: **lock %0.7 en iyi (-4,15)**,
kilitsiz -14,56, trail %1.0 -19,21 → kullanıcı %0.7'yi onayladı.
Final: VELOCITY_TRAIL_TRIGGER_PCT=0.7 (env override'lı), TRAIL_GAP=0.5,
PROFIT_LOCK=0.01, TP %2, SL %0.5. Yeni merdiven iyi girişleri
yakalıyor (+%1+ MFE'de trailing tam görevinde), zarar girişlerin
kalitesinden — 72h pencere + aday filtresi sıkılaştırma sonraki adım.
HOURS=24 yapıldı (work/chat_replay_6h.py ismi 6h kalıyor ama parametrik).
