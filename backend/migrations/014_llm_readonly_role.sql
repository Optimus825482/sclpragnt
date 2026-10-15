-- 014: LLM salt-okunur Postgres rolü (denetim 2026-10-15, P0).
--
-- `read_only_sql` aracı artık sqlglot AST doğrulamasından geçer
-- (app/sql_guard.py) ve sorgu `SET LOCAL ROLE llm_readonly` ile koşar. Bu rol
-- yalnızca izin listesindeki tabloların izin listesindeki SÜTUNLARINA SELECT
-- yetkisi taşır; parola hash'i, anahtar, IP/UA gibi sütunlar rolde yoktur. Yani
-- doğrulayıcı atlatılsa bile veritabanı katmanı sızıntıyı engeller.
--
-- Notlar:
--   * Rol NOLOGIN'dir; doğrudan giriş yapılamaz, yalnızca SET ROLE ile geçilir.
--   * Uygulama kullanıcısının bu role üyeliği aşağıdaki DO bloğunda verilmeye
--     çalışılır. Yetki yoksa NOTICE düşer ve sorgular rol geçişinde hata verir
--     (kapalı başarısızlık); deploy notu için README'ye bakın.
--   * Sütun listesi app/sql_guard.py `ALLOWED_COLUMNS` ile birebir aynı tutulmalı.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'llm_readonly') THEN
        CREATE ROLE llm_readonly NOLOGIN NOINHERIT;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO llm_readonly;

GRANT SELECT (symbol, side, entry_price, stop_price, take_profit, peak_price, breakeven_hit,
              quantity, entry_time, strategy, trade_id)
    ON positions TO llm_readonly;

GRANT SELECT (id, symbol, strategy, side, entry_price, exit_price, quantity, pnl, pnl_pct,
              entry_time, exit_time, commission, reason, max_favorable_pct, max_adverse_pct,
              hold_seconds, trade_id)
    ON trades TO llm_readonly;

GRANT SELECT (id, timestamp, symbol, action, price, reason, strategy, trade_id)
    ON signals TO llm_readonly;

GRANT SELECT (id, timestamp, symbol, strategy, decision, reason, price)
    ON decision_logs TO llm_readonly;

GRANT SELECT (asset, amount)
    ON virtual_wallet TO llm_readonly;

GRANT SELECT (id, symbol, timeframe, captured_at, source, methodology_version, regime,
              regime_confidence, confluence_score, trade_id)
    ON analysis_snapshots TO llm_readonly;

GRANT SELECT (id, timestamp, scope, tool_name, result_summary, duration_ms, success)
    ON llm_tool_logs TO llm_readonly;

-- Uygulama kullanıcısı rolü kullanabilsin (SET LOCAL ROLE için üyelik şart).
-- Yetki yoksa uyarı verilir; kurulum bu yüzden düşmez.
DO $$
BEGIN
    EXECUTE format('GRANT llm_readonly TO %I', current_user);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'llm_readonly rolüne üyelik verilemedi: %', SQLERRM;
END
$$;
