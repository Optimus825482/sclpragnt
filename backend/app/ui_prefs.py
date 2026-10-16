"""Kullanıcı arayüz tercihleri (menü, favoriler, sabitlenenler) — doğrulama (saf).

Menü kimlikleri frontend `MENU_ITEMS` ile AYNIDIR."""
import math
import re
import time

MENU_IDS: tuple[str, ...] = (
    "home", "notifications", "radar", "binance", "risk", "charts", "reports", "profile", "settings")
LOCKED_IDS: frozenset[str] = frozenset({"home", "settings"})
# Menüden KALDIRILMIŞ kimlikler (2026-10-16: otonom paper/portföy kullanıcı arayüzünden çıktı). Eski kayıtlı
# tercihlerde kalmış olabilir; hata değil, sessizce yok sayılır (aksi halde PUT 422 verirdi).
REMOVED_IDS: frozenset[str] = frozenset({"portfolio"})


def normalize_hidden(raw) -> list[str]:
    """Gizlenecek menü kimliklerini doğrula; tekrarları at, MENU_IDS sırasına koy."""
    if not isinstance(raw, list):
        raise ValueError("hidden_menu liste olmalı")
    seen: set[str] = set()
    for item in raw:
        key = str(item)
        if key in REMOVED_IDS:
            continue
        if key not in MENU_IDS:
            raise ValueError(f"Bilinmeyen menü öğesi: {key}")
        if key in LOCKED_IDS:
            raise ValueError(f"Gizlenemez menü öğesi: {key}")
        seen.add(key)
    return [m for m in MENU_IDS if m in seen]


# --- Favoriler / sabitlenen izleme listesi (2026-10-17) ---
_WATCH_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}TRY$")
WATCH_MAX_ITEMS = 30


def _positive_float(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} sayı olmalı")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} sayı olmalı") from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} sıfırdan büyük olmalı")
    return number


def normalize_watch_list(raw, max_items: int = WATCH_MAX_ITEMS, now: float | None = None) -> list[dict]:
    """[{symbol, price, at}] doğrula. Sembol büyütülür, tekrarda İLK kayıt kalır; geçersiz → ValueError."""
    if not isinstance(raw, list):
        raise ValueError("Liste olmalı")
    if len(raw) > max_items:
        raise ValueError(f"En fazla {max_items} öğe")
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Öğe nesne olmalı")
        symbol = str(item.get("symbol") or "").strip().upper()
        if not _WATCH_SYMBOL_RE.match(symbol):
            raise ValueError(f"Geçersiz sembol: {symbol or '?'}")
        price = _positive_float(item.get("price"), "price")
        at_raw = item.get("at")
        at = (time.time() if now is None else float(now)) if at_raw is None else _positive_float(at_raw, "at")
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append({"symbol": symbol, "price": price, "at": at})
    return out
