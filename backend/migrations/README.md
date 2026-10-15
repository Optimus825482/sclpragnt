# Şema migration'ları

Dosyalar `NNN_açıklama.sql` biçiminde, numara sırasıyla uygulanır. Koşucu hem
`backend/scripts/run_postgres_migration.py` (konteyner açılışı, `entrypoint.sh`)
hem de `app/database.py` `init_db()` içindeki aynı ortak modüldür
(`app/migration_plan.py`).

## Nasıl takip edilir

- Her dosya **kendi transaction'ında** koşar. DDL ile `schema_migrations`
  kaydı aynı transaction'dadır: hata olursa o dosyanın hiçbir değişikliği
  kalmaz, sonraki dosyalar koşmaz, bir sonraki açılışta kaldığı yerden devam eder.
- `schema_migrations(version, sha256, applied_at)` uygulanmış dosyaları tutar.
  Uygulanmış dosya **bir daha koşmaz**.
- Uygulanmış bir dosyanın içeriği değişmişse açılış **açık hatayla durur**
  (sessiz yeniden koşma yoktur).

## Kurallar

1. **Numara benzersiz olmalı.** Aynı numaralı iki dosya koşucuyu durdurur.
   İki dal aynı numarayı alırsa birleşmeden önce birinin numarası değişir.
2. **Uygulanmış dosya düzenlenmez.** Düzeltme için yeni numaralı bir dosya eklenir.
3. **Transaction içinde çalışmayan ifadeler kullanılmaz:** `CREATE INDEX
   CONCURRENTLY`, `VACUUM`, `ALTER TYPE ... ADD VALUE` (aynı transaction'da
   yeni değeri kullanmak), `BEGIN;` / `COMMIT;` (koşucu zaten transaction açar;
   `DO $$ ... $$` blokları içindeki `BEGIN` sorun değildir). Bu tür adımlar
   ayrı, elle uygulanan bir adıma taşınır ve dosyada not düşülür.
4. **Yıkıcı değişiklikler expand / contract ile yapılır.** `DROP COLUMN`,
   `DROP TABLE`, yeniden adlandırma ve tip değişikliği (`ALTER COLUMN ... TYPE`)
   tek adımda yapılmaz; çünkü açılış sırasında eski konteyner hâlâ çalışıyor
   olabilir ve bir rollback'te eski kod yeni şemada kırılır.
   - **Expand (migration N):** yeni kolon/tablo/index eklenir, gerekirse
     backfill yapılır. Mevcut kod bu şemada çalışmaya devam etmelidir.
   - **Uygulama kodu** yeni yapıyı okuyup yazacak şekilde deploy edilir; bir
     sürüm boyunca eski yapı da yazılmaya devam eder.
   - **Contract (migration M, N'den sonra, ayrı deploy):** eski kolon/tablo düşürülür.
     Eski kodun artık koşmadığı doğrulandıktan sonra yapılır.
   - Expand ile contract **aynı dosyada olmaz.**
5. **Geri alma dosyası yoktur.** Geri alma gerekirse ileri yönde yeni bir
   migration yazılır; contract adımı ertelenir.

## Eski kurulumdan geçiş

Önceki sürümde tüm migration'lar tek bir `llm_settings.schema_sha256` marker'ı
ile takip ediliyordu. `schema_migrations` boşken ve marker varsa, marker'ın
eşleştiği en uzun migration öneki "uygulanmış" sayılır ve yalnızca sonraki
dosyalar koşar. Hiçbir önek eşleşmezse (uygulandıktan sonra bir dosya
değişmiş olabilir) açılış durur; tahmin yürütülmez.

Elle tabloyu doldurmak gerekirse, `backend/` dizininden, uygulanmış dosyaların
sha256 değerleri:

```bash
python -c "from app.migration_plan import MIGRATIONS_DIR_DEFAULT, discover_migrations; [print(m.version, m.sha256) for m in discover_migrations(MIGRATIONS_DIR_DEFAULT)]"
```

Bu değerler `schema_migrations(version, sha256, applied_at)` tablosuna
yalnızca gerçekten uygulanmış dosyalar için yazılmalıdır.
