# Proje İnceleme & Analiz Raporu — 2026-11-10

Kapsam: `backend/` (FastAPI + Python), `frontend/` (Next.js), CI/lint/test altyapısı, README/test senkronu.
Yöntem: Tam test suite çalıştırması, `ruff check` sert kapısı, statik AST taraması, kaynak okuma.

## Özet

| Alan | Önce | Sonra |
|---|---|---|
| Backend test sonucu | 9 FAIL / 3606 pass | **0 FAIL / 3630 pass** ✅ |
| `ruff check` sert kapısı (CI) | **7 hata → CI KIRIK** | **All checks passed** ✅ |
| Üretim kodu gerçek hata | 1 (F821 NameError) | Giderildi ✅ |
| Python 3.11 uyum (üretim) | 2 script syntax hatası | Giderildi ✅ |

## Bulunan ve düzeltilen GERÇEK HATALAR

### 1. P0 — `auto_paper.py` üretim kodunda NameError (F821)
**Dosya:** `backend/app/routers/auto_paper.py` (`_try_open_impl`)

PPO/RL uyarlama bloğunda, henüz tanımlanmamış `effective_sl_pct` değişkeni
kullanılıyordu (tanımı ~88 satır sonra). Sonuç: her pozisyon açılışında
`NameError` fırlıyor, geniş `except Exception` bunu **sessizce yutuyordu**.

**Etki:** PPO/RL adaptasyonu (TP/SL kalibrasyonu, pozisyon boyutu çarpanı)
fiilen **tamamen ölüydü** — hiç çalışmıyordu ve kimse fark etmiyordu. Ayrıca
CI'da `ruff` F821 sert kapısı bu satırı yakaladığı için **CI kırmızıydı**,
yani bu hata deploy hattını da bloke ediyordu.

**Düzeltme:** PPO bloğu güncel `sl_pct`'i volatilite girdisi olarak kullanır;
PPO'nun SL önerisi ATR korumasından sonra ayrı bir değişkende birleştirilir ve
**yalnız kullanıcı planı/profili yokken** devreye girer. PPO stopu yalnızca
genişletir, asla daraltmaz (erken stop önlemi). `test_auto_paper.py` +
`test_ai_trading_suite.py` yeşil.

### 2. P1 — Python 3.11 söz dizimi ihlalleri (üretim çökme riski)
**Dosyalar:** `backend/scripts/ta_n6_replay.py`, `backend/scripts/ta_screen_backtest.py`

Üretim konteyneri `python:3.11-slim`. Bu iki scriptte PEP 701 (3.12+) iç içe
f-string tırnakları vardı → 3.11'de `SyntaxError`. Bunlar script olduğu için
backend import'unu kırmaz, ama `test_py311_fstring_guard.py` CI kapısını
kırmızıya çekiyordu ve ileride üretimde bir job bunları çağırırsa çöker.
**Düzeltme:** iç içe f-string'ler `format(...)` + yardımcı deyimlere çevrildi.

## Test tarafı düzeltmeleri (kaynak kod doğruydu, testler kırılgandı)

- **`test_p1_9_target_label.py`**: `joblib.dump` mock'u dosya yaratmıyordu;
  üretim kodu artık atomik yazım için `.tmp` + `os.replace` yapıyor →
  `FileNotFoundError`. Mock gerçek dosya oluşturacak şekilde düzeltildi.
- **`test_velocity_ml_backfill.py`**: `get_velocity_candidates_missing_ml(limit=200000)`
  en eski 200k satırı getirir; yerel/CI DB'sinde 575.587 aday olduğu için yeni
  test satırı listeye hiç girmiyordu (yanlış negatif). Test doğrudan
  `candidate_id` ile doğrulayacak şekilde düzeltildi (kendi yorumunun niyeti).
- **`test_readme_router_table.py`**: "modül sayısı == include_router sayısı"
  varsayımı yanlıştı — `ai_trading_suite_routes.py` iki router (`router` +
  `router_alias`) tanımlayıp iki kez kaydediliyor. Doğru değişmez
  (include_router ≥ modül sayısı) kullanılacak şekilde düzeltildi.
- **`README.md`**: router tablosu gerçekle senkronlandı (21 modül, 18 APIRouter,
  19 include_router; `n7_scan.py` ve `ai_trading_suite_routes.py` eklendi).

## GELİŞTİRİLMESİ GEREKEN ALANLAR (henüz dokunulmadı)

### A. Sessiz hata yutma — `except ...: pass`
Para/pozisyon yollarında (`analyzer`, `auto_paper`, `monitoring`, `velocity`,
`binance_tr_private`) geniş `except: pass` blokları hataları görünmez kılıyor.
Bu rapordaki F821 hatasının yıllarca fark edilmemesinin **kök nedeni** budur.

**Durum (2026-11-10):** En kritik 9 blok `logger.debug(..., exc_info=True)`'ya
çevrildi (toplam ~112 → 103). Değişenler:
- `analyzer.py`: hacim oranı, volume_ratio adayı, max/min fiyat güncellemesi (3)
- `auto_paper.py`: engel-kararı logu, MACD MTF kompakt, trade WS yayını (3)
- `monitoring.py`: daily_rising outcome, user_watchlist outcome, quiet_hours
  kontrolü (finansal etkili, fail-open ama artık görünür) (3)

**Kalan 103 blok bilinçli best-effort** (opsiyonel zenginleştirme, tip dönüşümü
guard'ı, WS yayını). Bunları da log yapmak log gürültüsü üretir; istenirse en
az `logger.debug` bırakılabilir. Öneri: yeni kodda `except: pass` CI'da
`flake8-bugbear` B110/B112 kuralı ile yasaklanabilir.

### B. Dev fonksiyonlar (bakım maliyeti)
- `app/analyzer.py::_open_position_unlocked` — 488 satır
- `app/routers/auto_paper.py::_try_open_impl` — 470 satır
- `app/routers/auto_paper.py::_manage_single_trade` — 404 satır
- `app/routers/monitoring.py::_notify` — 332 satır / `report_notifications` — 337 satır
Bu fonksiyonlar tek sorumluluk ilkesini ihlal ediyor; her değişiklikte regresyon
riski yüksek. Parçalama (ör. `_try_open_impl` → sizing / risk-kapıları / exit-plan
/ bildirim olarak ayrı fonksiyonlar) önerilir. Bu proje için `code-simplification`
ve `incremental-implementation` becerileri uygun.

### C. Test suite süresi — ~257 sn
En yavaş tekil testler 5-21 sn (radar/auto_paper ağır setup). CI'da da aynı.
**Öneri:** `pytest-xdist` (`-n auto`) ile paralelleştirme; ağ/DB fixture'larını
paylaşılan `conftest.py`'ye taşıma. Suite şu an ~250 sn, xdist ile ~60-90 sn'ye inebilir.

### D. Ruff kapısı dar
`ruff.toml` yalnız E9/F821/F811/F823'ü sert kapı yapıyor. Gerçek kod hatası
sınıfları (F401/F841 dışındakiler, ör. F811 zaten açık) genişletilebilir; ayrıca
`B` (bugbear) seçilip E501 hariç tutulabilir — bu sınıf sessiz hata avında değerli.

### E. Frontend doğrulaması
Bu turda frontend `typecheck`/`lint`/`test` çalıştırılmadı (zaman). `npm run
typecheck && npm run lint && npm test` ayrıca koşulmalı; değişiklikler backend
ağırlıklı olduğu için regresyon beklenmiyor.

## Doğrulama
- `ruff check app tests scripts` → **All checks passed**
- `pytest tests` → **3630 passed, 122 subtests passed, 0 failed (~257 sn)**
- Değişen dosyalar: `README.md`, `backend/app/routers/auto_paper.py`,
  `backend/scripts/ta_n6_replay.py`, `backend/scripts/ta_screen_backtest.py`,
  3 test dosyası.
