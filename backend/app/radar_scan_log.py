"""Radar tarama günlüğü (yalnız yönetici penceresi; karar/emir/bildirim davranışına DOKUNMAZ).

2026-10-18 (kullanıcı isteği): "radar tarama loglarını gör — tarama sonucunda tespit edilenler ve elenme nedenleri,
renkli rozetli". Her `monitoring._run_scan` turu sonunda tek bir kayıt tutulur: taranan HER sembolün durumu
(bildirildi / tespit edildi / kapıya takıldı / eşik altı / açık pozisyon / izlemede / elendi / veri yok) ve nedeni.

Bellek içi halka tampon (`ADMIN_SCAN_LOG_KEEP`, varsayılan 60 tur ≈ 30 dk). Restart'ta sıfırlanır — bilinçli: bu bir
canlı teşhis aracıdır, kalıcı kayıt değildir. Girdiler saf sözlüklerdir; kapı fonksiyonu dışarıdan verilir (test edilebilir).
"""
from __future__ import annotations

import re
import threading
from collections import deque
from typing import Callable, Iterable

# durum -> (etiket, ton). Ton: success | info | warn | caution | danger | muted | neutral
STATUS_CATALOG = (
    ("notified", "Bildirildi", "success"),
    ("detected", "Tespit edildi", "info"),
    ("held", "Bildirilmedi", "warn"),
    ("gated", "Kapıya takıldı", "warn"),
    ("below_threshold", "Eşik altı", "muted"),
    ("open_position", "Açık pozisyon", "muted"),
    ("watch", "İzlemede", "caution"),
    ("rejected", "Elendi", "danger"),
    ("no_data", "Veri yok", "neutral"),
)
_STATUS_META = {s: (label, tone) for s, label, tone in STATUS_CATALOG}
_STATUS_ORDER = {s: i for i, (s, _l, _t) in enumerate(STATUS_CATALOG)}

# neden kodu -> (etiket, ton)
REASON_META = {
    "atr_yetersiz": ("ATR yetersiz", "caution"),
    "bb_genisligi_yetersiz": ("BB dar", "caution"),
    "bb_verisi_yok": ("BB verisi yok", "neutral"),
    "yapisal_teyit_yok": ("Yapı teyidi yok", "caution"),
    "ust_fitil_tuzagi": ("Üst fitil tuzağı", "danger"),
    "mfi_asiri_alim": ("MFI aşırı alım", "danger"),
    "mfi_asiri_satim": ("MFI aşırı satım", "danger"),
    "rsi_asiri_alim": ("RSI aşırı alım", "danger"),
    "asiri_spread": ("Spread yüksek", "danger"),
    "master_surge_katman1": ("Likidite (katman 1)", "danger"),
    "skor_tabani": ("Skor tabanı altı", "warn"),
    "skor_esigi": ("Skor eşiği altı", "muted"),
    "aile_devre_disi": ("Aile devre dışı", "neutral"),
    "radar_kapisi_gecilmedi": ("Radar kapısı", "warn"),
    "extreme_long": ("Aşırı şişkin long", "danger"),
    "btc_panik": ("BTC panik", "danger"),
    "diger": ("Diğer", "neutral"),
    # bildirim aşaması (aday kapıyı geçti ama push üretilmedi)
    "teyit_yetersiz": ("Teyit yetersiz", "caution"),
    "teyit_kurali": ("Teyit kuralı", "caution"),
    "mod_devre_disi": ("Mod devre dışı", "muted"),
    "unified_skor_tabani": ("Unified skor tabanı", "muted"),
    "sembol_soguma": ("Sembol soğuma", "muted"),
    "gunluk_tavan": ("Günlük tavan", "muted"),
    "bildirim_zaten_gonderildi": ("Zaten bildirildi", "info"),
    "beklenen_fiyata_ulasilmadi": ("Ufuk dolmadı", "info"),
    "debounce": ("Debounce", "muted"),
    "fiyat_son_bildirimden_beri_yeterince_degismedi": ("Fiyat değişmedi", "muted"),
    "risk_odul_kapisi": ("Risk/ödül kapısı", "warn"),
    "macd_histerezisi": ("MACD histerezisi", "muted"),
    "yalniz_hiz_adayi_izleme_listesine_alindi": ("Yalnız-hız adayı", "muted"),
    # otonom paper giriş sonucu (bildirildi satırlarında)
    "paper_acildi": ("Paper açıldı", "success"),
    "paper_guncellendi": ("Paper TP güncellendi", "info"),
    "paper_engellendi": ("Paper engellendi", "warn"),
    "paper_denenmedi": ("Paper denenmedi", "muted"),
}

_SLUG_RE = re.compile(r"[^a-z0-9_]+")
_TR_MAP = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ö": "o", "Ö": "o",
                         "ç": "c", "Ç": "c"})

_lock = threading.Lock()
_log: deque = deque(maxlen=60)


def _keep() -> int:
    try:
        from app.config import config
        return max(5, min(500, int(getattr(config, "ADMIN_SCAN_LOG_KEEP", 60) or 60)))
    except Exception:  # noqa: BLE001
        return 60


def reason_code(text) -> str | None:
    """Ham neden metni -> kısa kod. 'atr_yetersiz:0.20%<0.25%' -> atr_yetersiz; 'skor tabanı altı (65 < 70)' -> skor_tabani."""
    raw = str(text or "").strip()
    if not raw:
        return None
    low = raw.lower().translate(_TR_MAP)
    if low.startswith("skor tabani"):
        return "skor_tabani"
    if low.startswith("skor esigi"):
        return "skor_esigi"
    if low.startswith("aile devre"):
        return "aile_devre_disi"
    head = re.split(r"[:(]", low, maxsplit=1)[0].strip()
    head = _SLUG_RE.sub("_", head).strip("_")
    return head or "diger"


def reason_info(text) -> dict:
    """{'reason', 'reason_code', 'reason_label', 'reason_tone'}; metin yoksa hepsi None."""
    code = reason_code(text)
    if not code:
        return {"reason": None, "reason_code": None, "reason_label": None, "reason_tone": None}
    label, tone = REASON_META.get(code, (code.replace("_", " "), "neutral"))
    return {"reason": str(text), "reason_code": code, "reason_label": label, "reason_tone": tone}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _round(v, nd=3):
    f = _num(v)
    return round(f, nd) if f is not None else None


def _row(symbol: str, status: str, *, reason=None, audit: dict | None = None, panel_score=None, horizon=None,
         horizons: dict | None = None, notified: bool = False, target_pct=None) -> dict:
    label, tone = _STATUS_META[status]
    a = audit or {}
    out = {
        "symbol": symbol, "status": status, "tone": tone, "label": label,
        **reason_info(reason),
        "panel_score": _round(panel_score, 1), "horizon": horizon, "price": _num(a.get("price")),
        "atr_pct": _round(a.get("atr_pct")), "rsi": _round(a.get("rsi"), 1), "mfi": _round(a.get("mfi"), 1),
        "ret3_pct": _round(a.get("ret3_pct")), "volume_ratio": _round(a.get("volume_ratio"), 2), "mode": a.get("mode"),
        "target_pct": _round(target_pct if target_pct is not None else a.get("target_pct")),
        "notified": bool(notified), "horizons": horizons or {},
    }
    return out


def build_entry(*, scan_no: int, scan_at: float, scans: dict, candidates: Iterable[dict], watchlist: Iterable[dict],
                notified_symbols: Iterable[str], open_symbols: Iterable[str], gate: Callable[[dict], str | None],
                panel: Callable[[float], float], min_panel_score: float | None, min_raw_score: float | None,
                risk_off: bool = False, risk_off_unknown: bool = False, skip_reasons: dict | None = None,
                notify_context: dict | None = None) -> dict:
    """Bir tarama turunun günlük kaydı. `scans`: {ufuk_dk: velocity sonucu (scan_audit / no_data_symbols taşır)}."""
    notified = {str(s or "").upper() for s in notified_symbols}
    skips = {str(k or "").upper(): v for k, v in (skip_reasons or {}).items()}
    opens = {str(s or "").upper() for s in open_symbols}
    cand_by_sym = {str(c.get("symbol") or "").upper(): c for c in candidates if isinstance(c, dict)}
    watch_syms = {str(w.get("symbol") or "").upper() for w in watchlist if isinstance(w, dict)}

    by_sym: dict[str, dict[int, dict]] = {}
    no_data: set[str] = set()
    pool: dict[str, int] = {}
    for h, scan in sorted((scans or {}).items()):
        if not isinstance(scan, dict):
            continue
        pool[str(h)] = int(scan.get("symbols_scanned") or 0)
        for a in scan.get("scan_audit") or []:
            sym = str(a.get("symbol") or "").upper()
            if sym:
                by_sym.setdefault(sym, {})[int(h)] = a
        for sym in scan.get("no_data_symbols") or []:
            no_data.add(str(sym).upper())

    rows: list[dict] = []
    for sym, per_h in by_sym.items():
        best_h, best = max(per_h.items(), key=lambda kv: (bool(kv[1].get("passes")), _num(kv[1].get("velocity_score")) or 0.0))
        horizons = {str(h): {"passes": bool(a.get("passes")), **{k: v for k, v in reason_info(a.get("block_reason")).items()
                                                                   if k in ("reason", "reason_code")}}
                    for h, a in sorted(per_h.items())}
        raw = _num(best.get("velocity_score")) or 0.0
        panel_score = panel(raw) if raw else None
        any_pass = any(bool(a.get("passes")) for a in per_h.values())
        cand = cand_by_sym.get(sym)
        was_notified = sym in notified
        if was_notified:
            row = _row(sym, "notified", audit=best, panel_score=panel_score, horizon=best_h, horizons=horizons,
                       notified=True, target_pct=(cand or {}).get("target_pct"))
        elif any_pass and sym in opens:
            row = _row(sym, "open_position", reason="açık pozisyon (bot yönetiyor)", audit=best, panel_score=panel_score,
                       horizon=best_h, horizons=horizons)
        elif cand is not None:
            blocked = gate(cand)
            if blocked:
                row = _row(sym, "gated", reason=blocked, audit=best, panel_score=panel_score, horizon=best_h, horizons=horizons)
            elif sym in skips:
                row = _row(sym, "held", reason=skips[sym], audit=best, panel_score=panel_score, horizon=best_h,
                           horizons=horizons, target_pct=cand.get("target_pct"))
            else:
                row = _row(sym, "detected", audit=best, panel_score=panel_score, horizon=best_h, horizons=horizons,
                           target_pct=cand.get("target_pct"))
        elif any_pass:
            thr = f"{min_panel_score:.1f}" if min_panel_score is not None else "?"
            ps = f"{panel_score:.1f}" if panel_score is not None else "?"
            row = _row(sym, "below_threshold", reason=f"skor eşiği altı ({ps} < {thr})", audit=best,
                       panel_score=panel_score, horizon=best_h, horizons=horizons)
        else:
            reason = best.get("block_reason") or best.get("warm_reason") or "diger"
            status = "watch" if (sym in watch_syms or best.get("warm")) else "rejected"
            row = _row(sym, status, reason=reason, audit=best, panel_score=panel_score, horizon=best_h, horizons=horizons)
        rows.append(row)

    # Füzyon-tek adaylar velocity denetiminde yoktur (radar kapısını geçemeyip MACD öncüsüyle girenler).
    for sym, cand in cand_by_sym.items():
        if sym in by_sym:
            continue
        blocked = gate(cand)
        status = ("notified" if sym in notified else "gated" if blocked else "held" if sym in skips else "detected")
        rows.append(_row(sym, status, reason=blocked if status == "gated" else skips.get(sym) if status == "held" else None,
                         audit=cand,
                         panel_score=cand.get("unified_score") or cand.get("panel_score"), horizon=None,
                         horizons={}, notified=sym in notified, target_pct=cand.get("target_pct")))

    for sym in sorted(no_data - set(by_sym) - set(cand_by_sym)):
        rows.append(_row(sym, "no_data", reason="kline verisi alınamadı"))

    rows.sort(key=lambda r: (_STATUS_ORDER[r["status"]], -(r["panel_score"] or 0.0), r["symbol"]))
    counts = {s: 0 for s, _l, _t in STATUS_CATALOG}
    for r in rows:
        counts[r["status"]] += 1
    return {"scan_no": int(scan_no), "scan_at": float(scan_at), "risk_off": bool(risk_off),
            "risk_off_unknown": bool(risk_off_unknown), "min_panel_score": _round(min_panel_score, 1),
            "min_raw_score": _round(min_raw_score, 1), "pool": pool, "counts": counts, "rows": rows,
            "notify_context": dict(notify_context or {})}


def note_paper_result(symbol: str, result) -> None:
    """Teslim aşamasında otonom paper girişinin sonucunu SON tarama kaydının ilgili satırına işler (teşhis).

    `result`: `try_open_from_notification` dönüşü (dict ya da None); tek çağıran odur (her sonuçta bir kez).
    Satırın nedeni "paper: ..." olur; durum değişmez. Bir satır "AÇILDI" olarak işlendiyse sonraki
    denemeler (ör. velocity turunun TP güncellemesi/dedup engeli) onu EZMEZ."""
    sym = str(symbol or "").upper()
    if not sym:
        return
    tried = isinstance(result, dict)
    res = result if tried else {}
    status = str(res.get("status") or "")
    if not tried:
        text, code = "paper: giriş denenmedi/sonuç yok (otonom kapalı ya da sessiz çıkış)", "paper_denenmedi"
    elif status == "opened":
        text, code = "paper: otonom pozisyon AÇILDI", "paper_acildi"
    elif status in ("tp_updated", "no_change"):
        text, code = "paper: açık pozisyon vardı (TP güncellendi/değişmedi)", "paper_guncellendi"
    else:
        text, code = f"paper: engellendi ({res.get('reason') or status or '?'})", "paper_engellendi"
    label, tone = REASON_META[code]
    with _lock:
        if not _log:
            return
        for row in _log[-1].get("rows", []):
            if row.get("symbol") == sym and row.get("status") in ("notified", "detected", "held"):
                if (row.get("paper") or {}).get("status") == "opened" and status != "opened":
                    break
                row.update({"reason": text, "reason_code": code, "reason_label": label, "reason_tone": tone,
                            "paper": {"status": str(res.get("status")) if tried else None, "reason": res.get("reason")}})
                break


def record(entry: dict) -> None:
    with _lock:
        keep = _keep()
        if _log.maxlen != keep:
            items = list(_log)[-keep:]
            _log.clear()
            globals()["_log"] = deque(items, maxlen=keep)
        _log.append(entry)


def reset() -> None:
    with _lock:
        _log.clear()


def get_log(limit: int = 10, symbol: str = "", status: str = "") -> dict:
    """Yönetici ucu: en yeni önce `limit` tarama; satırlar `symbol` (alt dize) ve `status` ile süzülür.

    Sayaçlar (`counts`) süzmeden ETKİLENMEZ (tüm turun özeti)."""
    sym = str(symbol or "").strip().upper().replace("_", "")
    st = str(status or "").strip()
    with _lock:
        items = list(_log)
        keep = _log.maxlen
    items.reverse()
    scans = []
    for entry in items[: max(1, min(int(limit), 100))]:
        rows = entry["rows"]
        if sym:
            rows = [r for r in rows if sym in r["symbol"]]
        if st in _STATUS_META:
            rows = [r for r in rows if r["status"] == st]
        scans.append({**entry, "rows": rows})
    return {"ok": True, "keep": keep, "total_scans": len(items),
            "status_catalog": [{"status": s, "label": l, "tone": t} for s, l, t in STATUS_CATALOG], "scans": scans}
