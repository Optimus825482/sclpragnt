---
name: scalper-pump-replay-2026-08-25
description: PUMP Monitor düzeltmelerinin analizi, uygulaması ve 24 saatlik
  replay/izleme planı
metadata:
  node_type: memory
  type: project
  originSessionId: sess_b935755b-ac48-4a17-bad8-7e86a50b3250
---

2026-08-25'de PUMP Monitor stratejisi analiz edildi (292 işlem, −1.680 TL net) ve düzeltmeler uygulandı:

**Analiz bulguları:** Trailing stop motoru sağlıklı (+2.376 TL / 110 işlem); kaybın tamamı system_stop_loss'ta (−3.653 TL). VR>2.0 girişleri tek başına −1.029 TL; 56 stop +%0.5 MFE görmüştü (−1.536 TL); stopların %48'i hiç +%0.3 görmemiş. Skor-4 girişler skor-3'ten kötüydü (win %31 vs %49.5). Beklenen-PnL modeli filtre değil sadece bağlam.

**Uygulanan düzeltmeler:** `PUMP_MONITOR_MAX_ENTRY_VOLUME_RATIO=2.0` giriş filtresi (UI reason: "pump zaten patladı"); `pump_break_even_*` — MFE ≥ +%0.5'te stop net-floor'a taşınır (`pump_break_even_stop` çıkışı); `PUMP_MONITOR_FAST_FAIL_SEC=900` + min_progress %0.3 → `pump_fast_fail_no_progress`. Yeni config anahtarları CONFIG_FIELDS'e eklendi. Test: `tests/test_pump_monitor_improvements.py` (5 test).

**Replay sonucu:** Gerçek Binance TR 5m klines (18 sembol × 48 saat) bar-bar replay: eski −2.663 TL vs yeni kurallar −2.113 TL (**+550 iyileşme; stop zararı −5.663 → −614**). Eşik taramaları: BE trigger **0.3% > 0.5%** (−1.353 vs −1.690) → default 0.3 seçildi; VR cap 2.0 makul; **fast-fail tüm eşiklerde net kötüleştirdi → `PUMP_MONITOR_FAST_FAIL_ENABLED=false` default** (env ile açılır). Motor: `work/pump_replay_engine.py` (farklı pencerede tekrar koşulabilir). Canlı doğrulama: ARBTRY vr=2.11 filtreye takıldı, UI reason göründü.

**Final ayarlar:** `PUMP_MONITOR_MAX_ENTRY_VOLUME_RATIO=2.0`, `PUMP_MONITOR_BREAK_EVEN_TRIGGER_PCT=0.3`, BE açık, fast-fail kapalı. Test sunucusu notu: auth için SCALPER_ADMIN_PASSWORD + SCALPER_SESSION_SECRET env gerekiyor; login cookie'si `/api/pump-monitor` çağrısında gönderilmeli.
