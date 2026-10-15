"""Radar kova analizi betiği testleri (scripts/radar_bucket_analysis.py).

Kapsam:
- Geç faz eşiği: range_pos_60 >= 0.8 bölgesinde isabet düşünce 0.8 döner.
- Özellik birleştirme: tolerans içinde eşleşir, dışında None kalır.
- Kova toplamları: n toplamı satır sayısına eşittir; tersil etiketi üç tanedir.
- Betik DATABASE_URL olmadan import edilebilir; eksik CSV Türkçe hatayla çıkar.
"""
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "radar_bucket_analysis.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("radar_bucket_analysis", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ra = _load_module()


def _synthetic_rows(n: int = 300) -> list[dict]:
    """range_pos_60 0..1 boyunca eşit dağılmış sentetik satırlar.

    pos < 0.8: isabet deseni %60. pos >= 0.8 (son 60 satır): isabet yok.
    """
    rows = []
    for i in range(n):
        pos = i / (n - 1)
        late = pos >= 0.8
        hit = False if late else (i % 10) < 6
        rows.append({
            "symbol": f"S{i % 7}",
            "detected_at": 1_700_000_000.0 + i * 600.0,
            "hit": hit,
            "range_pos_60": pos,
            "pos24": pos,
            "quote_vol_24h": float(1000 + (i * 37) % 997),
            "mfe_pct": 2.0 if hit else 0.5,
            "mae_pct": -0.8 if hit else -1.5,
        })
    return rows


def test_recommend_cutoff_finds_late_phase_at_0_8():
    rows = _synthetic_rows(300)
    buckets = ra.bucket_stats(rows, "range_pos_60", ra.DEFAULT_EDGES, "range_pos_60")
    assert ra.recommend_cutoff(buckets, min_n=30) == 0.8


def test_recommend_cutoff_none_when_sample_too_small():
    rows = _synthetic_rows(300)
    buckets = ra.bucket_stats(rows, "range_pos_60", ra.DEFAULT_EDGES, "range_pos_60")
    # Geç kovada 60 satır var; min_n=100 ile hiçbir kova yeterli değil.
    assert ra.recommend_cutoff(buckets, min_n=100) is None


def test_join_features_nearest_within_tolerance_else_none():
    features = [
        {"symbol": "aaa", "detected_at": 1000.0, "range_pos_60": 0.1, "pos24": 0.2, "quote_vol_24h": 5e6},
        {"symbol": "AAA", "detected_at": 1200.0, "range_pos_60": 0.7, "pos24": 0.8, "quote_vol_24h": 9e6},
        {"symbol": "AAA", "detected_at": 2000.0, "range_pos_60": 0.9, "pos24": 0.9, "quote_vol_24h": 1e6},
    ]
    rows = [
        {"symbol": "AAA", "detected_at": 1100.0, "hit": True},   # 1000 (100 s) ve 1200 (100 s) arası
        {"symbol": "AAA", "detected_at": 1150.0, "hit": False},  # 1200'e 50 s: en yakın
        {"symbol": "AAA", "detected_at": 1950.0, "hit": True},   # 2000'e 50 s
        {"symbol": "AAA", "detected_at": 1500.0, "hit": True},   # 120 s'den uzak -> None
        {"symbol": "BBB", "detected_at": 1100.0, "hit": True},   # sembol yok -> None
    ]
    out = ra.join_features(rows, features, tol_sec=120)
    assert out[1]["range_pos_60"] == 0.7 and out[1]["quote_vol_24h"] == 9e6
    assert out[2]["range_pos_60"] == 0.9 and out[2]["pos24"] == 0.9
    for idx in (3, 4):
        assert out[idx]["range_pos_60"] is None
        assert out[idx]["pos24"] is None
        assert out[idx]["quote_vol_24h"] is None
    # Dar tolerans: 1150 satırı 1200'e 50 s uzakta ama tol=20 ile eşleşmez.
    tight = ra.join_features(rows[1:2], features, tol_sec=20)
    assert tight[0]["range_pos_60"] is None
    # Girdi satırları değiştirilmez.
    assert "range_pos_60" not in rows[0]


def test_bucket_stats_counts_sum_to_total():
    rows = _synthetic_rows(300)
    buckets = ra.bucket_stats(rows, "range_pos_60", ra.DEFAULT_EDGES, "range_pos_60")
    assert len(buckets) == len(ra.DEFAULT_EDGES) - 1
    assert sum(b["n"] for b in buckets) == 300
    late = buckets[-1]
    assert late["n"] == 60 and late["hits"] == 0 and late["hit_rate"] == 0.0
    assert late["ci_high"] < 0.1


def test_bucket_stats_skips_unresolved_rows():
    rows = _synthetic_rows(50)
    for r in rows[:10]:
        r["hit"] = None
    buckets = ra.bucket_stats(rows, "range_pos_60", ra.DEFAULT_EDGES, "range_pos_60")
    assert sum(b["n"] for b in buckets) == 40


def test_liquidity_tertile_labels_are_three_and_partition_rows():
    assert len(ra.TERTILE_LABELS) == 3
    assert ra.TERTILE_LABELS == ("illikit", "orta", "likit")
    rows = _synthetic_rows(300)
    buckets = ra.bucket_stats(rows, "quote_vol_24h")
    assert [b["bucket"] for b in buckets] == list(ra.TERTILE_LABELS)
    assert sum(b["n"] for b in buckets) == 300


def test_continuation_vs_reversal_shares():
    rows = _synthetic_rows(300)
    cvr = ra.continuation_vs_reversal(rows)
    assert set(cvr) == set(ra.TERTILE_LABELS)
    assert sum(c["n"] for c in cvr.values()) == 300
    for c in cvr.values():
        assert abs(c["continuation_share"] + c["reversal_share"] - 1.0) < 1e-12
    # Hit satırlarında mfe 2.0 > |mae| 0.8 (devam); hit olmayanlarda 0.5 < 1.5 (geri dönüş).
    total_cont = sum(c["continuation_n"] for c in cvr.values())
    assert total_cont == sum(1 for r in rows if r["hit"])


def test_wilson_ci_bounds():
    lo, hi = ra.wilson_ci(0, 60)
    assert lo == 0.0 and 0.05 < hi < 0.07
    assert ra.wilson_ci(0, 0) == (None, None)
    lo, hi = ra.wilson_ci(30, 60)
    assert lo < 0.5 < hi


def test_compare_liquidity_verdict():
    same = [{"n": 100, "hit_rate": 0.5, "ci_low": 0.4, "ci_high": 0.6, "bucket": "illikit"},
            {"n": 100, "hit_rate": 0.5, "ci_low": 0.4, "ci_high": 0.6, "bucket": "orta"},
            {"n": 100, "hit_rate": 0.52, "ci_low": 0.42, "ci_high": 0.62, "bucket": "likit"}]
    assert ra.compare_liquidity(same, min_n=30)["verdict"] == "ayırt edilemiyor"
    far = [dict(same[0]), dict(same[1]),
           {"n": 100, "hit_rate": 0.9, "ci_low": 0.84, "ci_high": 0.94, "bucket": "likit"}]
    assert ra.compare_liquidity(far, min_n=30)["verdict"] == "farklı"
    assert ra.compare_liquidity(far, min_n=500)["verdict"] == "veri yetersiz"


def test_script_imports_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    mod = _load_module()
    assert callable(mod.main)
    assert mod._db_url() is None


def test_main_missing_csv_gives_turkish_error(tmp_path, capsys):
    rc = ra.main(["--csv", str(tmp_path / "missing.csv")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "HATA" in captured.err
    assert "Traceback" not in captured.err


def test_main_missing_csv_subprocess_no_traceback(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--csv", "missing.csv"],
        cwd=str(tmp_path), env=env, capture_output=True, timeout=60)
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode != 0
    assert "HATA" in stderr
    assert "Traceback" not in stderr


def test_main_without_features_prints_overall_only(tmp_path, capsys):
    now = time.time()
    csv_path = tmp_path / "outcomes.csv"
    header = ["symbol", "horizon_minutes", "sources", "scan_score", "entry_price",
              "ceiling_pct", "target_pct", "detected_at", "mfe_pct", "mae_pct",
              "hit", "outcome_filled_at"]
    lines = [",".join(header)]
    for i in range(40):
        hit = "1" if i % 2 == 0 else "0"
        lines.append(",".join(["AAA", "60", "x", "50", "1.0", "2.0", "3.0",
                               f"{now - i * 600:.0f}", "2.0", "-1.0", hit, ""]))
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rc = ra.main(["--csv", str(csv_path), "--days", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Genel istatistik" in out
    assert "--features" in out
    assert "(a) range_pos_60" not in out


def test_main_with_features_prints_buckets_and_recommendation(tmp_path, capsys):
    now = time.time()
    csv_path = tmp_path / "outcomes.csv"
    feat_path = tmp_path / "features.csv"
    header = ["symbol", "horizon_minutes", "sources", "scan_score", "entry_price",
              "ceiling_pct", "target_pct", "detected_at", "mfe_pct", "mae_pct",
              "hit", "outcome_filled_at"]
    feat_header = ["symbol", "detected_at", "range_pos_60", "pos24", "quote_vol_24h"]
    out_lines = [",".join(header)]
    feat_lines = [",".join(feat_header)]
    for i in range(300):
        sym = f"S{i % 5}"
        t = now - i * 600
        pos = i / 299.0
        late = pos >= 0.8
        hit = "0" if late else ("1" if (i % 10) < 6 else "0")
        out_lines.append(",".join([sym, "60", "x", "50", "1.0", "2.0", "3.0",
                                   f"{t:.0f}", "2.0" if hit == "1" else "0.5",
                                   "-0.8" if hit == "1" else "-1.5", hit, ""]))
        feat_lines.append(",".join([sym, f"{t + 5:.0f}", f"{pos:.6f}", f"{pos:.6f}",
                                    f"{1000 + (i * 37) % 997}"]))
    csv_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    feat_path.write_text("\n".join(feat_lines) + "\n", encoding="utf-8")
    rc = ra.main(["--csv", str(csv_path), "--features", str(feat_path),
                  "--days", "5", "--min-n", "30"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "(a) range_pos_60" in out and "(b) pos24" in out
    assert "(c) Likidite" in out
    assert "ÖNERİ:" in out
    assert "range_pos_60 >= 0.80" in out
