# Radar Tarama Akışı — Analiz ve Başarı Artırma Raporu (2026-10-15)

**Kapsam:** "Yükselme potansiyeli" radarı: evren seçimi → özellik hesabı → skor/kapı → bildirim/kombine liste → otonom paper → sonuç (outcome) geri beslemesi; `firsatlar` ve `daily-rising` sayfaları.
**Yöntem:** Üç paralel salt-okunur ajan: (1) kod akışı ve hesaplama denetimi, (2) repodaki 17 araştırma raporu + `sinyal_hedef_basarisi_all (3).csv` analizi, (3) dış literatür taraması (8 arama). Kritik kod bulguları koordinatör tarafından doğrulandı. Kod değiştirilmedi.

---

## 1. Yönetici Özeti

**Ana sonuç:** Radarın skoru, sembollerin ne kadar yükseleceğini **öngörmüyor**. Bu hem repodaki dört bağımsız replay'de (skor–getiri ilişkisi sıfır ya da ters) hem de tek günlük CSV'de (Spearman ρ = +0.05) tekrarlanıyor. Buna rağmen akışın çoğu yeri skoru seçici olarak kullanıyor ve son iki haftada eklenen 10 filtre/bonusun hiçbiri sonuç verisiyle ölçülmedi.

**İkinci sonuç:** Sonuç etiketleme (MFE/hedef isabeti) hatalı: mühürlenmiş pencerelere şimdiki fiyat ekleniyor, giriş fiyatı olarak sinyal fiyatı yerine devralınan anchor kullanılıyor ve dedup hiç çalışmıyor. Dolayısıyla "başarı" raporları ve `surge_learning` geri beslemesi kirli veriyle öğreniyor.

**Üçüncü sonuç (yapısal):** Ölçülen brüt kenar (+0.05 … +0.34 %/işlem) taker maliyetinin (~%0.30) altında; maker denemesi adverse-selection ile çöktü. Sinyal ayarıyla değil, ürün kararıyla (komisyon indirimi, daha uzun ufuk, hedef/çıkış geometrisi) aşılabilir.

| # | Alan | Bulgu | Önem |
|---|------|-------|------|
| 1 | Outcome | Mühürlü pencereye `lp` ekleniyor; giriş = anchor; `detected_at=now` → dedup yok | P0 |
| 2 | Kapılar | Kombine liste `passes/block_reason/failed_layer` süzmüyor; watchlist satırları `combined_paper`'a giriyor | P0 |
| 3 | Ölçek | Kombine yolda `panel_score` yok → ham skor (~1800) fusion'a giriyor, 100'e doyuyor; rising/squeeze 0-100 değeri ham alana yazılıp tekrar normalize ediliyor | P1 |
| 4 | Kanıt | Skor ↔ MFE ρ = 0.05; 100 puan kovası 95-99.9'dan kötü; hedef %3.08'e %41 isabet, %1.5-1.8'e %50 | — |
| 5 | Kanıt | Otonom işlem payoff 0.65 → başabaş için %61 isabet gerek; gerçekleşen %52 | — |

---

## 2. Akış (doğrulanmış)

```
ticker_24h ─► top_gainers(30, ≥5M TRY) + active_movers(15, ≥2.5M) + early_discovery(8) + SYMBOLS + extra[:10]
   │  scan_one: 24s hacim <1M TRY → ele; son 1m mum >180 sn → ele   (yaş/blacklist filtresi YOK)
   ▼
özellikler (kapanmış 1m ×60): ATR14, BB20, RSI14, MFI14, LinReg20, Aroon25, MACD, ret3/5, hacim(son/20 ort.)
   + 5m desen(40), 15m(130: ret_8h, ADX, ATR, eğim), taker(10), chop10, range_pos60, kitap dengesi(top-5), 24s değişim
   + rejim: BTC 1H EMA200, panik (macro_sentiment)
   ▼
velocity_score = 100·atr_r·bb_r·(0.2+0.8·struct)·(0.5+0.5·mom)·(0.5+0.5·vol)
   × MACD / lead-lag / taker / chop(×0.5) / geç faz(×0.6) / spread(×0.85) çarpanları
   ▼ normalize_score = 100·ln(1+raw)/ln(25001) → panel_score (0-100)
   │
   ├─ RADAR YOLU: _run_scan(limit 10) → enrich_candidates(fusion + master_surge) → _notify
   │     kapılar: panel ≥71.5 · hedef ≥ min · sert blok · debounce 2 · cooldown · fiyat Δ · RR ≥0.18 · MACD histerezis
   │     → push/WhatsApp → auto_paper (allowed_modes = trend_devam, unified)
   │
   └─ KOMBİNE YOL: combined_scan_rows (velocity 5m/15m limit 3, momentum, squeeze, rising, pulse, snapback)
         → (sembol,ufuk) tekilleştirme → quality = 0.6·panel + 8·kaynak + 4·katman + aile bonusu (tavan 99)
         → _send_combined_list(scan_score ≥ 10, top_n 2) → _inherit_anchor_prices → WhatsApp → combined_paper
   ▼
geri besleme: unified_outcomes (MFE/MAE/hit, ufuk+5 dk) · evaluate_daily_rising_report · surge_learning (±15 puan)
UI: /api/unified-scan/latest (20 sn önbellek) → firsatlar/page.tsx, page.tsx
```

---

## 3. Kod Bulguları

| Önem | Konum | Sorun | Çözüm |
|------|-------|-------|-------|
| **P0** | database.py:2186-2188 (doğrulandı); monitoring.py:3543 | Şimdiki fiyat `lp`, ufku bitmiş "mühürlü" listelerin MFE/MAE penceresine de ekleniyor → eski listenin sonucu sonradan değişiyor. Taşınan sembollerde fiyat `anchor_price` ile eziliyor → sinyal öncesi kazanç MFE'ye giriyor (sim `notify_price` kullanıyor, tutarsız). | `lp` yalnız `window_end ≥ now` iken; MFE/hit girişi `notify_price`; anchor ayrı sütun. |
| **P0** | unified_scan.py:267-269,435 (doğrulandı: `block_reason` yalnız geçiriliyor); monitoring.py:3211 | Kombine yol `passes`, `block_reason`, master-surge sert blok ve `failed_layer`'ı süzmüyor. `_notify`'ın elediği watchlist satırları (exhausted, üst fitil, aşırı spread) listeye ve `combined_paper`'a giriyor. | Tek `gate_candidate()` hem `_notify` hem kombine listede; sonuç `blocked_by` ile UI'da gri. |
| P1 | unified_signals.py:278-282 (doğrulandı) | Kombine yolda velocity satırında `panel_score` yok; ham `velocity_score` (örn. 1800) fusion'a giriyor, `min(100,·)` ile doyuyor → `unified_score` anlamsız. | `panel_score` her yerde `normalize_score(raw)`. |
| P1 | unified_scan.py:207-216,293-296; monitoring.py:4316; derivatives_service.py:240-259 | Ölçek karışımı: rising/squeeze 0-100 (squeeze 40-187) değeri ham alana yazılıp quality'de tekrar log-normalize ediliyor (70→~42); `_rank` ham ile panel'i kıyaslıyor; squeeze MILD_SHORT'u (−0.01 % funding) da alıyor. | Kaynak başına `_raw_from_panel`; `_rank` yalnız panel. |
| P1 | unified_scan.py:181-182 (doğrulandı: `detect_velocity_candidates({})`); velocity.py:1234,1320 | Kombine yol kendi taramasını limit 3 ve `journal_enabled=True` ile yapıyor → her `/latest` yenilemesi (20 sn) ve manuel tarama kalibrasyon journal'ına kopya yazıyor; UI top-3 görürken `_notify` 10 aday görüyor. | `journal_enabled=False`; `_run_scan` sonucunu önbellekten oku. |
| P1 | unified_scan.py:331-345 | `/latest` her satır için `_compute_potential` + `_live_atr_pct` REST çağrısı; limiter ve kline cache yok; 8 rps `_run_scan` ile paylaşılıyor; UI timeout 30 sn. | Stale-while-revalidate. |
| P1 | master_surge.py:465,529-541; monitoring.py:1151; velocity.py:1035 | `failed_layer==1` (spread/hacim/derinlik) blok üretmiyor; türev `fetch_error` yorumu fail-closed diyor, kod ceza vermiyor; spread yalnız WS evreninde (~18 sembol) ölçülüyor, dışında `None` → kapı atlanıyor. | `failed_layer` blok sayılsın; spread yoksa REST. |
| P1 | unified_signals.py:195,336; master_surge L2-L4 | MACD snapshot yaşı kontrol edilmiyor (yalnız `rising_signals` 120 sn bakıyor); fusion-only fiyatı bayat olabilir. | `rising_is_stale()` kapısı. |
| P1 | unified_outcomes.py:58,115-128 (doğrulandı: `detected_at` varsayılanı `time.time()`); database.py:7718 | Pencere ufuk+5 dk, eşik `ceiling_pct` (3×ATR) oysa bildirim hedefi %2-4; ufuksuz satırda pencere 5 dk; `detected_at=now` → DB dedup hiç çalışmıyor; boş mum dönen satır mühürlenmiyor, `LIMIT 200` kuyruğu tıkanabilir. | `_post_signal_window` + `_first_stop_or_target_bar` yeniden kullan; dedup anahtarı `(sym, h, floor(t/h))`. |
| P1 | monitoring.py:3086-3118; database.py:2023 | `last_daily_rising_report` `sent=False` satırları da döndürüyor, zaman sınırı yok → anchor gönderilmemiş/saatler önceki listeden miras. | `sent=1` ve en fazla 2×list_min yaş. |
| P1 | monitoring.py:3166-3167; unified_scan.py:276 | Tekilleştirme (sembol, ufuk) → aynı sembol 5m+15m olarak top-2'yi tek başına doldurabiliyor. | Sembol bazında tek satır, ufuklar rozet. |
| P1 | velocity.py:1006-1014 vs 1115-1154; unified_scan `_radar_family_bonus` | Hedef bandı ve `ceiling_pct` çarpan öncesi skorla, eşik çarpan sonrası skorla; aile bonusu aynı bayrakları (chop/late/spread/taker) ikinci kez puanlıyor. | Tek yerde uygula. |
| P2 | surge_learning.py:79-145; monitoring.py:6145 | `tp1_weight` işaretsiz (ceza da büyüyor); `win_rate`/`stop_rate` aynı işlemi iki kez sayıyor; `trade_count+radar_count` güveni şişiriyor; yalnız bildirilen/işlenenlerden öğreniyor (seçilim yanlılığı). | `unified_candidate_outcomes` + zaman sönümü + Beta büzülmesi. |
| P2 | monitoring.py:1678,1685,4809; velocity.py:564 | `notified_scores` süresiz kalıcı → eski yüksek skor meşru yeniden bildirimi engelliyor; `watch_symbols` alfabetik `[:10]`. | TTL; hacme göre sırala. |
| P2 | firsatlar/page.tsx:188, opportunity.ts:70,82; unified_scan.py:407; frontend/monitoring/page.tsx:340; main.py:1975,2004 | Hata/bayat veri gösterilmiyor, `_hit` tüketilmiyor; "Skor" quality (0-99) iken bildirim panel (log) skoru; "Hedef" 30g zirve (`potential_pct`), bildirim `target_pct`, outcome `ceiling_pct` → üç farklı "hedef"; `detected_at` her zaman now; norm sabitleri sabit kodlu; "ema" aslında SMA; verisiz TF 0 puan. | Tek sözleşme: `panel`, `target_pct`, `generated_at`, stale rozeti. |

---

## 4. Sembol Seçimini Etkileyen Eşikler

| Eşik | Varsayılan | Yer |
|------|-----------|-----|
| Panel min / fast-lane / debounce | 71.5 / 73.5 / 2 | monitoring `_effective_min_score`, `_notify` |
| Normalizasyon LOG_REF | 25000 | unified_scan:55 |
| Havuz: pool / active / top_gainers hacim / movers hacim | 30 / 15 / 5M / 2.5M TRY | velocity:490, binance_tr_public:613 |
| 24s hacim tabanı (scan_one) | 1M TRY | velocity:603 |
| Master-surge: hacim / spread / derinlik / min skor | 150k TRY / 0.45 % / 5k TRY / 70 | master_surge L1, :599 |
| ATR / BB / RSI-MFI uç | 0.25 / 2.5 / 80-90 | velocity:45-55 |
| Çarpanlar: taker 0.58/0.45, chop 61.8 ×0.5, geç faz %40 ×0.6, spread bilinmiyor ×0.85 | — | velocity:1107-1154 |
| RR min / RR SL | 0.18 / 5.0 % | monitoring:1238 |
| Hedef kademeleri | 74→4.0 %, 71.5→2.5 %, 68.2→2.0 % | velocity `dynamic_target_pct` |
| Kombine: min quality / top_n / list_min | 10 / 2 / 15 dk | `combined_rising_settings` |
| Combined paper SL / Auto paper SL | 1.0 % / 5.0 % | config:588, auto_paper |
| Ticker / rising snapshot azami yaş | 60 sn / 120 sn | monitoring:1034, rising_signals |

---

## 5. Kanıt: Repodaki Araştırmalar

| Bulgu | Kaynak | Durum |
|-------|--------|-------|
| SL 3→1 kaybı −0.675→−0.42 %/işlem (t≈7, 5.909 aday, walk-forward); hiçbir çıkış geometrisi pozitif EV vermedi | KALIBRASYON_combined_paper | **Uygulandı** (`COMBINED_PAPER_SL_PCT=1.0`) |
| Skor sıralaması ters: top-1 −1.03 % vs tümü −0.55 %; yüksek-skor yarısı daha kötü (t=−1.6); velocity ≥1000 −0.59 vs 100-300 −0.36; ML ≥0.5 en kötü | GIRIS_SECICI, KATMANLI_PUANLAMA, OTONOM_TESHIS | Karar `NO_ENTRY_EDGE`; `rising_pool.score_candidate` yazıldı ama kapalı |
| Çok-kaynak teyidi edge yaratmıyor (paired t=0.06; teyit=1 vs 3 ayrışmıyor) | BIRLESIK_HAVUZ, OTONOM | Canlıya alınmadı (doğru) |
| Tek pozitif mod `trend_devam` +0.269 % (5/5 hafta); diğerleri negatif; sıkı SL 1.5 canlıda 7× kötü | OTONOM_TESHIS | **Uygulandı** (`allowed_modes`, SL 5.0, trailing); iki paper katmanı çelişen SL bulgusu taşıyor |
| Tutma: 0-5 dk +0.45 %, sonrası her dilim negatif; hedef ulaşılabilir tepenin 2.7×; %87 hedefe değmiyor | OTONOM §2 | Ölçülmedi |
| Zirve/geç faz girişi: pos24 yüksek −0.68 % (t=−5.7), akşam −1.06 % (t=−4.2); vol_r, r1 başabaş | BAGIMSIZ_ONNGORUCU | Geç faz ×0.6 ve global %25 kapısı **uygulandı**, replay ile doğrulanmadı |
| Sinyal anında hareket olmuş: aday→15 dk slot −0.23 % | KOMBINE_LISTE_KADANS | Kadans değiştirilmedi (doğru) |
| Rejim ayrımı gerçek (RANGE t=+3.4, TREND −1.085 t=−7) ama EV pozitife dönmüyor | REJIM_GUDUMLU | Rejim kapısı **uygulandı**, outcome kanıtı yok |
| Maliyet duvarı: brüt +0.34 %, başabaş komisyon %0.17; maker −0.279 % (adverse selection); orderbook/basis/OI corr 0.04-0.08 → +0.06 % | MALIYET_DUYARLILIK, ORDERBOOK_MIKROYAPI, DERIN_ARASTIRMA | `book_imbalance`, `squeeze ×1.25` **uygulandı**, kanıtsız |
| Kesitsel momentum artefakt (örtüşen pencere, survivorship, taze listing; sabit evrende t=0.31) | KESITSEL_* | Yalnız USD residual lead-lag üretimde |
| radar-improvement-analysis'in 10 maddesinin 10'u uygulandı | grep ile doğrulandı | **Hiçbiri sonuç verisiyle ölçülmedi** (journal yeni) |

---

## 6. Kanıt: CSV (`sinyal_hedef_basarisi_all (3).csv`)

**Kapsam uyarısı:** 95 satır, tek gün (07.10.2026), 18 sembol; LAZIOTRY %34, ilk 5 sembol %65; 19 grup aynı sembol+dakika tekrar → ~76 bağımsız olay; tüm skorlar ≥85; fan-token pump günü. Genellenebilirlik düşük, ama yön repodaki replay'lerle tutarlı.

| Sonuç | n | | Kanal / Teyit | n | İsabet | Medyan MFE |
|---|---|---|---|---|---|---|
| HEDEFE DEĞDİ | 39 (%41) | | PUSH | 84 | %42.9 | +1.84 |
| KISMİ | 25 | | PANEL | 11 | %27.3 | +1.22 |
| TEPE (değmedi) | 13 | | Teyit = global | 24 | **%50.0** | **+2.84** |
| STOP (−1.5) | 10 | | jump+early+velocity | 28 | %39.3 | +1.97 |
| BAŞARISIZ | 7 | | yalnız velocity | 35 | **%31.4** | **+0.74** |

| Skor kovası | n | İsabet | Medyan MFE | | MFE eşiği | Ulaşan pay |
|---|---|---|---|---|---|---|
| 85-95 | 45 | %37.8 | +1.10 | | ≥0.5 % | %74.5 |
| 95-99.9 | 14 | %50.0 | +3.22 | | ≥1.0 % | %59.6 |
| 100 | 36 | %41.7 | +2.03 | | ≥1.5 % | %51.1 |
| **Spearman(skor, MFE)** | 94 | **+0.05** | | | ≥3.0 % | %41.5 |

- Ortalama hedef +3.08 % → %41 isabet. **%50'nin ulaştığı TP ≈ +1.5-1.8 %, %70'in ulaştığı ≈ +0.6 %.** MFE dağılımı iki tepeli (p50 1.76, p70 5.61, p90 8.75): ya gitmiyor ya büyük gidiyor; MFE ≤ 0 %18.
- `global` (lead-lag) teyitli sinyaller velocity-only'den belirgin iyi; üretimde sağ kalan tek kanalın lead-lag olmasıyla uyumlu (n küçük).
- **Otonom işlemler:** 30 satır → 21 benzersiz, net **−440.9 TRY**, 11 kazanan; kazanan +2.18 %, kaybeden −3.36 % (6'sı tam stop −4.32) → payoff 0.65, başabaş için %61 isabet gerek. KALIBRASYON'daki payoff birebir tekrar.
- SANDTRY 18:54 "HEDEFE DEĞDİ" (MFE +4.22) ama işlem −4.32 %: MFE penceresi ile işlem giriş/çıkışı ayrışıyor; rapor etiketi gerçekleşen PnL'i temsil etmiyor (bölüm 3 bulgu 1 ile tutarlı).

---

## 7. Kanıt: Dış Literatür (özet)

| İddia | Ufuk | Kaynak | Güç |
|-------|------|--------|-----|
| Günlük ufukta kısa vadeli **reversal** hâkim; illikit coinlerde güçlü, en likit birkaçında momentum | 1 gün | Zaremba vd., IRFA 2021 | güçlü (günlük) |
| BTC gün içi hem momentum hem reversal; büyük sıçrama/likidite deseni değiştiriyor | gün içi | Wen vd., NAJEF 2022 | orta |
| Hacim tek başına zayıf; **hacim şoku × geçmiş getiri** etkileşimi öngörüyor (reversal yönlü) | 12-24 sa | Bianchi & Dickerson (taslak, ikincil) | orta |
| Kesitsel faktörler (boyut, momentum, hacim) kripto getirisini açıklıyor | haftalık | Liu, Tsyvinski, Wu, JF 2022 | güçlü |
| ML kesitte doğrusaldan iyi ama sinyal birkaç basit özellikten geliyor; alfa illikitte yoğun | haftalık/aylık | Cakici vd. 2024 | orta |
| Çok kısa tutma süreli stratejiler maliyet sonrası negatif; trend faktörü yalnız likitte ayakta | haftalık | Fieberg vd., JFQA 2024 | orta |
| OFI eşzamanlı fiyatı açıklıyor, ileriye dönük gücü kanıtsız; top-of-book manipüle edilebilir | sn-dk | arXiv 2108.09750, BitMEX | zayıf-orta |
| Fonlama = baz arbitrajı, yönsel öngörü değil (TRY çiftlerinde vadeli yok) | 8 sa | He vd., arXiv 2212.06888 | — |
| Saat mevsimselliği (21-23 UTC) seçim yanlılıklı, çoklu test yok | saatlik | Quantpedia | zayıf |
| **Dakika ölçeğinde alt-coin için doğrudan hakemli kanıt bulunamadı** | 5m-1s | — | boşluk |

Tuzaklar (kod tabanında karşılığı): kapanmamış bar (burada `test_feature_scan_no_lookahead` ile kapalı); survivorship (evren bugünkü, delist yok); **kendi etiketlediği sonuçlar** (yalnız eşiği geçenlerden öğrenme → bölüm 3 P2 surge_learning); eşik overfit (10 yeni eşik, deney kaydı yok); zaman-sızıntılı doğrulama; spread/slippage (etiket mid-price üzerinden).

---

## 8. Başarıyı Artırma Planı (etki sırasıyla, kanıta bağlı)

1. **Önce ölçüm altyapısını düzelt (P0'lar).** MFE/hit girişi `notify_price`, mühürlü pencereye `lp` yok, `detected_at` gerçek sinyal zamanı, dedup `(sym,h,floor(t/h))`, tek outcome fonksiyonu; rapor/UI/`surge_learning` aynı tablodan. Bunlar olmadan diğer her ölçüm kirli. *Dayanak:* bölüm 3 bulgu 1, 9; CSV SANDTRY çelişkisi.
2. **Skoru seçici olmaktan çıkar; "kanıtlanana kadar ×1.0".** Son 10 filtre/bonus için `unified_candidate_outcomes` dolunca aile başına lift hesapla; lift < 1 olanı kaldır. Skor yerine `p_hit` (isotonic kalibre) üret ve precision@k ile değerlendir. *Dayanak:* ρ = 0.05; 4 replay'de ters/sıfır; literatür madde 6 (karmaşıklığın katkısı sınırlı).
3. **Hedefi ve çıkışı MFE dağılımına kalibre et.** `target_pct`'i ufuk bazlı medyan MFE'den türet (%1.5-1.8 → %50 isabet); TP-primary kapalı/trailing açık doğru. **Zaman-stop'u** test et: "15-20 dk içinde +X % yoksa çık" (0-5 dk tek pozitif dilim; sıkı SL canlıda 7× kötü). İki paper katmanının çelişen SL bulgusunu aynı harness'ta (`unified_pool_replay` / `calibrate_combined_paper`) kapat. *Dayanak:* CSV MFE eşikleri; OTONOM tutma tablosu; KALIBRASYON.
4. **Kapıları birleştir ve likidite katmanını blok yap.** `gate_candidate()` tek yerde; `failed_layer==1` blok; spread bilinmiyorsa REST ile ölç; kombine liste `passes` süzsün. *Dayanak:* bölüm 3 bulgu 2, 7; maliyet duvarı (spread %1-3 hedefi yiyor).
5. **Lead-lag (`global`) teyidini öne al, velocity-only'yi izleme listesine indir.** CSV %50 vs %31, medyan MFE 2.84 vs 0.74; üretimde sağ kalan tek kanal. Önce journal ile 2-3 hafta doğrula (n küçük). *Dayanak:* bölüm 6; KESITSEL_* (yalnız residual lead-lag ayakta).
6. **Sinyal akışında sembol bazlı dedup + günlük tavan.** Aynı dakika 38/95 tekrar, LAZIOTRY 32 sinyal/gün; çok-teyit tek olaydır (t=0.06). Sembol başına N saatlik tek bildirim, günlük tavan, (sembol) bazlı tekilleştirme (bulgu 11). *Dayanak:* BIRLESIK_HAVUZ; CSV kümelenme.
7. **Geç faz/zirve filtresini ölçerek sıkılaştır.** pos24 yüksek −0.68 % (t=−5.7), sinyal sonrası −0.23 % drift; mevcut %40 ×0.6 eşiği keyfi. `range_pos_60`/pos24 kovalarını journal'dan türet; OTONOM "kovalama fark yok" bulgusu ters yönde olduğundan ölçmeden eşik değiştirme. *Dayanak:* BAGIMSIZ_ONNGORUCU; literatür madde 1-3 (reversal/zirve).
8. **Likidite kovasına göre ayrı hipotez.** En likit TRY çiftlerinde momentum, illikitlerde reversal ayrı test; tek skor yerine kova başına ağırlık. *Dayanak:* literatür madde 1, 4, 7.
9. **Yapısal sınırı açıkça kabul et.** Brüt kenar taker maliyetinin altında; maker çöktü. Komisyon indirimi (VIP/BNB), daha uzun ufuk ya da yalnız `trend_devam` + lead-lag ile seyrek ama kaliteli sinyal ürün kararıdır. *Dayanak:* MALIYET_DUYARLILIK; literatür madde 7.
10. **Rapor hijyeni.** "Başarı" metriğini gerçekleşen işlem PnL'i ve ufuk-bazlı MFE olarak ayrı sütunlarda; ≥2 hafta ve sembol-dışı-bırakma (leave-one-symbol-out) testi olmadan karar yok; deney kaydı (hangi eşik, hangi tarih, hangi sonuç).

---

## 9. Sınırlar

- Statik inceleme; replay veya canlı veriyle yeni ölçüm yapılmadı (yerel Postgres yok).
- CSV tek gün ve sembol-kümelenmiş; sayılar yön gösterir, karar için yetersiz.
- Literatür özet düzeyinde okundu; dakika ölçeğinde alt-coin için hakemli kanıt bulunamadı.
- Kod ajanının bulgularından 1, 2, 3, 5, 9 koordinatör tarafından kodda doğrulandı; diğerleri ajan okumasına dayanır.
