# TESTLER — Güncel Test Koşumu ve Kalite Kapısı

> **2026-09-26 denetimi ile eklendi (bulgu #110).** Bu dosya tarihsel olarak bir
> PUMP araştırma raporuydu ve **güncel test koşma komutunu içermiyordu**. Aşağıdaki
> bölüm test tabanının güncel durumunu tanımlar; PUMP araştırma
> içeriği `docs/research/TESTLER_PUMP_ARASTIRMASI.md` dosyasına taşınmıştır.
>
> **2026-10-07 düzeltmesi:** Önceki tabloda "Frontend test dosyası | 0 (vitest yok)"
> yazıyordu — bu **yanlıştı**. Frontend'de vitest kuruludur (`frontend/vitest.config.ts`,
> `frontend/package.json` → `"test": "vitest run"`) ve 3 dosyadaki **67 test geçer**.
> Backend sayıları da güncellendi: **113** test dosyası, **1713** toplanan test.

## Güncel Durum (2026-10-07)

| Metrik | Değer |
| --- | --- |
| Backend test dosyası | **113** |
| Toplanan test | **1713** (`pytest --collect-only`) |
| Kapsama (coverage) | **%57** (`pytest --cov=app`) — CI eşiği `%55` |
| Frontend test dosyası | **3** (vitest) — **67 test geçiyor** |
| CI hedef Python | 3.11 (üretim) + 3.13 (uyumluluk) |

## Güncel Koşma Komutları

```powershell
# Tüm backend testleri
cd D:\scalperagent_v4\backend
.\venv\Scripts\python.exe -m pytest tests -q

# Coverage ile (CI'daki komut)
python -m pytest tests -q --cov=app --cov-report=term-missing --cov-report=xml --cov-fail-under=55

# Lint — SERT KAPI (gerçek hata sınıfları: E9, F821, F811, F823)
cd D:\scalperagent_v4\backend
ruff check app tests scripts

# Lint — danışma (geniş kural kümesi, kapı DEĞİLDİR)
ruff check --select E,F,W,I,B,SIM,UP --output-format=concise app tests scripts

# Biçim kontrolü — danışma (kapı DEĞİLDİR)
ruff format --check app tests scripts

# Frontend testleri (vitest; 3 dosyada 67 test)
cd D:\scalperagent_v4\frontend
npm test            # eşdeğeri: npx vitest run

# Frontend lint (frontend; CI job: frontend-lint)
npm run lint
```

Yapılandırma: `backend/ruff.toml` (kural kümesi), `backend/pytest.ini` (zaman aşımı), `backend/requirements-dev.txt` (pinned araçlar), `frontend/vitest.config.ts` (vitest kapsamı — `app/lib/*.test.ts` ve `app/charts/*.test.ts` altındaki saf matematik modülleri).

## Test Zaman Aşımı

`backend/pytest.ini` her test için **120 saniye** üst sınır koyar
(`pytest-timeout`, `timeout_method = thread`). Bu olmadan sonsuza kadar
bekleyen bir test CI işini job-timeout'a kadar asılı tutar ve nedeni görünmez.
Tek test için geçersiz kılmak isterseniz:

```powershell
python -m pytest tests/<dosya>.py -q --timeout=0
```

## Ortam Gereksinimleri

CI, üretimle **aynı** PostgreSQL imajını kullanır (`pgvector/pgvector:pg17-bookworm`)
ve şu ortam değişkenlerini bekler:

```
DATABASE_URL=postgresql://scalper:scalper@localhost:5432/scalper
DB_BACKEND=postgres
```

Yerelde Docker yoksa `pytest` yalnız saf birim testlerini koşar; DB'ye bağlanan
testler atlanır veya hata verir.

## Tarihsel Araştırma

2026-08-30/31 PUMP araştırma raporu (≥%2 M5 pump desenleri, OOS doğrulama, maliyet
simülasyonu, v2 aday filtresi) bu dosyadan taşındı:
[`docs/research/TESTLER_PUMP_ARASTIRMASI.md`](docs/research/TESTLER_PUMP_ARASTIRMASI.md).
