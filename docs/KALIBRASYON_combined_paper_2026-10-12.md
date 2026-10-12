# Otonom Paper Kalibrasyon — 2026-10-12

## Soru
"Gönderilen listeler çok iyi (%80–240 gerçekleşme) iken otonom paper portföyü neden -%3.19?"
Kök ayrışma: panel "Gerçekleşen %" = **MFE** (iyimser zirve), portföy = **realize PnL**.
Kapanan 46 işlemde payoff **0.65** < başabaş için gereken **%60.7** kazanma oranı → net negatif.

## Yöntem (walk-forward)
- **Adaylar:** PostgreSQL `velocity_candidates` (passes=true) — canlı taramanın ürettiği
  **5.909 gerçek sinyal**, fiyat+zaman+hedef ile.
- **Mumlar:** önce yerel `work/market_cache.sqlite` (5m/1m), eksik semboller Binance TR REST'ten.
- **Simülatör:** `app/paper_sim.simulate_exit` — canlı `combined_paper` ile **AYNI** geometri
  (stop / kâr kilidi-trailing / no-profit-timeout / max-hold + komisyon&kayma).
- **Walk-forward:** kronolojik ilk %60 eğitim, son %40 sınav. Grid: SL × trailing-trigger × gap.
- **Anlamlılık:** eşleştirilmiş fark (paired) t-testi, 5m+1m, üç slippage seviyesi.

## Bulgular
| Konfig (5m sınav) | EV/işlem | Kazanma | Payoff |
|---|---|---|---|
| Mevcut varsayılan (sl 3.0 / trig 2.0 / gap 1.0) | -0.675% | 46.7% | 0.57 |
| **Kalibre (sl 1.0 / trig 2.0 / gap 1.0)** | **-0.42%** | 30.8% | 1.19 |

- **Hiçbir çıkış geometrisi POZİTİF EV üretmiyor** → edge GİRİŞ sinyalinde değil. Bu ayar
  "kaybı azaltır", "kâra çevirmez" (dürüst çerçeve).
- Dar stop **monoton ve tutarlı** biçimde daha iyi: %3→%1 kaybı 5m'de -0.83→-0.42,
  1m'de -0.70→-0.34 puan/işlem.
- **Eşleştirilmiş test: t ≈ 6.6–7.8** (ANLAMLI), her slippage (0.025→0.30%) ve 5m/1m'de aynı yön.
- 0.8 vs 1.0 farkı istatistiksel anlamlı ama **çok küçük** (0.06 puan) ve TRY alt-coin
  spread/gürültüsünde riskli → **1.0'da kalındı** (toplam iyileşmenin ~%87'si).
- Trailing'e **dokunulmadı**: trail testleri (`gap>=0.8`, `trigger>gap`) ve kullanıcının
  "trailing çok sıkı olmasın" kararı (2026-10-11) korunur.

## Uygulanan değişiklik
`COMBINED_PAPER_SL_PCT`: **3.0 → 1.0** (`backend/app/config.py`).
`paper_sim.simulate_exit` ve `combined_paper._plan_entry` aynı sabiti okur → sim ile canlı ayrışamaz.

## Neden işe yarıyor
Kayıtlı medyan zirve (MFE) ~**+%1.7** iken %3 stop, kazananın zirvesini geri verip
-%3'te kapanmasına izin veriyordu. %1 taban kaybı erken kesiyor.

## Sınırlar
- Sonraki liste/paper penceresi 120 dk; 24s MFE ile karşılaştırma elmayla-armut.
- Gerçekçi market-stop slippage modellenenden yüksekse mutlak rakamlar iyimserdir
  (yön ve sıralama korunur — slippage taraması bunu doğruladı).
- Giriş sinyali edge'siz olduğundan portföy bu ayarla da negatif beklenir; pozitife
  dönüş için GİRİŞ seçicisi iyileştirilmeli (ayrı iş).

## Yeniden üretim
```
python backend/scripts/calibrate_combined_paper.py --hours 3600 --fetch
```
Rapor: `work/cp_calib_full.json` (gitignore'da; ham veri).
