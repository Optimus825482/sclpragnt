# Chat Modeli "En Hızlı Yükseliş" Veri Araştırması — 2026-11-10

Soru: Chat sayfasındaki LLM'in **"en kısa sürede, en hızlı ve en çok yükselecek sembol ya da semboller"** sorusunu doğru yanıtlayabilmesi için modele hangi verilerin, hangi tazelikte ve hangi formda verilmesi gerekir?

Bu belge kod durumu (dosya/satır kaynaklı) ve projenin kendi ölçümlü araştırma bulgularına dayanır. Deneysel disiplin gereği buradaki öneriler tek başına canlıya çıkmaz; bkz. `docs/DENEY_KAYDI.md`.

---

## 1. Bugünkü durum (kodla doğrulanmış)

### 1.1 Chat'in modele baştan verdiği piyasa verisi sınırlı

- Akış: `frontend/app/chat/page.tsx` → `POST /api/strategies/llm/chat` → `backend/app/routers/llm_chat.py:strategies_llm_chat()` (satır ~3475) → context dict (satır ~3569) → `llm_analysis.chat()`.
- Baştan enjekte edilen piyasa verisi **yalnızca** `market_opportunity_intent` regex'i eşleşirsemibir sembol adı yoksa gelir (`llm_chat.py:3514` ve `3617–3634`):

```python
market_scan = await scan_market_snapshots({
    "symbols": config.SYMBOLS,            # sabit evren
    "timeframes": ["15m", "30m", "1h"],   # 15 dk + ufuklar
    "limit": 10,
})
```

Bu taramanın "en hızlı yükseliş" sorusuyla dört uyumsuzluğu var:

| # | Sorun | Açıklama |
|---|---|---|
| 1 | **Evren** | `config.SYMBOLS` sabit listesi; tüm Binance TR piyasası değil. `early_discovery` halihazırda `!miniTicker@arr` ile **tüm** TRY paritelerini ~1 sn'de izliyor. |
| 2 | **Ufuk** | 15m/30m/1h. Sorunun ufkuyken 1m–15m tarama yapılmıyor. |
| 3 | **Sıralama anahtarı** | `_market_candidate_score` (analiz snapshot skoru). "Dakika başına beklenen yükseliş" anlamına gelen kanonik anahtar `upside_rank_score` (`routers/velocity.py` ~satır 2502) bu taramada yok. |
| 4 | **Tazelik/tur gecikmesi** | `scan_market_snapshots` sembol başına analiz üretir (`LLM_MARKET_SCAN_CACHE_SEC` önbellekli); hız kanallarının (1 sn) tazeliği burada yok. |

### 1.2 En hızlı veri kanalları zaten var — ama modele baştan gitmiyor

| Kanal | Modül | Verdiği değişkenler | Model şu an nasıl erişiyor? |
|---|---|---|---|
| Keşif (tüm piyasa, ~1 sn) | `app/early_discovery.py` → `top_candidates()` | `return_1m_pct`, `return_20s_pct`, `volume_burst` (eşikler 0.4% / 2.0×) | Yalnız velocity havuzu kaynaklarından biri olarak, dolaylı |
| Mikro-akış (aktif aday) | `app/microflow.py` → `get_snapshot()` | `ret_1s`, `ret_5s`, CVD proxy, whale sayısı, derinlik duvarı/merdiven dengesi | `get_subminute_microstructure` aracı (1s/5s barlar) |
| Hız Avcısı (kapanmış 1m) | `routers/velocity.py` (radar 30 sn) | `upside_rank_score`, `velocity_score`, `ret3/ret5`, `atr_pct`, `bb_width_pct`, RSI/MFI, `linreg_slope10_pct`, Aroon, hacim z, mod (trend_devam / v_donusu), journal kalitesi | `detect_5m/15m_upside_candidates` araçları veya `POST /api/llm/upside-scout` düğmesi |
| Master Surge (4 katman) | `app/master_surge.py` | `composite_index`, `confluence_4way`, TP1/TP2 | `get_master_surge_prediction` aracı |
| MACD/CVD monitörü | `routers/macd_monitor.py` (`_SNAPSHOT`) | tier, güç, erken skor, CVD alıcı-baskınlığı, kurulum (dip/yaklaşım/m1) | Yalnız hızlı şerit (`_symbol_quick_context`) veya araçlarla |
| Global→TR lead-lag | `app/lead_lag_signal.py` + `routers/global_radar.py` | Rezidüel sinyal (Global 5m getirisinin TR'ye açıklanmayan kısmı) | Sinyal/bildirim kanalı; chat context'inde değil |
| Vadeli/makro | `derivatives_service.py`, makro servis | Funding oranı/durumu, OI, Korku&Açgözlülük, BTC panik | `get_derivatives_intel`, `get_macro_market_sentiment` araçları |

Sonuç: Model bu verilere **araç (tool) çağrısı yaparak** erişebilir (~50 araç, sınırlı tur bütçesi). Ama (a) her araç turu gecikme demektir — "en kısa sürede" sorusu için ters, (b) model çağrı yapmaya karar vermezse veri hiç gitmez, (c) `upside-scout` yalnız düğme/onay ile çalışan ayrı bir uç noktadır.

---

## 2. Projenin kendi ölçümlü bulguları: ne mümkün, ne değil?

Araştırmalar (özet — kanıt listesi §5'te) ortak bir tablo çiziyor:

1. **Pump ÖNCESİ yönlü öncü YOK.** 401 özellik × 90 gün olay çalışması (`GOSTERGE_ERKEN_UYARI_2026-10-17.md`): olay başlangıcından önce hiçbir yönlü öncü çıkmadı; pump24 çalışması da karar barı açılışında gösterge EV katkısını +0.01–0.02 puanta sınırladı. **En erken güvenilir sinyal, pump'ın İLK M5 barının içinde.**
2. Bu yüzden "en hızlı yükselişi en kısa sürede tespit" üç parçaya ayrılır:
   - **(a) Yakalama hızı:** pump başlar başlamaz görmek → `early_discovery` (1 sn örneklem) + velocity'nin kapanmış-1m taraması. 24 saatlik top-gainer listesi ilk 1–3 dakikayı kaçırır; keşif kanalı tam bu boşluk için yazılmıştır.
   - **(b) Sıralama:** dakika başına beklenen yükseliş → `upside_rank_score` (beklenen yükseliş/dk × hız × sembol journal kalitesi × mikro-yapı çarpanı).
   - **(c) Gerçekçilik:** maliyet sonrası EV. Gidiş-dönüş maliyet duvarı ~%0.53; hedeflerin bunu aşması gerekir (pump24: pozitif EV'li hedef/stop ızgarası bulunamadı; çıkış modeli değil **giriş kalitesi** darboğaz).
3. **Ayırt edici eksenler** (velocity adli incelemesi, 10 saldırı / 60 kontrol): BB genişliği (d=+0.73), RSI iki modluluğu (d=+0.52), LinReg eğimi (d=+0.43), Aroon (d=+0.40). **Tek başına hacim sıçraması ayırt edici DEĞİL** (d=−0.01) — hacim zorunluluğu bu yüzden kaldırıldı.
4. **Tek ölçülmüş gerçek öncü:** Global→TR rezidüel lead-lag (ileri getiri korelasyonu +0.144, 45 gün / 112 sembol) ama maliyetle sınırlı (`REAL_BUT_COST_BOUND`) → bağlam olarak değerli, işlem kenarı olarak değil.
5. **LLM asla sonuç üretmez, ölçüleni açıklar:** `chat_predictions` / `chat_prediction_insights` döngüsü (120 sn) kapanmış M1'den sonucu ölçer, LLM sonrası analiz yapar. Modele verilecek her yeni blok bu disipline bağlanmalıdır.

---

## 3. Öneri: modele baştan verilecek "hızlı yükseliş kısa listesi" (fast-rise brief)

Baştan enjekte edilecek **kompakt blok** (yalnız bellek-içi/DB önbellek okuması, sıfır REST; hedef ~600–900 token). Kullanıcının "en hızlı yükselen hangisi" tarzı sorularında modelin araca tur atmadan kanıtlı listeyle başlaması için:

```jsonc
"fast_rise_brief": {
  "generated_at": ..., "age_sec": ...,           // tazelik zorunlu
  "data_policy": "bağlam; tahmin/garanti değildir, paper-only",
  "velocity_top": [                               // radar son turdan (≤30 sn), top-5, upside_rank_score sıralı
    {"symbol": "...", "upside_rank_score": ..., "velocity_score": ..., "mode": "trend_devam|v_donusu",
     "ret3_pct": ..., "ret5_pct": ..., "atr_pct": ..., "bb_width_pct": ..., "rsi": ..., "mfi": ...,
     "linreg_slope10_pct": ..., "aroon": ..., "volume_z": ..., "m5_pattern_ok": ...,
     "journal_touch_rate": ..., "target_pct": ..., "horizon_min": ..., "age_sec": ...}
  ],
  "discovery_top": [                              // early_discovery.top_candidates(limit=5)
    {"symbol": "...", "return_1m_pct": ..., "return_20s_pct": ..., "volume_burst": ..., "age_sec": ...}
  ],
  "microflow_top3": [                             // velocity_top ilk 3 için microflow.get_snapshot
    {"symbol": "...", "ret_1s": ..., "ret_5s": ..., "cvd_proxy": ..., "whale_count": ...,
     "depth_wall_ladder": ...}
  ],
  "shield": {"btc_15m": ..., "market_regime": "RISK_OFF|...", "avg_spread_ok": ...},
  "lead_lag_active": [                            // varsa; tek ölçülmüş öncü → bağlam
    {"tr_symbol": "...", "global_symbol": "...", "residual": ..., "age_sec": ...}
  ]
}
```

Tasarım gerekçeleri:

- **Ayırt edici eksenler tam set halinde** verilir (oynaklık genişlemesi `atr/bb_width`, yükseliş rejimi `rsi/ema-yapı`, yapısal teyit `linreg/aroon`); hacim alanı bilgi amaçlıdır, filtre olarak sunulmaz (§2.3).
- **İki katman:** `velocity_top` (kapanmış-1m teyitli, journal kalitesiyle ağırlıklandırılmış) + `discovery_top` (ilk dakika, henüz 1m bar kapanmamış olabilir). Keşif kanalı velocity'ye düşmüş adayları verir; ikisi birlikte "şu an yükselen + az önce ateşlenen"i kapsar.
- **Kalkan bloğu zorunlu:** rejim RISK_OFF iken model kısa listeyi öne çıkarmamalı; `market_regime` soft seçici olarak zaten `scan_market_snapshots` içinde de kullanılıyor.
- **Rol kuralına dokunmaz:** admin olmayan kullanıcıya gösterge dökümü yasağı **çıktı** içindir; modelin veriyi içeri'de kullanıp sade dilde sunması mevcut persona sözleşmesiyle uyumludur.
- **Niyet kapsaması:** mevcut `market_opportunity_intent` regex'i ("yüksel", "sembol", "momentum"…) bu soru tipini zaten yakalar; sorun taramanın evreni/ufku/sıralamasıdır. Öneri: bu niyette `market_scan`'in (15m/30m/1h) **yanına** bu blok eklenir; "en hızlı / en kısa sürede" gibi aciliyet ifadelerinde blok öncelikli anlatılır.
- **Alternatif araç toplama:** blok bağımsız olarak `get_fast_risers` adlı tek araç da yapılabilir (velocity top + discovery + microflow tek çağrıda) → agentic tur sayısı ve gecikme düşer. Blok + araç birlikte önerilir: blok cevabı hızlandırır, araç güncelliği korur.

### Verinin nereden okunacağı (uygulama notu)

> **Uygulama durumu (2026-11-10): v2 devrede.**
> - **v1:** `_build_fast_rise_brief` (`llm_chat.py`), `market_opportunity_intent` niyetinde `market_scan`'in yanına `context["fast_rise_brief"]` olarak eklenir. Kaynaklar: `monitoring.get_cached_radar_candidates()` (yeni salt-okunur erişimci) + `early_discovery.top_candidates()` + `market.get_microstructure()` (bellek-içi). Test: `backend/tests/test_chat_fast_rise_brief.py`.
> - **v2:** (a) journal touch-rate TTL'li önbellekle sıralamaya girdi (`_fast_rise_touch_rates`, `CHAT_FAST_RISE_BRIEF_TOUCH_TTL_SEC=300`); (b) lead-lag aktif sinyalleri katman 4 olarak eklendi (`global_radar.get_recent_leadlag_signals` — yeni halka tampon; `GLOBAL_SCAN_ENABLED` kapalıysa boş); (c) tek-tık yolu: `POST /api/llm/fast-risers` (deterministik kısa liste + kısa LLM yorumu; adaylar `prompt_version="fast-risers-v1"` ile journal'a yazılır — chat lane A/B'sini kirletmez) + chat'te `FastRiseCard` görsel kartı ve "🚀 EN HIZLI HANGİSİ" düğmesi.
> - **Ölçüm:** `backend/scripts/chat_prediction_ab_report.py` — `llm_forecasts`'ı prompt_version'a göre kırar (`fast-risers-v1` vs `upside-scout-%`); hit = `direction_correct`, getiri brüt. A/B anahtarları: `CHAT_FAST_RISE_BRIEF=false`. Kayıt: `docs/DENEY_KAYDI.md` 2026-11-10 satırı.
> - v1'de olmayıp v2'de girenler: journal touch-rate özeti (önbellekli) ve lead-lag sinyalleri (tampon erişimcisi). `get_fast_risers` tek-araç seçeneği hâlâ açık — uç nokta kısa liste ürettiği için şimdilik gerek görülmedi.


- **Velocity top:** radar döngüsü (`routers/monitoring.py`, `SCAN_INTERVAL_SEC=30`) zaten her tur `detect_velocity_candidates` çalıştırıp sonuçları DB'ye yazıyor. Ya DB'den son turun passing adayları çekilir ya da döngüye in-memory top-N kopyası eklenir (en düşük gecikme: ikincisi).
- **Discovery:** `early_discovery.top_candidates(limit=5)` hazır, in-memory.
- **Microflow:** `microflow.get_snapshot(symbol)` hazır (WS + REST depth, aktif aday için).
- **Kalkan/öncü:** `macd_monitor._SNAPSHOT`, master surge/derivatives/makro önbellekleri, `lead_lag_signal` aktif sinyal durumu mevcut.

### Kısa liste alanları bilinçli seçildi (araştırma yasakları)

- Eklenmedi: funding/OI işlem sinyali (net ≈ −0.3; yalnız bağlam), kesitsel momentum alfa iddiası (artefakt çıktı), tek başına hacim sıçraması filtresi (d=−0.01), "pump öncesi" iddiası taşıyan hiçbir alan (ölçülmüş öncü yok).
- Eklendi: journal touch-rate (sembolun kendi baz oranı — momentum_scan geleneği) ve `age_sec` (bayat veri uydurma riskini kırar).

---

## 4. Ölçüm planı (deneysel disiplin)

1. Değişiklik `prompt_version=chat-fast-rise-v1` etiketiyle `chat_predictions` journal'ına yazmaya devam eder (mevcut sözleşme bozulmaz).
2. 2 haftalık A/B: kısa liste bloğu **açık vs kapalı**; ölçütler: (a) hit@5m/15m (kapanmış M1'den), (b) yanıt gecikmesi (araç tur sayısı), (c) yanıt doğruluğu (uydurma/bayat sembol sayısı), (d) kullanıcının "en hızlı yükseliş" sorularına listeden cevap oranı.
3. Karar `radar_periodic_review` geleneğinde raporlanır; eşik/flag değişikliği `docs/DENEY_KAYDI.md` satırıyla canlıya çıkar.

---

## 5. Kanıt listesi (repo içi)

| Konu | Kaynak |
|---|---|
| Chat akışı ve context kurulumu | `backend/app/routers/llm_chat.py:3475, 3514, 3569, 3617–3644`; `frontend/app/chat/page.tsx` |
| Hızlı şerit context | `llm_chat.py:3229` (`_symbol_quick_context`) |
| Market tarama ve skor | `llm_chat.py:1646–1705` (`scan_market_snapshots`, `_market_candidate_score`) |
| upside-scout uç noktası | `llm_chat.py:1108`, `prompt_version=upside-scout-v2-blend` |
| Keşif kanalı | `backend/app/early_discovery.py` (1 sn örnekleme, `top_candidates`) |
| Mikro-akış | `backend/app/microflow.py` (1s/5s barlar, CVD proxy, whale, derinlik) |
| Hız Avcısı ve sıralama anahtarı | `backend/app/routers/velocity.py` (~2502 `upside_rank_score`; adli inceleme notları ~2224–2230) |
| Master Surge | `backend/app/master_surge.py` |
| Lead-lag | `docs/USD_LEADLAG_ARASTIRMASI_2026-10-12.md`, `docs/USD_LEADLAG_GENIS_PENCERE_2026-10-12.md`, `app/lead_lag_signal.py` |
| Veri kanalları | `docs/VERI_KANALI_ARASTIRMASI_2026-10-12.md` |
| Pump öncesi yokluğu / v2 izleme listesi | `memory/pump24-research-findings-2026-08-31.md`, `memory/pump24-pattern-research-2026-08-30.md` |
| 149 gösterge → olumsuz | `docs/GOSTERGE_REHBERI_V2_OZET_2026-10-17.md` (+ 4 kol raporu) |
| Erken uyarı olay çalışması (401 özellik) | `docs/GOSTERGE_ERKEN_UYARI_2026-10-17.md` |
| Kesitsel momentum artefaktı | `docs/KESITSEL_MOMENTUM_COK_REJIM_2026-10-13.md` |
| Çıkış/maliyet ekonomisi | `memory/chat-prediction-exit-plan-fix-2026-08-30.md` |
| Chat tahmin öğrenme döngüsü | `llm_chat.py:817` (120 sn döngü), `app/chat_prediction_learning.py`, `memory/chat-prediction-learning-2026-08-29.md` |
| Deneysel disiplin | `docs/DENEY_KAYDI.md`, `docs/RADAR_ESIK_SOZLESMESI.md`, README "Deney disiplini" |
