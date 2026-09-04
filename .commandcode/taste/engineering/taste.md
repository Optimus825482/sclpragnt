# Taste — Engineering

- Expects changes to be complete and error-free end-to-end ("eksiksiz, hatasız ve tam olarak") — backend, frontend, and supporting infrastructure updated together, not partially. Confidence: 0.8
- Asks for performance optimization of both backend and frontend — both when features are added and as standalone system-wide audits: DB layer (connection/locking, query patterns), all background loops and intervals, concurrency/task management, per-module flow functions, and frontend polling/re-render. Confidence: 0.85
- Wants versioned/cache-busted frontend assets after UI changes so a browser refresh loads the new CSS instead of stale cache. Confidence: 0.8
- Keeps the SQL schema migration in sync with columns the code INSERTs/SELECTs; when new columns are added, applies them idempotently to already-existing tables (CREATE TABLE IF NOT EXISTS plus ALTER TABLE ... ADD COLUMN IF NOT EXISTS) so runtime code never crashes on a missing column. Confidence: 0.8
