"""PostgreSQL boyut ölçümü ve boyut koruması.

NEDEN VAR: `prune_retention` zamana göre budar; ama tablo büyümesi zamana
tekabül etmez (karar günlüğü, microstructure, velocity adayları mevsimsel
patlar). Ayrıca disk baskısını görmenin tek yolu log değil, panel olmalı.

Bu modül:
  * `snapshot()`   → toplam veritabanı boyutu + en büyük tablolar (panel için)
  * `size_guard()` → boyut `DB_MAX_SIZE_MB` sınırını aşarsa budama penceresini
                     KADEMELİ olarak kısaltıp tekrar budar (sınır aşılmadan
                     satır silme başlamaz; `DB_MAX_SIZE_MB=0` → kapalı)

NOT: VACUUM silinen alanı işletim sistemine geri vermez. Boyut koruması
satırları düşürür ve `VACUUM (ANALYZE)` çağırır; gerçek geri kazanım için
tek seferlik `VACUUM FULL` gerekir (elle, bakım penceresinde).
"""
from __future__ import annotations

import logging
import os
import time

from app.api_common import _main_pg_pool

logger = logging.getLogger("scalper.db_stats")


LIMIT_SETTING_KEY = "db_size_limit_mb"


def env_limit_mb() -> int:
    """Ortam değişkeni sınırı (MB). 0 → koruma KAPALI (varsayılan)."""
    try:
        return max(0, int(os.getenv("DB_MAX_SIZE_MB", "0")))
    except ValueError:
        return 0


async def get_limit_mb() -> int:
    """Etkin sınır: Ayarlar > DB kartındaki değer, yoksa ortam değişkeni.

    2026-11-25 (kullanıcı geri bildirimi): VARSAYILAN KAPALI (0). Önceden 2048 MB
    idi; mevcut veritabanı bundan büyükse ilk turda kademeli budama tetikleyip
    istenmeyen silme yapıyordu. Artık sınır yalnız kullanıcı belirlerse uygulanır.
    """
    try:
        from app import database
        raw = await database.get_llm_setting(LIMIT_SETTING_KEY)
        if raw is not None and str(raw).strip() != "":
            return max(0, int(float(raw)))
    except Exception:
        pass
    return env_limit_mb()


async def set_limit_mb(value) -> int:
    """Sınırı kalıcı yazar (0 = kapalı). Dönüş: normalize edilmiş MB."""
    from app import database
    mb = max(0, int(float(value or 0)))
    await database.set_llm_setting(LIMIT_SETTING_KEY, str(mb))
    return mb


def _mb(value) -> float:
    try:
        return round(float(value or 0) / (1024 * 1024), 1)
    except (TypeError, ValueError):
        return 0.0


async def snapshot(limit_tables: int = 12) -> dict:
    """Veritabanı boyutu ve en büyük tablolar. DB yoksa `available=False`."""
    pool = _main_pg_pool()
    now = time.time()
    if not pool:
        return {"available": False, "reason": "postgres yapılandırılmadı",
                "generated_at": now, "limit_mb": await get_limit_mb()}
    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT pg_database_size(current_database())")
            rows = await conn.fetch(
                """
                SELECT relname AS table_name,
                       pg_total_relation_size(relid) AS total_bytes,
                       pg_relation_size(relid)      AS heap_bytes,
                       pg_indexes_size(relid)       AS index_bytes,
                       n_live_tup                   AS live_rows
                  FROM pg_stat_user_tables
                 ORDER BY pg_total_relation_size(relid) DESC
                 LIMIT $1
                """,
                max(1, min(40, int(limit_tables))),
            )
    except Exception as exc:  # ölçüm asla uygulamayı düşürmemeli
        logger.warning("DB boyut ölçümü başarısız: %s", exc)
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}",
                "generated_at": now, "limit_mb": await get_limit_mb()}

    tables = [{
        "table": row["table_name"],
        "total_mb": _mb(row["total_bytes"]),
        "heap_mb": _mb(row["heap_bytes"]),
        "index_mb": _mb(row["index_bytes"]),
        "rows": int(row["live_rows"] or 0),
    } for row in rows]
    limit = await get_limit_mb()
    size_mb = _mb(total)
    return {
        "available": True,
        "generated_at": now,
        "size_mb": size_mb,
        "limit_mb": limit,
        "over_limit": bool(limit and size_mb > limit),
        "usage_pct": round(100 * size_mb / limit, 1) if limit else None,
        "tables": tables,
    }


async def size_guard(*, prune=None) -> dict:
    """Boyut sınırı aşıldıysa budama pencerelerini kısaltarak tekrar buda.

    `prune` çağrılabilir bir budama fonksiyonudur (örn. `database.prune_retention`);
    test edilebilirlik için dışarıdan verilir. Dönüş: ne yapıldığının özeti.
    """
    limit = await get_limit_mb()
    state = await snapshot(limit_tables=8)
    if not state.get("available") or not limit:
        return {"checked": False, "reason": "kapalı veya db yok", "state": state}
    if not state.get("over_limit"):
        return {"checked": True, "pruned": False, "size_mb": state.get("size_mb"),
                "limit_mb": limit}

    # `app.config` modülü ayarları `config` nesnesinde tutar (modül değil).
    from app.config import config as cfg
    base_days = int(getattr(cfg, "RETENTION_DAYS", 30) or 30)
    base_history = int(getattr(cfg, "HISTORY_RETENTION_DAYS", 21) or 21)
    base_decisions = int(getattr(cfg, "DECISION_LOGS_RETENTION_DAYS", 90) or 90)
    base_memory = int(getattr(cfg, "MEMORY_RETENTION_DAYS", 180) or 180)
    micro_cap = int(getattr(cfg, "MICROSTRUCTURE_RETENTION_DAYS", 7) or 7)
    embedding_cap = int(getattr(cfg, "EMBEDDING_JOBS_RETENTION_DAYS", 14) or 14)
    # Kademeli sıkılaştırma: her adımda pencereler yarıya iner, en az 3 gün.
    steps = [
        (base_days, base_history, base_decisions, base_memory),
        (max(7, base_days // 2), max(7, base_history // 2),
         max(30, base_decisions // 2), max(60, base_memory // 2)),
        (3, 3, 30, 30),
    ]
    deleted: dict = {}
    size_after = state.get("size_mb")
    for days, history, decisions, memory in steps:
        logger.warning("DB boyutu %.1f MB > sınır %s MB — budama sıkılaştırılıyor (days=%s)",
                       state.get("size_mb") or 0, limit, days)
        if prune is None:
            from app import database as _db
            prune = _db.prune_retention
        try:
            result = await prune(days=days,
                                 microstructure_days=min(3, micro_cap),
                                 memory_days=memory,
                                 history_days=history,
                                 embedding_jobs_days=min(7, embedding_cap),
                                 decision_logs_days=decisions)
            for key, value in (result or {}).items():
                deleted[key] = int(deleted.get(key, 0)) + int(value or 0)
        except Exception as exc:
            logger.warning("boyut koruması budaması başarısız: %s", exc)
            break
        state = await snapshot(limit_tables=8)
        size_after = state.get("size_mb")
        if not state.get("over_limit"):
            break
    return {"checked": True, "pruned": True, "deleted": deleted,
            "size_mb": size_after, "limit_mb": limit,
            "still_over": bool(state.get("over_limit"))}


# --------------------------------------------------------------------------- #
# Derin temizlik (hafıza vektörleri)
# --------------------------------------------------------------------------- #
_DEEP_LOCK = None


def _deep_lock():
    """Aynı anda iki derin temizlik çalışmasın (REINDEX pahalı)."""
    global _DEEP_LOCK
    if _DEEP_LOCK is None:
        import asyncio as _asyncio
        _DEEP_LOCK = _asyncio.Lock()
    return _DEEP_LOCK


async def deep_clean(tables: tuple[str, ...] = ("memory_embeddings",),
                     prune=None) -> dict:
    """Budama + `REINDEX CONCURRENTLY` + `VACUUM (ANALYZE)`.

    NEDEN: DELETE diski boşaltmaz; pgvector HNSW indeksi silinen satırlardan
    küçülmez. Ölçümde 15,7 GB'lık `memory_embeddings` yalnız 88 MB veri
    taşıyordu — geri kazanım için indeksin yeniden kurulması şart.

    KURALLAR:
      * `VACUUM FULL` BİLİNÇLİ olarak YOK: tabloyu kilitler, canlı sistemde
        otomatik çalıştırılmaz. Gerçek küçülme için bakım penceresinde elle.
      * `REINDEX CONCURRENTLY` / `VACUUM` transaction dışında çalışmalı;
        asyncpg tek deyimi otomatik commit eder (BEGIN açılmaz).
      * İndeks yoksa/izin yoksa o adım atlanır ve sonuçta bildirilir.
    """
    lock = _deep_lock()
    if lock.locked():
        return {"ok": False, "error": "derin temizlik zaten çalışıyor"}
    async with lock:
        started = time.time()
        before = await snapshot(limit_tables=12)
        result: dict = {"ok": True, "before_mb": before.get("size_mb"),
                        "steps": {}, "errors": {}}

        if prune is None:
            from app import database as _db
            prune = _db.prune_retention
        from app.config import config as cfg
        try:
            result["deleted"] = await prune(
                days=int(getattr(cfg, "RETENTION_DAYS", 30) or 30),
                microstructure_days=int(getattr(cfg, "MICROSTRUCTURE_RETENTION_DAYS", 7) or 7),
                memory_days=int(getattr(cfg, "MEMORY_RETENTION_DAYS", 180) or 180),
                history_days=int(getattr(cfg, "HISTORY_RETENTION_DAYS", 21) or 21),
                embedding_jobs_days=int(getattr(cfg, "EMBEDDING_JOBS_RETENTION_DAYS", 14) or 14),
                decision_logs_days=int(getattr(cfg, "DECISION_LOGS_RETENTION_DAYS", 90) or 90),
            )
        except Exception as exc:
            result["errors"]["prune"] = f"{type(exc).__name__}: {exc}"

        pool = _main_pg_pool()
        if not pool:
            result.update({"ok": False, "error": "postgres yapılandırılmadı"})
            return result

        admin_ok = False
        for table in tables:
            step: dict = {}
            try:
                async with pool.acquire() as conn:
                    # 1) tabloya bağlı indeksler (HNSW/IVFFlat dahil)
                    rows = await conn.fetch(
                        "SELECT indexname FROM pg_indexes WHERE tablename = $1", table)
                    indexes = [r["indexname"] for r in rows]
                    step["indexes"] = indexes
                    # 2) süper kullanıcı yetkisi (REINDEX CONCURRENTLY için gerekmez ama VACUUM FULL için gerekir)
                    admin_ok = bool(await conn.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
                    step["superuser"] = admin_ok
                    for index in indexes:
                        try:
                            # Deyim transaction DIŞINDA olmalı: asyncpg autocommit.
                            await conn.execute(f'REINDEX INDEX CONCURRENTLY "{index}"')
                            step[index] = "yeniden kuruldu"
                        except Exception as exc:
                            step[index] = f"atlandı: {type(exc).__name__}: {exc}"
                    try:
                        await conn.execute(f'VACUUM (ANALYZE) "{table}"')
                        step["vacuum"] = "tamam"
                    except Exception as exc:
                        step["vacuum"] = f"atlandı: {type(exc).__name__}: {exc}"
            except Exception as exc:
                result["errors"][table] = f"{type(exc).__name__}: {exc}"
            result["steps"][table] = step

        after = await snapshot(limit_tables=12)
        result["after_mb"] = after.get("size_mb")
        if before.get("size_mb") is not None and after.get("size_mb") is not None:
            result["reclaimed_mb"] = round(float(before["size_mb"]) - float(after["size_mb"]), 1)
        result["duration_sec"] = round(time.time() - started, 1)
        result["tables"] = after.get("tables")
        result["note"] = ("Disk geri kazanımı REINDEX/VACUUM ile sınırlıdır; tam küçülme için "
                          "bakım penceresinde elle: VACUUM FULL memory_embeddings.")
        return result
