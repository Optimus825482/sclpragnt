"""LLM'in çalıştırdığı salt-okunur SQL için AST tabanlı doğrulayıcı.

Denetim 2026-10-15 (P0): eski doğrulayıcı tablo adlarını `FROM|JOIN <ad>`
regex'iyle arıyordu. Virgüllü join (`FROM positions p, users u`) regex'i
atlatıp `users.password_hash` gibi sütunları sızdırıyordu. Burada sorgu
sqlglot ile AYRIŞTIRILIR ve kurallar AST düğümleri üzerinden uygulanır:

  * Tek bir SELECT / WITH...SELECT / UNION ifadesi; yazma, DDL, `INTO`,
    `FOR UPDATE` ve bilinmeyen (Anonymous) fonksiyon çağrıları reddedilir.
  * Her tablo referansı izin listesinde olmalı; şema nitelikli adlar
    (`pg_catalog.x`) ve tablo fonksiyonları (`pg_read_file(...)`) reddedilir.
  * Her sütun referansı, niteliği bir gerçek tabloya çözülüyorsa o tablonun
    izin verilen sütunlarında olmalı; niteliksiz adlar sorguda geçen izinli
    tablolardan birinde bulunmalı.
  * `*` ve `tablo.*` yalnızca `COUNT(*)` içinde kabul edilir (genişletme
    izin listesini aşabilir).

Doğrulanan SQL, AST'den yeniden üretilip çalıştırılır: denetlenen metin ile
çalıştırılan metin aynıdır, ayrıştırıcı farkı (differential) riski yoktur.
Dış LIMIT her zaman uygulanır. Çalıştırma tarafındaki salt-okunur işlem,
`statement_timeout` ve `llm_readonly` rolü `database.read_only_query` içindedir.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

# Tablo başına MODELE AÇIK sütunlar. JSONB/opak ve sır çağrıştıran sütunlar
# (entry_context, metadata, payload, arguments, password_hash ...) KASITLI
# olarak listelenmez. Migration 014 aynı listeyi sütun bazlı GRANT ile uygular.
ALLOWED_COLUMNS: dict[str, frozenset[str]] = {
    "positions": frozenset({"symbol", "side", "entry_price", "stop_price", "take_profit",
                            "peak_price", "breakeven_hit", "quantity", "entry_time",
                            "strategy", "trade_id"}),
    "trades": frozenset({"id", "symbol", "strategy", "side", "entry_price", "exit_price",
                         "quantity", "pnl", "pnl_pct", "entry_time", "exit_time",
                         "commission", "reason", "max_favorable_pct", "max_adverse_pct",
                         "hold_seconds", "trade_id"}),
    "signals": frozenset({"id", "timestamp", "symbol", "action", "price", "reason",
                          "strategy", "trade_id"}),
    "decision_logs": frozenset({"id", "timestamp", "symbol", "strategy", "decision",
                                "reason", "price"}),
    "virtual_wallet": frozenset({"asset", "amount"}),
    "analysis_snapshots": frozenset({"id", "symbol", "timeframe", "captured_at", "source",
                                     "methodology_version", "regime", "regime_confidence",
                                     "confluence_score", "trade_id"}),
    "llm_tool_logs": frozenset({"id", "timestamp", "scope", "tool_name", "result_summary",
                                "duration_ms", "success"}),
}
ALLOWED_TABLES = frozenset(ALLOWED_COLUMNS)

# Salt-okunur işlemde uygulanan üst sınır (saniye cinsinden ifade edilen string).
STATEMENT_TIMEOUT = "5s"
MAX_ROWS = 500

# Veri değiştiren, şema değiştiren veya yönetim yapan düğümler. Ağaçta herhangi
# bir yerde (ör. `WITH d AS (DELETE ... RETURNING *)`) geçerlerse reddedilir.
_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command",
    "Into", "Lock", "Copy", "Transaction", "Commit", "Rollback", "Set", "Pragma",
    "Describe", "Show", "Analyze", "Vacuum", "Grant", "Revoke",
)
_FORBIDDEN_NODES = tuple(getattr(exp, name) for name in _FORBIDDEN_NODE_NAMES if hasattr(exp, name))


class UnsafeSQLError(ValueError):
    """Sorgu salt-okunur kurallarını ihlal ediyor."""


def validate_read_only_select(sql: str, limit: int = MAX_ROWS) -> str:
    """`sql` doğrulanır ve dış LIMIT'li, yeniden üretilmiş SQL metnini döndürür.

    Geçersiz sorguda `UnsafeSQLError` (ValueError alt sınıfı) fırlatır.
    """
    statement = str(sql or "").strip()
    if not statement or ";" in statement:
        raise UnsafeSQLError("Tek bir SELECT sorgusu gerekli; çoklu ifade veya noktalı virgül yasak")

    try:
        parsed = [node for node in sqlglot.parse(statement, read="postgres") if node is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSQLError(f"SQL ayrıştırılamadı: {exc}") from exc
    if len(parsed) != 1:
        raise UnsafeSQLError("Tek bir SELECT sorgusu gerekli; çoklu ifade yasak")
    root = parsed[0]
    if not isinstance(root, (exp.Select, exp.Union)):
        raise UnsafeSQLError("Yalnızca SELECT veya WITH ... SELECT sorgularına izin verilir")
    if root.find(*_FORBIDDEN_NODES):
        raise UnsafeSQLError("Yazma, DDL veya yönetim komutu tespit edildi")

    unknown_func = root.find(exp.Anonymous)
    if unknown_func is not None:
        raise UnsafeSQLError(f"Bilinmeyen fonksiyon çağrısına izin verilmez: {unknown_func.name}")

    for star in root.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise UnsafeSQLError("'*' ve 'tablo.*' yalnızca COUNT(*) içinde kullanılabilir; sütunları açıkça seçin")

    # --- Tablolar ---------------------------------------------------------
    # CTE adları gerçek tablo değildir; onlara yapılan referanslar CTE gövdesi
    # zaten denetlendiği için serbesttir. Türetilmiş tablolar (alt sorgu) da
    # iç sorgularındaki sütunlar üzerinden denetlenir.
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    # Nitelik adı → gerçek tablo (None: CTE/türetilmiş). Bir ad iki farklı
    # hedefe çözülürse belirsiz sayılıp reddedilir.
    qualifier_map: dict[str, str | None] = {}

    def _bind(qualifier: str, target: str | None) -> None:
        if qualifier_map.get(qualifier, target) != target:
            raise UnsafeSQLError(f"'{qualifier}' takma adı belirsiz")
        qualifier_map[qualifier] = target

    real_tables: set[str] = set()
    for table in root.find_all(exp.Table):
        if table.args.get("db") or table.args.get("catalog"):
            raise UnsafeSQLError("Şema nitelikli tablo adlarına izin verilmez")
        ident = table.this
        if not isinstance(ident, exp.Identifier):
            raise UnsafeSQLError("Tablo fonksiyonlarına izin verilmez")
        name = ident.name.lower()
        if name in cte_names:
            target = None
        elif name in ALLOWED_TABLES:
            target = name
            real_tables.add(name)
        else:
            raise UnsafeSQLError(f"Sorgu yalnızca izin verilen uygulama tablolarını kullanabilir: {sorted(ALLOWED_TABLES)}")
        _bind(name, target)
        if table.alias:
            _bind(table.alias.lower(), target)

    # --- Sütunlar ---------------------------------------------------------
    select_aliases = {alias.alias.lower() for alias in root.find_all(exp.Alias) if alias.alias}
    visible_columns = frozenset().union(*(ALLOWED_COLUMNS[name] for name in real_tables))
    for column in root.find_all(exp.Column):
        ident = column.this
        if not isinstance(ident, exp.Identifier):
            continue  # `*` biçimleri yukarıda reddedildi
        col = ident.name.lower()
        qualifier = (column.table or "").lower()
        if qualifier:
            target = qualifier_map.get(qualifier)
            if target is None:
                continue  # CTE / türetilmiş tablo: içerik iç sorguda denetlenir
            if col not in ALLOWED_COLUMNS[target]:
                raise UnsafeSQLError(f"{target}.{col} izinli sütunlar arasında değil")
        elif col not in visible_columns and col not in select_aliases:
            raise UnsafeSQLError(f"'{col}' sütunu izinli değil veya belirsiz; tablo adını niteleyin")

    # --- Satır sınırı -----------------------------------------------------
    # İç LIMIT'ler cap'e İNDİRİLİR (büyütülmez; ALL/değişken de cap olur), sonra
    # dış LIMIT koşulsuz eklenir: iki katmanlı sınır.
    cap = max(1, min(int(limit), MAX_ROWS))
    for limit_node in root.find_all(exp.Limit):
        bound = limit_node.expression
        if not (isinstance(bound, exp.Literal) and bound.is_int and int(bound.this) <= cap):
            limit_node.set("expression", exp.Literal.number(cap))
    rendered = root.sql(dialect="postgres")
    # Dış LIMIT koşulsuz: iç LIMIT büyük olsa da sonuç kümesi cap'i aşamaz.
    return f"SELECT * FROM ({rendered}) AS llm_read_only_result LIMIT {cap}"
