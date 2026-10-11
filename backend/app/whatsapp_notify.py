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
    # PUANA GÖRE SIRALA (kullanıcı isteği 2026-10-11): en yüksek puan en üstte.
    # Çağıranın sırasına GÜVENİLMEZ — formatlayıcı kendi garanti eder.
    def _puan(x: dict) -> float:
        try:
            return float(x.get("quality_score", x.get("scan_score")) or 0)
        except (TypeError, ValueError):
            return 0.0
    ordered = sorted(candidates, key=_puan, reverse=True)
    shown = ordered[:max(1, int(n))]
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
    # ALT SATIR: puan açıklaması yerine ortalamalar (kullanıcı isteği 2026-10-11) —
    # yükselme miktarı (hedef) ortalaması + yükselme potansiyeli ortalaması.
    mikts = [float(c["ceiling_pct"]) for c in shown if c.get("ceiling_pct") is not None]
    pots = [float(c["potential_pct"]) for c in shown if c.get("potential_pct") is not None]
    avg_bits = []
    if mikts:
        avg_bits.append(f"📈 ort. yükselme miktarı +%{sum(mikts) / len(mikts):.1f}")
    if pots:
        avg_bits.append(f"🚀 ort. potansiyel +%{sum(pots) / len(pots):.1f}")
    footer = ("  ·  ".join(avg_bits)) if avg_bits else ""
    # DEVAM EDEN SEMBOLLER (kullanıcı isteği 2026-10-11): önceki listeden arka
    # arkaya taşınanlar alt satırda belirtilir; her biri için anchor (ilk bildirim)
    # fiyatından bu yana toplam değişim yazılır.
    carried = [c for c in shown if c.get("carried")]
    if carried:
        bits = []
        for c in carried:
            a = c.get("anchor_price")
            p = c.get("price")
            try:
                chg = (float(p) / float(a) - 1) * 100 if (a and p) else None
            except (TypeError, ValueError):
                chg = None
            if chg is not None:
                bits.append(f"{_sym(c.get('symbol'))} {chg:+.2f}%")
            else:
                bits.append(_sym(c.get("symbol")))
        footer += ("\n🔁 Devam eden (ilk bildirimden beri): " + " · ".join(bits))
    out = f"{title}\n\n```\n" + "\n".join(body) + "\n```"
    return f"{out}\n{footer}" if footer else out


def format_combined_status(rows: list[dict], *, title: str,
                           baseline_label: str, show_peak: bool = False) -> str:
    """Bu adayların BİLDİRİM ANINA göre anlık durumu (fark) + ortalama değişim.

    `track_min` (5) dk'da bir, bir sonraki liste belirlenene kadar gönderilir.
    En altta adayların ORTALAMA % değişimi yazılır.

    `show_peak=True` (BİR SONRAKİ listeden önceki SON bildirim): her satıra,
    listeyi oluşturduktan sonra görülen **EN YÜKSEK değişim (zirve)** sütunu
    eklenir. Zirve, adayın liste ömrü boyunca ne kadar tepe yaptığını gösterir
    → sonraki değerlendirmelere veri sağlar.
    """
    if not rows:
        return f"{title}\n\nTakip edilecek aday yok."
    shown = sorted(rows, key=lambda r: (float(r["change_pct"])
                                        if r.get("change_pct") is not None else -999.0),
                   reverse=True)
    if show_peak:
        legend = "🪙 coin   💵 bildirim   📈 anlık   ⚡ değişim   🏔️ zirve"
        header = f"{'COIN':<8}{'BİLDİRİM':>10}{'ANLIK':>10}{'DEĞİŞİM':>10}{'ZİRVE':>9}"
    else:
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
        line = f"{_sym(r.get('symbol')):<8}{entry:>10}{cur:>10}{chg:>10}"
        if show_peak:
            pk = r.get("peak_pct")
            pk_s = f"{float(pk):+.2f}%".rjust(9) if pk is not None else "—".rjust(9)
            line += pk_s
        body.append(line)
    chgs = [float(r["change_pct"]) for r in shown if r.get("change_pct") is not None]
    peaks = [float(r["peak_pct"]) for r in shown if r.get("peak_pct") is not None]
    up = sum(1 for x in chgs if x > 0.2)
    dn = sum(1 for x in chgs if x < -0.2)
    flat = len(chgs) - up - dn
    summary = f"▲ {up} yükselen · ▼ {dn} düşen · • {flat} yatay"
    if chgs:
        summary += f"\n🐢 ORT. DEĞİŞİM ({baseline_label}'e göre): {sum(chgs) / len(chgs):+.2f}%"
    if show_peak and peaks:
        # SON DURUM BİLDİRİMİ (bir sonraki listeden ÖNCE): maks MFE artışının
        # ortalaması — yani adayların liste ömrü boyunca tepe yaptığı en yüksek
        # değişimlerin ortalaması (kullanıcı isteği 2026-10-11).
        summary += (f"\n🏔️ MAKS MFE (en yüksek değişim) ort.: "
                    f"{sum(peaks) / len(peaks):+.2f}%")
        best = max(shown, key=lambda r: float(r.get("peak_pct") or -1e9))
        try:
            summary += (f"\n🥇 En çok tepe: {_sym(best.get('symbol'))} "
                        f"{float(best.get('peak_pct')):+.2f}%")
        except (TypeError, ValueError):
            pass
    # DEVAM EDEN SEMBOLLER: önceki listeden taşınanlar (kullanıcı isteği 2026-10-11).
    carried = [r for r in rows if r.get("carried")]
    if carried:
        summary += "\n🔁 Devam eden: " + " · ".join(_sym(r.get("symbol")) for r in carried)
    return f"{title}\n\n```\n" + "\n".join(body) + "\n```\n" + summary

