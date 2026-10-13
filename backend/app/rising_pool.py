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
        c["pool_score"] = score_candidate(c)
        out.append(c)
    # sıralama: gerçekten-yükselen önce, sonra katmanlı skor
    out.sort(key=lambda r: (r.get("pool_genuinely_rising", False),
                            r.get("pool_score", 0.0)), reverse=True)
    return out


def genuinely_rising_rows(rows: list[dict]) -> list[dict]:
    """Havuzdan yalnız "gerçekten yükselen" adayları süz (push/WhatsApp/paper girdisi)."""
    return [r for r in (rows or []) if r.get("pool_genuinely_rising")]


# ---------------------------------------------------------------------------
# KATMANLI AĞIRLIKLI ADAY SKORU (2026-10-13) — aday seçimini iyileştirme denemesi
# ---------------------------------------------------------------------------
# Amaç: mevcut AYRI puanlamalar (panel/velocity, füzyon, master_surge composite,
# upside_rank) yerine TEK, katmanlı ve ağırlıklı bir aday skoru. Her katman 0-1
# normalize edilir, ağırlıklarla toplanır → 0-100. Ağırlıklar toplamı 1.0.
#
#   L1 GÜÇ      : velocity panel (ham skoru 0-100'e) — sinyal ne kadar güçlü
#   L2 MUTABAKAT: fuse kaynak sayısı + master_surge confluence katmanı — kaç motor teyit
#   L3 TREND    : kısa getiri (ret3) pozitif ve anlamlı — fiyat gerçekten yukarı mı
#   L4 LİKİDİTE : hacim/ATR uyumu — hareket yürütülebilir mi (ince tahtada değil)
#
# Varsayılan ağırlıklar (POOL_W_*): güç 0.35, mutabakat 0.30, trend 0.20, likidite 0.15.
# Replay (unified_pool_replay) bu skorun EV'yi iyileştirip iyileştirmediğini ölçer.
def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _weights() -> tuple[float, float, float, float]:
    from app.config import config
    w = (
        float(getattr(config, "POOL_W_STRENGTH", 0.35)),
        float(getattr(config, "POOL_W_AGREEMENT", 0.30)),
        float(getattr(config, "POOL_W_TREND", 0.20)),
        float(getattr(config, "POOL_W_LIQUIDITY", 0.15)),
    )
    tot = sum(w)
    return tuple(x / tot for x in w) if tot > 0 else (0.25, 0.25, 0.25, 0.25)


def score_candidate(row: dict) -> float:
    """Katmanlı ağırlıklı aday skoru (0-100). Saf fonksiyon; DB/ağ YOK.

    L1 GÜÇ      : panel/velocity skoru (0-100 → 0-1)
    L2 MUTABAKAT: (füzyon kaynak sayısı + master_surge katman sayısı) normalize;
                  hem ham kaynak hem 4-katman teyidi sayılır (kaç motor hemfikir).
    L3 TREND    : `ret3_pct` pozitifse ve >0.5% ise tam, 0-0.5% arası doğrusal,
                  negatifse 0 (fiyat gerçekten yukarı değil → trend katmanı sıfır).
    L4 LİKİDİTE : `volume_ratio` + `atr_pct` makul bandda ise tam; aşırı yüksek ATR
                  (ince/oynak tahta) veya sıfır hacim → düşürür.
    """
    # L1 güç — panel skoru (varsa panel_score, yoksa ham velocity'yi normalize et)
    panel = row.get("panel_score")
    if panel is None:
        try:
            from app.routers.velocity import _panel_score as _ps
            panel = _ps(row.get("velocity_score") or 0)
        except Exception:
            panel = 0.0
    l1 = _clamp01(_num(panel, 0.0) / 100.0)

    # L2 mutabakat — kaynak sayısı (0..3) + master_surge katmanı (0..4)
    srcs = len([s for s in (row.get("unified_sources") or []) if s])
    ms = row.get("master_surge") if isinstance(row.get("master_surge"), dict) else {}
    layers = int(_num(ms.get("confluence_count"), 0))
    l2 = _clamp01((min(3, srcs) / 3.0) * 0.5 + (min(4, layers) / 4.0) * 0.5)

    # L3 trend — ret3 pozitif ve anlamlı
    ret3 = _num(row.get("ret3_pct"), 0.0)
    if ret3 <= 0:
        l3 = 0.0
    elif ret3 >= 0.5:
        l3 = 1.0
    else:
        l3 = ret3 / 0.5

    # L4 likidite — aşırı oynak/ince tahtayı cezalandır (ATR>3% veya hacim yok)
    atr = _num(row.get("atr_pct"), 0.0)
    vol_r = _num(row.get("volume_ratio"), 0.0)
    if atr <= 0:
        l4 = 0.4                       # ATR bilinmiyor → ölçülü ceza
    elif atr > 3.0:
        l4 = _clamp01(1.0 - (atr - 3.0) / 3.0)   # 3%→1.0, 6%→0
    else:
        l4 = 1.0
    if vol_r > 0:                      # hacim verisi varsa hafif bonus/ceza
        l4 = _clamp01(l4 * (1.0 if vol_r >= 1.0 else 0.8))

    w1, w2, w3, w4 = _weights()
    return round(min(100.0, max(0.0, (l1 * w1 + l2 * w2 + l3 * w3 + l4 * w4) * 100.0)), 2)


def annotate_pool_scores(rows: list[dict]) -> list[dict]:
    """Havuz satırlarına `pool_score` yaz (katmanlı ağırlıklı skor). Sıralamaz."""
    for r in (rows or []):
        if isinstance(r, dict):
            r["pool_score"] = score_candidate(r)
    return rows


def top_by_pool_score(rows: list[dict], n: int) -> list[dict]:
    """Katmanlı skora göre en iyi N aday. Popülasyon alt kümesi seçimi için."""
    scored = [r for r in (rows or []) if isinstance(r, dict)]
    scored.sort(key=lambda r: _num(r.get("pool_score"), 0.0), reverse=True)
    return scored[:max(0, int(n))]
