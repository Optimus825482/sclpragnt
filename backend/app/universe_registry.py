"""S7a: point-in-time symbol universe registry.

Top-gainer rotation replaces the tradable list hourly; backtests that iterate
"current symbols" therefore carry survivorship bias (delisted/dropped symbols
vanish from research). This module records, on every universe change, which
symbols were active and when — giving research tools a way to reconstruct the
universe *as it existed at any past moment*.

Storage reuses llm_settings KV as JSON (small, low-churn document).
"""
import json
import time

from app import database

_KEY = "symbol_universe_history"
# B-20: saatlik snapshot başına 1 kayıt → 2000 kayıt ≈ 83 GÜN. Eski yorum
# "~ yıllar" diyordu ve yanlıştı; 83 günden eski kayıtlar sessizce silinir.
_MAX_ENTRIES = 2000


async def record_universe(active_symbols: list[str], source: str = "top_gainers"):
    """Append one snapshot {ts, source, symbols} and prune old entries."""
    try:
        raw = await database.get_llm_setting(_KEY, "[]")
        history = json.loads(raw or "[]")
    except (ValueError, TypeError):
        history = []
    now = time.time()
    # Skip duplicate consecutive snapshots (same set within 10 min).
    if history:
        last = history[-1]
        if now - float(last.get("ts") or 0) < 600 and \
                sorted(last.get("symbols") or []) == sorted(active_symbols):
            return {"recorded": False, "reason": "duplicate_recent"}
    history.append({"ts": now, "source": source,
                    "symbols": sorted(str(s).upper() for s in active_symbols)})
    history = history[-_MAX_ENTRIES:]
    await database.set_llm_setting(_KEY, json.dumps(history))
    return {"recorded": True, "entries": len(history)}


async def universe_at(ts: float) -> dict:
    """Reconstruct the active universe as it was at ``ts``.

    B-20: bu fonksiyon artık gerçekten TÜKETİLİR — `/api/research/universe-at`
    ucu üzerinden research/geri-test araçlarına açılır. Eskiden yazma yolu
    çalışıyor ama okuma yolu hiçbir yerden çağrılmıyordu; yani hayatta kalma
    yanlılığı (survivorship bias) düzeltmesi fiilen devre dışıydı.

    Sıralama varsayımı da kaldırıldı: `ts`'ten küçük-eşit EN BÜYÜK zaman
    damgalı kayıt seçilir (bozuk/sırasız geçmişte de doğru çalışır).
    """
    try:
        raw = await database.get_llm_setting(_KEY, "[]")
        history = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return {"symbols": [], "as_of": None}
    best = None
    best_ts = None
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        entry_ts = float(entry.get("ts") or 0)
        if entry_ts <= ts and (best_ts is None or entry_ts > best_ts):
            best, best_ts = entry, entry_ts
    if not best:
        return {"symbols": [], "as_of": None}
    return {"symbols": best.get("symbols") or [], "as_of": best.get("ts"),
            "source": best.get("source"), "entries": len(history or [])}
