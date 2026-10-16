"""Radar periyodik inceleme (haftalık) — tek komutla üç ölçüm + karar listesi.

Çalıştırır (hepsi salt-okunur):
  1. radar_lift_analysis        (aile / skor bandı lift'i, unified_candidate_outcomes)
  2. notification_outcomes_report (bildirimler x 5m mum: hit, şans tabanı, karşı-olgusal kapılar)
  3. radar_bucket_analysis      (kova analizi; --features verilmezse yalnız genel kısım)

ve `docs/reviews/RADAR_REVIEW_<YYYY-MM-DD>.md` dosyasına yazar:
  * başlık: aktif RADAR_* / AUTO_PAPER_* bayrakları (config.py'den regex ile okunur;
    ortamda tanımlıysa o değer, değilse koddaki varsayılan),
  * üç raporun birleşimi,
  * "KARAR" kontrol listesi (lift<1 aileler, şans altı modlar, skor tabanı kontrolü).

Karar listesi öneridir; eşik/flag değişikliği yine docs/DENEY_KAYDI.md satırı gerektirir.

Bu modül import anında DATABASE_URL okumaz; yalnız main() içinde okunur.
Konsol: PYTHONIOENCODING=utf-8 ayarlayın (Windows).

KULLANIM (backend klasöründen):
    python scripts/radar_periodic_review.py --days 14
    python scripts/radar_periodic_review.py --days 14 --out-dir ../docs/reviews --min-n 30

HAFTALIK ÇALIŞTIRMA: README.md "Periyodik ölçüm" bölümüne bakın.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

try:  # python -m scripts.x  veya  python scripts/x.py
    from scripts import notification_outcomes_report as nor
    from scripts import radar_bucket_analysis as rba
    from scripts import radar_lift_analysis as rla
except ImportError:  # pragma: no cover - doğrudan çalıştırma
    import notification_outcomes_report as nor
    import radar_bucket_analysis as rba
    import radar_lift_analysis as rla

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
CONFIG_PATH = BACKEND_DIR / "app" / "config.py"
FLAG_NAME_RE = re.compile(r"^(?:RADAR_|AUTO_PAPER_)[A-Z_]+$")
_GETENV_RE = re.compile(r'os\.getenv\(\s*"((?:RADAR_|AUTO_PAPER_)[A-Z_]+)"\s*(?:,\s*([^)]*?))?\)(?P<tail>[^\n]{0,80})')
_STR_RE = re.compile(r'^\s*(?:"([^"]*)"|\'([^\']*)\')\s*$')


# ------------------------------------------------------------ saf fonksiyonlar
def parse_config_flags(text: str) -> list[tuple[str, str]]:
    """config.py metninden (bayrak adı, varsayılan) çiftleri; ad başına ilk geçiş, ada göre sıralı.

    Varsayılan best-effort okunur: ikinci getenv argümanı; boş metin ise ardından gelen
    `or "x"` ifadesi; çözülemezse '(kodda)'.
    """
    found: dict[str, str] = {}
    for m in _GETENV_RE.finditer(text):
        name, raw, tail = m.group(1), m.group(2), m.group("tail") or ""
        if name in found:
            continue
        default = "(kodda)"
        if raw is not None:
            sm = _STR_RE.match(raw)
            if sm:
                default = sm.group(1) if sm.group(1) is not None else sm.group(2)
                if default == "":
                    om = re.search(r'or\s+"([^"]*)"', tail)
                    default = om.group(1) if om else ""
            else:
                default = raw.strip() or "(kodda)"
        found[name] = default
    return sorted(found.items())


def flag_values(flags: list[tuple[str, str]], environ: Mapping[str, str]) -> list[tuple[str, str, str]]:
    """(ad, değer, kaynak) — kaynak 'env' veya 'varsayilan'."""
    out = []
    for name, default in flags:
        if name in environ and environ[name] != "":
            out.append((name, environ[name], "env"))
        else:
            out.append((name, default, "varsayilan"))
    return out


def render_flag_header(values: list[tuple[str, str, str]], date_str: str, days: float) -> str:
    lines = [f"# Radar periyodik inceleme - {date_str}",
             f"Pencere: son {days:g} gun. Uretim: backend/scripts/radar_periodic_review.py (salt-okunur).",
             "",
             "## Aktif bayraklar (RADAR_* / AUTO_PAPER_*)",
             "Deger = ortamda tanimliysa env, degilse config.py varsayilani (ham ifade; hesaplanmis olabilir).",
             "",
             "| bayrak | deger | kaynak |",
             "|---|---|---|"]
    for name, val, src in values:
        lines.append(f"| {name} | `{val}` | {src} |")
    return "\n".join(lines) + "\n"


def parse_lift_karar(text: str) -> list[str] | None:
    """radar_lift_analysis çıktısındaki 'KARAR: lift<1.0 olan aileler: [...]' satırı."""
    m = re.search(r"KARAR: lift<1\.0 olan aileler:\s*\[(.*?)\]", text)
    if not m:
        return None
    return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]


_BUCKET_LOWER = {"1 <70": 0.0, "2 70-85": 70.0, "3 85-95": 85.0, "4 95-99.9": 95.0, "5 100+": 100.0}


def build_karar(summary: dict, lift_text: str, *, min_n: int, unified_min_score: float,
                modes_disabled: list[str]) -> list[str]:
    """KARAR kontrol listesi (markdown madde işaretleri). Saf: özet sözlük + lift metni girdidir."""
    out = ["## KARAR", "Her madde bir oneridir; uygulamak icin docs/DENEY_KAYDI.md satiri gerekir.", ""]

    # 1. aileler
    low_lift = parse_lift_karar(lift_text)
    fam = summary.get("by_family") or {}
    low_chance = sorted(f for f, v in fam.items()
                        if v["n"] >= min_n and v.get("lift_pp") is not None and v["lift_pp"] < 0)
    out.append("### 1. Aileler (lift < 1)")
    if low_lift is None:
        out.append("- [ ] radar_lift_analysis KARAR satiri okunamadi (veri yok / hata); elle kontrol edin.")
    elif low_lift:
        out.append(f"- [ ] lift<1.0 olan aileler (radar_lift_analysis): **{', '.join(low_lift)}** -> RADAR_DISABLED_SOURCE_FAMILIES / carpani 1.0 adayi")
    else:
        out.append("- [x] lift<1.0 olan aile yok (radar_lift_analysis).")
    if low_chance:
        out.append(f"- [ ] Mum bazli: sans tabaninin ALTINDA kalan aileler (n>={min_n}): **{', '.join(low_chance)}**")
    else:
        out.append(f"- [x] Mum bazli: sans tabaninin altinda kalan aile yok (n>={min_n}).")

    # 2. modlar
    by_mode = summary.get("by_mode") or {}
    below = []
    for m, v in sorted(by_mode.items()):
        if v["n"] < min_n or v.get("chance_hit60") is None:
            continue
        if v["hit60"] < v["chance_hit60"]:
            below.append(f"{m} (n={v['n']}, hit60 {v['hit60']:.1f} < sans {v['chance_hit60']:.1f})")
    out.append("\n### 2. Modlar (sans altinda)")
    if below:
        for b in below:
            m = b.split(" ")[0]
            if m in modes_disabled:
                out.append(f"- [x] {b} -> zaten kapali (dogru karar)")
            else:
                out.append(f"- [ ] {b} -> KAPATMA ADAYI")
    else:
        out.append(f"- [x] n>={min_n} olup hit60'i sans tabaninin altinda kalan mod yok.")
    still_open = [m for m in modes_disabled if by_mode.get(m, {}).get("n", 0) >= min_n
                  and by_mode[m].get("lift_pp") is not None and by_mode[m]["lift_pp"] > 5]
    for m in still_open:
        out.append(f"- [ ] Kapali mod '{m}' sans ustu (+{by_mode[m]['lift_pp']:.1f} pp, n={by_mode[m]['n']}): yeniden acma icin kanit (kural 1: >=2 hafta)")

    # 3. skor tabani
    buckets = summary.get("by_score_bucket") or {}
    out.append(f"\n### 3. Skor tabani (unified asgari skor = {unified_min_score:g})")
    lows, highs = [], []
    for b, v in buckets.items():
        if v.get("lift_pp") is None or v["n"] == 0:
            continue
        (highs if _BUCKET_LOWER.get(b, 0.0) >= unified_min_score else lows).append((b, v))

    def wmean(items: list) -> float | None:
        n = sum(v["n"] for _, v in items)
        return sum(v["lift_pp"] * v["n"] for _, v in items) / n if n else None
    wl, wh = wmean(lows), wmean(highs)
    for b, v in sorted(buckets.items()):
        if v.get("lift_pp") is not None:
            out.append(f"- skor kovasi {b}: n={v['n']}, hit60 {v['hit60']:.1f}, sans {v['chance_hit60']:.1f}, lift {v['lift_pp']:+.1f} pp")
    if wl is None or wh is None:
        out.append("- [ ] Taban kontrolu icin yeterli kova verisi yok.")
    elif wh > wl:
        out.append(f"- [x] Taban gerekceli: >={unified_min_score:g} kovalarinin ort. lift'i ({wh:+.1f} pp) altindakinden ({wl:+.1f} pp) yuksek.")
    else:
        out.append(f"- [ ] Taban gerekcesi ZAYIF: >={unified_min_score:g} lift {wh:+.1f} pp <= alt kovalar {wl:+.1f} pp -> tabani/kapiyi yeniden degerlendirin.")

    # 4. genel
    out.append("\n### 4. Genel")
    if summary.get("n60"):
        verdict = "[x]" if summary.get("net60", -1) > 0 else "[ ]"
        out.append(f"- {verdict} Net60 (maliyet sonrasi) = {summary['net60']:+.2f}% (n={summary['n60']}); sans net60 = {summary.get('chance_net60', float('nan')):+.2f}%. "
                   "Yapisal maliyet siniri icin docs/RADAR_ESIK_SOZLESMESI.md.")
        pol = next((v for k, v in (summary.get("scenarios") or {}).items() if k.startswith("c ")), None)
        if pol and pol.get("n"):
            out.append(f"- Guncel politika senaryosu: n={pol['n']}, hit60 {pol['hit60']:.1f}, sans {pol['chance_hit60']:.1f}, net60 {pol['net60']:+.2f}%.")
    else:
        out.append("- [ ] Olculen bildirim yok.")
    return out


def assemble_review(header: str, lift_text: str, notif_md: str, bucket_text: str, karar: list[str]) -> str:
    parts = [header,
             "\n---\n\n## A. radar_lift_analysis\n\n```\n" + lift_text.strip() + "\n```\n",
             "\n---\n\n## B. notification_outcomes_report\n\n" + notif_md.strip() + "\n",
             "\n---\n\n## C. radar_bucket_analysis\n\n```\n" + bucket_text.strip() + "\n```\n",
             "\n---\n\n" + "\n".join(karar) + "\n"]
    return "".join(parts)


def capture(fn: Callable[[list[str]], Any], argv: list[str]) -> tuple[int, str]:
    """Bir betiğin main(argv)'ini çalıştırır; stdout+stderr metni ve çıkış kodunu döner."""
    buf = io.StringIO()
    code: Any = 0
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = fn(argv)
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
        except Exception as exc:  # noqa: BLE001 - tek rapor çökse de diğerleri yazılsın
            print(f"HATA: {type(exc).__name__}: {exc}")
            code = 1
    return (code if isinstance(code, int) else 1), buf.getvalue()


# ------------------------------------------------------------------ G/Ç
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Radar haftalik inceleme: lift + bildirim sonuclari + kova analizi + KARAR.")
    ap.add_argument("--days", type=float, default=14.0)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--out-dir", default=str(REPO_DIR / "docs" / "reviews"))
    ap.add_argument("--features", default=None, help="radar_bucket_analysis --features CSV'si (opsiyonel)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    if args.days <= 0 or args.min_n < 1:
        print("HATA: --days pozitif, --min-n >= 1 olmali.", file=sys.stderr)
        return 2

    db_url = nor._db_url()  # DATABASE_URL yoksa burada net hata ile çıkar
    date_str = datetime.now(nor.TZ).strftime("%Y-%m-%d")
    flags = parse_config_flags(CONFIG_PATH.read_text(encoding="utf-8"))
    values = flag_values(flags, os.environ)
    env = {n: v for n, v, _ in values}
    try:
        floor = float(env.get("RADAR_NOTIFY_UNIFIED_MIN_SCORE", "95") or "95")
    except ValueError:
        floor = 95.0
    disabled = [m.strip() for m in env.get("RADAR_NOTIFY_DISABLED_MODES", ",".join(nor.DEFAULT_MODES_DISABLED)).split(",") if m.strip()]

    lift_code, lift_text = capture(rla.main, ["--days", f"{args.days:g}", "--min-n", str(args.min_n)])
    try:
        notif_md, summary = nor.run_report(db_url, days=args.days, modes_disabled=disabled,
                                           unified_min_score=floor, min_n=args.min_n)
    except Exception as exc:  # noqa: BLE001
        notif_md, summary = f"HATA: bildirim raporu uretilemedi ({type(exc).__name__}): {exc}\n", {}
    b_argv = ["--days", f"{args.days:g}", "--min-n", str(args.min_n)]
    if args.features:
        b_argv += ["--features", args.features]
    bucket_code, bucket_text = capture(rba.main, b_argv)

    karar = build_karar(summary, lift_text, min_n=args.min_n, unified_min_score=floor, modes_disabled=disabled)
    review = assemble_review(render_flag_header(values, date_str, args.days), lift_text, notif_md, bucket_text, karar)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"RADAR_REVIEW_{date_str}.md"
    path.write_text(review, encoding="utf-8")
    print(f"Yazildi: {path}  (lift rc={lift_code}, bucket rc={bucket_code}, bayrak sayisi={len(values)})")
    print("\n".join(karar))
    return 0


if __name__ == "__main__":
    sys.exit(main())
