"""`scripts/ta_n6_tracker.py` — M1H kuralı sayfası: kurala göre çıkış parametreleri, sütunlar ve açıklama (ağ yok)."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import momentum_scan as MC  # noqa: E402

M15 = 900_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % M15)


def _mod():
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ta_n6_tracker.py"
    spec = importlib.util.spec_from_file_location("ta_n6_tracker", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _data(html: str) -> dict:
    m = re.search(r"var DATA = (\{.*?\});\n", html, re.S)
    assert m, "DATA bulunamadı"
    return json.loads(m.group(1))


def _m1h_res():
    row = {"sym": "ZBTTRY", "px": 3.85, "score": 15.1, "r1": 5.5, "r2": 7.7, "r4": 8.9, "r24": 15.1, "vr": 17.2, "vol_ratio": 17.2, "chg24": 15.1,
           "vwap": 3.81, "vwap_rel": 1.05, "room": 2.7, "base": 2.0, "hl": 3, "atr15": 2.55, "qv24": 53e6, "fut": None, "imb1": None}
    return {"cutoff_ms": 1_800_000_000_000, "breadth": 0.0, "universe": 211, "candidates": 180, "picked": [row], "rule": "m1h", "n6_count": 0,
            "dropped": [], "force_top": True, "top": 3, "manual": False, "depth_src": "canlı defter", "depth_filter": False, "source": "rest"}


def test_m1h_page_uses_short_exit_and_momentum_columns():
    T = _mod()
    html = T.html_page(_m1h_res(), dt.datetime(2026, 10, 24, 20, 55, tzinfo=T.TZ))
    d = _data(html)
    assert d["rule"] == "m1h" and d["exit"] == {"trig": 2.0, "gap": 1.0, "stop": 4.0, "hold_h": 4}
    assert d["rows"][0]["r1"] == 5.5 and d["rows"][0]["score"] == 15.1 and d["rows"][0]["base"] == 2.0
    assert "<th>1 sa / 4 sa</th>" in html and "<th>Puan / taban</th>" in html and "<th>ADX / DI</th>" not in html
    assert "Kural M1H" in html and "en çok 4 saat" in html and "+%2'ten sonra zirvenin %1 altına" in html
    assert "<title>M1H Takip 24.10 20:55</title>" in html
    assert "var FEE = 0.001125, STAKE = 10000, TRIG = EX.trig" in html


def test_exit_overrides_apply_and_n7_keeps_defaults():
    T = _mod()
    html = T.html_page(_m1h_res(), dt.datetime(2026, 10, 24, 20, 55, tzinfo=T.TZ), {"hold_h": 2, "stop": 3.0})
    assert _data(html)["exit"] == {"trig": 2.0, "gap": 1.0, "stop": 3.0, "hold_h": 2}
    n7 = dict(_m1h_res(), rule="n7", picked=[{"sym": "AAATRY", "px": 1.0, "adx4": 30.0, "di_diff": 12.0, "vol_ratio": 2.0, "rsi1": 55.0, "d_rsi": 50.0,
                                                "chg24": 3.0, "qv24": 9e6, "score": 2, "f_funding": 0.01}])
    h7 = T.html_page(n7, dt.datetime(2026, 10, 22, 9, 0, tzinfo=T.TZ))
    assert _data(h7)["exit"] == {"trig": 3.0, "gap": 1.5, "stop": 10.0, "hold_h": 24}
    assert "<th>ADX / DI</th>" in h7 and "<th>1 sa / 4 sa</th>" not in h7 and "Kural: ADX 4h ≥ 25" in h7


def test_rule_exit_table_covers_every_rule_choice():
    T = _mod()
    assert set(T.RULE_EXIT) == {"n6", "n7", "m1h"}
    assert all({"trig", "gap", "stop", "hold_h"} <= set(v) for v in T.RULE_EXIT.values())


# ---- Tara (tarayıcı içi M1H taraması, 2026-10-24)

def _m1h_const(html: str) -> dict:
    m = re.search(r"var M1H = (\{.*?\});", html)
    assert m, "M1H bulunamadı"
    return json.loads(m.group(1))


def test_page_has_scan_button_and_m1h_constants_from_python():
    T = _mod()
    html = T.html_page(_m1h_res(), dt.datetime(2026, 10, 24, 20, 55, tzinfo=T.TZ))
    assert '<button id="scan" type="button"' in html and ">Tara</button>" in html and 'id="scan-note"' in html
    c = _m1h_const(html)
    assert c["WEIGHTS"] == MC.WEIGHTS and c["MIN_QV"] == MC.MIN_QV and c["MIN_BARS"] == MC.MIN_BARS and c["KLINES_LIMIT"] == MC.KLINES_LIMIT
    assert set(c["STABLE"]) == MC.STABLE and c["EXIT"] == T.RULE_EXIT["m1h"] and c["BASE_TARGET_PCT"] == MC.BASE_TARGET_PCT
    assert _data(html)["top"] == 3
    assert T.M1H_JS in html                                   # saf JS tek kaynaktan sayfaya girer
    for fn in ("momentumFeatures", "momentumScore", "isStable", "rankRows", "rowsToBars"):
        assert f"function {fn}(" in T.M1H_JS
    assert not re.search(r"\b(0\.8|672|200|5e6|5000000)\b", T.M1H_JS)   # sayılar JS'te elle yazılmaz, M1H'den okunur
    # başlıklar JS'e taşındı: n6 varyantı sayfada yalnız liste olarak var, <th> hâlinde değil
    assert '"ADX / DI"' in html and "<th>ADX / DI</th>" not in html and "<th>1 sa / 4 sa</th>" in html


def _bars(closes, q=1_000_000.0, t0=T0, spread=0.002):
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        qi = q[i] if isinstance(q, (list, tuple)) else q
        out.append({"t": t0 + i * M15, "o": o, "h": max(o, c) * (1 + spread), "l": min(o, c) * (1 - spread), "c": c, "q": qi})
    return out


def _parity_cases():
    flat = [10.0] * 290
    return [
        ("flat", _bars([10.0] * 300), None),
        ("rise", _bars(flat + [10.0 + 0.03 * i for i in range(1, 11)], q=[1e6] * 290 + [3e6] * 10), None),
        ("spike", _bars([10.0] * 296 + [10.0, 10.5, 11.0, 11.5], q=[1e6] * 296 + [3e6] * 4), None),
        ("cutoff_open", _bars([10.0] * 299 + [20.0]), T0 + 299 * M15),          # son mum kapanmamış → atılır
        ("base_hits", _bars([10.0] * 250 + [10.3] + [10.0] * 50, spread=0.0), None),
    ]


PARITY_KEYS = ("px", "r1", "r2", "r4", "r24", "vr", "vwap", "room", "base", "hl", "atr15", "qv24", "score")


def test_js_momentum_matches_python_under_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node yok")
    T = _mod()
    html = T.html_page(_m1h_res(), dt.datetime(2026, 10, 24, 20, 55, tzinfo=T.TZ))
    cases = _parity_cases()
    rise = MC.momentum_features(cases[1][1])
    rank_in = {"AAATRY": rise, "USDTTRY": rise, "BBBTRY": dict(rise, qv24=1e6), "CCCTRY": None, "DDDTRY": dict(rise, r1=rise["r1"] + 1)}
    script = (
        "var M1H = " + json.dumps(_m1h_const(html)) + ";\n" + T.M1H_JS + "\n"
        "var cases = " + json.dumps([{"name": n, "bars": b, "cutoff": c} for n, b, c in cases]) + ";\n"
        "var out = cases.map(function (c) { var f = momentumFeatures(c.bars, c.cutoff); return f ? Object.assign({}, f, { score: momentumScore(f) }) : null; });\n"
        "var rk = rankRows(" + json.dumps(rank_in) + ", 5);\n"
        "process.stdout.write(JSON.stringify({ feats: out, rank: rk.rows.map(function (r) { return [r.sym, r.score]; }), candidates: rk.candidates,"
        " stable: [isStable('USDTTRY'), isStable('PAXGTRY'), isStable('BTCTRY'), isStable('USDT')],"
        " bars: rowsToBars([[1, '1', '2', '0.5', '1.5', '100', 2, '150', 5, '0', '0', '0'], ['bozuk']]) }));\n"
    )
    js = tmp_path / "parity.js"
    js.write_text(script, encoding="utf-8")
    p = subprocess.run([node, str(js)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    res = json.loads(p.stdout)
    for (name, bars, cutoff), jf in zip(cases, res["feats"]):
        pf = MC.momentum_features(bars, cutoff)
        assert pf is not None and jf is not None, name
        pf = dict(pf, score=MC.momentum_score(pf))
        for k in PARITY_KEYS:
            assert abs(pf[k] - jf[k]) < 1e-9, (name, k, pf[k], jf[k])
    picked, n = MC.rank(rank_in, 5)
    assert res["candidates"] == n and [s for s, _ in res["rank"]] == [r["sym"] for r in picked]
    assert all(abs(js_sc - r["score"]) < 1e-9 for (_, js_sc), r in zip(res["rank"], picked))
    assert res["stable"] == [True, True, False, True]
    assert res["bars"] == [{"t": 1, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "q": 150.0}]


def test_n7_page_scan_switch_support_present():
    T = _mod()
    n7 = dict(_m1h_res(), rule="n7", picked=[{"sym": "AAATRY", "px": 1.0, "adx4": 30.0, "di_diff": 12.0, "vol_ratio": 2.0, "rsi1": 55.0, "d_rsi": 50.0,
                                                "chg24": 3.0, "qv24": 9e6, "score": 2, "f_funding": 0.01}])
    h7 = T.html_page(n7, dt.datetime(2026, 10, 22, 9, 0, tzinfo=T.TZ))
    assert '<button id="scan"' in h7 and _m1h_const(h7)["EXIT"] == T.RULE_EXIT["m1h"]
    th = json.loads(re.search(r"var TH = (\{.*?\});", h7).group(1))
    assert th["base"] == T.TH_BASE and th["extra"] == T.TH_EXTRA and list(th["extra"]) == ["m1h", "n6"]
    assert 'id="ex-trig">3</span>' in h7 and 'id="ex-hold">24</span>' in h7
