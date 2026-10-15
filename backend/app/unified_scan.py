"""Birleşik tarama motoru (Unified Scan).

Tüm radar stratejilerini salt-okunur biçimde birleştirip tek bir aday listesi
üretir. Her kaynak kendi algoritmasını çalıştırır; sonuçlar sembol + ufuk
bazında tekilleştirilir, kaynak uzlaşısı/çelişkisi ve kanıtları korunur.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

from app.config import config
from app import master_surge
from app import snapback_service
from app import unified_signals
from app.state import analyzer

logger = logging.getLogger(__name__)


def _score_norm_mode() -> str:
    mode = str(getattr(config, "MONITORING_SCORE_NORM_MODE", "log") or "log").lower()
    if mode == "linear":
        logger.warning(
            "MONITORING_SCORE_NORM_MODE=linear: ham velocity_score CAP'te "
            "sert kirpiliyor, esik ustü adaylarin siralamasi kayboluyor. "
            "Varsayilan (log) onerilir.")
    return mode


MONITORING_SCORE_NORM_VERSION = 2


def _panel_from_raw(raw_score: float) -> float:
    """Ham velocity_score → panel (0-100). Aktif ölçek moduna göre monoton harita.

    `linear`: eski `min(100, raw/CAP×100)` — CAP üstünde SERT kırpar (sıralama kaybı).
    `log`   : `100×log1p(raw)/log1p(REF)` — REF'e kadar kırpma YOK.
    """
    try:
        raw = float(raw_score or 0)
    except (TypeError, ValueError):
        return 0.0
    if raw <= 0:
        return 0.0
    if _score_norm_mode() == "linear":
        cap = float(getattr(config, "MONITORING_SCORE_NORM_CAP", 2000))
        if not cap > 0:
            return round(max(0.0, min(100.0, raw)), 1)
        return round(max(0.0, min(100.0, raw / cap * 100)), 1)
    ref = float(getattr(config, "MONITORING_SCORE_NORM_LOG_REF", 25000) or 0)
    denom = math.log1p(ref) if ref > 0 else 0.0
    if denom <= 0:
        return round(max(0.0, min(100.0, raw)), 1)
    return round(max(0.0, min(100.0, 100.0 * math.log1p(raw) / denom)), 1)


def _raw_from_panel(panel_score: float) -> float:
    """Panel (0-100) → ham velocity_score: `_panel_from_raw`'un TERSİ."""
    try:
        panel = max(0.0, min(100.0, float(panel_score)))
    except (TypeError, ValueError):
        panel = 0.0
    if _score_norm_mode() == "linear":
        cap = float(getattr(config, "MONITORING_SCORE_NORM_CAP", 2000))
        return panel / 100.0 * max(1e-9, cap)
    ref = float(getattr(config, "MONITORING_SCORE_NORM_LOG_REF", 25000) or 0)
    denom = math.log1p(ref) if ref > 0 else 0.0
    if denom <= 0:
        return panel
    return math.expm1(panel / 100.0 * denom)


def normalize_score(raw_score: float) -> float:
    """Ham velocity_score → panel (0-100)."""
    return _panel_from_raw(raw_score)


def _radar_family_bonus(c: dict) -> tuple[float, list[str]]:
    """Faz 3.2 ENSEMBLE AİLE BONUSU (2026-10-14, docs/radar-improvement-analysis.md).

    Korelasyonsuz 3 kanıt ailesi, her biri +2 (toplam cap +6):
      * flow      : taker alıcı payı güçlü VEYA emir defteri alış baskın (>0.15)
      * proximity : 1 saatlik aralık konumu ≥0.9 (tepe yenileme bölgesi;
                    George&Hwang 2004 zirve-yakınlık etkisi)
      * clean     : rejim chop DEĞİL VE geç faz DEĞİL VE spread bilinmiyor DEĞİL
    Kanıt YOKSA (sentetik/test satırlarında `radar` alanı yoktur) bonus 0 —
    mevcut puanlama davranışı birebir korunur.
    """
    radar = c.get("radar") if isinstance(c.get("radar"), dict) else {}
    if not radar:
        return 0.0, []
    bonus = 0.0
    fam: list[str] = []
    if radar.get("taker_confirm") == "strong" or float(radar.get("book_imbalance") or 0) > 0.15:
        bonus += 2.0
        fam.append("flow")
    if float(radar.get("range_pos_60") or 0) >= 0.9:
        bonus += 2.0
        fam.append("proximity")
    if not radar.get("regime_chop") and not radar.get("late_phase") and not radar.get("spread_unknown"):
        bonus += 2.0
        fam.append("clean")
    return min(6.0, bonus), fam


def _combined_quality_score(c: dict) -> tuple[float, int, int]:
    """Kombine KALİTE PUANI (0-99, doygunluğa GİRMEZ).

    Bileşenler:
      * velocity panel skoru (0-100)           : ağırlık %60
      * çok-kaynak teyidi (0..3 motor)         : her kaynak +8 (max +24)
      * Master Surge katman sayısı (0..4)      : her katman +4 (max +16)
      * radar aile bonusu (Faz 3.2, 0..+6)     : kanıta dayalı ensemble
    Üst sınır 99 → "100 = kesin garanti" yanılgısı oluşmaz.

    Döner: (puan, teyit_motor_sayısı, surge_katman_sayısı).
    """
    panel = normalize_score(c.get("velocity_score", 0))
    sources = len([s for s in (c.get("unified_sources") or []) if s])
    ms = c.get("master_surge") if isinstance(c.get("master_surge"), dict) else {}
    layers = int(ms.get("confluence_count") or 0)
    fam_bonus, _fam = _radar_family_bonus(c)
    score = panel * 0.6 + min(3, sources) * 8 + min(4, layers) * 4 + fam_bonus
    return round(min(99.0, max(0.0, score)), 1), sources, layers


def dedup_rows_by_symbol(rows: list[dict]) -> list[dict]:
    """2026-10-15 (radar düzeltmesi): kombine liste SEMBOL bazında tekildir.

    `combined_scan_rows` (sembol, ufuk) satırları üretir; gönderilen TOP N'de
    aynı sembol 5m+15m olarak iki yer kapamasın. Sembol başına en yüksek
    `scan_score`'lu satır kalır; tüm ufuklar `horizons` (artan) listesinde
    rozet olur. Girdi satırları değiştirilmez (kopya döner); sıra en iyi puana
    göre azalan.
    """
    best: dict[str, dict] = {}
    horizons: dict[str, set[int]] = {}
    for row in rows or []:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        try:
            h = int(row.get("horizon_minutes") or 0)
        except (TypeError, ValueError):
            h = 0
        horizons.setdefault(sym, set()).add(h)
        try:
            score = float(row.get("scan_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        cur = best.get(sym)
        if cur is None or score > float(cur.get("scan_score") or 0):
            best[sym] = row
    out = []
    for sym, row in best.items():
        copy = dict(row)
        copy["horizons"] = sorted(h for h in horizons.get(sym, set()) if h > 0) or [0]
        out.append(copy)
    out.sort(key=lambda r: float(r.get("scan_score") or 0), reverse=True)
    return out


def _source_ids(item: dict) -> list[str]:
    known = item.get("signal_sources")
    if isinstance(known, list):
        return [str(source) for source in known if source]
    source = item.get("source_only") or item.get("source") or item.get("strategy")
    if source == "both":
        return ["daily_momentum", "short_squeeze"]
    return [str(source)] if source else []


def _is_both(candidate: dict) -> bool:
    strategy = str(candidate.get("strategy") or "")
    sources = candidate.get("signal_sources") or []
    return strategy == "both" or (isinstance(sources, list) and len(set(str(s) for s in sources)) > 1)


async def combined_scan_rows() -> list[dict]:
    """TÜM radar stratejilerini salt-okunur biçimde birleştirip puan üret.

    Akış: velocity(5/15 + ek ufuklar), günlük momentum, short-squeeze, MACD
    jump/erken/yükseliş, MACD MTF teyidi, yükseliş eğilimi, pulse ve Snapback
    adaylarını ortaklaştırır. Adaylar sembol + ufuk bazında tekilleşir; geçersiz
    Binance TR sembolleri elenir ve kaynak uzlaşısı/kanıtı korunur. Global Radar
    kullanıcıya ayrı kaynak olarak eklenmez. Tavanına ulaşan adaylar `_hit` olur.
    """
    # monitoring.py'den lazy import: modül döngüsünü önler, çağrı anında
    # monitoring.py zaten tamamen yüklenmiş olur.
    from app.routers import monitoring as mo
    from app.binance_tr_public import trading_symbols as _trading_syms
    from app import early_discovery
    from app import macd_mtf
    from app import rising_signals as _rising

    # 2026-10-15 (radar düzeltmesi): tarama anı TEK damga — kendi zaman damgası
    # olmayan kaynak satırları (velocity) bu anı alır; satır başına ayrı
    # `time.time()` üretilmez (journal dedup'ı kovaya göre çalışır).
    scan_started_at = time.time()
    valid_symbols: set[str] = set()
    try:
        tr_syms = [str(symbol).upper() for symbol in await _trading_syms("TRY")]
        valid_symbols.update(tr_syms)
    except Exception:
        tr_syms = []
    try:
        valid_symbols.update(str(symbol).upper() for symbol in await _trading_syms("USDT"))
    except Exception:
        pass
    if not valid_symbols:
        valid_symbols.update(str(symbol).upper() for symbol in (getattr(config, "SYMBOLS", []) or []))

    from app.routers.velocity import _active_horizons as _act_h2
    _extra_h = [h for h in _act_h2() if h not in (5, 15)]
    # 2026-10-15 (radar düzeltmesi): kombine yol KENDİ velocity taramasını
    # `journal_enabled=False` ile koşar — /latest yenilemesi (20 sn) ve manuel
    # tarama kalibrasyon journal'ına (velocity_candidates) kopya YAZMAZ;
    # journal yalnız `monitoring._run_scan` turundan beslenir.
    _gather = [
        mo.detect_velocity_candidates({}, horizon_minutes=5, journal_enabled=False),
        mo.detect_velocity_candidates({}, horizon_minutes=15, journal_enabled=False),
        mo._short_squeeze_candidates(tr_syms),
    ] + [mo.detect_velocity_candidates({}, horizon_minutes=h, journal_enabled=False)
         for h in _extra_h]
    _gather.append(snapback_service.scan_snapback_opportunities())
    _res = await asyncio.gather(*_gather, return_exceptions=True)
    scan5 = _res[0] if isinstance(_res[0], dict) else {}
    scan15 = _res[1] if isinstance(_res[1], dict) else {}
    squeeze = _res[2] if isinstance(_res[2], list) else []
    extra_scans = {h: (_res[3 + i] if isinstance(_res[3 + i], dict) else {})
                   for i, h in enumerate(_extra_h)}
    snapback_result = _res[3 + len(_extra_h)]
    snapback_rows = (snapback_result.get("opportunities") or []) if isinstance(snapback_result, dict) else []
    try:
        pulse_rows = early_discovery.top_candidates(config.DISCOVERY_PULSE_LIMIT) or []
    except Exception as exc:
        logger.debug("kombine: keşif nabzı alınamadı: %s", exc)
        pulse_rows = []
    mom = await mo._daily_momentum_candidates(scan5, scan15)

    rising_rows: list[dict] = []
    try:
        for rc in _rising.detect_rising_candidates():
            sym = str(rc.get("symbol") or "").upper()
            if not sym:
                continue
            # 2026-10-15 (radar düzeltmesi): rising skoru 0-100 PANEL ölçeğidir;
            # ham alana `_raw_from_panel` ile yazılır (ikinci log-normalize yok).
            _rising_panel = max(0.0, min(100.0, float(rc.get("score") or 0.0)))
            rising_rows.append({
                "symbol": sym,
                "strategy": "rising",
                "horizon_minutes": int(rc.get("horizon_minutes") or 5),
                "velocity_score": _raw_from_panel(_rising_panel),
                "panel_score": _rising_panel,
                "rising_score": float(rc.get("score") or 0.0),
                "target_pct": rc.get("target_pct"),
                "rising_kind": rc.get("kind"),
                "green": rc.get("green"),
                "price": rc.get("price"),
                "source_only": "rising",
                # 2026-10-15 (radar düzeltmesi): rising'in kendi tespit zamanı.
                "detected_at": rc.get("detected_at"),
            })
    except Exception as exc:
        logger.debug("kombine: yükseliş adayları alınamadı: %s", exc)

    pulse_candidates: list[dict] = []
    for pulse in pulse_rows:
        symbol = str(pulse.get("symbol") or "").upper()
        try:
            return_1m = float(pulse.get("return_1m_pct") or 0)
            volume_burst = float(pulse.get("volume_burst") or 0)
        except (TypeError, ValueError):
            continue
        if not symbol or return_1m <= 0:
            continue
        pulse_score = max(35.0, min(99.0, 50.0 + return_1m * 8.0 + min(max(volume_burst - 1.0, 0.0), 5.0) * 3.0))
        pulse_candidates.append({
            "symbol": symbol, "strategy": "pulse", "source_only": "pulse",
            "horizon_minutes": 5, "price": pulse.get("price"),
            "velocity_score": _raw_from_panel(pulse_score), "panel_score": pulse_score,
            "source_evidence": {"return_1m_pct": return_1m,
                                "return_20s_pct": pulse.get("return_20s_pct"),
                                "volume_burst": volume_burst,
                                "sample_age_sec": pulse.get("sample_age_sec")},
        })

    snapback_candidates: list[dict] = []
    for snapback in snapback_rows:
        symbol = str(snapback.get("symbol") or "").upper()
        try:
            panel_score = float(snapback.get("quality_score") or 0)
        except (TypeError, ValueError):
            continue
        if not symbol or panel_score <= 0:
            continue
        snapback_candidates.append({
            "symbol": symbol, "strategy": "snapback", "source_only": "snapback",
            "horizon_minutes": 60, "price": snapback.get("current_price"),
            "velocity_score": _raw_from_panel(panel_score), "panel_score": panel_score,
            "stop_loss": snapback.get("stop_loss"),
            "stop_loss_pct": snapback.get("stop_loss_pct"),
            "source_evidence": {"rsi7": snapback.get("rsi7"),
                                "rsi14": snapback.get("rsi14"),
                                "grade": snapback.get("grade"),
                                "macro_regime": snapback.get("macro_regime"),
                                "stop_loss": snapback.get("stop_loss"),
                                "stop_loss_pct": snapback.get("stop_loss_pct")},
        })

    pool: list[dict] = []
    for src in [scan5, scan15, *extra_scans.values()]:
        pool.extend(src.get("candidates") or [])
        pool.extend(src.get("watchlist") or [])
    pool.extend(mom)
    pool.extend(squeeze)
    pool.extend(rising_rows)
    pool.extend(pulse_candidates)
    pool.extend(snapback_candidates)

    by_key: dict[tuple[str, int], dict] = {}
    for candidate in pool:
        symbol = str(candidate.get("symbol") or "").upper()
        if not symbol:
            continue
        # 2026-10-15 (radar düzeltmesi): HER kaynak satırı panel (0-100) taşır
        # — velocity satırları ham skorla gelir; `_rank` yalnız panel kıyaslar.
        if candidate.get("panel_score") is None:
            candidate["panel_score"] = normalize_score(candidate.get("velocity_score"))
        try:
            horizon = int(candidate.get("horizon_minutes") or 0)
        except (TypeError, ValueError):
            horizon = 0
        key = (symbol, horizon)
        current = by_key.get(key)
        if current is None:
            candidate["signal_sources"] = _source_ids(candidate)
            by_key[key] = candidate
            continue
        merged_sources = list(dict.fromkeys(_source_ids(current) + _source_ids(candidate)))

        def _rank(item: dict) -> float:
            # 2026-10-15 (radar düzeltmesi): YALNIZ panel — ham velocity_score
            # (300) ile panel (70) kıyaslanmaz.
            try:
                return float(item.get("panel_score") or 0)
            except (TypeError, ValueError):
                return 0.0

        chosen = candidate if _rank(candidate) > _rank(current) else current
        chosen["signal_sources"] = merged_sources
        if len(merged_sources) > 1:
            chosen["strategy"] = "both"
        by_key[key] = chosen
    merged = list(by_key.values())

    try:
        fusion_only = unified_signals.enrich_candidates(merged) or []
    except Exception as exc:
        logger.debug("kombine füzyon zenginleştirme: %s", exc)
        fusion_only = []
    seen: set[tuple[str, int]] = set()
    for candidate in merged:
        try:
            seen.add((str(candidate.get("symbol") or "").upper(), int(candidate.get("horizon_minutes") or 0)))
        except (TypeError, ValueError):
            seen.add((str(candidate.get("symbol") or "").upper(), 0))
    for candidate in fusion_only:
        symbol = str(candidate.get("symbol") or "").upper()
        try:
            horizon = int(candidate.get("horizon_minutes") or 0)
        except (TypeError, ValueError):
            horizon = 0
        key = (symbol, horizon)
        if symbol and key not in seen:
            candidate["signal_sources"] = _source_ids(candidate)
            merged.append(candidate)
            seen.add(key)
    for candidate in merged:
        candidate["unified_sources"] = list(dict.fromkeys(
            [str(source) for source in (candidate.get("unified_sources") or []) if source]
            + _source_ids(candidate)
        ))

    _today_mfe: dict[tuple[str, int], float] = {}
    try:
        for r in await mo._today_rising_rows(limit=200):
            sym = str(r.get("symbol") or "").upper()
            if r.get("mfe_pct") is not None:
                try:
                    horizon = int(r.get("horizon_minutes") or 0)
                except (TypeError, ValueError):
                    horizon = 0
                key = (sym, horizon)
                prev = _today_mfe.get(key)
                if prev is None or float(r["mfe_pct"]) > prev:
                    _today_mfe[key] = float(r["mfe_pct"])
    except Exception:
        pass

    out: list[dict] = []
    for c in merged:
        sym = str(c.get("symbol") or "").upper()
        if not sym or (valid_symbols and sym not in valid_symbols) or sym in analyzer.positions:
            continue
        try:
            price = float(mo._ticker_price(sym) or c.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            continue
        ceil_pct = c.get("ceiling_pct")
        if ceil_pct is None:
            atr_live = await mo._live_atr_pct(sym)
            if atr_live:
                try:
                    _t = master_surge.calculate_adaptive_targets(70.0, atr_pct=atr_live, base_target_pct=3.0)
                    ceil_pct = round(max(float(_t.get("tp2_runner_pct") or 0), atr_live * 3.0), 2)
                except Exception:
                    ceil_pct = round(atr_live * 3.0, 2)
        if c.get("potential_pct") is None:
            pot = await mo._compute_potential(sym, price)
            if pot:
                c["potential_pct"] = pot.get("potential_pct")
                c["potential_price"] = pot.get("potential_price")
        atr_pct = c.get("atr_pct_15m") or c.get("atr_pct")
        prob = c.get("target_probability")
        if prob is None:
            prob = mo.touch_probability(ceil_pct, atr_pct)
        hit = False
        try:
            mfe = _today_mfe.get((sym, int(c.get("horizon_minutes") or 0)))
            if mfe is None:
                mfe = _today_mfe.get((sym, 0))
            if mfe is not None and ceil_pct is not None and float(mfe) >= float(ceil_pct):
                hit = True
        except (TypeError, ValueError):
            hit = False
        mtf = macd_mtf.cached_compact(sym)
        if mtf:
            try:
                if float(mtf.get("age_sec") or 0) > 180:
                    mtf = None
                elif float(mtf.get("confluence") or 0) >= 45:
                    c["unified_sources"] = list(dict.fromkeys(
                        list(c.get("unified_sources") or []) + ["macd_mtf"]
                    ))
            except (TypeError, ValueError):
                mtf = None
        quality, tc_sources, tc_layers = _combined_quality_score(c)
        _fam_bonus, _fam_list = _radar_family_bonus(c)
        # 2026-10-15 (radar düzeltmesi): `_notify` ile AYNI kapı. Süzülen satır
        # listeden DÜŞMEZ — `blocked_by` ile UI'da gri kalır; gönderilen TOP N
        # ve combined_paper bu satırları almaz (monitoring._send_combined_list).
        blocked_by = mo.gate_candidate(c)
        signal_sources = list(dict.fromkeys(
            [str(source) for source in (c.get("signal_sources") or []) if source]
            + [str(source) for source in (c.get("unified_sources") or []) if source]
        ))
        row = {
            "symbol": sym, "price": price,
            "change_pct": (c.get("source_evidence") or {}).get("return_1m_pct"),
            "return_1m_pct": (c.get("source_evidence") or {}).get("return_1m_pct"),
            "volume_burst": (c.get("source_evidence") or {}).get("volume_burst"),
            # 2026-10-15 (radar düzeltmesi): GERÇEK sinyal zamanı — adayın
            # kendi damgası (`detected_at`/`created_at`/kanıt), yoksa tarama anı.
            "detected_at": (c.get("detected_at") or c.get("created_at")
                            or (c.get("source_evidence") or {}).get("detected_at")
                            or scan_started_at),
            "target_pct": c.get("target_pct"),
            "horizon_minutes": c.get("horizon_minutes"),
            "ceiling_pct": ceil_pct,
            "ceiling_price": c.get("ceiling_price") or (
                round(price * (1 + float(ceil_pct) / 100.0), 8) if ceil_pct else None),
            "potential_pct": c.get("potential_pct"),
            "potential_price": c.get("potential_price"),
            "target_probability": prob,
            "scan_score": quality,
            "quality_score": quality,
            "confirm_sources": tc_sources,
            "confirm_layers": tc_layers,
            "signal_sources": signal_sources,
            "supporting_sources": ["macd_mtf"] if mtf and mtf.get("verdict") == "GÜÇLÜ" else [],
            "opposing_sources": c.get("opposing_sources") or [],
            "source_evidence": c.get("source_evidence") or {},
            "macd_mtf": mtf,
            "stop_loss": c.get("stop_loss"),
            "stop_loss_pct": c.get("stop_loss_pct"),
            "unified_score": c.get("unified_score"),
            "unified_sources": c.get("unified_sources"),
            "strategy": c.get("strategy") or "combined",
            "velocity_score": c.get("velocity_score"),
            # 2026-10-15 (radar düzeltmesi): panel (0-100) UI/liste için açık alan.
            "panel_score": c.get("panel_score"),
            "ret_8h_pct": c.get("ret_8h_pct"),
            "adx_14": c.get("adx_14"),
            "slope_15m": c.get("slope_15m"),
            "atr_pct_15m": atr_pct,
            "master_surge_block": (c.get("master_surge") or {}).get("block_reason") if isinstance(c.get("master_surge"), dict) else None,
            "confluence_4way": bool(c.get("confluence_4way")),
            # Radar güçlendirme (Faz 1/3, 2026-10-14): kanıt bayrakları + aile
            # listesi + emir defteri dengesizliği (sıralama tie-breaker'ı).
            "radar": c.get("radar"),
            "radar_families": _fam_list,
            "blocked_by": blocked_by,
            "_hit": hit,
        }
        out.append(row)

    # Bloklu satırlar temiz satırların ARKASINA (2026-10-15 radar düzeltmesi).
    out.sort(key=lambda r: (not r.get("blocked_by"), float(r.get("scan_score") or 0), _is_both(r),
                            (r.get("radar") or {}).get("book_imbalance") or 0.0),
             reverse=True)
    return out


__all__ = [
    "MONITORING_SCORE_NORM_VERSION",
    "normalize_score",
    "_raw_from_panel",
    "_panel_from_raw",
    "_combined_quality_score",
    "_radar_family_bonus",
    "combined_scan_rows",
    "dedup_rows_by_symbol",
]
