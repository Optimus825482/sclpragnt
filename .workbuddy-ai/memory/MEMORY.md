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

## Dikkat

- Araştırma betikleri (`backend/scripts`, `backend/work`) **silinmez** — kullanıcının
  kanıta dayalı araştırma araçlarıdır ve korunur.
