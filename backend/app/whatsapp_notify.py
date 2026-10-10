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
    # Hizalı tablo (monospace): COIN | FİYAT | HEDEF | POTANSİYEL | KAYNAK
    def _sym(s: str) -> str:
        s = str(s or "?").upper()
        return (s[:-3] if s.endswith("TRY") else s)[:8]
    header = f"{'COIN':<8}{'FİYAT':>10}{'HEDEF':>8}{'POTANSİYEL':>12}{'KAYNAK':>8}"
    sep = "─" * len(header)
    body = [header, sep]
    for c in rows[:15]:
        tgt = c.get("ceiling_pct")
        pot = c.get("potential_pct")
        strat = str(c.get("strategy") or "")
        tag = "⚡📈" if strat == "both" else ("⚡" if strat == "short_squeeze" else "📈")
        body.append(
            f"{_sym(c.get('symbol')):<8}"
            f"{_fmt_price(c.get('price'), 10):>10}"
            f"{(f'+%{round(float(tgt))}' if tgt is not None else '—'):>8}"
            f"{(f'+%{round(float(pot))}' if pot is not None else '—'):>12}"
            f"{tag:>8}"
        )
    nm = sum(1 for c in rows if str(c.get("strategy") or "") == "daily_momentum")
    ns = sum(1 for c in rows if str(c.get("strategy") or "") == "short_squeeze")
    nb = sum(1 for c in rows if str(c.get("strategy") or "") == "both")
    lines = [title, "", "```", *body, "```",
             f"Toplam {len(rows)} aday: 📈 {nm} momentum · ⚡ {ns} squeeze · ⚡📈 {nb} ikisi de"]
    return "\n".join(lines)
    lines.append("📈 momentum   ⚡ short-squeeze   ⚡📈 ikisi de")
    return "\n".join(lines)


def _fmt_price(v, width: int = 8) -> str:
    """Fiyatı sütun genişliğine sığacak biçimde akıllı formatla (0.1098 / 2.44 / 16.3 / 119)."""
    if v is None:
        return "—".rjust(width)
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—".rjust(width)
    # basamak sayısını fiyata göre seç (küçük fiyatlarda daha fazla ondalık)
    if x >= 1000:
        s = f"{x:,.0f}"
    elif x >= 100:
        s = f"{x:.1f}"
    elif x >= 1:
        s = f"{x:.2f}"
    elif x >= 0.01:
        s = f"{x:.4f}"
    else:
        s = f"{x:.6f}"
    if len(s) > width:
        s = s[:width]
    return s.rjust(width)


def _fmt_chg(v, width: int = 8) -> str:
    """Değişimi işaretli + ok ile biçimle (＋/－)."""
    if v is None:
        return "—".rjust(width)
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—".rjust(width)
    arrow = "▲" if x > 0 else ("▼" if x < 0 else "•")
    s = f"{x:+.1f}%{arrow}"
    return s.rjust(width)


def format_tracking_table(rows: list[dict], *, title: str = "📊 Aday Takip") -> str:
    """Adayların anlık fiyat/değişim tablosu (WhatsApp monospace, hizalı).

    Tablo düzeni (2026-10-10 revize): sembolden 'TRY' ekı kaldırılır (hizalama
    bozuluyordu), fiyatlar sütuna göre akıllı formatlanır, değişime ok işareti
    eklenir ve en alta özet satırı (kazanan/kaybeden sayısı + ortalama) konur.
    """
    if not rows:
        return f"{title}\n\nTakip edilecek aday yok."

    def _key(r: dict):
        v = r.get("change_pct")
        return float(v) if v is not None else -999.0
    rows = sorted(rows, key=_key, reverse=True)

    def _sym(s: str) -> str:
        s = str(s or "?").upper()
        return (s[:-3] if s.endswith("TRY") else s)[:8]

    header = f"{'COIN':<8}{'GİRİŞ':>9}{'ANLIK':>9}{'DEĞİŞİM':>10}"
    sep = "─" * len(header)
    body = [header, sep]
    unchanged = 0
    for r in rows[:20]:
        sym = _sym(r.get("symbol"))
        entry = _fmt_price(r.get("entry_price"), 9)
        cur = _fmt_price(r.get("current_price"), 9)
        chg = _fmt_chg(r.get("change_pct"), 10)
        if r.get("current_price") is None:
            unchanged += 1
        mark = " ✓" if r.get("hit_ceiling") else ""
        body.append(f"{sym:<8}{entry:>9}{cur:>9}{chg:>10}{mark}")

    # Özet: kazanan/kaybeden/yatay + ortalama değişim
    chgs = [float(r["change_pct"]) for r in rows if r.get("change_pct") is not None]
    up = sum(1 for x in chgs if x > 0.2)
    dn = sum(1 for x in chgs if x < -0.2)
    flat = sum(1 for x in chgs if -0.2 <= x <= 0.2)
    avg = (sum(chgs) / len(chgs)) if chgs else None
    summary = f"▲ {up} yükselen · ▼ {dn} düşen · • {flat} yatay"
    if avg is not None:
        summary += f"  |  ort {avg:+.1f}%"
    if unchanged:
        summary += f"  |  {unchanged} fiyat alınamadı"

    header_line = f"{title}"
    return f"{header_line}\n\n```\n" + "\n".join(body) + "\n```\n" + summary

