# Radar Eşik Sözleşmesi

Kaynak: `docs/RADAR_TARAMA_ANALIZI_2026-10-15.md` bölüm 4 (eşik tablosu), bölüm 5 (kanıt durumu), bölüm 8 madde 2, 9 ve 10. Her değişiklik `docs/DENEY_KAYDI.md` içinde bir satır gerektirir.

Kanıt durumu tanımları:

- **ölçüldü:** repodaki replay veya journal ile yön ve büyüklüğü ölçülmüş (tek günlük veya zayıf veri varsa parantezde belirtilir).
- **literatür:** özet düzeyde literatürle desteklenen, ama repo içinde ölçülmemiş.
- **keyfi:** ne ölçüm ne literatür desteği var; ölçülmemiş olanlar da buraya girer.

## Eşik tablosu

| Eşik | Varsayılan | Yer | Kanıt durumu |
|------|-----------|-----|--------------|
| Panel min / fast-lane / debounce | 71.5 / 73.5 / 2 | monitoring `_effective_min_score`, `_notify` | keyfi (skor ↔ MFE Spearman +0.05; eşik ölçülmedi) |
| Normalizasyon LOG_REF | 25000 | unified_scan:55 | keyfi (sabit kodlu norm sabiti) |
| Havuz: pool / active / top_gainers hacim / movers hacim | 30 / 15 / 5M / 2.5M TRY | velocity:490, binance_tr_public:613 | keyfi |
| 24s hacim tabanı (scan_one) | 1M TRY | velocity:603 | keyfi |
| Master-surge: hacim / spread / derinlik / min skor | 150k TRY / 0.45 % / 5k TRY / 70 | master_surge L1, :599 | keyfi (spread maliyet duvarıyla ilgili; eşik ölçülmedi) |
| ATR / BB / RSI-MFI uç | 0.25 / 2.5 / 80-90 | velocity:45-55 | keyfi |
| Çarpanlar: taker 0.58/0.45 | — | velocity:1107-1154 | keyfi (taker teyidi ölçülmedi; orderbook/OI korelasyonu 0.04–0.08) |
| Çarpanlar: chop 61.8 ×0.5 | — | velocity:1107-1154 | keyfi |
| Çarpanlar: geç faz %40 ×0.6 | — | velocity:1107-1154 | keyfi (yön ölçüldü: pos24 yüksek −0.68 %, t=−5.7; eşik ve çarpan ölçülmedi) |
| Çarpanlar: spread bilinmiyor ×0.85 | — | velocity:1107-1154 | keyfi |
| RR min / RR SL | 0.18 / 5.0 % | monitoring:1238 | keyfi |
| Hedef kademeleri | 74→4.0 %, 71.5→2.5 %, 68.2→2.0 % | velocity `dynamic_target_pct` | ölçüldü, zayıf (tek gün CSV, n=94; ortalama hedef +3.08 % → %41 isabet; kademeler kalibre değil) |
| Kombine: min quality / top_n / list_min | 10 / 2 / 15 dk | `combined_rising_settings` | keyfi |
| Combined paper SL / Auto paper SL | 1.0 % / 5.0 % | config:588, auto_paper | ölçüldü (combined SL: KALIBRASYON, n=5.909, walk-forward; auto SL: OTONOM, sıkı SL 1.5 canlıda 7× kötü; iki katman çelişen bulgu taşıyor) |
| Ticker / rising snapshot azami yaş | 60 sn / 120 sn | monitoring:1034, rising_signals | keyfi |

## Kurallar

1. **Yeni filtre ×1.0 ile çıkar.** Yeni bir filtre, bonus veya çarpan, lift ≥ 1 ölçülene kadar etkisi 1.0 olarak devreye girer. Lift, filtreden geçen adayların isabet oranının filtresiz tüm adayların isabet oranına bölümüdür; net EV aynı tabloda ayrıca raporlanır ve EV negatifken lift tek başına karar vermez. Ölçüm en az 2 haftalık journal ve sembol-dışı-bırakma (leave-one-symbol-out) kontrolü ile yapılır.
2. **Ölçülen lift < 1 olan filtre kaldırılır.** Çarpan 1.0'a çekilir veya kod silinir; bu da `docs/DENEY_KAYDI.md`'ye satır olarak yazılır.
3. **Üç "hedef" kavramı UI'da ayrı etiketlenir ve tek başına "hedef" yazılmaz:**
   - `potential_pct`: "30 gün zirve (potansiyel)"
   - `target_pct`: "bildirim hedefi"
   - `ceiling_pct`: "sonuç tavanı (outcome eşiği)"
4. **Eşik değişikliği kayıtsız çıkmaz.** Her eşik veya flag değişikliği önce `docs/DENEY_KAYDI.md` tablosuna bir satır olarak eklenir (README'deki "Deney disiplini" kuralı).

## Yapısal maliyet sınırı

Açıkça: mevcut sinyal ayarı bu sınırı aşamaz.

- Ölçülen brüt kenar işlem başına **+0.05 … +0.34 %**.
- Taker ücreti yaklaşık **%0.30**. Brüt kenar bu maliyetin altında kalıyor. Not: MALIYET_DUYARLILIK raporunda başabaş komisyon %0.17 olarak da geçer; gidiş-dönüş mü tek taraflı mı olduğu netleştirilmeden bu iki sayı karşılaştırılmamalı.
- Maker denemesi **−0.279 %** verdi; dolmayan ve ters seçilen (adverse selection) emirler nedeniyle çöktü.
- Sonuç: eşik, çarpan ve kapı ayarları bu açığı kapatmaz. Üç ürün seçeneği var; hangisinin (ya da hangi birleşiminin) uygulanacağı **ürün kararıdır**, mühendislik yalnızca her seçenek için kanıt koşulunu sağlayan ölçümü hazırlar.

| Seçenek | Ne değişir | Bu seçeneği haklı kılacak kanıt |
|---------|-----------|----------------------------------|
| A. Komisyon indirimi (BNB ödemesi, VIP kademesi) | Taker ücreti düşer; brüt kenar aynı kalır | Hesabın gerçek ücret oranı işlem geçmişinden ölçülmüş olmalı ve `backend/scripts/research_cost_sensitivity.py` ile bu ücret altında net EV > 0 çıkmalı; sonuç en az 2 haftalık journal ile tutarlı olmalı. |
| B. Daha uzun ufuk (örn. 60–120 dk tutma) | Pozisyon tutma süresi uzar; hedef ve SL geometrisi yeniden kurulur | Ufuk bazlı maliyet sonrası net EV pozitif ve örneklem yeterli olmalı. Mevcut veri 0–5 dk dilimi dışında negatif; literatür (Fieberg vd., JFQA 2024) kısa tutmanın maliyet sonrası negatif olduğunu gösteriyor. Ölçülmeden karar verilmez. |
| C. Seyrek, yüksek kaliteli sinyal (yalnız `trend_devam` + lead-lag teyitli) | Sinyal sayısı azalır; bildirim sıklığı düşer | Bu alt kümede net EV > 0, tüm evrene göre lift ≥ 1 ve sembol-dışı-bırakma testinde ayakta kalmalı; bağımsız olay sayısı önceden tanımlanmış bir alt sınırı (öneri: en az 100) geçmeli. Mevcut CSV'de yalnız yaklaşık 76 bağımsız olay var; bu yetersiz. |

Durum (2026-10-15): üç seçeneğin hiçbiri uygulanmadı ve hiçbiri için kanıt koşulu sağlanmadı.

## Periyodik ölçüm

Eşik ve kapı kararları haftalık olarak aynı araçlarla yeniden ölçülür (ayrıntı: README "Periyodik ölçüm"):

- `backend/scripts/radar_periodic_review.py --days 14` → `docs/reviews/RADAR_REVIEW_<tarih>.md`: aktif `RADAR_*`/`AUTO_PAPER_*` bayrakları, lift raporu, bildirim sonuç raporu, kova analizi ve KARAR listesi (lift<1 aileler, şans altı modlar, skor tabanı kontrolü).
- `backend/scripts/notification_outcomes_report.py` — kural 1 ve 2'nin kanıt aracı: aile/mode/skor kovası hit60'ı, aynı sembolde eşleşmiş rastgele anlardan oluşan **şans tabanı** ve "güncel politika" karşı-olgusalı (`--modes-disabled`, `--unified-min-score`). Karar ölçütü hit60'ın şans tabanına farkı (pp) ve net60'tır; `n < 30` satırlar sonuç çıkarmaya uygun değildir.
- `backend/scripts/horizon_grid_report.py` — seçenek B (uzun ufuk) için H×T×S×maliyet ızgarası; en iyi hücrenin t'si çok hücre denendiği için şişiktir, A→B / B→A örneklem-dışı sütunları ve şans tabanı farkı birlikte okunur.
- Eski dönemlere ait (kaldırılmış) stratejiler `--source signals` raporunda tarih aralığıyla ayrı gösterilir; güncel politika kararında kullanılmaz.

Rapor KARAR maddeleri öneridir; uygulanması yine `docs/DENEY_KAYDI.md` satırı gerektirir (kural 4).
