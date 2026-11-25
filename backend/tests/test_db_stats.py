"""DB boyut ölçümü ve boyut koruması testleri (2026-11-25).

Kural: DB yokken/hatalıyken ölçüm uydurma değer üretmez; boyut koruması
yalnız sınır aşıldığında budama çağırır ve kademeli sıkılaştırır.
"""
import asyncio
import os

import pytest

from app import db_stats


def test_env_limit_default_is_disabled(monkeypatch):
    """Varsayılan KAPALI olmalı: mevcut büyük DB'de kazara budama yapmamalı."""
    monkeypatch.delenv("DB_MAX_SIZE_MB", raising=False)
    assert db_stats.env_limit_mb() == 0
    monkeypatch.setenv("DB_MAX_SIZE_MB", "512")
    assert db_stats.env_limit_mb() == 512
    monkeypatch.setenv("DB_MAX_SIZE_MB", "abc")
    assert db_stats.env_limit_mb() == 0


def test_snapshot_without_pool(monkeypatch):
    monkeypatch.setattr(db_stats, "_main_pg_pool", lambda: None)

    async def no_limit():
        return 0

    monkeypatch.setattr(db_stats, "get_limit_mb", no_limit)
    out = asyncio.run(db_stats.snapshot())
    assert out["available"] is False
    assert "reason" in out


def test_size_guard_skips_when_under_limit(monkeypatch):
    calls = []

    async def fake_limit():
        return 1000

    monkeypatch.setattr(db_stats, "get_limit_mb", fake_limit)

    async def fake_snapshot(limit_tables=12):
        return {"available": True, "size_mb": 100.0, "limit_mb": 1000, "over_limit": False}

    async def fake_prune(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(db_stats, "snapshot", fake_snapshot)
    out = asyncio.run(db_stats.size_guard(prune=fake_prune))
    assert out["checked"] is True
    assert out["pruned"] is False
    assert calls == []


def test_size_guard_prunes_then_stops(monkeypatch):
    async def fake_limit():
        return 1000

    monkeypatch.setattr(db_stats, "get_limit_mb", fake_limit)
    sizes = iter([1500.0, 900.0])
    calls = []

    async def fake_snapshot(limit_tables=12):
        size = next(sizes, 900.0)
        return {"available": True, "size_mb": size, "limit_mb": 1000,
                "over_limit": size > 1000}

    async def fake_prune(**kwargs):
        calls.append(kwargs)
        return {"decision_logs": 10, "historical_candles": 5}

    monkeypatch.setattr(db_stats, "snapshot", fake_snapshot)
    out = asyncio.run(db_stats.size_guard(prune=fake_prune))
    assert out["pruned"] is True
    assert len(calls) == 1, "sınır altına inince ikinci tur çağrılmamalı"
    assert out["deleted"]["decision_logs"] >= 10
    assert out["still_over"] is False


def test_size_guard_disabled_when_limit_zero(monkeypatch):
    async def zero_limit():
        return 0

    monkeypatch.setattr(db_stats, "get_limit_mb", zero_limit)
    calls = []

    async def fake_prune(**kwargs):
        calls.append(kwargs)
        return {}

    out = asyncio.run(db_stats.size_guard(prune=fake_prune))
    assert out["checked"] is False
    assert calls == []


def test_deep_clean_runs_reindex_and_vacuum(monkeypatch):
    """Derin temizlik: indeksleri CONCURRENTLY yeniden kurar, VACUUM FULL çağırmaz."""
    monkeypatch.setenv("DB_MAX_SIZE_MB", "0")
    executed: list[str] = []

    class FakeConn:
        async def fetch(self, sql, *args):
            assert "pg_indexes" in sql
            return [{"indexname": "idx_mem_hnsw"}]

        async def fetchval(self, sql, *args):
            return False

        async def execute(self, sql, *args):
            executed.append(sql)
            return "OK"

    class FakePool:
        def acquire(self):
            class Ctx:
                async def __aenter__(self_inner):
                    return FakeConn()

                async def __aexit__(self_inner, *exc):
                    return False
            return Ctx()

    async def fake_snapshot(limit_tables=12):
        return {"available": True, "size_mb": 15000.0, "limit_mb": 0,
                "over_limit": False, "tables": []}

    async def fake_prune(**kwargs):
        return {"memory_documents": 100}

    monkeypatch.setattr(db_stats, "_main_pg_pool", lambda: FakePool())
    monkeypatch.setattr(db_stats, "snapshot", fake_snapshot)

    out = asyncio.run(db_stats.deep_clean(prune=fake_prune))

    assert out["ok"] is True
    assert any("REINDEX INDEX CONCURRENTLY" in sql for sql in executed)
    assert any(sql.startswith("VACUUM (ANALYZE)") for sql in executed)
    assert not any("VACUUM FULL" in sql for sql in executed), "VACUUM FULL otomatik çalışmamalı"
    assert out["steps"]["memory_embeddings"]["idx_mem_hnsw"] == "yeniden kuruldu"


def test_deep_clean_without_pool(monkeypatch):
    async def fake_snapshot(limit_tables=12):
        return {"available": False}

    async def fake_prune(**kwargs):
        return {}

    monkeypatch.setattr(db_stats, "_main_pg_pool", lambda: None)
    monkeypatch.setattr(db_stats, "snapshot", fake_snapshot)
    out = asyncio.run(db_stats.deep_clean(prune=fake_prune))
    assert out["ok"] is False
