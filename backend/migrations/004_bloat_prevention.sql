-- 004 — BLOAT ÖNLEME: sıcak tablolarda agresif autovacuum (2026-09-16)
--
-- NEDEN: 2026-09-16 disk denetiminde DB 21 GB çıktı ama CANLI veri ~1-2 GB'dı.
--   microstructure_snapshots : 12 GB / yalnız 2.463 satır (en yeni kayıt 11 Eylül)
--   decision_logs            : 1.7 GB / yalnız 34 satır (indeks 1.5 GB)
-- Kök neden: satırlar `DELETE` ile budanıyordu ama hiç `VACUUM` edilmiyordu.
-- `pg_stat_user_tables.last_autovacuum` birçok tabloda NULL'du: PostgreSQL'in
-- varsayılanı `autovacuum_vacuum_scale_factor = 0.2` olduğundan 12 GB'lık bir
-- tabloda temizliğin başlaması için ~2.4 GB ölü tuple birikmesi gerekiyordu.
--
-- ÇÖZÜM: yüksek hacimli / sık silinen tablolarda eşiği tablo bazında düşür.
--   * `autovacuum_vacuum_scale_factor = 0.02`  → ölü oranı yüzde 2'de temizle
--   * `autovacuum_vacuum_insert_scale_factor = 0.05` → salt-ekleme (append-only)
--     tablolarda da temizle (PG13+; varsayılan 0.2 idi, hiç tetiklenmiyordu)
--   * `autovacuum_analyze_scale_factor = 0.02` → plan istatistikleri taze kalsın
--
-- Idempotent: `ALTER TABLE ... SET (...)` tekrar çalıştırılabilir; yeni kurulumda
-- da aynı davranışı kurar. Varsayılan GUC'lere DOKUNULMAZ — yalnız bu tablolar.

DO $$
DECLARE
  t TEXT;
  hedef TEXT[] := ARRAY[
    'microstructure_snapshots',   -- saniyede bir satır + retention DELETE
    'historical_candles',         -- 10^6-10^7 satır, retention DELETE
    'historical_feature_snapshots',
    'memory_documents',           -- her sohbet isteğinde satır (+ CASCADE embedding)
    'memory_embeddings',          -- halfvec + HNSW; heap küçük, indeks büyük
    'velocity_candidates',        -- 30 günlük retention DELETE
    'embedding_jobs',             -- tam JSONB belge taşır
    'agent_traces',               -- CASCADE ile trace_events
    'analysis_snapshots',         -- JSONB payload
    'monitoring_notifications',
    'macd_monitor_alerts',
    'rising_alerts',
    'llm_tool_logs',
    'chat_messages',
    'memory_retrieval_logs',
    'alert_events',
    'decision_logs'
  ];
BEGIN
  FOREACH t IN ARRAY hedef LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      -- NOT: `format()` KULLANILMAZ. Bu dosya bir gun `_PostgresCompat.execute`
      -- yolundan gecebilir; orada yuzde isareti psycopg'nin parametre yer
      -- tutucusu sayilir ve "only permitted placeholders" hatasi verir.
      -- `quote_ident` ile birlesim hem guvenli hem yuzde-isaretsiz.
      EXECUTE 'ALTER TABLE public.' || quote_ident(t)
           || ' SET (autovacuum_vacuum_scale_factor = 0.02,'
           || ' autovacuum_vacuum_insert_scale_factor = 0.05,'
           || ' autovacuum_analyze_scale_factor = 0.02)';
    END IF;
  END LOOP;
END $$;
