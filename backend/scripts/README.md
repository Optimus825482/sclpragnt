# backend/scripts/ — Envanter

> **2026-09-26 denetimi ile eklendi.** Denetim raporu (§6 "Ölü kod / ölü ayar"):
> "`backend/scripts/` — 118 dosya, 5'i testler/üretim tarafından kullanılıyor
> … ~113 ölü."
>
> Bu README, hangi script'in **kalıcı bağımlılık** olduğunu, kalanların ne
> olduğunu ve neden silinmediğini belgeler.
>
> **Ölü script'ler SİLİNMEDİ.** Denetim bunları silmeyi önerdi (Faz 5, madde
> 29: "3 üretim bağımlısını `backend/tools/`'a taşı, ~113 ölü dosyayı sil"),
> ancak bu bir **ürün kararıdır** ve kullanıcının onayı gerekir. Silme
> kararını bırakılmıştır.

## Dizin içeriği (2026-09-26)

| Kategori | Adet | Git durumu |
| --- | --- | --- |
| Python script | 93 | `backend/scripts/*.py` |
| JSON araştırma çıktısı | 108 | `.gitignore`'da (satır 24) |
| Log dosyası | 27 | `.gitignore`'da (satır 26) |
| Alt dizin (`pump24/`, `m5_all_flow/`, `__pycache__/`) | 3 | — |
| **Toplam girdi** | **231** | |

> **Not:** Denetim "118 dosya" derken `ls | wc -l` ile JSON çıktılarını da
> saymıştı. Gerçek **Python script sayısı 93**'tür. Kalan ~113 "ölü" ifadesi
> bu nedenle 93 - 5 = 88 olarak okunmalıdır.

## 1. KALICI BAĞIMLILIK (5 script) — silinmemeli

Bu beş script **çalışma zamanında veya testte fiilen çağrılır**. Kaldırılırsa
üretim ya da test kırılır.

| Script | Çağıran | Kanıt (satır) |
| --- | --- | --- |
| `run_postgres_migration.py` | `backend/entrypoint.sh` | satır 15 — **her konteyner açılışında** şemayı uygular |
| `run_portfolio_backtest.py` | Testler | `tests/test_regressions.py:66,82,96` — `pine_profile`, `rows_to_series`, `load_market` içe aktarılıyor |
| `combined_radar_replay_24h.py` | `app/routers/maintenance.py` | satır 640-641 — `importlib.util.spec_from_file_location` ile **çalışma zamanında** yükleniyor |
| `research_m1_spikes_all_symbols.py` | `app/pattern_research.py` | satır 124 — `subprocess` ile çağrılıyor |
| `migrate_sqlite_to_postgres.py` | Testler | `tests/test_secondary_behavior.py:17-18` — varlığı ve içeriği doğrulanıyor |

### `run_postgres_migration.py` hakkında önemli not (2026-09-26 düzeltmesi)

Bu script iki ayrı kaynaktan şema okuyordu ve `app/database.py`'in `init_db()`
fonksiyonu ile **farklı bir dosya listesi** kullanıyordu (denetim #72).
Entrypoint her açılışta 001+002'nin sha'sını yazıyor, `init_db()` ise beş
dosyanın tamamını yeniden DDL olarak koşuyordu → her restart tam DDL + ACCESS
EXCLUSIVE kilit yarışı, ve `004_bloat_prevention.sql` / `005_user_binance_keys.sql`
**yalnızca ikinci yolda** oluşuyordu.

**Düzeltildi:** Artık her iki yol da `migrations/` dizinini **glob ile aynı
sıraya** tarar ve birebir aynı sha'yı üretir. Doğrulandı:

```
script sha: fc9d0ac4adf1117b6f9092269cb6b8a005d52d9339f197917760c03a3d3aac9c
db.py  sha: fc9d0ac4adf1117b6f9092269cb6b8a005d52d9339f197917760c03a3d3aac9c
SQL IDENTICAL: True
```

Yeni migration eklendiğinde **hiçbir Python dosyası güncellenmez** — glob
kendiliğinden yakalar.

## 2. ARAŞTIRMA ARTAĞI (~88 script) — silinmedi, bakım dışı

Bu script'ler **hiçbir yerden çağrılmıyor**. Üç kategoride:

### 2a. Çıktısı `docs/` altındaki CSV'lere giden replay/tarama script'leri

`combined_radar_replay_24h.py` dışındaki tüm `birlesik-radar-*.csv` ve
`analysis_snapshots (2).sql` / `velocity_candidates (2).sql` / `monitoring_notifications.sql`
dosyalarını üreten script'ler. Envanter için bkz. [`../../docs/ARTEFAKTLAR.md`](../../docs/ARTEFAKTLAR.md).

### 2b. Tek seferlik strateji araştırması

`replay_*.py`, `pump24_*.py`, `research_m1_*.py` vb. Çoğu `config.py`'de artık
**var olmayan** sabitlere (`config.BB_MFI_*`, `config.SMA_CASCADE_*`,
`config.ACTIVE_STRATEGY`, `config.BACKTEST_ASSUMED_SPREAD_PCT`) erişir ve
çalıştırıldığında `AttributeError` verir. Bunlar **tarihsel kayıt olarak
anlamlıdır** — hangi stratejinin neden test edildiğini gösterir.

### 2c. Operasyonel yardımcılar (manuel çalıştırılır)

`purge_*.py`, `cleanup_*.py`, `show_*.py`, `analyze_*.py` gibi tek seferlik
operasyon script'leri. Bunlar otomatik çağrılmaz ama bir operasyonda **manuel**
gerekebilir (veri temizliği, smoke kontrolü). Silinmeden önce operasyon
ekibiyle teyit edilmelidir.

## 3. Silme kararı — neden uygulanmadı

Denetimin Faz 5 / madde 29'u "3 üretim bağımlısını `backend/tools/`'a taşı,
~113 ölü dosyayı sil" diyor. **Bu uygulanmadı**, çünkü:

1. **Karar kullanıcının.** Araştırma geçmişi silinmez; bazı script'ler
   gelecekte yeniden yazılan stratejiler için referans.
2. **Risk.** Bazıları "çağrılmıyor" görünse de `pattern_research.py:124` gibi
   **dinamik** subprocess yolları grep'te görünmez.
3. **Ayrıştırma kararı ayrı bir iş.** `backend/tools/` altına taşımak, 3
   script'in import yollarını ve `entrypoint.sh`'i değiştirir — ayrı bir
   değişiklik paketi, ayrı test turu gerektirir.

### Önerilen sonraki adım (onay gerektirir)

1. Önce 2a ve 2b kategorilerini ayır (2 operasyonel olan 2c'de kalır).
2. 2a/2b'yi `git rm` ile sil veya `archive/` altına taşı.
3. `run_postgres_migration.py` + `combined_radar_replay_24h.py` +
   `research_m1_spikes_all_symbols.py`'i `backend/tools/`'a taşı ve
   çağıran 3 yolu güncelle.
4. Her adımdan sonra `pytest` + `entrypoint.sh` smoke testi.

## İlgili belgeler

- [`../../docs/ARTEFAKTLAR.md`](../../docs/ARTEFAKTLAR.md) — bu dizinin ürettiği CSV/SQL çıktıları
- [`../../docs/SISTEM_DENETIMI_2026-09-26.md`](../../docs/SISTEM_DENETIMI_2026-09-26.md) — denetim raporu
- [`../../README.md`](../../README.md) — genel bakış
