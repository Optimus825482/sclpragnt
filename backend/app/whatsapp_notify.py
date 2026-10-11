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


def _sym(s: str) -> str:
    s = str(s or "?").upper()
    return (s[:-3] if s.endswith("TRY") else s)[:8]


def format_combined_list(candidates: list[dict], *, n: int = 3,
                         title: str = "🌅 KOMBİNE YÜKSELİŞ LİSTESİ") -> str:
    """Kombine tarama TOP N listesi (2026-10-11 kullanıcı kararı).

    Radar döngülerindeki TÜM stratejiler (hız/günlük momentum/short-squeeze/MACD
    jump+erken/yükseliş eğilimi/Master Surge 4 katman/MACD MTF/mikro yapı) TEK
    taramada birleşir; sıralama TEK **kalite puanına** (0-99) göre yapılır. Her
    satırda: coin · o anki fiyat · yükselme ihtimali · yükselme miktarı(%) ·
    potansiyel(%) · teyit (kaç motor + kaç katman) · puan.

    PUAN bir OLASILIK DEĞİL; sinyal gücü/kalite endeksidir (100 = garanti değil).
    En iyi aday 99'a kadar çıkabilir; farklı adaylar farklı puan alır.
    """
    if not candidates:
        return f"{title}\n\nBugün koşulları geçen aday bulunamadı."
    shown = candidates[:max(1, int(n))]
    legend = "🪙 coin  💵 fiyat  🎲 ihtimal  📈 miktar  🚀 potansiyel  🧩 teyit  ⭐ puan"
    header = (f"{'COIN':<8}{'FİYAT':>9}{'İHTİMAL':>8}{'MİKTAR':>8}"
              f"{'POTANSİYEL':>12}{'TEYİT':>7}{'PUAN':>6}")
    sep = "─" * len(header)
    body = [legend, header, sep]
    for c in shown:
        prob = c.get("target_probability")
        miktar = c.get("ceiling_pct")
        pot = c.get("potential_pct")
        puan = c.get("quality_score", c.get("scan_score"))
        # TEYİT: kaç sinyal motoru + kaç Master Surge katmanı hemfikir (maks 3+4).
        src_n = int(c.get("confirm_sources") or 0)
        lyr_n = int(c.get("confirm_layers") or 0)
        teyit_s = f"{src_n}+{lyr_n}"
        prob_s = f"%{prob:.0f}" if prob is not None else "—"
        mik_s = f"+%{round(float(miktar))}" if miktar is not None else "—"
        pot_s = f"+%{round(float(pot))}" if pot is not None else "—"
        puan_s = f"{float(puan):.0f}" if puan is not None else "—"
        body.append(
            f"{_sym(c.get('symbol')):<8}"
            f"{_fmt_price(c.get('price'), 9):>9}"
            f"{prob_s:>8}"
            f"{mik_s:>8}"
            f"{pot_s:>12}"
            f"{teyit_s:>7}"
            f"{puan_s:>6}"
        )
    # Puanın ne olduğunu açıkla (100 = kesin DEĞİL).
    footer = ("⭐ Puan = sinyal gücü (0-99), olasılık DEĞİL. "
              "🧩 Teyit = motor+katman sayısı.")
    return f"{title}\n\n```\n" + "\n".join(body) + "\n```\n" + footer


def format_combined_status(rows: list[dict], *, title: str,
                           baseline_label: str) -> str:
    """Bu 3 adayın BİLDİRİM ANINA göre anlık durumu (fark) + ortalama değişim.

    Her 10 dk'da bir, bir sonraki liste belirlenene kadar gönderilir. En altta
    üçünün ORTALAMA % değişimi yazılır.
    """
    if not rows:
        return f"{title}\n\nTakip edilecek aday yok."
    shown = sorted(rows, key=lambda r: (float(r["change_pct"])
                                        if r.get("change_pct") is not None else -999.0),
                   reverse=True)
    legend = "🪙 coin   💵 bildirim   📈 anlık   ⚡ değişim"
    header = f"{'COIN':<8}{'BİLDİRİM':>10}{'ANLIK':>10}{'DEĞİŞİM':>10}"
    sep = "─" * len(header)
    body = [legend, header, sep]
    for r in shown:
        entry = _fmt_price(r.get("entry_price"), 10)
        cur = _fmt_price(r.get("current_price"), 10)
        if r.get("change_pct") is None:
            chg = "—".rjust(10)
        else:
            chg = f"{float(r['change_pct']):+.2f}%".rjust(10)
        body.append(f"{_sym(r.get('symbol')):<8}{entry:>10}{cur:>10}{chg:>10}")
    chgs = [float(r["change_pct"]) for r in shown if r.get("change_pct") is not None]
    up = sum(1 for x in chgs if x > 0.2)
    dn = sum(1 for x in chgs if x < -0.2)
    flat = len(chgs) - up - dn
    summary = f"▲ {up} yükselen · ▼ {dn} düşen · • {flat} yatay"
    if chgs:
        summary += f"\n🐢 ÜÇÜN ORT. DEĞİŞİMİ ({baseline_label}'e göre): {sum(chgs) / len(chgs):+.2f}%"
    return f"{title}\n\n```\n" + "\n".join(body) + "\n```\n" + summary

