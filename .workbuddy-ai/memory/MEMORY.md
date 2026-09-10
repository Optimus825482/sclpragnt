# Scalper Agent V4 — Kalıcı Proje Notları

Kalıcı (oturumlar arası) proje kuralları ve mimari kararlar. Günlük iş kaydı için
`YYYY-MM-DD.md` dosyalarına bakın.

## Değişmez kurallar / sözleşmeler

- **Paper-only.** Tüm çalışma sanal cüzdanladır; gerçek emir yolu yoktur. Strateji
  değişiklikleri OOS kanıtı olmadan aktive edilmez.
- **Renk anlamı:** YEŞİL = kâr, KIRMIZI = zarar. `null`/`NaN` **nötr**
  (`text-bunker-muted`) — asla yeşile/kırmızıya boyanmaz.
- **Gösterge tanımları tek kanonik kaynak:** `app/technical_analysis.py`
  (`_rsi` = Wilder, `_aroon` = high/low + `period+1` pencere + **son-tekrar
  tie-break**, `_linreg_slope_pct` = 10-bar yüzde). `ml_forecast.py` ve
  `routers/velocity.py` bunları import etmeli; kendi kopyalarını üretmemeli.
- **Özellik sürümleme:** gösterge tanımı/özellik şekli değişirse
  `ml_forecast.FEATURE_VERSION` artırılır (bayat artifact'lar geçersiz olsun).
- **Geç bağlama:** router→main fonksiyon bağlama **yalnızca**
  `app/runtime_deps.py` üzerinden (`pending_dep` + `bind`). `startup_services()`
  ilk satırı `runtime_deps.assert_ready()`. Router global'leri monkeypatch
  EDİLMEZ.
- **Okuma yolu saftır:** `database.load_*` / `get_*` DB'ye yazmaz. Tek seferlik
  backfill işleri ayrı fonksiyon + `init_db()` çağrısı (ör.
  `backfill_position_trade_ids`).
- **Birim sözleşmesi:** dışa açılan `*_pct` alanları **yüzde**, iç hesap **kesir**
  (`_ratio_from_pct`).

## Aktif otonom döngüler

- `routers/velocity.py::autonomous_velocity_loop` — **AKTİF** (2026-09-10,
  kullanıcı kararı). `main.py::startup_services()` içinde
  `_start_background(autonomous_velocity_loop, "velocity-autonomous")`.
  Çift kilit: `VELOCITY_AUTO_ENABLED` (env=.env'de true) **ve**
  `llm_paper_trade_enabled` (DB=1) — ikisi de açık olmalı. Kapı her turda
  yeniden okunur → ayar değişimi restart gerektirmez. Paper-only.
  Kapatma: env'i false yap **veya** DB ayarını 0 yap.
  `/api/velocity/status` → `auto_enabled` (ayar) ve `loop_running` (fiilen
  başlatıldı mı) ayrı raporlanır.
- Kablolama koruması: `tests/test_loop_wiring.py` — `app/` altındaki her
  `*_loop` tanımı ya `main.py`'de geçmeli ya modülünde `create_task` ile
  başlatılmalı. Yeni döngü eklerken bu test kırılırsa wiring unutulmuş demektir.

## Bilinçli olarak bağlanmamış kancalar (çağıranı yok, silinmedi)

- `routers/runtime.py::invalidate_wallet_caches` (TTL=3sn olduğu için bayatlık
  sınırlı), `_ma_cascade_observation_context`,
  `routers/maintenance.py::_persist_replay_parity_observation` — işaretlendi.

## Komutlar

- Backend test: `backend/venv/Scripts/python.exe -m pytest tests/ -q`
- Tip denetimi: `frontend` içinde `npx tsc --noEmit`
- Derleme kontrolü: `python -m py_compile <dosyalar>`

## MACD MONITOR — bilinen tasarım özellikleri / açık kararlar

Denetim raporu: `outputs/macd_monitor_denetim_raporu.md` (2026-09-10). Modül:
`routers/macd_monitor.py` (döngü + `GET /api/macd-monitor` + ayar ucu), beslediği paneller:
`/macd-monitor` ve `/monitoring` (YÜKSELİŞ EĞİLİMİ ADAYLARI, SIRÇRAMA ADAYLARI).

- **Trend gücü göreceli ve yönsüzdür ve bu KANITLA DOĞRUDUR.** `strength` 0-10, evren-içi min-max ile
  normalize edilir (`_strength_meta`) ve hız `abs(slope)/bar_aralığı` olduğundan **yön içermez**.
  OOS/replay (312 sembol · 571.980 gözlem) yönlü formülün bu evrende **contrarian** olduğunu gösterdi
  (IC −0.049, t −23.8 @30m) → yön skora EKLENMEZ. `dir` alanı yalnızca tanımlayıcıdır, skora girmez.
  `monitoring/page.tsx` `RISING_MIN_STRENGTH=9.8` "evren maksimumu"nu seçer; bu davranış korundu.
- **Tazelik (C1 ile düzeltildi):** M3/M30 serileri WS aboneliğinde değildir, `market.refresh_series()`
  ile REST'ten tazelenir (3m≈75sn, 30m≈1860sn). Artık tazelenen `(sym,tf)` hücreleri fiyat değişmese
  de yeniden hesaplanır (`refreshed` kümesi + `_bar_marker` yeni-bar kapısı).
- **Alarm cooldown'ları ayrıdır:** jump (`_jump_alerted_at`) ve erken (`_early_alerted_at`),
  ikisi de 30 dk sabitini kullanır ama birbirini bloke etmez.
- **Kanıt katmanı VAR (C3):** `macd_monitor_alerts` tablosu; her alarm sinyal imzası + fiyatla kaydedilir,
  5m/15m/30m ileri getirisi doldurulur (`macd_evidence_loop`, ~2 dk). `GET /api/macd-monitor/alerts`.
  UI: MACD MONITOR sayfasında "ALARM GEÇMİŞİ & İSABET" paneli. **Eşik/ağırlık ayarı yalnızca bu
  kanıtla yapılır** — sezgiyle veya kısmi modellerle DEĞİL.
- **Performans:** `_trend_cache` (B8) değişmeyen sembolde trend/sinyal hesabını atlar;
  `macd_monitor_delta` WS mesajı (B9) yalnız değişen sembolleri yayınlar, her 5. pass'ta tam yayın.
- **MACD snapshot'ın İKİ tüketicisi vardır:** `/macd-monitor` ve `/monitoring` (YÜKSELİŞ/SIRÇAAMA panelleri).
  Yeni bir WS mesaj tipi eklerken **ikisini de** güncelle — B9'da yalnız biri güncellendiği için
  `/monitoring` sessizce ~1 sn → ~5 sn'ye yavaşladı. Birleştirme tek kaynaktan:
  `frontend/app/lib/macdSnapshot.ts` → `mergeMacdDelta`.
- **Kararlar (2026-09-10, kullanıcı onayı):** C1/C3 uygulandı; C2 kanıt sonrası → yön eklenmedi,
  eşik/ağırlık DEĞİŞMEDİ; B6 histerezis + B8/B9 uygulandı. Kanıt: `outputs/macd_monitor_replay_kanit.md`.

## Dikkat

- Araştırma betikleri (`backend/scripts`, `backend/work`) **silinmez** — kullanıcının
  kanıta dayalı araştırma araçlarıdır ve korunur.
