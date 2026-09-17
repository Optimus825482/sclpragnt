"""Unified replay derin analizi: kayıp nereden geliyor?

Soru: unified akisinin -0.80% ort. net'i TEK KAYNAKLI (sadece MACD ayagi)
olaylarindan mi, cok kaynakli (confluence) olaylardan mi geliyor?
"""
import csv
import sys
from collections import defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else (
    r"C:\Users\erkan\Downloads\birlesik-radar-replay-20260917-100950.csv")

rows = []
with open(PATH, encoding="utf-8-sig", newline="") as fh:
    for row in csv.DictReader(fh):
        rows.append(row)

def f(row, key):
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0

def src_list(row):
    """CSV `sources` alani virgulle ayrik (DictReader tirnaklamayi cozer)."""
    return [s for s in (row.get("sources") or "").split(",") if s]

def stats(subset):
    n = len(subset)
    if not n:
        return "n=0"
    nets = [f(r, "net_pct") for r in subset]
    wins = sum(1 for x in nets if x > 0)
    avg = sum(nets) / n
    srt = sorted(nets)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    mfe = sum(f(r, "mfe_pct") for r in subset) / n
    tgt = sum(f(r, "target_pct") for r in subset) / n
    return (f"n={n:<4} ort.net={avg:+.3f}%  medyan={med:+.3f}%  "
            f"kazanma={wins / n * 100:.1f}%  ort.MFE={mfe:.2f}%  hedef={tgt:.2f}%")

print("=== UNIFIED akisi: kaynak sayisina gore ===")
uni = [r for r in rows if r["stream"] == "unified"]
print("TUM unified          :", stats(uni))
for k in (1, 2, 3):
    sub = [r for r in uni if len(src_list(r)) == k]
    if sub:
        print(f"  {k} kaynakli       :", stats(sub))
# confluence bayragi
conf_t = [r for r in uni if r.get("confluence") in ("True", "true", "1")]
conf_f = [r for r in uni if r.get("confluence") not in ("True", "true", "1")]
print("  confluence=True   :", stats(conf_t))
print("  confluence=False  :", stats(conf_f))

print("\n=== UNIFIED: kaynak kombinasyonuna gore ===")
groups = defaultdict(list)
for r in uni:
    groups[tuple(sorted(src_list(r)))].append(r)
for srcs, sub in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    print(f"  {'+'.join(srcs):<30}", stats(sub))

print("\n=== 'early'iceren vs icermeyen (unified) ===")
has_early = [r for r in uni if "early" in src_list(r)]
no_early = [r for r in uni if "early" not in src_list(r)]
print("  early ICEREN      :", stats(has_early))
print("  early ICERMEYEN   :", stats(no_early))

print("\n=== 'velocity'iceren vs icermeyen (unified) ===")
has_vel = [r for r in uni if "velocity" in src_list(r)]
no_vel = [r for r in uni if "velocity" not in src_list(r)]
print("  velocity ICEREN   :", stats(has_vel))
print("  velocity ICERMEYEN:", stats(no_vel))

print("\n=== velocity_only: unified'la cakisanlar vs caymayanlar ===")
# ayni sembol + 30 dk icinde unified olayi varsa velocity "cakisiyor" say
uni_syms = defaultdict(list)
for r in uni:
    uni_syms[r["symbol"]].append(f(r, "detected_at_unix"))
vel = [r for r in rows if r["stream"] == "velocity_only"]
vel_hit, vel_miss = [], []
for r in vel:
    ts = f(r, "detected_at_unix")
    hits = [t for t in uni_syms.get(r["symbol"], []) if abs(t - ts) <= 1800]
    (vel_hit if hits else vel_miss).append(r)
print("  velocity (unified'da da var):", stats(vel_hit))
print("  velocity (sadece velocity)  :", stats(vel_miss))

print("\n=== MACD ayagi SKORUNA gore unified performansi ===")
buckets = {"<60": [], "60-74": [], ">=75": []}
for r in uni:
    sc = f(r, "score")
    buckets["<60" if sc < 60 else "60-74" if sc < 75 else ">=75"].append(r)
for name, sub in buckets.items():
    if sub:
        print(f"  skor {name:<7}", stats(sub))

print("\n=== Cikis sebepleri (unified) ===")
reasons = defaultdict(list)
for r in uni:
    reasons[r.get("exit_reason") or "?"].append(r)
for reason, sub in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
    print(f"  {reason:<14} n={len(sub):<4} ort.net={sum(f(r, 'net_pct') for r in sub) / len(sub):+.3f}%")
