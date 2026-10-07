# Scalper Agent V4 — Denetim Bulgularının Düzeltilmesi (2026-10-07)

Bu belge, [DENETIM_RAPORU_2026-10-07.md](DENETIM_RAPORU_2026-10-07.md) içindeki
tüm bulgulara yapılan **kod düzeltmelerini** özetler. Her madde: ne yapıldı,
hangi dosyada, ve nasıl doğrulandı.

**Çalışma yöntemi:** Bulgular dosya-sahiplikli 12 paralel alt-ajanla düzeltildi;
koordinatör (ana oturum) çakışmayı önlemek için her ajanı tek bir dosya kümesine
bağladı ve her düzeltmeyi bağımsız olarak yeniden doğruladı.

---

## P0 — Kritik (5/5 düzeltildi)

### P0-1 — Master Surge 4'lü-teyit kapısı tüm radar adaylarını bastırıyordu ✅
**Kök neden:** `passed=False` üreten "yetersiz 4'lü teyit" SERT RİSK ile
karıştırılıp adayı öldürüyordu; oysa bu bir SKORLAMA girdisidir.
**Düzeltme:**
- `config.py`: `MASTER_SURGE_REQUIRE_4WAY` varsayılanı `true → false` (kanıt + geri-alma notuyla).
- `routers/monitoring.py`: kapı ikiye ayrıldı — `_master_surge_hard_block_reason`
  (gerçek risk: EXTREME_LONG fonlaması / BTC panik / BTC rejim kalkanı → daima bloklar)
  ve `_master_surge_confluence_gate_reason` (yetersiz teyit → yalnız **gözlemlenebilirlik**,
  karar yolunu KAPATMAZ). Yalnız gerçek risk bloğu bildirimi ve otonom girişi engeller.
**Doğrulama:** `_master_surge_block_reason({passed:False})` artık `None` döner; radar +
hızlı-yol + yükseliş yollarının üçü de aynı sert-risk kapısını paylaşır.

### P0-2 — Mod filtresi radar yolunu kapatıyordu ✅
**Düzeltme:** `auto_paper.py` — `allowed_modes` artık `["trend_devam", "unified"]`.
Radar/birleşik bildirimleri (`mode="unified"`) yeniden otonom açılabiliyor.
**Doğrulama:** DB varsayılanı ve endpoint varsayılanı aynı listeyi taşıyor.

### P0-3 — `reports_baseline` açık pozisyonları yönetimden düşürüyordu ✅
**Kök neden:** Rapor görünüm sınırı İŞLEM YÖNETİMİNE sızıyordu; sınırdan eski açık
pozisyon SL/TP/max_hold/trailing'e hiç uğramıyor ve risk tavanından muaf kalıyordu.
**Düzeltme:**
- `database.py`: `list_auto_paper_trades(..., apply_reports_baseline: bool = True)` —
  varsayılan `True` rapor davranışını **birebir korur**; `False` yalnız rapor sınırını
  kaldırır (portföy reset cutoff'u KALIR). Aynı sızıntı `get_auto_paper_stats`
  açık-sayımında da kapatıldı.
- `auto_paper.py` (yönetim döngüsü + açık-pozisyon risk tavanı), `runtime.py`
  (açık liste, düşen-sembol kapatma, pasif-sembol kapatma), `macd_monitor.py`
  (MACD çıkış takibi), `llm_chat.py` (LLM'e açık pozisyon görünürlüğü),
  `main.py` (`/api/positions`), `auto_paper.py` `list_trades_endpoint`
  (yalnız `status="open"` için) — hepsi `apply_reports_baseline=False` geçer.
**Doğrulama:** 30 test (`test_portfolio_reset_archiving.py`) + tüm açık-okuma
çağrı yerleri tarandı; varsayılan `True`'da kalan tek `status="open"` çağrısı yok.

### P0-4 — "Tüm emirleri iptal et" HTTP hatasını başarı sayıyordu ✅
**Düzeltme:** `frontend/app/binance-tr/page.tsx` — `apiRequest` non-ok'da throw
etmediği için artık `r.ok && d?.ok !== false` başarı sayılır; hatalar `failCount`'a
gider ve dürüst sonuç gösterilir.

### P0-5 — Farklı kilit anahtarı, aynı cüzdan satırı ✅
**Düzeltme:** `database.py` — `open_auto_paper_trade` ve `close_auto_paper_trade`
artık transaction'ın **ilk** statement'ı olarak `pg_advisory_xact_lock(hashtext('paper_portfolio_open'))`
alır (cüzdan okunmadan önce). Dört cüzdan-yazan yol (reset / reconcile / aç / kapat)
TEK anahtarda serileşir; sembol/işlem kapsamlı kilitler churn denetimi için korunur.

---

## P1 — Yüksek (11/11 düzeltildi)

| # | Bulgu | Düzeltme | Dosya |
|---|-------|----------|-------|
| **P1-1** | Fast-scan hiç bildirim teslim etmiyordu | `_run_scan()` sonucu artık teslim edilir (`_deliver_scan_notifications`) | `monitoring.py` |
| **P1-2** | Risk kapısı yükseliş yolunda yoktu | `_rising_risk_block_reason` eklendi; sert risk hem doğrudan hem UPDATE yolunu kapatır | `monitoring.py` |
| **P1-3** | LLM ikinci-göz kapısı girişte etkisizdi | Otonom giriş LLM kararı yazılana dek ertelenir; sağlayıcı yoksa **fail-open** giriş | `monitoring.py` |
| **P1-4** | Eksik admin kapıları | 5 rota `_require_admin`; mutasyon-tool'ları için nazik ret (`_llm_admin_denied`) | `main.py`, `llm_chat.py` |
| **P1-5** | Oturum/güvenlik | `X-Real-IP` yalnız güvenilir proxy'den; WS `Origin` allowlist; token UA parmak izine bağlı | `security.py`, `main.py` |
| **P1-6** | read-only SQL beyaz-liste + LIMIT bypass | Tablo-başı sütun allowlist + opak/sır reddi; LIMIT koşulsuz uygulanır | `database.py` |
| **P1-7** | SSE thread sızıntısı → DB havuzu açlığı | `_poll_queue_until` (bounded `get(timeout=)`) — hiçbir işçi sonsuza dek beklemez | `llm_analysis.py` |
| **P1-8** | Borsa emir güvenilirliği | Kısmi dolum tespiti + mutabakat; idempotency anahtarlı POST retry; toz kapısı canlı fiyatla; SL/TP geri-kurma | `binance_tr_private.py`, `main.py` |
| **P1-9** | ML optimistik etiket | Regresör artık **gerçekleştirilebilir çıkış** (ufuk-sonu kapanış) ile eğitilir; `class_weight="balanced"`; FEATURE_VERSION v4 | `ml_forecast.py` |
| **P1-10** | Velocity mikro-yapı ölü | `get_snapshot(symbol=…)` gerçekten parametrik (seri/akış/defter sembole anahtarlı) | `microflow.py`, `velocity.py` |
| **P1-11** | DevOps/üretim sertleştirmesi | `SCALPER_ENV=production`; secret'lar `_env_secret` (Docker secret dosyası); alıcı/trade varsayılan KAPALI; imajlar non-root; DDL 30s kilit + geçici-hatada retry; migration glob parite | `config.py`, `docker-compose.yaml`, `Dockerfile`, `scripts/run_postgres_migration.py` |

---

## P2 — Orta (13/13 düzeltildi)

| # | Bulgu | Düzeltme |
|---|-------|----------|
| **P2-1** | Trailing/BE üst-sınır koruması yok | DB `UPDATE` yalnız `(col IS NULL OR col <= ?)` ile yazar; aksi halde `False` |
| **P2-2** | `TP_PRIMARY_ENABLED=false` → TP çıkışı ölü | Varsayılan `true` (kanıta dayalı), DB ile ezilebilir |
| **P2-3** | Dedup açık pozisyondayken TP yükseltmeyi engelliyor | Dedup yalnız YENİ girişte çalışır (`open_trade is None`) |
| **P2-4** | Cooldown'lar yalnız bellekte; SL `breakeven_stop`'u kapsamıyor | Cooldown'lar DB'ye persist/restore; `breakeven_stop` SL ailesine eklendi |
| **P2-5** | `reconcile` geçerli pozisyonu model varsayımıyla siliyor | Silme yalnız **gerçek rakamlarla** gerekçelenir; preview/apply parite |
| **P2-6** | Yedek/geri-yükleme karşılıklı dışlama yok | Paylaşılan `_backup_restore_lock` (409 + serileştirme) |
| **P2-7** | Tek varsayılan executor → `PoolTimeout` | P1-7 thread sızıntısı giderildi (havuz artık pinlenmiyor) |
| **P2-8** | ws_broadcast istemci yokken/değişmeden yeniden serileştiriyor | Ucuz imza + istemci kontrolü; ilk kare garantisi |
| **P2-9** | Frontend K/Z ve rozet tutarsızlıkları | SHORT işareti; `canli` rozeti bayatlayabiliyor; `mtfBadge` render; stale closure |
| **P2-10** | Test kalitesi | 4 no-op silindi; 7 kaynak-metni testi davranışsal yapıldı; `conftest.py`; CI'ya `npm test` sert kapısı |
| **P2-11** | Köprü replay koruması yok | `event_id` dedup (TTL+cap), saat-kayması reddi, `force` min-aralık |
| **P2-12** | Yedek aynı diskte; doküman yanlış komut | Doküman `pg_restore`'a düzeltildi (off-disk + alarm operatör kararı) |
| **P2-13** | Bakiye push döngüsü ölü anahtar/modül okuyor | `user_binance_keys` + `llm_analysis.decrypt_key`; admin-olmayan kullanıcılar dahil |

---

## Koordinatörün Ek Doğrulama Sırasında Bulup Düzelttiği İki Sorun

Bu ikisi denetim raporunda YOKTU; düzeltmeleri doğrularken çıktı:

1. **`BinanceTrPartialFillError` yakalanmıyordu (P1-8'in ikinci yarısı).**
   `place_market_sell` kısmi dolumda raise ediyordu ama tek üretim çağıranı
   (`/api/binance/sell`) tüm istisnaları genel 502'ye çeviriyordu → kısmi dolum
   "emir gönderilemedi" sanılıyor, `.result`/`remaining_qty` atılıyor, satılan
   kısım kullanıcıya bildirilmiyor ve maliyet-cache invalidation + audit atlanıyordu.
   **Düzeltme:** `main.py` — `except BinanceTrPartialFillError` dalı; kalan miktar
   `reconcile_sell_fill` ile tek MARKET SELL'de mutabık kılınır, gerçek dolum raporlanır.

2. **P0-3 düzeltmesi yarımdı.** DB ajanı yalnız iki çağrı yerini güncellemiş; kalan
   6 açık-pozisyon okuması varsayılan `True`'da kalmıştı (MACD çıkış takibi,
   düşen/pasif-sembol kapatma, panel listesi, LLM görünürlüğü). **Düzeltme:**
   hepsi `apply_reports_baseline=False` geçecek şekilde tamamlandı.

---

## Doğrulama (dondurulmuş ağaç)

- **Backend test paketi:** `pytest tests -q` → **exit 0, tam yeşil** (~1.818 test).
- **Lint (CI sert kapısı):** `ruff check app tests scripts` → **All checks passed**.
- **Derleme:** `compileall app` → OK.
- **Frontend:** `tsc --noEmit` → exit 0; `npm test` → **74/74 geçti**.
- **Süpürme:** Tüm `getattr(config, X, <literal>)` çağrıları gerçek config'e karşı
  denetlendi — orijinal P0-1 sınıfı (yanlış öznitelik adı → sessiz fallback) kalmadı.

---

## Operatör Kararına Bırakılanlar (kod dışı)

Bunlar bilinçli olarak DEĞİŞTİRİLMEDİ (politika/ürün kararı):

1. **87 kullanılmayan `backend/scripts/*.py` betiği.** `scripts/README.md` bunların
   "tarihsel kayıt olarak saklandığını ve silmenin kullanıcı onayı gerektirdiğini"
   belgeliyor. Silme/arşivleme sizin kararınız.
2. **Yedeklerin off-disk'e taşınması + başarısızlıkta alarm** (retention=2 aynı diskte).
   S3/NFS hedefi ve izleme entegrasyonu altyapı kararı.
3. **Git geçmişi küçültme** (~333 MB `.git`; büyük kısmı geçmişte commitlenmiş
   `work/**/node_modules`). `git filter-repo` + force-push tüm klonların
   yeniden çekilmesini gerektirir → koordineli, sizin onayınızla yapılmalı.

---

## Değişen Dosyalar

**Backend (`app/`):** `main.py`, `config.py`, `database.py`, `security.py`,
`binance_tr_private.py`, `tr_bridge_receiver.py`, `llm_analysis.py`, `ml_forecast.py`,
`microflow.py`, `routers/{monitoring,auto_paper,velocity,runtime,llm_chat,macd_monitor,reports}.py`

**Testler:** `conftest.py` (yeni), `test_p1_authz_guards.py`, `test_p1_9_target_label.py`,
`test_p1_10_microflow_symbol_snapshot.py`, `test_receiver_safe_defaults.py` (yeni);
`test_{auto_paper,portfolio_reset_archiving,rising_wiring,radar_unified_wiring,discovery_pulse,chat_quick_lane,regressions,ws_live_candles,w18_runtime_residual,binance_tr_private,tr_bridge_receiver,ml_feature_parity}.py` (düzenlendi)

**Frontend:** `app/{binance-tr/page,chat/page,charts/page,monitoring/page}.tsx`,
`app/binance-tr/BinancePositionChartModal.tsx`, `app/settings/ChatSettingsPanel.tsx`,
`app/technical-charts/MultiChartCard.tsx`, `app/lib/pnl.{ts,test.ts}`

**Altyapı:** `docker-compose.yaml`, `backend/Dockerfile`, `frontend/Dockerfile`,
`nginx/Dockerfile`, `.env.example`, `.gitignore`, `backend/requirements-dev.txt`,
`backend/scripts/run_postgres_migration.py`, `.github/workflows/backend-tests.yml`
