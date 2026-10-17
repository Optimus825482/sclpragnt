"""İndikatör filtresi / hedef çalışması — rapor birleştirici (2026-10-17). work/indfilter/section_A.md + section_B.md + özet pickle'ları
→ work/indfilter/report.md. Karar cümleleri SAYILARDAN otomatik üretilir (elle yazılmış yargı yok).

Kullanım (backend/): python scripts/indfilter_report.py
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import indfilter_common as K  # noqa: E402


# ------------------------------------------------------------------------------------------------ saf karar işlevleri (testli)
def rule_passes(rows: list[dict], name: str, n_blocks: int, min_n: int = 50) -> dict:
    """Bir kuralın SEÇİM-DIŞI her blokta: (1) Δ(net−taban) > 0, (2) net(tutulan) > net(hepsi), (3) birleşik OOS Δ %95 alt sınırı > 0,
    (4) n ≥ min_n. net_pos: OOS bloklarının hepsinde tutulanın neti > 0."""
    r = [x for x in rows if x["name"] == name]
    oos = [x for x in r if x["block"] >= 1]
    comb = [x for x in r if x["block"] == -1]
    if len(oos) < n_blocks - 1 or not comb:
        return {"ok": False, "reason": "eksik veri", "net_pos": False}
    every = all(x["delta"] > 0 and x["net"] > x["net_all"] and x["n"] >= min_n for x in oos)
    lcb = comb[0]["lo"] > 0
    return {"ok": bool(every and lcb), "every_block": bool(every), "lcb_pos": bool(lcb), "net_pos": all(x["net"] > 0 and x["n"] >= min_n for x in oos),
            "delta_comb": comb[0]["delta"], "lo_comb": comb[0]["lo"], "net_comb": comb[0]["net"]}


def model_vs_fixed(res: list[dict], model: str, fixed: str, n_blocks: int, key: str = "dnet") -> dict:
    """Model − sabit hedef (AYNI olaylarda eşleştirilmiş fark; key: 'dnet' = ham net, 'dex' = net−taban): SEÇİM-DIŞI her blokta fark > 0 VE
    birleşik seçim-dışı %95 alt sınırı > 0. (2 dilimli nüfusta tek seçim-dışı dilim hem blok hem birleşik sayılır.)"""
    def get(name, b):
        for x in res:
            if x["name"] == name and x["block"] == b:
                return x
        return None
    blocks = list(range(1, n_blocks))
    comb = get(model, -1) if n_blocks > 2 else get(model, 1)
    per = [get(model, b) for b in blocks]
    if comb is None or any(x is None for x in per):
        return {"ok": False, "per": []}
    ok = all(x[key] > 0 for x in per) and comb[key + "_lo"] > 0
    return {"ok": bool(ok), "per": [(x["block"], x[key], x[key + "_lo"]) for x in per] + [(comb["block"], comb[key], comb[key + "_lo"])]}


def classic_pass(summary_pop: dict) -> list[str]:
    return [n for n, ok, d, t in summary_pop.get("classic", []) if ok]


# ------------------------------------------------------------------------------------------------ sabit metinler
METHOD = """## 1. Soru ve yöntem

**Soru:** TradingView göstergeleri kılavuzundaki ~100 klasik + SMC göstergesi, sistemin (a) bildirdiği sinyallerin HASSASİYETİNİ (net sonuç, yalnız hit değil)
ya da (b) HEDEFİN büyüklüğünü iyileştirebilir mi? (Erken uyarı başka bir çalışmada.)

**Nüfuslar.** (1) Hız Avcısı (HA) canlı-benzeri bölümler: `work/rescan_90g_nogate.jsonl`, rank ≤ 10, aşırı alımda değil, aynı sembolde 60 dk içindeki tekrarlar tek bölüm; 90 gün,
üç blok: B1 20 Tem–18 Ağu, B2 19 Ağu–17 Eyl, B3 18 Eyl–16 Eki. (2) Push bildirimleri: `work/confirm_elems/events.pkl` (2007 olay, 17 Eyl–17 Eki) ve bunların YENİ canlı
teyit kuralını geçen alt kümesi (≥ 2 farklı kaynak ∧ Hız kaynaklar arasında ∧ mod ≠ unified). Seçim dönemi 17.09–09.10, değerlendirme 10.10–17.10 (önceki çalışmayla aynı).

**Özellikler (sinyal anından ÖNCE kapanmış son 5 dk ve 15 dk barı).** `app/rescan/indicators_ext.py::compute_all` (134 sütun/zaman dilimi: hareketli ortalama aileleri, OBV/CMF/Klinger/CVD,
osilatörler, SuperTrend kümesi, Ichimoku, Donchian, Keltner/sıkışma, Choppiness, VWAP/çapalı VWAP/POC, SMC: BOS/CHoCH, eşit tepe/dip, likidite süpürmesi, FVG, order block, yer değiştirme, TD),
`pattern_study.features_matrix` (EMA fan, RSI, MFI, ATR, BB, MACD, ADX/DI, Aroon, getiriler, taker...), jsonl/event alanları (`ex:*`), `dyn_target` bileşenleri (`dyn:*`),
direnç mesafeleri (`res:*`: 24 sa / 60 dk zirve, son onaylı salınım tepesi, eşit tepe, POC üstü) ve 25 önceden belirlenmiş klasik fikir (`idea:*`; eşikler literatür varsayılanları, AYARLANMADI).
Boşluklu mumlar `pattern_study.fill_gaps` ile düz mumla doldurulur. Nedensellik: kesilmiş seriyle yeniden hesap testi + sentetik gelecek-bozma birim testi (aşağıda).

**Başarı tanımları.** (A) *hit*: giriş (sinyal + 60 sn) barının açılışına göre 60 dk içinde 1 dk yüksekleri sinyal hedefini görür. (B) *net*: `exit_sim` — 60 sn gecikme, %0,15 kayma, %0,1125/bacak ücret,
TP = sinyal hedefi, SL %3, zaman stopu 60 dk. *Taban:* olay başına 3 rastgele giriş — aynı sembol, aynı blok, herhangi bir sinyalden ≥ 2 sa uzak, 5 dk ATR%'si ±%25 (en az 8 aday; yoksa en yakın 8),
AYNI TP/SL/zaman. *net−taban* = olay neti − o olayın tabanının ortalaması (oynaklık eşleşmiş çift fark).

**Oynaklık kontrolü.** (i) Kısmi Spearman: özellik ve sonucun sıraları, ATR ve hedef/ATR sıralarının 1.+2. derece terimlerine göre arındırılır; t küme-dayanıklı (gün kümeleri). (ii) ATR tersilleri içinde
özelliğin üst yarısı − alt yarısı farkı (tersil ağırlıklı). (iii) Sonuç olarak *net−taban* (taban ATR'ye eşleşmiş). BH q değerleri özellikler arası.

**Filtre kuralları.** Aday = özellik × yön × 3 eşik (1/3, 1/2, 2/3 yüzdelik; yalnız SEÇİM döneminden, sonra dondurulur). Seçim dönemi (HA: B1; bildirim: 17.09–09.10) t-istatistiğine göre iki hedef işleviyle en iyi 3'er FARKLI özellik
(A: net−taban, N: ham net; toplam ≤ 6 kural). Değerlendirme: diğer bloklarda dokunulmadan. Aşırı uyum tanısı: seçimde en iyi 50 adayın seçim-dışı performansı.

**Hedef modelleri.** M0 sinyalin kendi hedefi; M1 ATR ölçekli (k eğitimde); M2 ATR + direnç payı (kaynak/pay/k eğitimde); M3 ampirik (dyn_target (c), q eğitimde); M4 doğrusal kuantil regresyonu
(eğitimde seçilen 5 özellik + log ATR); M5 gradyan artırmalı kuantil (tüm özellikler). Parametreler YALNIZ eğitim bloğunda seçilir (net−taban ölçütüyle; taban aynı hedefle). Test: sonraki bloklar dokunulmadan."""

LIMITS = """## 5. Sınırlar

- **Çoklu karşılaştırma:** yüzlerce özellik × 4–7 sonuç × 2 nüfus × 2 kapsam; BH q özellikler arası uygulandı, ama sonuçlar arası değil. Seçilen kurallar/ayarlar tek bir seçim dönemine uyar; yalnız
  seçim-dışı bloklardaki dokunulmamış sonuçlar kanıt sayılmalı. t>2 tek başına kanıt değildir (bkz. aşırı uyum tanısı).
- **Tek piyasa dönemi:** 90 gün / 30 gün; rejim değişimi (özellikle son blok) genellenebilirliği sınırlar. Gün kümeleri bağımsız sayılmıştır; bloklar arası bağımlılık (rejim) ölçülmedi.
- **Bildirim nüfusu küçük:** 2007 olay (seçim 1522, değerlendirme 485), yeni teyit kuralı alt kümesi 416 (değerlendirme ≈ 78): güç düşük; sıfır bulgu "etki yok" kanıtı değildir.
- **Taban:** oynaklık-eşleşmiş rastgele giriş (ATR ±%25); sinyal yakınındaki bilgi (ör. aynı gün hareketli semboller) tamamen eşleşmez. HA'da taban bloğun tüm 5 dk anlarından, sinyallerden ≥ 2 sa uzak seçilir.
- **Gerçekçilik:** rescan canlıyı birebir üretmez; 60 sn gecikme ve %0,15 kayma varsayım. Hit/net bir sembolün 1 dk verisine dayanır; boşluklu dakika düz mum sayıldı.
- **Klasik fikir eşikleri** (ADX 25, Choppiness 38,2 vb.) literatür varsayılanıdır, bu veride ayarlanmadı; "SuperTrend kümesi" = (10,1)-(11,2)-(12,3); VWAP oturumu UTC günü; "FVG/OB içinde" = bu barda önceki açık
  boşluğa/bölgeye giriş; "süpürme sonrası" = son 3/12 barda dip süpürmesi; "eşit tepe" = son iki onaylı tepe ATR·0,15 içinde.
- **Hedef modelleri:** tek hedef ufku (60 dk); kuantil regresyon az örnekli bildirim nüfusunda (≈1500 eğitim) kararsız; GBM tüm özellikleri kullanır ve aşırı uyuma en yatkın modeldir.
- Bu çalışma yönlü edge aramaz; sinyal gerçek (şansın üstünde) ama maliyet sonrası net negatif olduğu önceki çalışmalarda gösterildi. Filtre/hedef yalnız "daha az negatif" ya da pozitif yapabilir."""


# ------------------------------------------------------------------------------------------------ rapor
def verdict_text(A: dict, B: dict) -> tuple[str, dict]:
    lines = []
    facts: dict = {}
    for pop, nb in (("ha", 3), ("notif", 2)):
        s = A.get(pop)
        if not s:
            continue
        names = sorted({x["name"] for sc in s if sc.startswith("rules_") for x in s[sc]})
        for sc in [k for k in s if k.startswith("rules_")]:
            res = []
            for nm in names:
                rr = rule_passes(s[sc], nm, nb)
                if rr.get("reason"):
                    continue
                res.append((nm, rr))
            ok = [nm for nm, rr in res if rr["ok"]]
            npos = [nm for nm, rr in res if rr["net_pos"]]
            facts[(pop, sc)] = (len(res), ok, npos)
            lines.append("- **A / %s / %s:** seçilen %d kuraldan SEÇİM-DIŞI her blokta net−taban'ı iyileştiren ve birleşik %%95 alt sınırı > 0 olan: **%d**; "
                         "her seçim-dışı blokta mutlak net > 0 olan: **%d**." % (pop, sc[6:], len(res), len(ok), len(npos)))
        cl = classic_pass(s)
        facts[(pop, "classic")] = cl
        lines.append("- **A / %s / klasik fikirler:** her blokta tutulan−düşen farkı > 0 ve %%95 alt sınırı > 0 olan fikir sayısı: **%d** (%s)."
                     % (pop, len(cl), ", ".join(c[5:] for c in cl) if cl else "–"))
    for pop, nb in (("ha", 3), ("notif", 2)):
        s = B.get(pop)
        if not s:
            continue
        for sc, res in s["res"].items():
            fixed = "M0 sabit (sinyalin hedefi)"
            models = sorted({x["name"] for x in res} - {fixed})
            okn, oke, netpos = [], [], []
            for m in models:
                if model_vs_fixed(res, m, fixed, nb, "dnet")["ok"]:
                    okn.append(m)
                if model_vs_fixed(res, m, fixed, nb, "dex")["ok"]:
                    oke.append(m)
                oos = [x for x in res if x["name"] == m and x["block"] >= 1]
                if oos and all(x["net"] > 0 for x in oos):
                    netpos.append(m)
            at = s.get("attr", {}).get(sc, [])
            okat = sorted({x["name"] for x in at if x["name"].startswith(("M4", "M5"))
                           and model_vs_fixed(at, x["name"], "", nb, "dnet")["ok"]})
            facts[("B", pop, sc)] = (okn, oke, netpos, okat)
            lines.append("- **B / %s / %s:** sabit hedefe göre (AYNI olaylarda eşleştirilmiş) SEÇİM-DIŞI her blokta ham neti artıran ve birleşik %%95 alt sınırı > 0 olan model: **%d** (%s); "
                         "net−taban'ı artıran: **%d** (%s); seçim-dışı her blokta mutlak net > 0 olan model: **%d**. "
                         "İndikatör katkısı (özellikli model − ATR-yalnız referans, her seçim-dışı blokta Δnet > 0 ve birleşik alt sınır > 0): **%d** (%s)."
                         % (pop, sc, len(okn), ", ".join(okn) if okn else "–", len(oke), ", ".join(oke) if oke else "–", len(netpos),
                            len(okat), ", ".join(okat) if okat else "–"))
    return "\n".join(lines), facts


def main() -> int:
    A = pickle.load(open(K.OUT / "summary_A.pkl", "rb")) if (K.OUT / "summary_A.pkl").exists() else {}
    B = pickle.load(open(K.OUT / "summary_B.pkl", "rb")) if (K.OUT / "summary_B.pkl").exists() else {}
    secA = (K.OUT / "section_A.md").read_text(encoding="utf-8") if (K.OUT / "section_A.md").exists() else "(A bölümü üretilmedi)"
    secB = (K.OUT / "section_B.md").read_text(encoding="utf-8") if (K.OUT / "section_B.md").exists() else "(B bölümü üretilmedi)"
    ver = ""
    for pop in ("ha", "notif"):
        f = K.OUT / ("verify_%s.txt" % pop)
        if f.exists():
            ver += "- nedensellik testi (%s): %s\n" % (pop, f.read_text(encoding="utf-8").splitlines()[0])
    vt, facts = verdict_text(A, B)
    head = "# İndikatör Kılavuzu — Hassasiyet (filtre) ve Hedef Boyutu Çalışması (2026-10-17)\n\n"
    head += "Bu rapor `backend/scripts/indfilter_report.py` tarafından üretilmiştir (A: `indfilter_study.py`, B: `indfilter_target.py`, özellikler `indfilter_feats.py`, " \
            "kütüphane `app/rescan/indicators_ext.py`). Çevrimdışı araştırma; canlı koda bağlanmaz.\n\n"
    from scripts import indfilter_prose as PR
    nbp = {"ha": 3, "notif": 2}
    head += ("## 0. Hüküm (sayılardan otomatik üretilir)\n\n**Karar:** " + PR.verdict_line(A, B, nbp) + "\n\n### 0a. Hassasiyet (filtre)\n\n" + "\n".join(PR.filter_prose(A, nbp))
             + "\n\n### 0b. Hedef boyutu\n\n" + "\n".join(PR.target_prose(B, nbp)) + "\n\n### 0c. Ölçüt özeti (kural/model geçişleri)\n\n" + vt + "\n\n")
    if ver:
        head += "Doğrulama:\n" + ver + "\n"
    text = head + METHOD + "\n\n## 3. A — Hassasiyet (filtre) çalışması\n\n" + secA + \
        "\n\n## 4. B — Hedef boyutlandırma çalışması\n\n" + secB + "\n\n" + LIMITS
    (K.OUT / "report.md").write_text(text, encoding="utf-8")
    print("rapor: %s (%d karakter)" % (K.OUT / "report.md", len(text)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
