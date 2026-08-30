---
name: scalper-v4-audit-2026-08-25
description: 2026-08-25 tam kapsam Scalper Agent V4 denetiminin teyit edilmiş
  kritik/önemli bulguları ve doğrulama komutları
metadata:
  node_type: memory
  type: project
  originSessionId: sess_b935755b-ac48-4a17-bad8-7e86a50b3250
---

2026-08-25'de D:\scalperagent_v4 için tam kapsam (backend akışı, veri hattı, backtest/öğrenme, frontend, DB/güvenlik/deploy) salt-okunur denetim yapıldı; kod değiştirilmedi. Teyit edilen en önemli bulgular:

1. `backtest.py:587-592` kısmi çıkış (exit-profile) muhasebesi net_pnl'i order_size kadar şişiriyor → tüm exit-profile araştırmaları güvenilmez.
2. `database.py:119-135` tek psycopg bağlantısı + global lock, reconnect yok → PG restartı süreci kalıcı zehirler.
3. `/api/postgres/restore` (`main.py:~4387`) gövdeden keyfi `path` alıp `pg_restore --clean` çalıştırıyor.
4. README'deki -%1 stop/+%0.2 BE/%0.5 trailing modeli kodda yok; canlı strateji BB-MFI (-%8.882 stop/+%2.317 TP). `breakeven_hit`, `TAKE_PROFIT_PCT`, `TRAILING_*` ölü.
5. `binance_tr_public.py:58-60` tanımsız `_rate_limit_used`/`_rate_limit_last_reset` → rate-limit takibi hiç çalışmıyor.
6. Mutabakat formülü (`main.py:1284-1288`) açık pozisyon giriş komisyonlarını iki kez düşüyor.
7. WS kesintisi sonrası mum gap-backfill yok; top-gainer aktivasyonu yeni sembol geçmişini hydrate etmiyor.
8. Frontend `/signal-replay` ve `/migration-monitor` rotaları boş (404); settings NaN→null gönderebiliyor; GainerRadar pasif izlemede PUT /api/config + radar execute tetikliyor.

Doğrulama ortamı: backend venv `backend/venv`, pytest YOK (unittest kullan), `python -m unittest discover -s tests` → 130/131 geçer; tek başarısız `tests/test_regressions.py::test_bb_mfi_v1_signal_contract` bayat sözleşme testi (dip teyidi filtresinden önce yazılmış; `BB_MFI_DIP_CONFIRMATION_ENABLED=False` yamasıyla geçiyor — üretim hatası değil). `npm run build` başarılı (23 rota). Backend derleme temiz.

İlgili skill'ler: [[goal-loop]], [[scalper-paper-research]], [[scalper-trade-manager]].
