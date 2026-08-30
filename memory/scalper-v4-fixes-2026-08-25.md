---
name: scalper-v4-fixes-2026-08-25
description: 2026-08-25 denetim sonrası uygulanan tüm düzeltmelerin özeti,
  doğrulama durumu ve ileri geliştirme yol haritası
metadata:
  node_type: memory
  type: project
  originSessionId: sess_b935755b-ac48-4a17-bad8-7e86a50b3250
---

2026-08-25'de [[scalper-v4-audit-2026-08-25]] denetimindeki bulgular düzeltildi. 24 dosya değişti + 2 yeni dosya (`backend/tests/test_audit_fixes.py`, `frontend/app/signal-replay/page.tsx`). Tam rapor: `docs/AUDIT_FIX_REPORT_2026-08-25.md`.

Ana düzeltmeler: backtest kısmi çıkış muhasebesi (sanal sermaye şişmesi giderildi), psycopg reconnect, restore endpoint allowlist'i, OCO bacak validasyonu, rate-limit global'leri, clock-skew payı, `repair_history_gaps()` (WS gap-backfill), top-gainer hidrasyonu, mutabakat çift komisyonu, custom backtest spread tabanı, trailing önceki-bar zirvesi, instinct kanıt tekilleştirme, `_json_safe_dumps` (37 çağrı noktası), retention_loop (`RETENTION_DAYS`), koşullu ayar-kaydetme refetch'i, kalıcı re-entry blokları (llm_settings KV), frontend hydration/radar yan etkisi/NaN/backoff/stale göstergesi/kontrast/reduced-motion.

Doğrulama: **136/136 unittest OK**, backend py_compile temiz, `npm run build` EXIT 0 (24 rota).

**Kritik ortam notları:** venv'de pytest YOK (unittest kullan). Depoda `.gitattributes` yok — dosyalar LF/CRLF karışık; düzenleme yaparken hedef dosyanın HEAD bayt stilini koru (Python ile byte-exact patch en güvenlisi), aksi halde binlerce satır EOL kirliliği oluşuyor. Edit aracının karışık-EOL dosyalarda brace yapısını bozabildiği görüldü; büyük TSX patch'lerinden sonra `npx tsc --parse` benzeri kontrol şart.

Açık kalem: exit-profile araştırma sonuçları eski motorla üretildi — yeniden koşulmalı.
