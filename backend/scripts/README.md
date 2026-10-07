# backend/scripts/ — Envanter

> **2026-10-07: Araştırma betikleri SİLİNDİ.** 2026-09-26 denetiminde işaretlenen
> ~88 kullanılmayan araştırma betiği ile `pump24/` ve `m5_all_flow/` alt
> dizinleri, ürün sahibinin onayıyla (2026-10-07) kaldırıldı. Geriye **yalnızca
> kalıcı bağımlılık olan 5 betik** kaldı. Silinen betikler git geçmişinden de
> temizlendi (`git filter-repo`); başka bir kopyada hâlâ varsa
> `git log --all -- backend/scripts/<ad>.py` ile bulunabilir.

## Dizin içeriği (2026-10-07)

| Kategori | Adet | Git durumu |
| --- | --- | --- |
| **Çalışan Python betiği** | **5** | `backend/scripts/*.py` |
| README | 1 | `backend/scripts/README.md` |
| Replay çıktısı (JSON) | ~108 | `.gitignore`'da (üretilen veri) |
| Alt dizin (`pump24/`, `m5_all_flow/`) | **0** | silindi |

> Silinen betikler: `analyze_*`, `audit_*`, `replay_*`, `research_*`,
> `run_exit_profile_backtests.py`, `run_historical_backtests.py`,
> `strategy_research_agent.py`, `vectorbt_research.py` vb. Bunların çıktısı olan
> JSON dosyaları `.gitignore`'dadır ve listede kalır; istenirse ayrıca
> temizlenebilir.

## 1. KALICI BAĞIMLILIK (5 betik) — silinmemeli

Bu beş betik **çalışma zamanında veya testte fiilen çağrılır**. Kaldırılırsa
üretim ya da test kırılır.

| Betik | Çağıran | Kanıt |
| --- | --- | --- |
| `run_postgres_migration.py` | `backend/entrypoint.sh` (satır 15) | **her konteyner açılışında** şemayı uygular |
| `run_portfolio_backtest.py` | `tests/test_regressions.py` | satır 66/82/96 — `pine_profile`, `rows_to_series`, `load_market` içe aktarılır |
| `combined_radar_replay_24h.py` | `app/routers/maintenance.py` (satır 673) | `importlib.util.spec_from_file_location` ile **çalışma zamanında** yüklenir |
| `research_m1_spikes_all_symbols.py` | `app/pattern_research.py` (satır 124) | `subprocess` ile çağrılır |
| `migrate_sqlite_to_postgres.py` | `tests/test_secondary_behavior.py` (satır 17-18) | varlığı ve içeriği doğrulanır |

### `run_postgres_migration.py` hakkında önemli not (2026-09-26 düzeltmesi)

Bu betik iki ayrı kaynaktan şema okuyordu ve `app/database.py`'in `init_db()`
fonksiyonu ile **farklı bir dosya listesi** kullanıyordu (denetim #72).
Entrypoint her açılışta 001+002'nin sha'sını yazıyor, `init_db()` ise beş
dosyanın tamamını yeniden DDL olarak koşuyordu → her restart tam DDL + ACCESS
EXCLUSIVE kilit yarışı, ve `004_bloat_prevention.sql` / `005_user_binance_keys.sql`
**yalnızca ikinci yolda** oluşuyordu.

**Düzeltildi:** Artık her iki yol da `migrations/` dizinini **glob ile aynı
sıraya** tarar ve birebir aynı sha'yı üretir. Yeni migration eklendiğinde
**hiçbir Python dosyası güncellenmez** — glob kendiliğinden yakalar.

## 2. Silinen araştırma artığı (arşiv notu)

2026-09-26 denetimi (`docs/SISTEM_DENETIMI_2026-09-26.md` §6) bu dizinde 93
Python betiğinden yalnızca 5'inin kullanıldığını tespit etmiş, silmeyi
"ürün kararı" olarak ertelemişti. **2026-10-07'de silme kararı uygulandı.**

Silinenler üç kategorideydi:
- **2a.** `docs/` altındaki CSV/SQL çıktılarını üreten replay/tarama betikleri
  (`combined_radar_replay_24h.py` hariç — o kalıcı).
- **2b.** Tek seferlik strateji araştırması (`replay_*`, `pump24_*`,
  `research_*`) — çoğu artık `config.py`'de bulunmayan sabitlere erişiyordu.
- **2c.** Manuel operasyon yardımcıları (`purge_*`, `cleanup_*`, `show_*`,
  `analyze_*`).

## İlgili belgeler

- [`../../docs/ARTEFAKTLAR.md`](../../docs/ARTEFAKTLAR.md) — bu dizinin ürettiği CSV/SQL çıktıları
- [`../../docs/SISTEM_DENETIMI_2026-09-26.md`](../../docs/SISTEM_DENETIMI_2026-09-26.md) — denetim raporu
- [`../../README.md`](../../README.md) — genel bakış
