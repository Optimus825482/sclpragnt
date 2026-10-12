"""BİRLEŞİK YÜKSELİŞ HAVUZU (2026-10-13) — tüm motorlardan beslenen TEK aday havuzu.

NEDEN: Sistemde 4 ayrı üretici vardı (radar push, yükseliş push, Global push,
WhatsApp kombine liste) ve ikisi AYNI taramayı tekrar yapıyor, farklı skor/eşik
kullanıyordu. Bu modül hepsini TEK havuzda birleştirir; hem push hem WhatsApp
aynı havuzu okur → çelişki ve çift tarama biter.

AKIŞ (`build_pool`):
    velocity (tüm ufuklar) + momentum + squeeze + rising + GLOBAL (lead-lag/velocity)
      → sembol bazında tekilleştir
      → `unified_signals.enrich_candidates` (füzyon: velocity+jump+early+rising)
      → `master_surge.evaluate_master_surge` (4-KATMAN ORTAK KARAR: composite_index
        + confluence_count)
      → kalite/hedef/potansiyel alanları
      → TTL önbellek (~25 sn)

ORTAK KARAR KAPISI (`is_genuinely_rising`): aday GERÇEKTEN yükseliyor mu?
    (a) fiyat yukarı  (ret3_pct > 0 veya passes=True)
    (b) ortak karar   (master_surge composite_index >= eşik)
    (c) mutabakat     (confluence_count >= N)
Üçü birlikte → bildirime/listeye girer. Zayıf izleyici ve füzyon-tek adaylar GİRMEZ.

DÜRÜST SINIR: Bu mimari birleştirmedir; KÂRLILIK İDDİASI YOK. Aşama B'de replay/
walk-forward ile doğrulanmadan canlıya bağlanmaz (bkz. docs + scripts/unified_pool_replay).
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("scalper.rising_pool")

# TTL: tarama turu 30 sn; 25 sn önbellek iki tüketicinin (push + WhatsApp) AYNI
# turu görmesini sağlar ama bayat veriyi 1 turdan fazla tutmaz.
_POOL_TTL_SEC = 25.0
_pool_cache: dict = {"ts": 0.0, "rows": []}


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def ttl_seconds() -> float:
    return _POOL_TTL_SEC


def cached(now: float | None = None) -> list[dict] | None:
    """Önbellekten havuzu döndür (taze ise); değilse None."""
    now = float(now if now is not None else time.time())
    if _pool_cache["rows"] and (now - _pool_cache["ts"]) < _POOL_TTL_SEC:
        return _pool_cache["rows"]
    return None


def store(rows: list[dict], now: float | None = None) -> None:
    _pool_cache["rows"] = list(rows or [])
    _pool_cache["ts"] = float(now if now is not None else time.time())


def reset_cache() -> None:
    _pool_cache["rows"] = []
    _pool_cache["ts"] = 0.0


def is_genuinely_rising(row: dict, *, min_composite: float | None = None,
                        min_confluence: int | None = None) -> bool:
    """ORTAK KARAR KAPISI: aday gerçekten yükseliş potansiyelli mi?

    Üç koşul birlikte:
      (a) fiyat yukarı: `ret3_pct > 0` VEYA `passes is True`
      (b) ortak karar : master_surge `composite_index` >= eşik (varsayılan 60)
      (c) mutabakat   : `confluence_count` >= N (varsayılan 2 — en az iki motor teyit)
    Eksik alan ceza DEĞİL ama kapıyı da geçirmez (fail-closed): composite/confluence
    yoksa aday "gerçekten yükselen" sayılmaz.
    """
    from app.config import config
    if min_composite is None:
        min_composite = float(getattr(config, "POOL_MIN_COMPOSITE", 60.0))
    if min_confluence is None:
        min_confluence = int(getattr(config, "POOL_MIN_CONFLUENCE", 2))

    ret3 = row.get("ret3_pct")
    try:
        price_up = (_num(ret3, 0.0) > 0.0) or bool(row.get("passes"))
    except (TypeError, ValueError):
        price_up = bool(row.get("passes"))
    if not price_up:
        return False

    ms = row.get("master_surge") or {}
    comp = _num(ms.get("composite_index"), 0.0)
    conf = int(_num(ms.get("confluence_count"), 0))
    if comp < min_composite:
        return False
    if conf < min_confluence:
        return False
    # Sert risk bloğu varsa geçirmez.
    if row.get("block_reason") or ms.get("block_reason"):
        return False
    return True


async def build_pool(*, force: bool = False, now: float | None = None) -> list[dict]:
    """Tüm motorlardan tek havuz üret. Önbellek taze ve `force` değilse onu döndür.

    CANLI YOLU DEĞİŞTİRMEZ: bu fonksiyon yalnız çağrıldığında çalışır; Aşama C'ye
    kadar üretimde çağrılmaz. Replay'de (`unified_pool_replay`) doğrudan kullanılır.
    """
    now = float(now if now is not None else time.time())
    if not force:
        hit = cached(now)
        if hit is not None:
            return hit

    rows = await _collect_all(now)
    store(rows, now)
    return rows


async def _collect_all(now: float) -> list[dict]:
    """Motorların çıktısını topla → tekilleştir → füzyon + ortak karar."""
    from app.routers.velocity import detect_velocity_candidates

    scan_rows: list[dict] = []
    # 1) velocity — tüm aktif ufuklar
    try:
        from app.routers.velocity import _active_horizons
        for h in _active_horizons():
            try:
                sc = await detect_velocity_candidates({}, horizon_minutes=h, journal_enabled=False)
                scan_rows.extend((sc or {}).get("candidates") or [])
                scan_rows.extend((sc or {}).get("watchlist") or [])
            except Exception as exc:
                logger.debug("havuz: velocity %sm atlandı: %s", h, exc)
    except Exception as exc:
        logger.debug("havuz: velocity taraması hatası: %s", exc)

    # 2) yükseliş adayları (MACD snapshot — salt okunur)
    try:
        from app import rising_signals
        for rc in rising_signals.detect_rising_candidates():
            sym = str(rc.get("symbol") or "").upper()
            if sym:
                scan_rows.append({"symbol": sym, "strategy": "rising",
                                  "velocity_score": float(rc.get("score") or 0.0),
                                  "panel_score": float(rc.get("score") or 0.0),
                                  "target_pct": rc.get("target_pct"),
                                  "price": rc.get("price")})
    except Exception as exc:
        logger.debug("havuz: rising atlandı: %s", exc)

    if not scan_rows:
        return []

    # 3) sembol bazında tekilleştir (en yüksek panel/velocity skoru kalır)
    by_sym: dict[str, dict] = {}
    for c in scan_rows:
        sym = str(c.get("symbol") or "").upper()
        if not sym:
            continue
        cur = by_sym.get(sym)
        if cur is None or _num(c.get("panel_score") or c.get("velocity_score")) > \
                _num(cur.get("panel_score") or cur.get("velocity_score")):
            by_sym[sym] = c

    merged = list(by_sym.values())

    # 4) füzyon (velocity+jump+early+rising) + master_surge ORTAK KARAR
    try:
        from app import unified_signals
        unified_signals.enrich_candidates(merged)
    except Exception as exc:
        logger.debug("havuz: füzyon hatası: %s", exc)

    # 5) ortak karar kapısı + alan normalizasyonu
    out: list[dict] = []
    for c in merged:
        if not isinstance(c, dict):
            continue
        ms = c.get("master_surge") or {}
        c["pool_composite_index"] = _num(ms.get("composite_index"), 0.0)
        c["pool_confluence"] = int(_num(ms.get("confluence_count"), 0))
        c["pool_genuinely_rising"] = bool(is_genuinely_rising(c))
        out.append(c)
    # sıralama: gerçekten-yükselen önce, sonra composite
    out.sort(key=lambda r: (r.get("pool_genuinely_rising", False),
                            r.get("pool_composite_index", 0.0)), reverse=True)
    return out


def genuinely_rising_rows(rows: list[dict]) -> list[dict]:
    """Havuzdan yalnız "gerçekten yükselen" adayları süz (push/WhatsApp/paper girdisi)."""
    return [r for r in (rows or []) if r.get("pool_genuinely_rising")]
