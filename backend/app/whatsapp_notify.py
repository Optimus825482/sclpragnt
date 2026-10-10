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


def _is_both(c: dict) -> int:
    return 1 if str(c.get("strategy") or "") == "both" else 0


def _combined_score(c: dict) -> float:
    """Birleşik aday puanı: ihtimal(%) × potansiyel(%) / 100.

    Rapor ve takip tablosu AYNI puana göre sıralanır → ikisinde de aynı ilk 5
    sembol görünür. İhtimal yoksa nötr taban (%50) kullanılır; potansiyel yoksa
    puan 0 olur (sıralamada geriye düşer).
    """
    pot = float(c.get("potential_pct") or 0)
    prob = c.get("target_probability")
    p = float(prob) if prob is not None else 50.0
    return p * max(pot, 0.0) / 100.0


def select_top(candidates: list[dict], n: int = 5) -> list[dict]:
    """Adayları raporla AYNI ölçüte göre sıralayıp ilk `n`'i döndür.

    Ölçüt: önce momentum+squeeze onaylı ('both'), sonra ihtimal×potansiyel puanı.
    WhatsApp raporu, takip tablosu ve uygulama sayfası bu TEK fonksiyonu kullanır
    → üçü de birebir aynı sembolleri aynı sırada gösterir.
    """
    return sorted(candidates, key=lambda c: (_is_both(c), _combined_score(c)),
                  reverse=True)[:max(1, int(n))]


def format_scan_report(candidates: list[dict], *, title: str = "🌅 Günlük Yükseliş Adayları") -> str:
    """Aday listesini emoji başlıklı + sayısal hizalı biçime çevir (en iyi 5).

    TASARIM (2026-10-10 revize):
    - Kullanıcı kararı: liste **10 değil**, **en yüksek 5** sembol olsun; sıralama
      "yükselme ihtimali × potansiyel" birleşik puanına göre.
    - WhatsApp monospace'te EMOJI genişliği sabit değildir; veri sütunlarına emoji
      koymak hizalamayı bozar → üstte bir **emoji açıklama satırı**, altında
      **tam sayısal hizalı** düz sütunlar, strateji etiketi (⚡📈) satır SONUNDA.
    - Alt satırda gösterilen 5'in **ortalama ihtimal/hedef/potansiyel %**'leri.

    Sıralama puanı: ihtimal(%) × potansiyel(%) / 100; ihtimal yoksa potansiyele
    düşer. Eşitlikte momentum+squeeze onaylı ('both') öne geçer.
    """
    if not candidates:
        return f"{title}\n\nBugün koşulları geçen aday bulunamadı."

    rows = select_top(candidates, 5)   # uygulama sayfasıyla AYNI ilk 5
    total = len(candidates)

    def _sym(s: str) -> str:
        s = str(s or "?").upper()
        return (s[:-3] if s.endswith("TRY") else s)[:8]

    legend = "🪙 coin  💵 fiyat  🎲 ihtimal  🎯 hedef  🚀 potansiyel"
    header = f"{'COIN':<8}{'FİYAT':>9}{'İHTİMAL':>9}{'HEDEF':>7}{'POTANSİYEL':>12}  KAYNAK"
    sep = "─" * len(header)
    body = [legend, header, sep]
    shown = rows  # zaten en iyi 5
    for c in shown:
        tgt = c.get("ceiling_pct")
        pot = c.get("potential_pct")
        prob = c.get("target_probability")
        strat = str(c.get("strategy") or "")
        tag = "⚡📈" if strat == "both" else ("⚡" if strat == "short_squeeze" else "📈")
        prob_s = f"%{prob:.0f}" if prob is not None else "—"
        body.append(
            f"{_sym(c.get('symbol')):<8}"
            f"{_fmt_price(c.get('price'), 9):>9}"
            f"{prob_s:>9}"
            f"{(f'+%{round(float(tgt))}' if tgt is not None else '—'):>7}"
            f"{(f'+%{round(float(pot))}' if pot is not None else '—'):>12}"
            f"  {tag}"
        )
    nm = sum(1 for c in candidates if str(c.get("strategy") or "") == "daily_momentum")
    ns = sum(1 for c in candidates if str(c.get("strategy") or "") == "short_squeeze")
    nb = sum(1 for c in candidates if str(c.get("strategy") or "") == "both")
    footer = f"Toplam {total} aday: 📈 {nm} momentum · ⚡ {ns} squeeze · ⚡📈 {nb} ikisi de"
    # Bu 5'in ortalamaları (yalnız veri olan kalemler üzerinden)
    probs = [float(c["target_probability"]) for c in shown
             if c.get("target_probability") is not None]
    pots = [float(c["potential_pct"]) for c in shown if c.get("potential_pct") is not None]
    tgts = [float(c["ceiling_pct"]) for c in shown if c.get("ceiling_pct") is not None]
    avg_bits = []
    if probs:
        avg_bits.append(f"ort. ihtimal %{sum(probs) / len(probs):.0f}")
    if tgts:
        avg_bits.append(f"ort. hedef +%{sum(tgts) / len(tgts):.1f}")
    if pots:
        avg_bits.append(f"ort. potansiyel +%{sum(pots) / len(pots):.1f}")
    avg_line = ("Bu 5'in " + " · ".join(avg_bits)) if avg_bits else ""
    out_lines = [title, "", "```", *body, "```", footer]
    if avg_line:
        out_lines.append(avg_line)
    return "\n".join(out_lines)


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


def format_tracking_table(rows: list[dict], *, title: str = "📊 Aday Takip") -> str:
    """Adayların anlık fiyat/değişim tablosu — emoji başlıklı + sayısal hizalı.

    Tasarım (2026-10-10 revize):
    - Rapor ile AYNI ilk 5 sembol gösterilir: sıralama `_combined_score`
      (ihtimal × potansiyel) ile yapılır → 30 dk'lık güncelleme, 11:30 raporunun
      takip ettiği sembollerle tutarlı kalır.
    - EMOJI genişliği monospace'te sabit değildir → emoji yalnız **açıklama
      satırında** ve strateji etiketinde (satır SONUNDA); rakam sütunları düz.
    - En altta bu 5'in **11:30'a göre ortalama % değişimi** yazılır (giriş fiyatı
      11:30 taramasındaki fiyattır).
    """
    if not rows:
        return f"{title}\n\nTakip edilecek aday yok."

    # ÖNCE raporla aynı ölçütle ilk 5'i SEÇ (birebir aynı semboller), SONRA
    # ekranda değişime göre sırala (en çok yükselen üstte) — seçim bozulmaz.
    shown = select_top(rows, 5)
    shown = sorted(shown, key=lambda r: (float(r["change_pct"])
                                         if r.get("change_pct") is not None else -999.0),
                   reverse=True)

    def _sym(s: str) -> str:
        s = str(s or "?").upper()
        return (s[:-3] if s.endswith("TRY") else s)[:8]

    # Emoji açıklama barı (başlık) + hizalı etiket barı
    legend = "🪙 coin   💵 giriş   📈 anlık   ⚡ değişim"
    header = f"{'COIN':<8}{'GİRİŞ':>10}{'ANLIK':>10}{'DEĞİŞİM':>10}  KAYNAK"
    sep = "─" * len(header)
    body = [legend, header, sep]
    unchanged = 0
    for r in shown:
        sym = _sym(r.get("symbol"))
        entry = _fmt_price(r.get("entry_price"), 10)
        cur = _fmt_price(r.get("current_price"), 10)
        if r.get("change_pct") is None:
            chg = "—".rjust(10)
        else:
            chg = f"{float(r['change_pct']):+.1f}%".rjust(10)
        if r.get("current_price") is None:
            unchanged += 1
        strat = str(r.get("strategy") or "")
        tag = "⚡📈" if strat == "both" else ("⚡" if strat == "short_squeeze"
                                              else ("📈" if strat else ""))
        mark = "✓" if r.get("hit_ceiling") else ""
        suffix = f"  {tag}{(' ' + mark) if mark else ''}"
        body.append(f"{sym:<8}{entry:>10}{cur:>10}{chg:>10}{suffix}")

    chgs = [float(r["change_pct"]) for r in shown if r.get("change_pct") is not None]
    up = sum(1 for x in chgs if x > 0.2)
    dn = sum(1 for x in chgs if x < -0.2)
    flat = sum(1 for x in chgs if -0.2 <= x <= 0.2)
    summary = f"▲ {up} yükselen · ▼ {dn} düşen · • {flat} yatay"
    if unchanged:
        summary += f"  |  {unchanged} fiyat alınamadı"
    # Kullanıcı isteği: bu 5'in 11:30'a göre ORTALAMA % değişimi en altta.
    if chgs:
        summary += f"\n🎯 Bu {len(shown)}'in 11:30'a göre ort. değişimi: {sum(chgs) / len(chgs):+.2f}%"

    return f"{title}\n\n```\n" + "\n".join(body) + "\n```\n" + summary

