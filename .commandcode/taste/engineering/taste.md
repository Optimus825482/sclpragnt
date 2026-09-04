# Taste — Engineering

- Expects changes to be complete and error-free end-to-end ("eksiksiz, hatasız ve tam olarak") — backend, frontend, and supporting infrastructure updated together, not partially. Confidence: 0.8
- Asks for performance optimization of both backend and frontend when features are added. Confidence: 0.8
- Wants versioned/cache-busted frontend assets after UI changes so a browser refresh loads the new CSS instead of stale cache. Confidence: 0.8
- Keeps the SQL schema migration in sync with columns the code INSERTs/SELECTs; when new columns are added, applies them idempotently to already-existing tables (CREATE TABLE IF NOT EXISTS plus ALTER TABLE ... ADD COLUMN IF NOT EXISTS) so runtime code never crashes on a missing column. Confidence: 0.8
