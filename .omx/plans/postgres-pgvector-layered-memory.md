# PostgreSQL + pgvector ve Katmanlı LLM Hafızası Uygulama Planı

## Amaç

Paper-trading sistemindeki SQLite veri katmanını kayıpsız ve geri dönüşlü biçimde PostgreSQL'e taşımak; pgvector ile teknik snapshot, karar, işlem ve LLM bilgisini anlamsal olarak aratmak; chat/analiz modellerinden bağımsız embedding provider/model yönetimi eklemek.

Gerçek emir yürütme eklenmeyecek. Sistem Binance TR public market data ve paper trading sınırında kalacak.

## Mevcut durum ve kanıtlar

- Docker Compose'ta backend SQLite dosyasını `/data/scalper_db_v4.sqlite` olarak kullanıyor (`docker-compose.yaml:1-19`).
- SQLite bağlantısı global bağlantı + thread lock ile yönetiliyor (`backend/app/database.py:19-37`).
- LLM provider/model/skill tabloları mevcut; model kaydı şu anda chat/embedding ayrımı içermiyor (`backend/app/database.py:110-125`).
- LLM entegrasyonu OpenAI-compatible `/chat/completions` endpoint'i ve Fernet ile şifrelenmiş API key kullanıyor (`backend/app/llm_analysis.py:6-28`).
- Çalışma ağacında `llm_models` için chat/embedding ayrımı ve dimension alanları hazırlanmaya başlanmıştır; migration hedefi bu değişiklikleri resmi şemaya taşımaktır.
- Teknik analiz ve işlem giriş context'leri JSON olarak mevcut DB kayıtlarında tutuluyor; bu alanlar embedding üretiminin kaynağı olacak.

## Dış dokümantasyon bulguları

- pgvector exact search ile başlayabilir; HNSW daha iyi hız/recall dengesi sunar ancak daha fazla bellek ve daha uzun index oluşturma süresi gerektirir. Filtreli aramalarda filtre kolonlarına indeks eklenmesi ve yüksek seçicilikte partitioning öneriliyor: [pgvector README](https://github.com/pgvector/pgvector).
- pgvector resmi Docker imajları PostgreSQL 13-18 varyantlarıyla yayınlanıyor; sürüm pinlenecek, `latest` kullanılmayacak: [pgvector Docker bilgisi](https://github.com/pgvector/pgvector#docker).
- PostgreSQL `jsonb` alanları GIN indekslerle aranabilir; teknik snapshot metadata'sı JSONB olarak korunabilir: [PostgreSQL JSON types](https://www.postgresql.org/docs/17/datatype-json.html).
- Embedding modelleri çok dilli metinleri desteklemeli ve model/dimension değişimi ayrı bir embedding versiyonu olarak izlenmelidir: [OpenAI embedding models](https://developers.openai.com/api/docs/models/text-embedding-3-large).

## RALPLAN-DR özeti

### İlkeler

1. Veri kaybı olmadan ve geri dönüşlü migration.
2. Chat modeli, embedding modeli ve provider yetenekleri birbirinden ayrı.
3. LLM yalnızca paper-trading verisini okuyacak; işlem yetkisi olmayacak.
4. Her hafıza kaydının kaynağı, zamanı, modeli, boyutu ve güvenilirliği izlenebilir olacak.
5. Vector arama normal metadata filtrelerinin yerine geçmeyecek; hibrit sorgu kullanılacak.

### Karar sürücüleri

1. Üretimde güvenilirlik ve geri dönüş.
2. Filtreli arama doğruluğu ve sorgu maliyeti.
3. Provider/model değişiminde veri uyumluluğu.

### Uygulanabilir seçenekler

#### Seçenek A — PostgreSQL + pgvector, mevcut Python katmanını koruma (önerilen)

- Artı: En az davranış değişikliği; mevcut FastAPI/analyzer/LLM akışları korunur.
- Artı: Tek DB içinde ilişkisel sorgu + vector arama.
- Eksi: Async PostgreSQL driver ve migration katmanı eklenir.

#### Seçenek B — Ayrı vector database + PostgreSQL

- Artı: Vector iş yükü bağımsız ölçeklenebilir.
- Eksi: İki veri kaynağında transaction/consistency karmaşası; bu proje hacminde gereksiz operasyonel yük.

#### Seçenek C — SQLite + harici vector service

- Artı: En düşük ilk migration maliyeti.
- Eksi: Üretim verisi ve hafıza farklı sistemlerde kalır; yedekleme, filtreleme ve audit zorlaşır.

### ADR

- **Karar:** Seçenek A; PostgreSQL + pgvector, migration tamamlanana kadar SQLite fallback.
- **Sürücüler:** Tek transaction sınırı, mevcut backend akışlarını koruma, hibrit metadata/vector sorgusu.
- **Alternatifler:** Ayrı vector DB ve SQLite + harici vector service.
- **Neden:** İşlem/sinyal/karar kayıtları ilişkisel; embedding yalnızca bunların bir indeksidir. İki ayrı veri deposu bu ölçekte gereksiz tutarsızlık riski oluşturur.
- **Sonuçlar:** PostgreSQL bağlantı yönetimi, migration CLI, embedding kuyruğu ve model versiyonlama eklenir.
- **Takip:** Hacim büyürse exact-vs-HNSW recall ve sorgu p95 ölçülerek index/partition kararı yeniden değerlendirilecek.

## Uygulama adımları

### 1. PostgreSQL altyapısı ve konfigürasyon

Dosyalar: `docker-compose.yaml`, `backend/requirements.txt`, `backend/app/config.py`, yeni `backend/app/db_postgres.py`.

- PostgreSQL + pgvector imajını sürüm pinli ekle.
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL` değerlerini secret/env üzerinden al.
- Backend startup'ta bağlantı/extension/health kontrolü yap.
- SQLite fallback'i migration süresince feature flag ile koru.
- API key ve DB parolalarını loglama.

### 2. Şema ve migration altyapısı

Yeni migration dosyaları: `backend/migrations/001_postgres_schema.sql`, `002_memory_schema.sql`, `backend/scripts/migrate_sqlite_to_postgres.py`.

- `positions`, `trades`, `signals`, `decision_logs`, `llm_tool_logs`, `virtual_wallet`, `chart_settings`, `llm_providers`, `llm_models`, `llm_skills`, `llm_settings`, `backtests` tablolarını PostgreSQL'e taşı.
- Migration kaynağı önceden seçilecek: production `/data/scalper_db_v4.sqlite`, yerel SQLite veya kullanıcı yedeği. Kaynak dosya SHA-256, dosya boyutu, row count ve migration zamanı kaydedilmeden taşıma başlamayacak.
- `JSON` alanlarını `JSONB` yap; GIN metadata indexleri ekle.
- UUID/idempotency ve unique constraint kullan.
- SQLite migration'i dry-run, row-count karşılaştırması ve checksum ile doğrula.
- Migration sonunda SQLite dosyasını silme; read-only rollback kopyası oluştur.

### 3. Provider/model yetenek ayrımı

Dosyalar: `backend/app/database.py` veya yeni repository katmanı, `backend/app/main.py`, `backend/app/llm_analysis.py`, `frontend/app/settings/LlmManagement.tsx`.

`llm_models` alanları:

- `model_type`: `chat` veya `embedding`
- `dimensions`
- `embedding_metric`: `cosine`, `ip`, `l2`
- `max_input_tokens`
- `enabled`, `created_at`, `updated_at`
- `model_version`

UI sekmeleri:

- Chat Modelleri
- Embedding Modelleri
- Provider yönetimi
- Uzmanlık/skill yönetimi
- Aktif model seçimi

Embedding test endpoint'i:

- `POST /api/llm/embedding/test`
- Sağlanan kısa metinle provider'a istek atar.
- Vektör uzunluğu, süre, model ve hata mesajını döndürür.
- API key hiçbir response/log içinde dönmez.

### 4. Katmanlı hafıza şeması

Yeni tablolar:

```text
memory_documents
- id, layer, scope, symbol, strategy, timeframe
- source_type, source_id, content, metadata JSONB
- observed_at, created_at, expires_at
- embedding_model_id, embedding_dimensions, embedding_status

memory_embeddings
- memory_document_id, model_id, embedding vector(D)
- content_hash, created_at

memory_retrieval_logs
- query_scope, query_text_hash, filters JSONB
- model_id, result_ids JSONB, latency_ms, created_at
```

Katmanlar:

- `session`: mevcut chat konuşması.
- `symbol`: sembol ve timeframe teknik geçmişi.
- `strategy`: strateji, sinyal ve sonuç geçmişi.
- `trade`: giriş snapshot'ı, komisyon, PnL ve aktif süre.
- `system`: paper-trading kuralları ve veri güvenilirliği talimatları.
- `user`: yalnızca açıkça kalıcı olarak saklanmasına izin verilen tercihler.

### 5. Embedding üretim kuyruğu

Yeni dosyalar: `backend/app/embedding_service.py`, `backend/app/memory_service.py`.

- İşlem, sinyal, karar ve teknik snapshot sonrası idempotent memory document oluştur.
- `content_hash` ile aynı kaydın tekrar embedding'ini engelle.
- Dimension stratejisi: bu deployment için tek sabit dimension `2048` seçildi; farklı dimension'lı model kaydedilemez/aktif edilemez. İleride farklı dimension gerekirse ayrı embedding tablosu ve yönlendirme migration'ı yapılmadan mevcut tabloya yazılamaz.
- Provider/model değişiminde eski vector'ü silmeden yeni model versiyonu üret.
- Retry/backoff, hata durumu ve son deneme zamanı tut.
- API gecikmesi işlem/sinyal loop'unu bloklamasın; asyncio queue/worker kullan.
- Kuyruk dolduğunda paper-trading akışı durmasın; health ekranında uyarı göster.

### 6. Hibrit retrieval ve LLM entegrasyonu

Dosyalar: `backend/app/llm_analysis.py`, `backend/app/main.py`.

- Önce sembol/strateji/timeframe/tarih metadata filtreleri.
- Sonra vector cosine similarity araması.
- Güncel teknik snapshot her zaman birincil context; geçmiş hafıza yalnızca yardımcı context.
- Benzer kayıtlar kaynak ID'si ve tarih bilgisiyle LLM'e verilsin.
- Retrieval sonucu saklanıp LLM chat/tool loglarıyla ilişkilendirilsin.
- LLM açıkça “veri yok” diyebilsin; embedding benzerliği kanıt yerine geçmesin.

### 7. Hafıza ve embedding yönetim ekranları

Yeni/ güncellenecek sayfalar: `frontend/app/settings/page.tsx`, `frontend/app/system-health/page.tsx`, yeni `frontend/app/memory/page.tsx`.

- Provider/model test ve aktiflik durumu.
- Embedding kuyruğu: bekleyen, başarılı, başarısız, son hata.
- Model versiyonları ve dimension uyumu.
- Hafıza katmanı/sembol/strateji/timeframe filtreleri.
- Kaynağı görüntüleme, tek kaydı silme, model değişiminde yeniden oluşturma.
- Toplu silme yalnızca açık confirmation ve backup sonrası.

### 8. Gözlemlenebilirlik ve raporlama

- PostgreSQL bağlantı durumu, migration sürümü, pgvector sürümü.
- Backup/restore, reset ve memory-reset ayrımı; paper-trading reset'i hafıza kayıtlarını varsayılan olarak silmeyecek.
- Embedding p50/p95 latency, hata oranı, queue depth.
- Retrieval p50/p95 latency, sonuç sayısı, boş sonuç oranı.
- LLM tool-call ve retrieval audit logları.
- `/api/system/health` ve Sistem Sağlığı ekranına eklenir.

## Kabul kriterleri

1. Temiz ortamda PostgreSQL + pgvector ile backend başlar ve health endpoint `database=postgresql`, `vector_extension=available` döndürür.
2. SQLite migration sonrası her ana tabloda kaynak/hedef row count eşleşir; örnek kayıt checksum doğrulaması geçer.
3. Chat modeline embedding model seçilemez; embedding endpoint'i chat modelini kabul etmez.
4. Embedding testinde dimension, model ve süre görünür; API key response/loglarda bulunmaz.
5. Aynı işlem/sinyal için ikinci embedding üretimi content hash nedeniyle oluşmaz.
6. Sembol/timeframe/strateji filtreleriyle vector retrieval doğru scope'tan kayıt döndürür.
7. Embedding provider down olsa bile paper-trading loop'u işlemeye devam eder ve health ekranında uyarı oluşur.
8. LLM yanıtı yalnızca Türkçe ve sağlanan güncel/geçmiş context'e dayalı olur.
9. Hafıza kayıtları kaynak işlem/sinyal ID'sine geri izlenebilir.
10. Backup, reset, reports, portfolio, symbol analysis ve strategy chat akışları PostgreSQL üzerinde çalışır.

## Riskler ve önlemler

- **Migration veri kaybı:** dry-run, row count, checksum, read-only SQLite rollback.
- **Dimension uyumsuzluğu:** model ID + dimension zorunlu; her model için ayrı vector kolon/tablo veya model bazlı kayıt.
- **Filtreli HNSW eksik sonuç:** önce metadata indeksleri; düşük hacimde exact search, hacim büyüyünce HNSW ve recall testi.
- **Provider gecikmesi:** queue/worker; ana strateji loop'u embedding çağrısını beklemeyecek.
- **LLM yanlış hafıza yorumu:** güncel snapshot önceliği, kaynak/tarih gösterimi, confidence ve “kanıt değil” kuralı.
- **Secret sızıntısı:** encrypted key, redacted logs, frontend'e yalnızca masked metadata.
- **Üretim kesintisi:** önce staging compose, sonra backup, sonra kontrollü cutover; rollback komutu hazır.

## Doğrulama planı

### Unit

- Embedding payload/parser, response unwrap, dimension validation.
- Content hash/idempotency.
- Layer scope and metadata filters.
- SQLite-to-PostgreSQL type conversion.

### Integration

- PostgreSQL connection and `CREATE EXTENSION vector`.
- Provider/model CRUD and embedding test.
- Queue retry and provider failure isolation.
- Retrieval + LLM chat/tool audit.

### E2E

- Reset → signal → open trade → close trade → memory document → embedding → symbol chat.
- Strategy chat asks for historical failures and receives filtered records.
- Reports/portfolio/system health reflect PostgreSQL data.
- Backup/restore roundtrip.

### Observability

- p50/p95 embedding/retrieval metrics.
- DB/vector health and migration version.
- Error logs with secrets redacted.
- Approximate-vs-exact recall sample benchmark before HNSW activation.

## Uygulama sırası ve durma koşulu

1. Schema/repository abstraction and tests.
2. PostgreSQL compose + staging startup.
3. Migration dry-run and verification.
4. Provider/model embedding UI/API.
5. Memory tables and asynchronous embedding worker.
6. Hybrid retrieval and LLM integration.
7. Health/UI/metrics.
8. Production cutover only after all acceptance tests pass.

Her aşama bir öncekinin testleri geçmeden ilerlemeyecek. PostgreSQL geçişi doğrulanmadan SQLite silinmeyecek.

## Staffing / follow-up guidance

- `explore`: mevcut DB/API/UI etkilenme yüzeyini doğrulama.
- `architect`: migration, repository abstraction ve memory schema incelemesi.
- `executor`: backend DB/memory/embedding worker uygulaması.
- `designer`: Settings/Memory/Health UX.
- `test-engineer`: migration, provider failure ve E2E testleri.
- `verifier`: build, migration dry-run, acceptance evidence.
- `code-reviewer`: secret, data-loss, async loop ve SQL review.

Genel takip için `$ultragoal` uygun; paralel backend/frontend/test çalışması için Team + Ultragoal tercih edilmeli. Kalıcı tek sahipli sıralı doğrulama ancak açıkça istenirse `$ralph` ile yapılmalı.
