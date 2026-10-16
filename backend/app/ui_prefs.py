"""Kullanıcı menü tercihleri — doğrulama (saf). Kimlikler frontend `MENU_ITEMS` ile AYNIDIR."""

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
