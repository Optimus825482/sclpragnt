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


def evaluate(entry: dict) -> str | None:
    """Bloklanacaksa Türkçe neden, aksi halde None."""
    if not _enabled() or not isinstance(entry, dict):
        return None
    mode = str(entry.get("mode") or "").strip().lower()
    if not mode:
        return None
    if mode in _disabled_modes():
        return f"mod devre dışı: {mode}"
    if mode == "unified":
        floor = _unified_min_score()
        if floor > 0:
            try:
                score = float(entry.get("score"))
            except (TypeError, ValueError):
                return None  # skor yok → ölçek bilinmiyor, bloklama
            if score != score or score > _PANEL_MAX:
                return None  # NaN / eski ham ölçek → skora göre bloklama
            if score < floor:
                return f"unified skor tabanı altı ({score:.1f} < {floor:g})"
    return None


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
