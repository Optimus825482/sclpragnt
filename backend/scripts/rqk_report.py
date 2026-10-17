"""RQK çalışması — rapor üretici: work/rqk/res_*.json → work/rqk/report.md (Türkçe)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.rqk_study import BLOCKS, COMBOS, COMBO_KEYS, DEFAULT, MIN_QUOTE

MIN_PER_DAY_SELECT = 20.0
BN = ["B1", "B2", "B3"]
BLOCK_LABEL = {"B1": "B1 (20 Tem–18 Ağu)", "B2": "B2 (19 Ağu–17 Eyl)", "B3": "B3 (18 Eyl–16 Eki)"}


# ------------------------------------------------------------------------------------------------ biçim
def n_(x, d=1):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}".replace(".", ",")


def p_(x, d=1):
    """oran → yüzde"""
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else ("%" + f"{100 * x:.{d}f}".replace(".", ","))


def pp_(x, d=1):
    """fark (oran) → işaretli puan"""
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else (f"{100 * x:+.{d}f}".replace(".", ",") + " pp")


def sg_(x, d=2):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:+.{d}f}".replace(".", ",")


def k_(x):
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def lift_ci(v):
    """şans farkı ± 1,96·SE (puan)"""
    if not v or v.get("lift15") is None:
        return "—"
    se = v.get("se15")
    s = f"{100 * v['lift15']:+.1f}".replace(".", ",")
    if se is not None:
        s += " ± " + f"{196 * se:.1f}".replace(".", ",")
    return s


def md_table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def load(out: Path, name: str):
    p = out / f"res_{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def spearman(a: list[float], b: list[float]) -> float | None:
    from scipy.stats import spearmanr
    if len(a) < 5:
        return None
    r = spearmanr(a, b)
    return float(r.correlation)


# ------------------------------------------------------------------------------------------------ bölümler
def sec_timing(T: dict) -> tuple[str, dict]:
    L: list[str] = []
    info: dict = {}
    L.append(f"## 3. Analiz 1 — Olay zamanlaması: çekirdek YÜKSELİŞTEN ÖNCE mi, SONRA mı yeşile dönüyor?")
    L.append("")
    L.append(f"Olay = 90 günlük çalışmadaki kümesiz birincil olay (**{k_(T['n_events'])}**; t0 = koşunun ilk mumunun açılışı = bir önceki 5m mumun kapanışı). "
             f"Taban = aynı sembol + aynı gün, olay başına rastgele ≤ 40 geçerli an (**{k_(T['n_base'])}** an; olay koşusu dışında). "
             "Durum = t anında KAPANMIŞ son çekirdek barının rengi (yeşil=boğa). Uygulama varsayılanları: varyant A, h=8, r=2. "
             "'AL dönüşü' = kırmızı→yeşil renk değişimi, dönüş zamanı = o barın kapanışı. P0 = t0'daki fiyat (olayda koşudan önceki kapanış). "
             "**Dikkat:** olay tanımı geleceğe bakar (ilk 5m mum yeşil ve P0'ın üstünde, koşu P0'ın altına inmez, 60 dk'da ≥ %4), bu yüzden t0'dan SONRAKİ pencerelerdeki (t0+5 …) oranlar kısmen tanım gereğidir; "
             "t0 ve ÖNCESİ (t0−15 … t0) ölçümleri nedensel ve 'önceden işaret veriyor mu?' sorusunun asıl cevabıdır. HA ile karşılaştırma aynı pencerede yapıldığından adildir.")
    L.append("")
    for tf in ("1m", "5m", "15m"):
        d = T["tf"][tf]; e, b = d["event"], d["base"]
        L.append(f"### {tf} çekirdek (A, h=8, r=2)")
        L.append("")
        rows = []
        for nm, lab in (("s_m15", "yeşil — t0−15 dk"), ("s_m10", "yeşil — t0−10 dk"), ("s_m5", "yeşil — t0−5 dk"), ("s_0", "**yeşil — t0**"),
                        ("s_p5", "yeşil — t0+5 dk (yükseliş başladı)"), ("s_p10", "yeşil — t0+10 dk"), ("s_p15", "yeşil — t0+15 dk"), ("s_p30", "yeşil — t0+30 dk")):
            rows.append([lab, p_(e[nm]), p_(b[nm])])
        rows.append(["t0'dan ÖNCEKİ 15 dk içinde AL dönüşü var", p_(e["p_n_up_m15"]), p_(b["p_n_up_m15"])])
        rows.append(["t0'dan SONRAKİ 15 dk içinde AL dönüşü", p_(e["p_n_up_p15"]), p_(b["p_n_up_p15"])])
        rows.append(["t0'dan sonraki 30 dk içinde AL dönüşü", p_(e["p_n_up_p30"]), p_(b["p_n_up_p30"])])
        rows.append(["medyan: son AL dönüşü kaç dk ÖNCE (t0'a göre)", n_(e["lastup_med"], 0), n_(b["lastup_med"], 0)])
        rows.append(["medyan: sonraki AL dönüşü kaç dk SONRA", n_(e["nextup_med"], 0), n_(b["nextup_med"], 0)])
        rows.append(["medyan: sonraki AL dönüşünde fiyat (P0'a göre %)", sg_(e["nextup_gain_med"]), sg_(b["nextup_gain_med"])])
        L.append(md_table(["ölçü", "olay", "taban (eşleşmiş rastgele an)"], rows))
        L.append("")
        a = d["auc"]
        rows = []
        for fn, lab in (("bull_t0", "t0'da yeşil (ikili)"), ("signed_age_t0", "işaretli durum yaşı (yeşil +, kırmızı −)"), ("fresh_bull_t0", "t0'da yeni yeşil (≤ 3 bar)"),
                        ("flip_last15", "t0−15…t0 arası AL dönüşü"), ("bull_p15", "t0+15'te yeşil (yükseliş içinde)"),
                        ("flip_next15", "t0…t0+15 arası AL dönüşü"), ("flip_next30", "t0…t0+30 arası AL dönüşü")):
            rows.append([lab] + [n_(a[fn][k], 3) for k in ("all", "B1", "B2", "B3")])
        L.append("AUC (olay ↔ taban; 0,5 = ayırt etmez; < 0,5 olay daha az / > 0,5 olay daha çok):")
        L.append("")
        L.append(md_table(["özellik", "tümü", "B1", "B2", "B3"], rows))
        L.append("")
        hp, hn = d["hist_prev"], d["hist_next"]
        labs = ["0–5", "5–10", "10–15", "15–30", "30–60", ">60", "hiç yok"]
        rows = [[labs[i], p_(hp["event"][i]), p_(hp["base"][i]), "" if i >= 6 else ""] for i in range(7)]
        labn = ["0–5", "5–10", "10–15", "15–30", "30–60", ">60", "hiç yok"]
        rows2 = [[labn[i], p_(hn["event"][i]), p_(hn["base"][i])] for i in range(7)]
        L.append("Gecikme histogramı — SON AL dönüşü t0'dan kaç dk önce (sol) ve SONRAKİ AL dönüşü t0'dan kaç dk sonra (sağ):")
        L.append("")
        L.append(md_table(["dk önce", "olay", "taban"], [[r[0], r[1], r[2]] for r in rows]))
        L.append("")
        L.append(md_table(["dk sonra", "olay", "taban"], rows2))
        L.append("")
        info[tf] = {"bull_t0_ev": e["s_0"], "bull_t0_base": b["s_0"], "m15_ev": e["p_n_up_m15"], "m15_base": b["p_n_up_m15"], "p15_ev": e["p_n_up_p15"],
                    "p15_base": b["p_n_up_p15"], "next_med": e["nextup_med"], "next_base": b["nextup_med"], "gain_med": e["nextup_gain_med"], "auc_next15": a["flip_next15"]["all"],
                    "auc_last15": a["flip_last15"]["all"], "auc_bull0": a["bull_t0"]["all"]}
    h = T["ha"]
    L.append("### Hız Avcısı (HA) ile aynı ölçüt")
    L.append("")
    rows = [["HA adayı t0…t0+15 dk içinde", p_(h["ev_15"]), p_(h["base_15"]), n_(h["ev_15"] / h["base_15"], 1) + "×"],
            ["HA adayı t0…t0+30 dk içinde", p_(h["ev_30"]), p_(h["base_30"]), n_(h["ev_30"] / h["base_30"], 1) + "×"]]
    for tf in ("1m", "5m", "15m"):
        e, b = T["tf"][tf]["event"], T["tf"][tf]["base"]
        rows.append([f"{tf} çekirdek AL dönüşü t0…t0+15 dk", p_(e["p_n_up_p15"]), p_(b["p_n_up_p15"]), n_(e["p_n_up_p15"] / b["p_n_up_p15"], 1) + "×"])
        rows.append([f"{tf} çekirdek AL dönüşü t0…t0+30 dk", p_(e["p_n_up_p30"]), p_(b["p_n_up_p30"]), n_(e["p_n_up_p30"] / b["p_n_up_p30"], 1) + "×"])
    L.append(md_table(["sinyal penceresi", "olay", "taban", "olay/taban"], rows))
    L.append("")
    L.append(f"HA'nın ilk adayı (30 dk içinde olanlarda) medyan **{n_(h['ev_first_med_30'], 0)} dk** sonra, o andaki fiyat P0'ın medyan **{sg_(h['ev_gain_med_30'])}%** üstünde "
             f"(tabanda {sg_(h['base_gain_med_30'])}%). 5m çekirdek AL dönüşü için aynı sayı: medyan {n_(T['tf']['5m']['event']['nextup_med'], 0)} dk, "
             f"{sg_(T['tf']['5m']['event']['nextup_gain_med'])}%.")
    L.append("")
    rows = []
    for tf in ("1m", "5m", "15m"):
        o = T["order"][tf]
        rows.append([tf, k_(o["n_both"]), p_(o["rqk_first_share"]), p_(o["tie_share"]), n_(o["med_ha_minus_rqk_min"], 0),
                     p_(o["ev_rqk_le30"]), p_(o["ev_union_30"]), p_(o["base_union_30"])])
    L.append("Aynı olayda 30 dk içinde HA adayı VE çekirdek AL dönüşü varsa kim önce (HA−RQK > 0 ⇒ RQK önce); birleşim yakalama oranı:")
    L.append("")
    L.append(md_table(["tf", "ikisi de olan olay", "RQK önce", "aynı 5 dk", "medyan HA−RQK (dk)", "olayda RQK ≤30 dk", "olayda RQK∪HA ≤30 dk", "tabanda RQK∪HA ≤30 dk"], rows))
    L.append("")
    L.append("Not: 1m çekirdek her ~5 dk'da bir döndüğü için 'AL dönüşü ≤ 30 dk' neredeyse her an doğru (taban %97); 1m için bu tablo bilgi taşımıyor.")
    L.append("")
    # tüm kombinasyonlar
    rows = []
    for key in COMBO_KEYS:
        c = T["all_combos"][key]
        rows.append([key, p_(c["p_bull_t0_ev"]), p_(c["p_bull_t0_base"]), n_(c["auc_bull_t0"], 3), n_(c["auc_flip_last15"], 3), n_(c["auc_flip_next15"], 3),
                     p_(c["p_flip_next15_ev"]), p_(c["p_flip_next15_base"])])
    L.append("Ek — 24 kombinasyonun zamanlama özeti (AUC'ler tüm olaylarda):")
    L.append("")
    L.append(md_table(["kombinasyon", "yeşil t0 (olay)", "yeşil t0 (taban)", "AUC yeşil t0", "AUC dönüş t0−15…t0", "AUC dönüş t0…t0+15", "dönüş ≤15 dk sonra (olay)", "(taban)"], rows))
    L.append("")
    return "\n".join(L), info


def sec_lunatry(Lr: dict) -> str:
    L = ["## 7. Analiz 5 — LUNATRY 17 Ekim 01:00", ""]
    L.append(f"t0 = {Lr['t0']} (5m ızgara; P0 = 00:55 mumunun kapanışı = **{n_(Lr['p0'], 3)}**). Sonraki 60 dk'da en yüksek 5m kapanış {n_(Lr['peak_close_60'], 3)} (**{sg_(Lr['gain_close_60'])}%**), en yüksek fiyat {n_(Lr['peak_high_60'], 3)}. "
             "Çekirdekler HAM mumlar üzerinde (uygulamanın gördüğü sıra); zaman = bar KAPANIŞ zamanı.")
    L.append("")
    rows = []
    for key, v in Lr["tf"].items():
        fu = v["first_up_after"]; lb = v["last_up_before"]
        la = v.get("last_up_any")
        rows.append([key, v["state_t0"],
                     ("—" if la is None else f"{la['t']} ({n_(la['price'], 3)}; {n_(la['min_before'], 0)} dk önce)"),
                     "—" if fu is None else f"{fu['t']} ({n_(fu['price'], 3)}; {sg_(fu['vs_p0_pct'])}%; {n_(fu['min_vs_t0'], 0)} dk)"])
    L.append(md_table(["çekirdek", "t0'da renk", "t0 öncesi son AL dönüşü (tüm geçmiş; gün saat, fiyat)", "t0 SONRASI ilk AL dönüşü (zaman, fiyat, P0'a göre, t0'dan dk)"], rows))
    L.append("")
    for key, v in Lr["tf"].items():
        rows = [[x["t"], x["dir"], n_(x["price"], 3), sg_(x["vs_p0_pct"]) + "%", n_(x["min_vs_t0"], 0)] for x in v["flips"]]
        L.append(f"**{key}** — 00:00–04:00 arası tüm renk değişimleri:")
        L.append("")
        L.append(md_table(["bar kapanışı", "yön", "kapanış", "P0'a göre", "t0'a göre dk"], rows) if rows else "(değişim yok)")
        L.append("")
    ser = Lr["series_1m"]
    rows = [[x["t"], n_(x["close"], 3), n_(x["yhat"], 4), "yeşil" if x["bull"] else "kırmızı"] for x in ser]
    L.append("1m çekirdek (A, h=8, r=2) — 00:50…01:30 bar kapanışları:")
    L.append("")
    L.append(md_table(["kapanış", "close", "yhat", "renk"], rows))
    L.append("")
    if Lr.get("ha_rows"):
        L.append("HA adayları (rescan): " + ", ".join(f"{x['t']} @ {x['price']}" for x in Lr["ha_rows"][:10]))
    else:
        L.append("HA adayı satırı yok: `work/rescan_90g_nogate.jsonl` 16 Ekim 23:55'te bitiyor. Canlıda LUNATRY radarın izleme listesinin tepesindeydi ama "
                 "bildirim `BTC_BEAR_REGIME_SHIELD` + `mfi_asiri_alim:96` kapılarına takıldı (docs/REJIM_KALKANI_ANALIZI_2026-10-17.md).")
    L.append("")
    return "\n".join(L)


def sec_entry(E: dict, meta: dict) -> tuple[str, dict]:
    L = ["## 4. Analiz 2 — RQK dönüşü giriş sinyali olarak", ""]
    L.append(f"Sinyal = çekirdeğin **kırmızı→yeşil** dönüşü (bar kapanışında), 24 sa quote ≥ {MIN_QUOTE / 1e6:.0f}M TRY. Sonuç ölçüsü 90 günlük çalışmadakiyle aynı: TP 1,5 / SL −3 / maliyet 0,225 / 60 dk "
             "(pencere karardan 5 dk sonra başlar); trailing = tetik %1,0 / iz %0,8. Şans farkı = isabet − null3 (aynı sembol, ±1 sa dilimi, benzer 30 dk aralık ve getiri; "
             "3 tohum × 3000 sinyal örneği; ± = gün-kümeli %95). Her sembolde 60 dk soğuma (filtreden SONRA). "
             "'olay içi' = sinyal anı bir olayın [t0−10 dk, bitiş] penceresinde; 'kat' = bunun rastgele geçerli ana oranı (HA ≈ 13–14×).")
    L.append("")
    br = meta["base_rates"]
    L.append("Rastgele geçerli anın olay penceresinde olma olasılığı (taban): " + "; ".join(f"{b} {p_(br[b]['in'], 2)}" for b in BN) + ".")
    L.append("")
    names = {"liq": "yalnız likidite", "liq+ema99": "+ fiyat > EMA99 (5m)", "liq+k15": "+ 15m çekirdek yeşil", "liq+ema99+k15": "+ ikisi"}
    info: dict = {"rows": []}
    for tf in ("5m", "1m"):
        rows = []
        for filt in ("liq", "liq+ema99", "liq+k15", "liq+ema99+k15"):
            cfg = E["configs"].get(f"{tf}|{filt}")
            if not cfg:
                continue
            for b in BN:
                v = cfg["cd"][b]
                rows.append([f"{tf} · {names[filt]}", b, n_(cfg["raw"][b]["per_day"], 0), n_(v.get("per_day"), 0), p_(v.get("hit15")), p_(v.get("hit2")),
                             sg_(v.get("net15"), 3), sg_(v.get("trail"), 3), lift_ci(v), sg_(v.get("liftnet"), 3), p_(v.get("p_in"), 2), n_(v.get("p_in_lift"), 1) + "×"])
                info["rows"].append({"cfg": f"{tf}|{filt}", "b": b, "lift": v.get("lift15"), "se": v.get("se15"), "n": v.get("n")})
        for b in BN:
            v = E["ha_ref"][b]
            if tf == "5m":
                rows.append(["**HA referansı**", b, "—", n_(v.get("per_day"), 0), p_(v.get("hit15")), p_(v.get("hit2")), sg_(v.get("net15"), 3), sg_(v.get("trail"), 3), lift_ci(v),
                             sg_(v.get("liftnet"), 3), p_(v.get("p_in"), 2), n_(v.get("p_in_lift"), 1) + "×"])
        L.append(f"### {tf} dönüşleri (A, h=8, r=2)")
        L.append("")
        L.append(md_table(["yapılandırma", "blok", "ham sinyal/gün", "soğumalı/gün", "hit60@1,5", "hit60@2,0", "net60", "trailing net", "şans farkı (pp)", "net şans farkı", "olay içi/öncesi pay", "olay içi kat"], rows))
        L.append("")
    return "\n".join(L), info


def sec_filter(F: dict, A: dict | None) -> tuple[str, dict]:
    L = ["## 5. Analiz 3 — RQK, Hız Avcısı adayları üzerinde filtre olarak", ""]
    L.append(f"Hız Avcısı (HA) adayı = `rescan_90g_nogate` rank ≤ 10, aşırı alımda değil, 60 dk bölümlenmiş (**{k_(F['n_ha'])}** bölüm; bölüm başına ilk aday). Aday anında KAPANMIŞ son 5m ve 15m çekirdek barının durumu "
             "(A, h=8, r=2): yeşil/kırmızı; 'yeni' = renk en çok 3 bar önce değişti, 'olgun' = daha eski. Metrikler HA'nın kendi bloklarıyla aynı: hit60@1,5, net60 (TP 1,5/SL −3/maliyet 0,225), trailing, "
             "şans farkı (null3; 3 tohum × 3000). **Δ isabet** = grup − tümleyeni (gün-kümeli bootstrap %95 aralık); aralık 0'ı içermiyorsa ayırt edici.")
    L.append("")
    info: dict = {"groups": {}}
    gall = F["groups"]["TÜM (HA)"]
    for bname in BN:
        pass
    rows = []
    for g, row in F["groups"].items():
        for b in BN:
            v = row[b]
            d = v["d_hit15"]; dn = v["d_net15"]
            rows.append([("**" + g + "**") if g.startswith("TÜM") else g, b, k_(v["n"]), p_(v.get("share"), 0), p_(v.get("hit15")), sg_(v.get("net15"), 3), sg_(v.get("trail"), 3), lift_ci(v),
                         "—" if d.get("diff") is None else f"{100 * d['diff']:+.1f} [{100 * d['lo']:+.1f}; {100 * d['hi']:+.1f}]".replace(".", ",")])
            info["groups"].setdefault(g, {})[b] = {"n": v["n"], "lift": v.get("lift15"), "d": d, "hit": v.get("hit15"), "net": v.get("net15"),
                                                  "trail": v.get("trail"), "dn": dn}
    L.append(md_table(["grup (aday anında çekirdek durumu)", "blok", "n", "pay", "hit60@1,5", "net60", "trailing net", "şans farkı (pp)", "Δ isabet vs tümleyen (pp) [%95]"], rows))
    L.append("")
    return "\n".join(L), info


def sec_params(Pm: dict, F: dict) -> tuple[str, dict]:
    L = ["## 6. Analiz 4 — Parametreler ve yürüyen-ileri doğrulama", ""]
    L.append("24 kombinasyon: 5m için varyant A ve B × h ∈ {8,16,25} × r ∈ {1,2,8} (18); 1m ve 15m için yalnız varyant A, r=2, h ∈ {8,16,25} (6). "
             "Tam ızgara (54) çalıştırılmadı (çoklu karşılaştırmayı sınırlamak için). **Seçim yalnız B1'de**, B2 ve B3 dokunulmadan test edildi. "
             f"İki rol: (E) sade AL dönüşü sinyali (likidite + 60 dk soğuma; seçim ölçütü B1 şans farkı, sinyal/gün ≥ {MIN_PER_DAY_SELECT:.0f}); "
             "(F) HA filtresi (5m/15m kombinasyonlar; ölçüt B1'de skor = şans farkı(yeşil) − şans farkı(kırmızı), her iki grupta n ≥ 300).")
    L.append("")
    info: dict = {}
    # ---- E
    E = Pm["entry"]
    rows = []
    sel = []
    for key in COMBO_KEYS:
        v = E.get(key)
        if not v:
            continue
        rows.append([key] + [n_(v[b].get("per_day"), 0) for b in BN] + [pp_(v[b].get("lift15")) if v[b].get("lift15") is not None else "—" for b in BN]
                    + [sg_(v[b].get("net15"), 3) for b in BN])
        if v["B1"].get("per_day") and v["B1"]["per_day"] >= MIN_PER_DAY_SELECT and v["B1"].get("lift15") is not None:
            sel.append((v["B1"]["lift15"], key))
    L.append("### (E) Sade AL dönüşü sinyali — 24 kombinasyon")
    L.append("")
    L.append(md_table(["kombinasyon", "sinyal/gün B1", "B2", "B3", "şans farkı B1", "B2", "B3", "net60 B1", "B2", "B3"], rows))
    L.append("")
    if sel:
        sel.sort(reverse=True)
        best = sel[0][1]
        ha = Pm["ha_all"]
        b1 = [E[k]["B1"]["lift15"] for k in COMBO_KEYS if k in E and E[k]["B1"].get("lift15") is not None]
        l2 = [E[k]["B2"]["lift15"] for k in COMBO_KEYS if k in E and E[k]["B1"].get("lift15") is not None]
        l3 = [E[k]["B3"]["lift15"] for k in COMBO_KEYS if k in E and E[k]["B1"].get("lift15") is not None]
        rho12 = spearman(b1, l2); rho13 = spearman(b1, l3)
        rows = []
        for lab, key in (("B1'de seçilen (en yüksek şans farkı)", best), ("uygulama varsayılanı 5m A h8 r2", DEFAULT["5m"]), ("uygulama varsayılanı 1m A h8 r2", DEFAULT["1m"])):
            v = E[key]
            rows.append([lab, key] + [lift_ci(v[b]) for b in BN] + [sg_(v[b].get("net15"), 3) for b in BN])
        rows.append(["HA (aynı ölçü)", "—"] + [lift_ci(ha[b]) for b in BN] + [sg_(ha[b].get("net15"), 3) for b in BN])
        L.append("Seçim sonucu — örneklem-içi (B1) ve örneklem-dışı (B2, B3):")
        L.append("")
        L.append(md_table(["", "kombinasyon", "şans farkı B1 (içi)", "B2 (dışı)", "B3 (dışı)", "net60 B1", "B2", "B3"], rows))
        L.append("")
        mx2 = max(l2); mx3 = max(l3)
        L.append(f"24 kombinasyonun B1 şans farkı sırası ile B2/B3 sırası arasında Spearman ρ: B2 için **{n_(rho12, 2)}**, B3 için **{n_(rho13, 2)}** "
                 "(kombinasyonlar birbirine çok benzediği — r değişimi neredeyse etkisiz — için 24 gözlem bağımsız değil; ρ'nun bir kısmı ortak 'piyasa dönemi' etkisidir). "
                 f"Hiçbir kombinasyonun şans farkı B1'de {pp_(max(b1))}'i, B2'de {pp_(mx2)}'yi, B3'te {pp_(mx3)}'ü geçmiyor; HA ise {pp_(Pm['ha_all']['B1'].get('lift15'))} / {pp_(Pm['ha_all']['B2'].get('lift15'))} / "
                 f"{pp_(Pm['ha_all']['B3'].get('lift15'))}.")
        L.append("")
        info["E_best"] = best
        info["E_rho"] = (rho12, rho13)
        info["E_best_lifts"] = [E[best][b].get("lift15") for b in BN]
        info["E_ha_lifts"] = [ha[b].get("lift15") for b in BN]
        info["E_max_lift_any"] = max(((E[k][b].get("lift15") or -9), k, b) for k in E for b in BN)
        info["E_max_by_block"] = {b: max((E[k][b].get("lift15") or -9) for k in E) for b in BN}
        info["E_max_perday"] = max((E[k]["B1"].get("per_day") or 0) for k in E)
    # ---- F
    FM = Pm["filter"]
    rows = []
    sel = []
    for key, row in FM.items():
        g, r = row["yeşil"], row["kırmızı"]
        rec = [key]
        sc = {}
        for b in BN:
            if g[b].get("lift15") is not None and r[b].get("lift15") is not None:
                sc[b] = g[b]["lift15"] - r[b]["lift15"]
            else:
                sc[b] = None
        rec += [pp_(sc[b]) if sc[b] is not None else "—" for b in BN]
        for b in BN:
            d = g[b]["d_hit15"]
            rec.append("—" if d.get("diff") is None else f"{100 * d['diff']:+.1f} [{100 * d['lo']:+.1f}; {100 * d['hi']:+.1f}]".replace(".", ","))
        rec += [f"{k_(g['B1']['n'])}/{k_(r['B1']['n'])}"]
        rows.append(rec)
        if sc["B1"] is not None and g["B1"]["n"] >= 300 and r["B1"]["n"] >= 300:
            sel.append((sc["B1"], key))
    L.append("### (F) HA filtresi — 5m ve 15m kombinasyonlar")
    L.append("")
    L.append("Skor = şans farkı(yeşil grup) − şans farkı(kırmızı grup) (pp; > 0 ⇒ 'yeşil' HA adayı daha iyi). Δ isabet = yeşil grup − tümleyeni (kırmızı + bilinmeyen) [%95].")
    L.append("")
    L.append(md_table(["kombinasyon", "skor B1", "B2", "B3", "Δ isabet B1 (pp)", "Δ isabet B2", "Δ isabet B3", "n yeşil/kırmızı (B1)"], rows))
    L.append("")
    if sel:
        sel.sort(reverse=True)
        best = sel[0][1]; worst = sel[-1][1]
        ha = Pm["ha_all"]
        rows = []
        for lab, key in (("B1'de en yüksek skor ('yeşil daha iyi')", best), ("B1'de en düşük skor ('kırmızı daha iyi')", worst), ("varsayılan 5m A h8 r2", DEFAULT["5m"]), ("varsayılan 15m A h8 r2", DEFAULT["15m"])):
            g, r = FM[key]["yeşil"], FM[key]["kırmızı"]
            rec = [lab, key]
            for b in BN:
                rec.append(lift_ci(g[b]) + " / " + lift_ci(r[b]))
            rows.append(rec)
        rows.append(["HA tümü", "—"] + [lift_ci(ha[b]) for b in BN])
        L.append("Seçim sonucu — şans farkı (yeşil grup / kırmızı grup), pp ± %95:")
        L.append("")
        L.append(md_table(["", "kombinasyon", "B1 (içi)", "B2 (dışı)", "B3 (dışı)"], rows))
        L.append("")
        s1 = [x[0] for x in sel]
        keys = [x[1] for x in sel]
        s2 = [FM[k]["yeşil"]["B2"]["lift15"] - FM[k]["kırmızı"]["B2"]["lift15"] for k in keys if FM[k]["yeşil"]["B2"].get("lift15") is not None and FM[k]["kırmızı"]["B2"].get("lift15") is not None]
        s3 = [FM[k]["yeşil"]["B3"]["lift15"] - FM[k]["kırmızı"]["B3"]["lift15"] for k in keys if FM[k]["yeşil"]["B3"].get("lift15") is not None and FM[k]["kırmızı"]["B3"].get("lift15") is not None]
        if len(s2) == len(s1) and len(s3) == len(s1):
            r2, r3 = spearman(s1, s2), spearman(s1, s3)
            L.append(f"Skorun B1→B2 sıra korelasyonu ρ = **{n_(r2, 2)}**, B1→B3 ρ = **{n_(r3, 2)}**.")
            L.append("")
            info["F_rho"] = (r2, r3)
        # seçilen filtrenin ayrıntısı: yeşil / kırmızı / tümü
        rows = []
        for b in BN:
            for lab, v in (("yeşil (korunan)", FM[best]["yeşil"][b]), ("kırmızı (elenen)", FM[best]["kırmızı"][b]), ("HA tümü", Pm["ha_all"][b])):
                rows.append([b, lab, k_(v["n"]), p_(v.get("hit15")), p_(v.get("hit2")), sg_(v.get("net15"), 3), sg_(v.get("trail"), 3), lift_ci(v)])
        L.append(f"B1'de seçilen filtre **{best}** ayrıntısı (HA adayı anında bu çekirdek yeşil ise tut):")
        L.append("")
        L.append(md_table(["blok", "grup", "n", "hit60@1,5", "hit60@2,0", "net60", "trailing net", "şans farkı (pp)"], rows))
        L.append("")
        info["F_best"] = best; info["F_worst"] = worst
        info["F_detail"] = {b: {"green": FM[best]["yeşil"][b], "red": FM[best]["kırmızı"][b], "all": Pm["ha_all"][b]} for b in BN}
        info["F_scores"] = {k: {b: (FM[k]["yeşil"][b].get("lift15"), FM[k]["kırmızı"][b].get("lift15")) for b in BN} for k in keys}
    return "\n".join(L), info


# ------------------------------------------------------------------------------------------------ yargı
def sec_control(C: dict) -> str:
    L = ["### Kontrol — çekirdek durumu HA'ya ÖZGÜ bilgi mi, yoksa genel bir taban etkisi mi?", ""]
    L.append("Çekirdek rengi her rastgele anda da kısa vadeli momentumu yansıtır; HA zaten momentum seçtiği için etkinin HA içinde azalması beklenir. Kontrol: her HA bölümü için AYNI sembol + AYNI günden ≤ 20 rastgele likit an "
             f"(toplam {k_(C['n']['matched'])}) alındı; 'yeşil − tümleyeni' hit60@1,5 farkı bu anlarda ve HA'da ölçüldü. **Fark-farkı** = HA farkı − rastgele an farkı (gün-kümeli bootstrap %95): "
             "< 0 ise çekirdek rengi HA'nın üstüne bilgi eklemiyor (HA zaten içeriyor), > 0 ise HA'ya özgü katkı var. "
             "Not: rastgele anların kendi isabeti HA'ya yakın (≈ %40) çünkü HA'nın seçtiği sembol-günler zaten 'sıcak'.")
    L.append("")
    rows = []
    for key, v in C.items():
        if key == "n":
            continue
        for b in BN:
            r = v[b]
            d = r["did"]
            rows.append([key, b, p_(r["share_green_ha"], 0), p_(r["share_green_matched"], 0), p_(r["hit_ha_green"]), p_(r["hit_ha_other"]), pp_(d["d_ha"]),
                         p_(r["hit_m_green"]), p_(r["hit_m_other"]), pp_(d["d_rand"]),
                         f"{100 * d['did']:+.1f} [{100 * d['lo']:+.1f}; {100 * d['hi']:+.1f}]".replace(".", ",")])
    L.append(md_table(["çekirdek", "blok", "yeşil payı HA", "yeşil payı rastgele", "HA hit yeşil", "HA hit diğer", "HA farkı", "rastgele hit yeşil", "rastgele hit diğer", "rastgele fark", "fark-farkı (pp) [%95]"], rows))
    L.append("")
    return "\n".join(L)


def verdict(ti, ei, fi, pi, T, F, Pm, E, C) -> tuple[str, dict]:
    V: list[str] = []
    flags: dict = {}
    t5 = ti["5m"]; t1 = ti["1m"]; t15 = ti["15m"]
    ha = T["ha"]
    # --- 1) zamanlama
    V.append(f"**Erken tespit — hayır.** Çekirdek yükselişten ÖNCE yeşile dönmüyor: t0'da yeşil olma oranı olayda 1m/5m/15m için {p_(t1['bull_t0_ev'], 0)}/{p_(t5['bull_t0_ev'], 0)}/{p_(t15['bull_t0_ev'], 0)} "
             f"(rastgele anda {p_(t1['bull_t0_base'], 0)}/{p_(t5['bull_t0_base'], 0)}/{p_(t15['bull_t0_base'], 0)}); t0'dan önceki 15 dk'da AL dönüşü olay tarafında rastgele andan DAHA AZ "
             f"(5m: {p_(t5['m15_ev'], 0)} vs {p_(t5['m15_base'], 0)}; AUC {n_(t5['auc_last15'], 2)}) — olaylar küçük bir düşüşün dibinden başlıyor ve çekirdek o sırada kırmızı. "
             f"Dönüş yükseliş başladıktan SONRA geliyor: 5m dönüşü t0'dan medyan {n_(t5['next_med'], 0)} dk sonra, fiyat P0'ın {sg_(t5['gain_med'])}% üstündeyken "
             f"(HA'nın ilk adayı: medyan {n_(ha['ev_first_med_30'], 0)} dk, {sg_(ha['ev_gain_med_30'])}%); 15m dönüşü {sg_(t15['gain_med'])}% ile çok geç. "
             f"1m çekirdek t0'dan medyan {n_(t1['next_med'], 0)} dk sonra dönüyor ama 1m çekirdek rastgele anlarda da her ~{n_(t1['next_base'], 0)} dk'da dönüyor (t0…t0+15 AUC'si {n_(t1['auc_next15'], 2)}). "
             "(t0'dan SONRAKİ pencerelerdeki yüksek oranlar kısmen tanım gereği: olayın ilk 5m mumu yeşil ve P0'ın üstünde olmak zorunda.)")
    o5 = T["order"]["5m"]
    e5, b5 = T["tf"]["5m"]["event"], T["tf"]["5m"]["base"]
    V.append(f"Sinyal penceresi karşılaştırması (olay ↔ rastgele an): 5m çekirdek AL dönüşü t0…t0+15 dk {p_(t5['p15_ev'], 0)} ↔ {p_(t5['p15_base'], 0)} ({n_(t5['p15_ev'] / t5['p15_base'], 1)}×), t0…t0+30 dk "
             f"{p_(e5['p_n_up_p30'], 0)} ↔ {p_(b5['p_n_up_p30'], 0)} ({n_(e5['p_n_up_p30'] / b5['p_n_up_p30'], 1)}×); HA adayı için {p_(ha['ev_15'], 0)} ↔ {p_(ha['base_15'], 0)} ({n_(ha['ev_15'] / ha['base_15'], 1)}×) ve "
             f"{p_(ha['ev_30'], 0)} ↔ {p_(ha['base_30'], 0)} ({n_(ha['ev_30'] / ha['base_30'], 1)}×). İkisi de 30 dk içinde sinyal veren {k_(o5['n_both'])} olayda 5m dönüşü HA'dan {p_(o5['rqk_first_share'], 0)} oranında önce "
             f"({p_(o5['tie_share'], 0)} aynı 5 dk), medyan {n_(o5['med_ha_minus_rqk_min'], 0)} dk önce — küçük bir zaman avantajı var; ama dönüş rastgele anların da {p_(b5['p_n_up_p30'], 0)}'inde görüldüğü için ayırt edicilik HA'dan düşük "
             "ve çekirdek bağımsız bir 'erken uyarı' vermiyor. LUNATRY'de 5m çekirdek zaten t0'dan önce yeşildi (son AL dönüşü 160 dk önce; yükseliş boyunca hiç dönüş yok), 1m çekirdek 01:02'de P0 seviyesinde döndü "
             "(ama 00:00–01:02 arasında 1m çekirdek altı kez AL döndü; tek başına gürültü).")
    # --- 2) giriş sinyali
    ent = ei["rows"]
    hal = {b: Pm["ha_all"][b].get("lift15") for b in BN}
    parts = []
    for b in BN:
        cells = [r for r in ent if r["b"] == b and r["lift"] is not None]
        npos = sum(1 for r in cells if r["se"] is not None and r["lift"] - 1.96 * r["se"] > 0)
        mx = max(r["lift"] for r in cells)
        parts.append(f"{b}: {npos}/{len(cells)} hücrede aralık > 0, en yüksek {pp_(mx)} (HA {pp_(hal[b])})")
    max_net = max(E["configs"][c]["cd"][b].get("net15") or -9 for c in E["configs"] for b in BN)
    max_tr = max(E["configs"][c]["cd"][b].get("trail") or -9 for c in E["configs"] for b in BN)
    beats = sum(1 for r in ent if r["lift"] is not None and r["lift"] > hal[r["b"]])
    flags["entry_beats_ha"] = beats
    pd_all = [r.get("per_day") for c in E["configs"] for b in BN for r in [E["configs"][c]["cd"][b]] if r.get("per_day")]
    V.append("**Giriş sinyali olarak — HA'nın gerisinde; B1'de rastgeleden ayrışmıyor, B2/B3'te küçük ama pozitif.** 8 yapılandırma (5m/1m × {yalnız likidite, +EMA99, +15m yeşil, +ikisi}) için şans farkı: " + "; ".join(parts) + ". "
             f"HA'yı geçen hücre sayısı **{beats}/{len(ent)}**. Soğuma sonrası bile günde ≈ {k_(min(pd_all))}–{k_(max(pd_all))} sinyal (HA ≈ 200–250). net60 hiçbir hücrede pozitif değil (en iyi {sg_(max_net, 3)} %/işlem; "
             f"HA −0,36…−0,43 — fakat HA daha oynak sembol-günlerde olduğundan net60 doğrudan kıyaslanmaz, şans farkı kıyaslanır); trailing net en iyi {sg_(max_tr, 3)} (HA ≈ 0,00 … −0,06). "
             "'Olay içi' kat ≈ 1–1,5× (HA ≈ 13–14×): dönüş sinyali olay pencerelerini rastgele ana göre pek zenginleştirmiyor. B2/B3'teki küçük pozitif fark, B1'de olmayışı ve HA'nın yarısı kadar büyüklüğü nedeniyle "
             "büyük olasılıkla genel yükseliş-momentumuyla ilgili (nedensellik bu veriyle ayrıştırılamaz).")
    # --- 3) HA filtresi
    good_all = []; good2 = []; bad_all = []
    for g, row in fi["groups"].items():
        if g.startswith("TÜM"):
            continue
        ok_b = 0; bad_b = 0
        for b in BN:
            d = row[b]["d"]
            if d.get("diff") is None:
                continue
            lf = row[b]["lift"]; lf_all = F["groups"]["TÜM (HA)"][b].get("lift15")
            if d["lo"] > 0 and lf is not None and lf_all is not None and lf > lf_all:
                ok_b += 1
            if d["hi"] < 0:
                bad_b += 1
        if ok_b == 3:
            good_all.append(g)
        elif ok_b == 2:
            good2.append(g)
        if bad_b == 3:
            bad_all.append(g)
    flags["filter_all3"] = good_all; flags["filter_2of3"] = good2; flags["filter_bad3"] = bad_all
    s = f"**HA filtresi olarak — ölçülebilir ek değer yok.** 15 durum grubundan (varsayılan A/h8/r2, 5m ve 15m) üç blokta birden (Δ isabet %95 aralığı > 0 ve şans farkı HA'nın üstünde) HA'yı iyileştiren: " + ("; ".join(good_all) if good_all else "**yok**") + ". "
    if good2:
        s += "Üç bloktan ikisinde tutan (post-hoc): " + "; ".join(good2) + ". "
    if bad_all:
        s += "Üç blokta da HA'yı kötüleştiren: " + "; ".join(bad_all) + ". "
    r5 = fi["groups"].get("5m kırmızı")
    if r5:
        s += ("5m çekirdek aday anında KIRMIZI iken HA daha iyi (beklenen 'yeşil teyit eder'in tersi): Δ isabet (kırmızı − yeşil) " + ", ".join(
            (b + " " + ("—" if r5[b]["d"].get("diff") is None else f"{100 * r5[b]['d']['diff']:+.1f} pp [{100 * r5[b]['d']['lo']:+.1f}; {100 * r5[b]['d']['hi']:+.1f}]".replace(".", ","))) for b in BN)
            + " — etki B3'te kayboluyor.")
    V.append(s)
    # kontrol: genel taban etkisi
    ck = "15m_A_h25_r2"
    if C and ck in C:
        c = C[ck]
        V.append(f"Kontrol (aynı sembol-gün rastgele anlar): {ck} yeşilken rastgele anlarda hit60@1,5 {pp_(c['B1']['did']['d_rand'])}/{pp_(c['B2']['did']['d_rand'])}/{pp_(c['B3']['did']['d_rand'])} yüksek (B1/B2/B3) — genel momentum etkisi; "
                 f"HA içinde ise yalnız {pp_(c['B1']['did']['d_ha'])}/{pp_(c['B2']['did']['d_ha'])}/{pp_(c['B3']['did']['d_ha'])}. Fark-farkı {pp_(c['B1']['did']['did'])}/{pp_(c['B2']['did']['did'])}/{pp_(c['B3']['did']['did'])} "
                 "(her blokta aralık < 0): çekirdek rengi HA'nın seçtiği adayların üstüne ek bilgi taşımıyor — HA bu bilgiyi zaten içeriyor.")
    # --- 4) yürüyen-ileri
    if "E_best" in pi:
        eb = pi["E_best"]; ls = pi["E_best_lifts"]; hl = pi["E_ha_lifts"]
        V.append(f"**Parametreler (yürüyen-ileri, B1'de seçip B2/B3'te test):** (E) AL dönüşü sinyali için B1'in en iyisi {eb}: şans farkı B1 {pp_(ls[0])} → B2 {pp_(ls[1])}, B3 {pp_(ls[2])}; HA {pp_(hl[0])}/{pp_(hl[1])}/{pp_(hl[2])}. "
                 f"Tüm 24 kombinasyonda blok başına en yüksek şans farkı {pp_(pi['E_max_by_block']['B1'])}/{pp_(pi['E_max_by_block']['B2'])}/{pp_(pi['E_max_by_block']['B3'])} — HA'nın altında; varyant B, h=16/25, r=1/8 ve 1m/15m "
                 "seçenekleri varsayılandan anlamlı biçimde iyi değil.")
    if "F_best" in pi:
        fb = pi["F_best"]; fd = pi["F_detail"]
        sc = {b: fd[b]["green"].get("lift15") - fd[b]["red"].get("lift15") for b in BN}
        gv = {b: fd[b]["green"].get("hit15") - fd[b]["all"].get("hit15") for b in BN}
        V.append(f"(F) HA filtresi olarak B1'de seçilen **{fb}** (HA adayı anında 15m çekirdek h=25 yeşil ise tut): skor (yeşil−kırmızı şans farkı) B1 {pp_(sc['B1'])} (içi), B2 {pp_(sc['B2'])}, B3 {pp_(sc['B3'])} (dışı) — işaret üç blokta tutarlı, "
                 f"ama korunan kümenin isabeti HA tümünün yalnız {pp_(gv['B1'])}/{pp_(gv['B2'])}/{pp_(gv['B3'])} üstünde, net60 hâlâ negatif ve kontrol testinde HA'ya özgü katkı yok. Bu, tek bir filtre varyantının "
                 "seçim-dışı bloklarda küçük ve pratik değeri olmayan bir işaret tutarlılığıdır.")
    # --- sonuç
    g15n = fi["groups"].get("15m yeşil, yeni (≤3 bar)")
    g5r = fi["groups"].get("5m kırmızı")
    extra = ""
    if g15n:
        extra = ("Tek tutarlı örüntü: 15m çekirdek az önce (≤ 3 bar) yeşile döndüyse HA adayı daha kötü (Δ isabet " + ", ".join(
            f"{b} {100 * g15n[b]['d']['diff']:+.1f}".replace(".", ",") for b in BN) + " pp; üç blokta aralık < 0), 5m çekirdek kırmızıysa (geri çekilme) biraz daha iyi (B3'te kayboluyor). "
            "Bu 'yeni dönüşü kovalama / geri çekilmeyi bekle' hipotezi olarak ileri (kâğıt-defter) testle sınanabilir; 15 grup × 3 blok çoklu karşılaştırması içinde kanıtlanmış sayılmaz.")
    V.append("**Genel hüküm:** RQK çekirdeği (uygulamadaki ya da kanonik ayarlarla) LUNA tipi erken yükselişlerde (a) yükselişten önce değil sonra döndüğü (HA ile ortak olaylarda birkaç dk önce olabilir ama rastgele anlarda da sık döndüğü için ayırt edici değil), "
             "(b) giriş sinyali olarak HA'nın gerisinde kalan, B1'de sıfır, B2/B3'te küçük bir şans farkı ürettiği, (c) HA adaylarına filtre olarak örneklem dışında HA'nın zaten seçtiği momentumun ötesinde bilgi eklemediği "
             "(kontrol testinde fark-farkı her blokta negatif) için **HA'ya anlamlı bir destek sağlamıyor; daha erken değil, daha iyi de değil**. Canlıya alma önerisi yok. " + extra)
    return "\n\n".join(V), flags


def build(args) -> None:
    out = Path(args.out_dir)
    T = load(out, "timing"); E = load(out, "entry"); F = load(out, "filter"); Pm = load(out, "params"); Lr = load(out, "lunatry"); meta = load(out, "meta"); C = load(out, "control")
    s_t, ti = sec_timing(T)
    s_e, ei = sec_entry(E, meta)
    s_f, fi = sec_filter(F, Pm["ha_all"])
    s_c = sec_control(C) if C else ""
    s_p, pi = sec_params(Pm, F)
    s_l = sec_lunatry(Lr)
    vtxt, flags = verdict(ti, ei, fi, pi, T, F, Pm, E, C)
    head = HEADER.format(verdict=vtxt)
    limits = LIMITS.format(n_comb=len(COMBOS))
    rep = "\n\n".join([head, METHOD, s_t, s_e, s_f, s_c, s_p, s_l, limits]) + "\n"
    (out / "report.md").write_text(rep, encoding="utf-8")
    print(f"[report] yazıldı: {out / 'report.md'} ({len(rep)} karakter)", flush=True)


HEADER = """# Rational Quadratic Kernel (RQK) göstergesi — LUNA tipi erken yükselişler için destek verir mi? (2026-10-17)

**Soru:** Grafiğin "Rational Quadratic Kernel" göstergesi (yükselirken yeşil, düşerken kırmızı; renk değişimi = al/sat) LUNATRY 17 Ekim 01:00 (+%8 / 60 dk) gibi erken yükselişleri
**mevcut sistemden (Hız Avcısı, HA) daha erken ya da daha iyi** yakalamaya yardım eder mi?

## 1. Sonuç

{verdict}

> Bu rapor `scripts/rqk_study.py` (+ `rqk_analysis.py`, `rqk_report.py`) tarafından üretildi; gösterge `app/rescan/rqk.py`. Canlı koda dokunulmadı.
"""

METHOD = """## 2. Gösterge ve yöntem

**Gösterge (grafik hesabı, `frontend/app/charts/IndicatorPicker.tsx` → `SLING_SHOT_ENTRY`).** Varsayılan h=8, r=2, smoothColors=false. yhat(i) = Σ_{k<min(h,i+1)} close[i−k]·w(k) / Σ w(k), w(k) = (1 + k²/(h²·2r))^(−r); toplam yalnız SON h muma uzanır
(özgün jdehorty betiği ~25+ bar toplar; uygulama kesiyor). Renk: yeşil ⇔ yhat(i−1) < yhat(i) veya (yhat(i−2) > yhat(i−1) ve yhat(i−1) > yhat(i) DEĞİL). AL = kırmızı→yeşil renk değişimi.
Port: `app/rescan/rqk.py` (vektörel numpy; toplama sırası uygulamayla aynı olduğundan bit-düzeyinde aynı — düz serilerdeki eşitlik dalları dâhil). Parite testi: `tests/test_rqk.py` (TS mantığının birebir JS kopyası
`work/rqk/rqk_calc.js` Node ile çalıştırıldı → `tests/fixtures/rqk_parity.json`; 5 seri × 7 parametre kümesi, > 1000 yhat/renk karşılaştırması; Node varsa test yeniden çalıştırır). Varyant B = kanonik: pencere 25 bar, bant genişliği h, renk yhat(i−1) < yhat(i).

> **Önemli not (kullanıcı varsayımı):** Grafikte bu göstergenin B/S okları renk değişiminden ÇIKMIYOR. `page.tsx` `registryId === "sling_shot"` için `signals.ts → slingShotSignals`'ı çağırıyor; bu fonksiyon çekirdekle ilgisiz bir
> **EMA50/EMA11 SlingShot** mantığı (EMA11 > EMA50 iken önceki kapanış ≤ EMA11 ve yeni kapanış > EMA11 ⇒ AL; alternasyonlu). Aşağıdaki analizler çekirdeğin RENK DEĞİŞİMİNİ ölçüyor (soruda istenen); grafikteki oklar ayrı bir mantık.

**Veri.** `historical_candles` 1m/5m/15m, 19 Tem → 17 Eki 2026 (306 sembol; 1m yalnız 304 likit sembol). Çekirdek HAM mumlar üzerinde (uygulamanın gördüğü sıra; boşluk doldurulmadı — DB 0 hacimli düz mumları da tutuyor, eksik satır çok az).
Olaylar: `work/pattern90/events.csv` (tanım docs/CIKIS_DESEN_ANALIZI_90G_2026-10-17.md: 60 dk içinde ≥ +%4, ≥ %70 yeşil mum, geri çekilme ≤ %1,5, tek mum ≤ %2,5, 24 sa quote ≥ 5M TRY; t0 = koşunun ilk mumu).
HA: `work/rescan_90g_nogate.jsonl` canlı-benzeri alt küme (rank ≤ 10, aşırı alımda değil; 20 343 bölüm, ≈ 226/gün). Sonuç araçları: `pattern_study.forward_outcomes` (5m ızgara; 1m sinyaller için aynı kurallar 1 dk ızgarada:
karardan 5. dk … 60. dk, ≥ 45/55 gerçek mum) ve 90 günlük çalışmanın `NullEngine` (null3) şans tabanı. Bloklar (yürüyen-ileri): **B1** 20 Tem–18 Ağu, **B2** 19 Ağu–17 Eyl, **B3** 18 Eyl–16 Eki.
"""

LIMITS = """## 8. Sınırlar

- **Çoklu karşılaştırma.** {n_comb} kombinasyon × 3 blok × (E ve F rolleri) + 15 durum grubu × 3 blok + 8 giriş yapılandırması × 3 blok: yüzün üstünde hücre. %95 aralıkları çoklu karşılaştırma için düzeltilmedi; "post-hoc" etiketli bulgular
  (ör. 15m olgun yeşil) seçim dışı gözlemdir ve ileri bir testten geçmeden kanıt sayılmamalı. Parametre seçimi tek bloğa (B1, ≈ 30 gün) dayanıyor.
- **Tek piyasa dönemi.** 90 günün tamamı tek rejim kümesi: BTC EMA200 altı günler çoğunlukta, 22 Ağu/21 Ağu/15 Eki/21 Eyl gibi birkaç geniş yükseliş günü olayların ≈ %16'sını veriyor. Bloklar bağımsız piyasalar değil, ardışık parçalar.
- **t0 ileriye bakışı.** Olay tanımı geleceğe bakıyor (60 dk içinde ≥ %4, ≥ %70 yeşil mum, koşu boyunca kapanış ≥ P0, ilk mum yeşil): olay anı hep küçük bir düşüşün/duraklamanın ardından seçiliyor, bu yüzden t0'da 'kırmızı' çekirdek ve 'düşüş sonrası' özelliklerin
  görünümü kısmen tanım artefaktı; çekirdeğin 'öncü' olmadığı sonucu bu seçimden etkilenir (t0'ın biraz öncesi/sonrası değişse AUC'ler kayar). Sinyal tarafındaki ölçümler (giriş, filtre) ileriye bakmaz; yalnız sonucun ölçülebilirlik koşulu (60 dk'lık pencerede gerçek mum) gelecekten gelir (tüm çalışmalarda aynı).
- **Pencere/çözünürlük.** 5m sinyal sonuçları 5m mum içi sırayı kötümser (SL önce) ele alır; 1m sinyallerde 1 dk yolu kullanıldığı için net60/trailing biraz farklı çözünürlükte ölçülüyor, şans tabanı ise 5m ızgara üzerinde (karar pencereleri 5 dk kayık: sinyal 5. dk'da, taban 0. dk'da başlıyor — taban lehine, yani kazançlar muhafazakâr).
- **HA satırları bağımsız değil** (aynı sembolde art arda bölümler, gün kümeli bootstrap kullanıldı ama sembol kümeli değil). NullEngine örneklemli (3 tohum × 3000; ± gün-kümeli).
- **Kontrol testi (fark-farkı)** HA'nın seçtiği kümede aralık kısıtlıdır (tavan/seçilim etkisi): HA içinde etkinin küçülmesi 'HA zaten içeriyor' ile 'HA'nın dar aralığı' ayrımını tam yapmaz; rastgele anlar da aynı sembol-günden (HA satırı başına ≤ 20) örneklendi, 5m ızgara hit60@1,5 ölçüsüyle.
- **Önbellek/yeniden üretim.** Analizler 90 günlük çalışmanın önbelleğini (`pattern90_study.py --cache-dir`: d1/d5/grid/snap/events) ve `work/pattern90/ha.npz` dosyasını kullanır; sıra: `rqk_study.py --p90-cache <dizin> --stages fetch15,sym,agg,analyze,report`.
- **Aday dosyası** 16 Ekim 23:55'te bitiyor; 17 Ekim (LUNATRY) için HA satırı yok. LUNATRY tek örnek ve analiz öncesi görülmüş.
- **Çekirdek kısaltması.** Uygulama toplamı son h muma kesiyor (h=8 → 8 bar): gösterge fiyata çok yakın, hızlı bir yumuşatma; kanonik (25 bar pencere) ile karşılaştırma 5m'de yapıldı (varyant B); h=25'te iki varyant aynı pencereyi kullanır, yalnız renk kuralı farklıdır.
"""
