"""WhatsApp grup bildirimi (Baileys köprüsü üzerinden) — 2026-10-10.

NEDEN: WhatsApp'ın gruba mesaj gönderen ücretsiz resmi API'si yok. Bu modül
`whatsapp-bridge/` (ayrı Node servisi) ile HTTP konuşur; backend'e WhatsApp
bağımlılığı EKLEMEZ (yalnız outbound POST). Yapılandırma yoksa sessizce
atlar (fail-safe) — mevcut akış bozulmaz.

Kullanım (monitoring._daily_momentum_scan_once): 11:30 taraması bittikten sonra
`format_scan_report(...)` metni `send_whatsapp(...)` ile gönderilir.
"""
import asyncio
import json
import logging
import os
import urllib.request
from urllib.error import URLError, HTTPError

logger = logging.getLogger("scalper.whatsapp")
_TIMEOUT_SEC = 8.0


def _cfg() -> tuple[str, str, str]:
    """(bridge_url, bridge_key, group_id) — env'den."""
    url = os.getenv("WHATSAPP_BRIDGE_URL", "").strip().rstrip("/")
    key = os.getenv("WHATSAPP_BRIDGE_KEY", "").strip()
    grp = os.getenv("WHATSAPP_GROUP_ID", "").strip()
    return url, key, grp


def whatsapp_enabled() -> bool:
    """Gönderim yapılandırılmış ve açık mı?"""
    from app.config import config
    if not bool(getattr(config, "WHATSAPP_NOTIFY_ENABLED", False)):
        return False
    url, _key, _grp = _cfg()
    return bool(url)


def _post_sync(url: str, payload: dict, headers: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}


async def send_whatsapp(text: str) -> bool:
    """Rapor metnini WhatsApp köprüsüne gönder. Yapılandırma yoksa False (sessiz).

    Hata fırlatmaz: köprü kapalı/erişilemez olsa bile çağıran akış (tarama)
    etkilenmez, yalnız log düşer.
    """
    if not text or not whatsapp_enabled():
        return False
    url, key, grp = _cfg()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Bridge-Key"] = key
    payload = {"message": text}
    if grp:
        payload["to"] = grp
    try:
        result = await asyncio.to_thread(_post_sync, f"{url}/send", payload, headers)
        ok = bool(result.get("ok"))
        if not ok:
            logger.warning("WhatsApp gönderimi başarısız: %s", result.get("error"))
        return ok
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.warning("WhatsApp köprüsüne ulaşılamadı: %s", exc)
        return False
    except Exception as exc:
        logger.warning("WhatsApp gönderim hatası: %s", exc)
        return False


def format_scan_report(candidates: list[dict], *, title: str = "🌅 Günlük Yükseliş Adayları") -> str:
    """Aday listesini WhatsApp için okunur metne çevir.

    Sıralama önceliği: strategy='both' (momentum+squeeze onaylı) üstte, sonra
    potansiyel %, sonra skor. WhatsApp düz metin + emoji kullanır (tablo yok).
    """
    if not candidates:
        return f"{title}\n\nBugün koşulları geçen aday bulunamadı."
    def _key(c: dict):
        both = 1 if str(c.get("strategy") or "") == "both" else 0
        return (both, float(c.get("potential_pct") or 0), float(c.get("velocity_score") or 0))
    rows = sorted(candidates, key=_key, reverse=True)
    lines = [title, ""]
    for c in rows[:12]:
        sym = str(c.get("symbol") or "?")
        px = c.get("price")
        px_s = f"{float(px):,.4f}".rstrip("0").rstrip(".") if px else "—"
        tgt = c.get("ceiling_pct")
        pot = c.get("potential_pct")
        strat = str(c.get("strategy") or "")
        tag = "⚡📈" if strat == "both" else ("⚡" if strat == "short_squeeze" else "📈")
        parts = [f"{tag} *{sym}*  {px_s}"]
        if tgt is not None:
            parts.append(f"hedef +%{round(float(tgt))}")
        if pot is not None:
            parts.append(f"potansiyel +%{round(float(pot))}")
        lines.append("  • " + "  |  ".join(parts))
    lines.append("")
    lines.append("📈 momentum   ⚡ short-squeeze   ⚡📈 ikisi de")
    return "\n".join(lines)


def format_tracking_table(rows: list[dict], *, title: str = "📊 Aday Takip") -> str:
    """11:30 adaylarının anlık fiyat/değişim tablosu (WhatsApp monospace).

    `rows` her öğesi: {symbol, entry_price, current_price, change_pct,
    potential_pct, hit_ceiling} döner. WhatsApp'ta hizalı görünmesi için
    ``` bloğu (monospace) içinde sabit genişlikli tablo üretir.
    """
    if not rows:
        return f"{title}\n\nTakip edilecek aday yok."
    # değişime göre azalan (en iyi üstte)
    def _key(r: dict):
        v = r.get("change_pct")
        return float(v) if v is not None else -999.0
    rows = sorted(rows, key=_key, reverse=True)

    def _f(v, nd=4):
        if v is None:
            return "—"
        try:
            return f"{float(v):.{nd}f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return "—"

    def _p(v):
        if v is None:
            return "—"
        try:
            x = float(v)
            return f"{x:+.1f}%"
        except (TypeError, ValueError):
            return "—"

    header = f"{'SEMBOL':<10}{'GİRİŞ':>9}{'ANLIK':>9}{'DEĞ%':>8}"
    sep = "-" * len(header)
    body = [header, sep]
    for r in rows[:15]:
        sym = str(r.get("symbol") or "?")[:10]
        entry = _f(r.get("entry_price"))
        cur = _f(r.get("current_price"))
        chg = _p(r.get("change_pct"))
        mark = "✓" if r.get("hit_ceiling") else ""
        body.append(f"{sym:<10}{entry:>9}{cur:>9}{chg:>8} {mark}")
    return f"{title}\n\n```\n" + "\n".join(body) + "\n```"

