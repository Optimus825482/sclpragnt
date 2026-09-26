"""SQLite → PostgreSQL migration monitor (pasif).

SQLite desteği uygulamadan tamamen kaldırılmıştır; uygulama yalnızca
PostgreSQL kullanır. Migration aracı artık gereksizdir. `/api/migration/*`
uçları çağrılmaya devam ederse "SQLite migration gerekmiyor" durumu döner
ve hiçbir SQLite dosyasına dokunulmaz.
"""

import time

# Durable tables that any historical SQLite → PostgreSQL migration had to
# cover. Kept as the canonical list so migration/verification contracts stay
# testable even though the live app is PostgreSQL-only.
TABLES = ("positions", "trades", "signals", "decision_logs", "llm_tool_logs",
          "llm_symbol_guards", "virtual_wallet", "chart_settings",
          "llm_providers", "llm_models", "llm_skills", "llm_settings")

state = {
    "status": "closed",
    "phase": "closed",
    "progress": 0,
    "message": "Uygulama yalnızca PostgreSQL kullanıyor; SQLite migration gerekmiyor",
    # 2026-09-26 (#80): Bu modül bir MIGRATION DOĞRULAMA ARACI DEĞİLDİR ve
    # hiçbir zaman öyle olmadı. `implemented: False` bayrağı bilinçlidir:
    # `/api/migration/status` daha önce `progress: 100` ve
    # `status: "completed"` döndürdüğü halde hiçbir tabloyu SAYMIYORDU —
    # biri bu uçtaki 200'ü "migration doğrulandı" diye okursa yanılır.
    # Aşağıdaki `counts` alanı artık GERÇEK satır sayılarıdır (bilgi amaçlı);
    # ancak SQLite KAYNAK tarafı hiçbir zaman okunmadığı için
    # KAYNAK/HEDEF KARŞILAŞTIRMASI yapılmaz ve yapılamaz.
    "implemented": False,
    "verification_performed": False,
    "source": None,
    "counts": {},
    "error": None,
    "started_at": None,
    "finished_at": None,
    "logs": [{"time": time.time(), "level": "info",
               "message": "SQLite desteği kaldırıldı; PostgreSQL tek veritabanıdır."}],
}
def _log(message, level="info"):
    state.setdefault("logs", []).append({"time": time.time(), "level": level, "message": message})
    state["logs"] = state["logs"][-200:]


def inspect_source(path):
    raise RuntimeError("SQLite migration kaldırıldı; uygulama yalnızca PostgreSQL kullanır")


def compare_counts(source_counts, target_counts):
    """Return deterministic lower-bound violations for migrated tables."""
    errors = []
    for table in TABLES:
        source_count = source_counts.get(table)
        if source_count is None:
            continue
        target_count = int(target_counts.get(table) or 0)
        if target_count != int(source_count):
            errors.append(f"{table}: hedef satır sayısı uyuşmuyor ({target_count}/{source_count})")
    return errors


# Tablo adları bir sabit liste; bunları SQL metnine gömüyoruz. `to_regclass`
# ile varlık kontrolü yaptığımız için injection riski oluşmasın diye
# yine de yalnızca TABLES'taki isimler sorgulanır (kullanıcı girdisi değil).
_COUNT_SQL = """
SELECT (SELECT count(*) FROM {table})::bigint
"""


async def fetch_target_counts(pool):
    """PostgreSQL hedefindeki tablo satır sayılarını GERÇEKTEN sorgular.

    2026-09-26 (#80) düzeltmesi: eski hâli `return {}` idi — yani "hedef
    sayılarını topladık" izlenimi veriyordu ama hiçbir şey toplamıyordu.

    Uygulama PostgreSQL-only olduğu için bu fonksiyon artık bilgi amaçlıdır:
    operatörün mevcut tablo boyutlarını görmesini sağlar. `compare_counts`
    ile karşılaştırma YAPILMAZ, çünkü SQLite kaynak tarafı hiç okunmuyor
    (bkz. `inspect_source`). Eksik tablolar sessizce atlanır (0 döner),
    böylece henüz oluşmamış bir tablo hata üretmez.
    """
    if pool is None:
        return {}
    counts = {}
    for table in TABLES:
        try:
            # Güvenli: tablo adı TABLES sabitinden gelir, parametre
            # bind edilemediği için doğrudan birleştirilir (to_regclass ile
            # varlığı doğrulanır).
            exists = await pool.fetchval("SELECT to_regclass($1)", f"public.{table}")
            if exists is None:
                counts[table] = 0
                continue
            counts[table] = int(await pool.fetchval(_COUNT_SQL.format(table=table)))
        except Exception as exc:  # tek tablo sayımı hatası tüm sorguyu düşürmesin
            _log(f"{table} satır sayısı okunamadı: {exc}", level="warning")
            continue
    return counts


async def run(source, database_url, publish=None):
    """Eski SQLite → PostgreSQL migration koşucusu.

    Kalıcı olarak kaldırıldı; bu gövde bilinçli olarak YALNIZCA durumu
    "kapalı" olarak işaretler. Gerçek bir migration ÇALIŞTIRMAZ.
    `system.py` bu fonksiyonu çağırmadan önce `inspect_source()` ile 410
    Gone döndürür, dolayısıyla normalde buraya ulaşılmaz.
    """
    await _set(
        status="closed",
        phase="closed",
        progress=0,
        message="SQLite migration kaldırıldı; PostgreSQL tek backend. "
                "Doğrulama YAPILMADI (implemented=False).",
        implemented=False,
        verification_performed=False,
        source=None,
        counts={},
        finished_at=time.time(),
    )
    _log("Migration koşucusu pasif; hiçbir veri okunmadı veya yazılmadı.")


async def _set(**kwargs):
    state.update(kwargs)