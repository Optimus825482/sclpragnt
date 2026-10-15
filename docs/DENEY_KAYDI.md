# Deney Kaydı

Radar ve otonom paper akışındaki her eşik ve flag değişikliğinin tek kayıt yeri. Kaynak analiz: `docs/RADAR_TARAMA_ANALIZI_2026-10-15.md` (bölüm 8, madde 2 ve 10).

## Nasıl kullanılır

- Her eşik veya flag değişikliği canlıya çıkmadan ÖNCE bu tabloya tek satır eklenir; satır sonradan silinmez, karar değişirse yeni satır eklenir.
- "Karar" (kabul / reddet / beklemede) vermek için en az 2 haftalık journal verisi ve sembol-dışı-bırakma (leave-one-symbol-out) kontrolü gerekir.
- "Ölçüm komutu" sütununa kullanılan replay veya analiz komutu (dosya yolu ile) yazılır; komut repoda yoksa bunu açıkça belirtilir.
- "Sonuç" sütununa bağımsız olay sayısı (n), isabet ve beklenen değer (EV, %/işlem, net maliyet sonrası) yazılır.
- "Commit" sütunu değişikliği içeren commit'in kısa hash'i ile doldurulur; bekleyen ve henüz commit'lenmemiş satırlarda boş kalır.
- Eşik sözleşmesi ve kanıt durumu için `docs/RADAR_ESIK_SOZLESMESI.md` okunur.

| Tarih | Değişiklik (flag/eşik) | Eski → Yeni | Hipotez | Ölçüm komutu | Sonuç (n, isabet, EV) | Karar | Commit |
|---|---|---|---|---|---|---|---|
| 2026-10-12 | `COMBINED_PAPER_SL_PCT` (KALIBRASYON) | 3.0 → 1.0 | Dar SL, walk-forward'da kayıp EV'yi iyileştirir | `python backend/scripts/calibrate_combined_paper.py --hours 3600 --fetch` | n=5.909 aday; EV −0.675 → −0.42 %/işlem (t≈7); isabet raporda yok | kabul | 6bc2ee6b |
| 2026-10-07 | `allowed_modes` (OTONOM_TESHIS) | önceki değer (c62ce8eb öncesi) → `trend_devam,unified` | Yalnız pozitif modlar canlıda kalırsa net EV pozitif olur | `docs/OTONOM_TRADE_TESHIS_2026-10-07.md` (analiz scriptleri `work/*.py`, repoda yok) | EV +0.269 %/işlem; 5/5 hafta pozitif; n raporda yok | kabul | c62ce8eb |
| 2026-10-14 | `VELOCITY_LATE_PHASE_CHANGE_PCT=40` × `VELOCITY_LATE_PHASE_SCORE_MULT=0.6` | yok → 40 / ×0.6 | 24s değişimi %40 üzerindeki (geç faz) girişler negatif EV verir | Henüz yok; `docs/BAGIMSIZ_ONNGORUCU_TARAMASI_2026-10-12.md` pos24 kovalarından türetilecek | ölçülmedi (pos24 yüksek −0.68 %, t=−5.7 yönü destekler; eşik keyfi) | beklemede | b90f38ef |
| 2026-10-14 | `VELOCITY_REGIME_GATE_ENABLED` | yok → true | Rejim kapısı TREND'deki kayıp girişleri keser | Henüz yok; `docs/REJIM_GUDUMLU_SINYAL_ARASTIRMASI_2026-10-12.md` replay'i | ölçülmedi (RANGE t=+3.4, TREND t=−7 ayrımı var, EV pozitif değil) | beklemede | b90f38ef |
| 2026-10-14 | `book_imbalance` tie-breaker (kitap dengesi) | — → açık | Top-5 kitap dengesi eşit skorlu adaylarda yönü ayırır | Henüz yok; `docs/ORDERBOOK_MIKROYAPI_TESTI_2026-10-13.md` | ölçülmedi (orderbook korelasyonu 0.04–0.08) | beklemede | b90f38ef |
| 2026-10-14 | `squeeze_confirmation` çarpanı | 1.0 → 1.25 | OI squeeze teyidi sinyali güçlendirir | Henüz yok; `docs/DERIN_ARASTIRMA_5_YENI_ADAY_2026-10-13.md` (OI korelasyonu) | ölçülmedi (OI korelasyonu 0.04–0.08) | beklemede | b90f38ef |
| 2026-10-15 | `RADAR_NOTIFY_SYMBOL_COOLDOWN_MIN` (öneri 120) | 0 (kapalı) → 120 dk | Aynı sembol 120 dk içinde yeniden bildirilmez; tekrar bildirim gürültüsü azalır (38/95 aynı dakika tekrarı) | Henüz yok; journal'da sembol başına bildirim sayımı | ölçülmedi | beklemede, varsayılan kapalı (0); mevcut refire kapılarıyla birlikte ölçülmeli | |
| 2026-10-15 | `RADAR_NOTIFY_DAILY_CAP_PER_SYMBOL` (öneri 4) | 0 (kapalı) → 4 / gün | Sembol başına günlük tavan tekrarı keser (LAZIOTRY 32 sinyal/gün) | Henüz yok; journal'da sembol başına günlük sayım | ölçülmedi | beklemede, varsayılan kapalı (0) | |
| 2026-10-15 | `RADAR_NOTIFY_LEADLAG_PRIORITY=0` | yok → 0 (kapalı) | Lead-lag (`global`) teyitli sinyal velocity-only'den öne alınırsa isabet artar (CSV %50 vs %31) | Henüz yok; `unified_candidate_outcomes` üzerinden kanal bazlı kıyas | ölçülmedi (CSV tek gün, n küçük) | beklemede, varsayılan kapalı | |
| 2026-10-15 | `RADAR_TARGET_CALIBRATION_ENABLED=0` | yok → 0 (kapalı) | `target_pct` ufuk bazlı medyan MFE'den türetilirse hedef isabeti artar (%1.5–1.8 → %50) | Henüz yok; `docs/RADAR_TARAMA_ANALIZI_2026-10-15.md` bölüm 6 MFE eşikleri ile journal kıyası | ölçülmedi | beklemede, varsayılan kapalı | |
| 2026-10-15 | `AUTO_PAPER_TIME_STOP_MIN=0` | yok → 0 (kapalı) | 15–20 dk içinde yeterli hareket yoksa çıkış, kayıp tutmayı azaltır (0–5 dk tek pozitif dilim) | Henüz yok; `docs/OTONOM_TRADE_TESHIS_2026-10-07.md` tutma tablosu, zaman-stop replay'i | ölçülmedi | beklemede, varsayılan kapalı | |

Not: Yukarıdaki beş flag 2026-10-15 itibarıyla çalışma ağacında tanımlı (`backend/app/routers/monitoring.py`, `backend/app/routers/auto_paper.py`, `backend/app/target_calibration.py`) ancak henüz commit edilmemiştir; commit yapıldığında Commit sütunu doldurulur.
| 2026-10-15 | `RADAR_REPORTS_BASELINE_AT=2026-10-15 22:30` | yok → 2026-10-15 22:30 (UTC+3) | Radar bildirimi raporları (başarı, teyit kademeleri, liste, MACD MTF, Rising, Kombine Yükseliş) yalnız yeni algoritma sonrası bildirimlerle ölçülürse başarı eski algoritmayla kirlenmez (görünüm filtresi, silme yok; paper/bakiye raporları etkilenmez) | `GET /api/reports/notifications?day=all` vs `&include_archived=true` kıyası | n/a (ölçüm filtresi, eşik değil) | uygulandı, "Arşivi göster" ile eski veri görünür | |
| 2026-10-16 | Ölçüm: `blocked_by` journal kolonu (migration 016) + `scripts/radar_shield_analysis.py` | yok → kapı nedeni kaydedilir | BTC rejim kalkanı (`BTC_BEAR_REGIME_SHIELD`) engellediği adayların bir kısmını kaçırıyor olabilir (canlı: skor 85.8, ML %90.9 aday 3 saat bildirimsiz kaldı) | `cd backend && python scripts/radar_shield_analysis.py --days 14 --min-n 30` | veri birikiyor (kayıt 016 sonrası başlar; eski satırlar dışlanır) | ön kayıtlı kural: hit(kalkan) >= hit(geçen)-5p → KALKAN_FAZLA_SIKI; < -10p → KALKAN_ISE_YARIYOR; aksi BELIRSIZ; kalkan davranışı DEĞİŞMEDİ | |
