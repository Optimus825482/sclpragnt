"""Bildirim politikası — ortak lavabo (sink) kapısı.

2026-10-16 (sinyal politikası): docs/BACKTEST_RAPORU_7G_2026-10-16.md §7 (30 gün):
hit60 — trend_devam %53,6, global_lead_lag %38,5, unified %32,8 (skor ≥95 çok daha iyi),
notr %41,1 (eşleşen şans %45,9'un ALTINDA), llm_ikinci_goz %22,1, v_donusu %19,0 (n=21).
Skor yalnız TABAN olarak çalışır (95+ %54,4; 85–95 %36,7).

Politika:
  * `RADAR_NOTIFY_DISABLED_MODES` içindeki modlar bildirilmez (vars. notr,v_donusu,llm_ikinci_goz).
  * `unified` modu yalnız panel skoru >= `RADAR_NOTIFY_UNIFIED_MIN_SCORE` (vars. 95; 0 = kapalı).
  * `RADAR_NOTIFY_POLICY_ENABLED=0` → tam geçiş (passthrough).

`evaluate` saf fonksiyondur (yalnız config okur); `apply` sayaçları günceller.
Ayarlar ÇAĞRI ANINDA okunur (`config` sınıf nitelikleri) — testte yama yapılabilir.
Kayıt: docs/DENEY_KAYDI.md. Uygulama noktası: `database.save_monitoring_notifications`.
"""
from __future__ import annotations

import threading
from collections import deque

_PANEL_MAX = 100.0  # panel ölçeği tavanı; üstü = eski ham ölçek (bilinmeyen)
_lock = threading.Lock()
_stats: dict = {"kept": 0, "blocked": 0, "by_reason": {}, "recent": deque(maxlen=20)}


def _cfg(name: str, default):
    try:
        from app.config import config
        return getattr(config, name, default)
    except Exception:
        return default


def _enabled() -> bool:
    raw = _cfg("RADAR_NOTIFY_POLICY_ENABLED", True)
    if isinstance(raw, str):
        return raw.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(raw)


def _disabled_modes() -> set[str]:
    raw = _cfg("RADAR_NOTIFY_DISABLED_MODES", "notr,v_donusu,llm_ikinci_goz")
    if isinstance(raw, (list, tuple, set, frozenset)):
        items = raw
    else:
        items = str(raw or "").split(",")
    return {str(m).strip().lower() for m in items if str(m).strip()}


def _unified_min_score() -> float:
    try:
        return max(0.0, float(_cfg("RADAR_NOTIFY_UNIFIED_MIN_SCORE", 95.0)))
    except (TypeError, ValueError):
        return 95.0


def _flag(name: str, default: bool) -> bool:
    raw = _cfg(name, default)
    if isinstance(raw, str):
        return raw.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(raw)


def _csv_set(name: str, default: str) -> set[str]:
    raw = _cfg(name, default)
    items = raw if isinstance(raw, (list, tuple, set, frozenset)) else str(raw or "").split(",")
    return {str(m).strip().lower() for m in items if str(m).strip()}


def sources_of(entry: dict) -> set[str]:
    """Bildirimin FARKLI teyit kaynakları (küçük harf). Liste, JSON metni ya da virgüllü metin kabul edilir."""
    raw = entry.get("sources") if isinstance(entry, dict) else None
    if raw is None or raw == "":
        return set()
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                import json
                raw = json.loads(text)
            except (TypeError, ValueError):
                raw = text.strip("[]").replace('"', "").split(",")
        else:
            raw = text.split(",")
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return set()
    return {str(s).strip().lower() for s in raw if str(s).strip()}


def confirm_rule_reason(entry: dict) -> str | None:
    """2026-10-17 TEYİT KURALI (config RADAR_NOTIFY_CONFIRM_*): ihlal varsa neden, yoksa None."""
    if not _flag("RADAR_NOTIFY_CONFIRM_RULE_ENABLED", True):
        return None
    srcs = sources_of(entry)
    try:
        min_n = max(1, int(_cfg("RADAR_NOTIFY_MIN_SOURCES", 2)))
    except (TypeError, ValueError):
        min_n = 2
    if len(srcs) < min_n:
        return f"teyit yetersiz ({len(srcs)} < {min_n} kaynak)"
    required = str(_cfg("RADAR_NOTIFY_REQUIRED_SOURCE", "velocity") or "").strip().lower()
    if required and required not in srcs:
        return f"teyit kuralı: {required} kaynağı yok"
    mode = str(entry.get("mode") or "").strip().lower()
    if mode and mode in _csv_set("RADAR_NOTIFY_CONFIRM_EXCLUDED_MODES", "unified"):
        return f"teyit kuralı: mod {mode} hariç"
    return None


TIER_SINGLE = "tek_kaynak"
TIER_HEARTBEAT = "teyitsiz"
TIER_PREFIX = {TIER_SINGLE: "TEK KAYNAK · ", TIER_HEARTBEAT: "TEYİTSİZ · "}


def _single_source_min_score() -> float:
    try:
        return max(0.0, float(_cfg("RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _score_of(entry: dict) -> float | None:
    try:
        s = float(entry.get("score"))
    except (TypeError, ValueError):
        return None
    return s if s == s else None


def single_source_tier_ok(entry: dict) -> bool:
    """2026-10-18 İKİNCİ KADEME: YALNIZ gerekli kaynak (Hız) ∧ panel skoru ≥ taban ∧ mod hariç değil.

    Yalnız "teyit yetersiz" nedeniyle takılan adaylar içindir; kapalı mod / unified tabanı /
    `velocity yok` nedenlerini aşmaz. Taban 0 → kademe kapalı.
    """
    floor = _single_source_min_score()
    if floor <= 0 or not isinstance(entry, dict):
        return False
    required = str(_cfg("RADAR_NOTIFY_REQUIRED_SOURCE", "velocity") or "").strip().lower()
    if not required or sources_of(entry) != {required}:
        return False
    score = _score_of(entry)
    if score is None or score > _PANEL_MAX or score < floor:
        return False
    mode = str(entry.get("mode") or "").strip().lower()
    if mode and (mode in _disabled_modes() or mode in _csv_set("RADAR_NOTIFY_CONFIRM_EXCLUDED_MODES", "unified")):
        return False
    return True


def mark_tier(entry: dict, tier: str) -> None:
    """Kademeyi bildirime işler ve başlığa öneki (tek sefer) ekler — kayıt ve push aynı başlığı taşır."""
    entry["notify_tier"] = tier
    prefix = TIER_PREFIX.get(tier, "")
    title = str(entry.get("title") or "")
    if prefix and not title.startswith(prefix):
        entry["title"] = prefix + title


def heartbeat_pick(blocked_entries, now: float, last_push_ts: float | None) -> dict | None:
    """2026-10-18 SESSİZLİK NABZI: nabız süresi dolduysa, yalnız TEYİT nedeniyle takılan en yüksek skorlu aday.

    Saf: hiçbir şeyi değiştirmez. `last_push_ts` None → nabız sayacı başlamamış (boot) → None.
    Kapalı mod, unified taban ve "mod unified hariç" nedenleri aday olmaz (ölçümde isabet %3).
    """
    try:
        minutes = int(_cfg("RADAR_NOTIFY_HEARTBEAT_MINUTES", 0) or 0)
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0 or last_push_ts is None or (now - float(last_push_ts)) < minutes * 60:
        return None
    best = None
    best_score = -1.0
    for e in blocked_entries or []:
        if not isinstance(e, dict):
            continue
        reason = str(e.get("policy_blocked") or "")
        if not (reason.startswith("teyit yetersiz") or reason.startswith("teyit kuralı: ") and "kaynağı yok" in reason):
            continue
        score = _score_of(e)
        if score is None:
            continue
        if score > best_score:
            best, best_score = e, score
    return best


def shadow_match(entry: dict) -> str | None:
    """GÖLGE kural (yalnız kayıt): ≥2 kaynak ∧ mod = trend_devam → kural adı, aksi halde None."""
    if not isinstance(entry, dict) or not _flag("RADAR_NOTIFY_SHADOW_RULE_ENABLED", True):
        return None
    if len(sources_of(entry)) >= 2 and str(entry.get("mode") or "").strip().lower() == "trend_devam":
        return "ge2_trend_devam"
    return None


def evaluate(entry: dict) -> str | None:
    """Bloklanacaksa Türkçe neden, aksi halde None."""
    if not _enabled() or not isinstance(entry, dict):
        return None
    # 2026-10-18: nabız seçimi (monitoring tarafından işaretlenir) lavaboda yeniden bloklanmaz.
    if entry.get("notify_tier") == TIER_HEARTBEAT:
        return None
    mode = str(entry.get("mode") or "").strip().lower()
    if mode and mode in _disabled_modes():
        return f"mod devre dışı: {mode}"
    if mode == "unified":
        floor = _unified_min_score()
        if floor > 0:
            try:
                score = float(entry.get("score"))
            except (TypeError, ValueError):
                score = None  # skor yok → ölçek bilinmiyor, skora göre bloklama
            if score is not None and score == score and score <= _PANEL_MAX and score < floor:
                return f"unified skor tabanı altı ({score:.1f} < {floor:g})"
    reason = confirm_rule_reason(entry)
    # 2026-10-18 İKİNCİ KADEME: yalnız "teyit yetersiz" takılması, tek kaynaklı yüksek skorlu Hız'da aşılır.
    if reason and reason.startswith("teyit yetersiz") and single_source_tier_ok(entry):
        mark_tier(entry, TIER_SINGLE)
        return None
    return reason


def shadow_rows(entries) -> list[dict]:
    """Gölge kurala uyan bildirimler için kayıt satırları (canlı karar dahil). Saf; DB yazmaz."""
    import time as _time
    rows: list[dict] = []
    for e in entries or []:
        rule = shadow_match(e)
        if not rule:
            continue
        rows.append({
            "detected_at": float(e.get("detected_at") or _time.time()),
            "symbol": str(e.get("symbol") or "").upper(),
            "price": e.get("price"), "target_pct": e.get("target_pct"),
            "expected_price": e.get("expected_price"),
            "horizon_minutes": e.get("horizon_minutes"), "mode": e.get("mode"),
            "sources": ",".join(sorted(sources_of(e))), "score": e.get("score"),
            "live_blocked_reason": e.get("policy_blocked") or evaluate(e) or "",
            "shadow_rule": rule,
        })
    return rows


def apply(entries) -> tuple[list, list]:
    """(kept, blocked) döner; blocked = [(entry, neden), ...]. Sayaçları günceller."""
    kept: list = []
    blocked: list = []
    for e in entries or []:
        reason = evaluate(e)
        if reason is None:
            kept.append(e)
        else:
            blocked.append((e, reason))
    if entries:
        with _lock:
            _stats["kept"] += len(kept)
            _stats["blocked"] += len(blocked)
            for e, reason in blocked:
                key = reason.split(" (")[0]
                if key.startswith("mod devre dışı"):
                    key = reason
                _stats["by_reason"][key] = _stats["by_reason"].get(key, 0) + 1
                _stats["recent"].append({
                    "symbol": e.get("symbol"), "mode": e.get("mode"),
                    "score": e.get("score"), "reason": reason,
                })
    return kept, blocked


def precheck(entries) -> list:
    """Kalıcı yazım OLMADAN politika ön kontrolü (2026-10-17, panel bildirimi kaldırıldı).

    Bildirim satırı artık YALNIZ push denendiğinde yazılır (`database.save_monitoring_notifications`
    push'tan hemen önce çağrılır). Ama otonom paper / teslim yolları politika kararını daha
    erken bilmek zorunda: bloklananlara `policy_blocked` nedeni işlenir (`apply` ile AYNI
    `evaluate`). `kept` sayacı ARTMAZ (satır henüz yazılmadı; yazıldığında `apply` sayar);
    `blocked` sayacı artar — bloklanan satır hiçbir zaman `save`'e ulaşmayacağı için çift
    sayım olmaz. Dönüş: [(entry, neden), ...] (bloklananlar).
    """
    blocked: list = []
    for e in entries or []:
        reason = evaluate(e)
        if reason is not None:
            e["policy_blocked"] = reason
            blocked.append((e, reason))
    if blocked:
        with _lock:
            _stats["blocked"] += len(blocked)
            for e, reason in blocked:
                key = reason.split(" (")[0]
                if key.startswith("mod devre dışı"):
                    key = reason
                _stats["by_reason"][key] = _stats["by_reason"].get(key, 0) + 1
                _stats["recent"].append({
                    "symbol": e.get("symbol"), "mode": e.get("mode"),
                    "score": e.get("score"), "reason": reason,
                })
    return blocked


def get_stats() -> dict:
    with _lock:
        return {
            "enabled": _enabled(),
            "kept": _stats["kept"],
            "blocked": _stats["blocked"],
            "by_reason": dict(_stats["by_reason"]),
            "recent": list(_stats["recent"]),
        }


def reset_stats() -> None:
    with _lock:
        _stats.update(kept=0, blocked=0, by_reason={})
        _stats["recent"].clear()
