"""2026-10-17: tarihsel futures bağlamı — sembol eşleme, CSV ayrıştırma, yardımcılar (ağ/DB yok)."""
import datetime as dt
import hashlib
import io
import zipfile

import pytest

from scripts import backfill_futures_hist as bf


def _tr(*pairs):
    return {"symbols": [{"symbol": s, "baseAsset": b, "quoteAsset": q, "status": st} for s, b, q, st in pairs]}


def _fut(*items):
    return {"symbols": [{"symbol": s, "baseAsset": b, "quoteAsset": "USDT", "contractType": "PERPETUAL",
                         "status": st} for s, b, st in items]}


def test_symbol_map_direct_renamed_and_multiplied():
    tr = _tr(("BTCTRY", "BTC", "TRY", "TRADING"), ("LUNATRY", "LUNA", "TRY", "TRADING"),
             ("PEPETRY", "PEPE", "TRY", "TRADING"), ("SHIBTRY", "SHIB", "TRY", "TRADING"),
             ("BABYDOGETRY", "BABYDOGE", "TRY", "TRADING"), ("RADTRY", "RAD", "TRY", "TRADING"),
             ("USDTTRY", "USDT", "TRY", "TRADING"), ("ETHUSDT", "ETH", "USDT", "TRADING"),
             ("OLDTRY", "OLD", "TRY", "BREAK"))
    fut = _fut(("BTCUSDT", "BTC", "TRADING"), ("LUNA2USDT", "LUNA2", "TRADING"), ("1000PEPEUSDT", "1000PEPE", "TRADING"),
               ("1000SHIBUSDT", "1000SHIB", "TRADING"), ("1MBABYDOGEUSDT", "1MBABYDOGE", "TRADING"),
               ("OLDUSDT", "OLD", "TRADING"))
    m = {r["try_symbol"]: r for r in bf.build_symbol_map(tr, fut)}
    assert set(m) == {"BTCTRY", "LUNATRY", "PEPETRY", "SHIBTRY", "BABYDOGETRY"}  # RAD perp'siz, USDT stable, OLD kapalı
    assert (m["BTCTRY"]["perp_symbol"], m["BTCTRY"]["multiplier"]) == ("BTCUSDT", 1.0)
    assert (m["LUNATRY"]["perp_symbol"], m["LUNATRY"]["multiplier"]) == ("LUNA2USDT", 1.0)
    assert (m["PEPETRY"]["perp_symbol"], m["PEPETRY"]["multiplier"]) == ("1000PEPEUSDT", 1000.0)
    assert m["SHIBTRY"]["perp_symbol"] == "1000SHIBUSDT"
    assert (m["BABYDOGETRY"]["perp_symbol"], m["BABYDOGETRY"]["multiplier"]) == ("1MBABYDOGEUSDT", 1_000_000.0)


def test_symbol_map_skips_pending_and_prefers_exact():
    tr = _tr(("XTRY", "X", "TRY", "TRADING"), ("YTRY", "Y", "TRY", "TRADING"))
    fut = _fut(("XUSDT", "X", "PENDING_TRADING"), ("1000XUSDT", "1000X", "TRADING"),
               ("YUSDT", "Y", "TRADING"), ("1000YUSDT", "1000Y", "TRADING"))
    m = {r["try_symbol"]: r for r in bf.build_symbol_map(tr, fut)}
    assert m["XTRY"]["perp_symbol"] == "1000XUSDT"  # bekleyen birebir perp atlanır
    assert m["YTRY"]["perp_symbol"] == "YUSDT" and m["YTRY"]["multiplier"] == 1.0


METRICS = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
           "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
           "2026-10-16 00:00:00,BTCUSDT,94398.319,7763695571.2,1.58,1.28,1.50,1.30\n"
           "2026-10-16 00:05:00,BTCUSDT,94400.0,7763700000.0,,1.29,1.51,0.97\n")


def test_parse_metrics_csv():
    rows = bf.parse_metrics_csv(METRICS, "BTCUSDT")
    assert len(rows) == 2
    assert rows[0] == ("BTCUSDT", 1_792_108_800_000, 94398.319, 7763695571.2, 1.58, 1.28, 1.50, 1.30)
    assert rows[1][4] is None and rows[1][1] - rows[0][1] == 300_000
    assert bf.parse_metrics_csv("garbage", "X") == []


def _bd_snapshot(ts, scale=1.0):
    out = []
    for p in (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5):
        k = abs(p)
        out.append("%s,%d.00,%.8f,%.8f" % (ts, p, 10.0 * k * scale, 1000.0 * k * scale * (2 if p < 0 else 1)))
    return out


def test_parse_bookdepth_picks_last_snapshot_per_5min_and_pivots():
    lines = ["timestamp,percentage,depth,notional"]
    for ts in ("2026-10-16 00:00:01", "2026-10-16 00:02:30", "2026-10-16 00:04:55",   # dilim 1
               "2026-10-16 00:05:20", "2026-10-16 00:09:59"):                            # dilim 2
        lines += _bd_snapshot(ts, scale=1.0 + int(ts[15:16]) / 10.0 + int(ts[17:19]) / 1000.0)
    rows = bf.parse_bookdepth_csv("\n".join(lines) + "\n", "BTCUSDT")
    assert len(rows) == 2
    assert [r[1] for r in rows] == [bf.parse_ts_ms("2026-10-16 00:04:55"), bf.parse_ts_ms("2026-10-16 00:09:59")]
    r = rows[0]
    assert len(r) == 22
    bid_n, ask_n = r[2:7], r[7:12]
    assert bid_n[0] == pytest.approx(2.0 * ask_n[0])  # -1 % alış = 2x satış (fixture)
    assert list(bid_n) == sorted(bid_n) and list(ask_n) == sorted(ask_n)  # |yüzde| ile monoton artan
    assert r[12] == pytest.approx(r[17])  # derinlik (baz) iki yanda eşit


def test_parse_bookdepth_missing_level_and_empty():
    text = "timestamp,percentage,depth,notional\n2026-10-16 00:00:01,-1.00,5.0,500.0\n2026-10-16 00:00:01,1.00,4.0,400.0\n"
    r = bf.parse_bookdepth_csv(text, "X")[0]
    assert r[2] == 500.0 and r[7] == 400.0 and r[3] is None and r[8] is None
    assert bf.parse_bookdepth_csv("", "X") == [] and bf.parse_bookdepth_csv("timestamp,percentage,depth,notional\n", "X") == []


def test_depth_imbalance():
    assert bf.depth_imbalance({"bid_n1": 300.0, "ask_n1": 100.0}, 1) == pytest.approx(0.5)
    assert bf.depth_imbalance({"bid_n1": 0.0, "ask_n1": 0.0}, 1) is None
    assert bf.depth_imbalance({"bid_n1": None, "ask_n1": 1.0}, 1) is None


def test_parse_funding_csv_filters_by_start():
    text = "calc_time,funding_interval_hours,last_funding_rate\n1788220800005,8,0.00008482\n1788249600000,8,0.0001\n"
    rows = bf.parse_funding_csv(text, "BTCUSDT", min_ms=1788249600000)
    assert rows == [("BTCUSDT", 1788249600000, 0.0001, None, 8)]
    assert len(bf.parse_funding_csv(text, "BTCUSDT")) == 2


def test_ts_and_ranges():
    assert bf.parse_ts_ms("2026-10-16 00:00:00") == 1_792_108_800_000
    assert bf.parse_ts_ms("1788220800005") == 1788220800005
    assert bf.date_range(dt.date(2026, 7, 19), dt.date(2026, 10, 16))[0] == "2026-07-19"
    assert len(bf.date_range(dt.date(2026, 7, 19), dt.date(2026, 10, 16))) == 90
    assert bf.month_list(dt.date(2026, 7, 19), dt.date(2026, 10, 16)) == ["2026-07", "2026-08", "2026-09", "2026-10"]
    assert bf.month_list(dt.date(2025, 11, 5), dt.date(2026, 1, 2)) == ["2025-11", "2025-12", "2026-01"]


def test_checksum_parse_and_zip_roundtrip():
    assert bf.parse_checksum("a" * 64 + "  file.zip\n") == "a" * 64
    assert bf.parse_checksum("bozuk") is None

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", METRICS)
    blob = buf.getvalue()
    sha = hashlib.sha256(blob).hexdigest()

    class R:
        def __init__(self, code, content):
            self.status_code, self.content = code, content

    class Client:
        def __init__(self, checksum):
            self.checksum = checksum

        def get(self, url, **kw):
            if url.endswith(".CHECKSUM"):
                return R(200, (self.checksum + "  x.zip").encode())
            return R(200, blob)

    assert bf.fetch_zip_text(Client(sha), "http://h/x.zip") == METRICS
    with pytest.raises(bf.ChecksumError):
        bf.fetch_zip_text(Client("0" * 64), "http://h/x.zip")
    assert bf.fetch_zip_text(Client("0" * 64), "http://h/x.zip", verify=False) == METRICS


def test_missing_on_404():
    class R:
        status_code = 404
        content = b""

    class C:
        def get(self, url, **kw):
            return R()

    with pytest.raises(bf.Missing):
        bf.fetch_zip_text(C(), "http://h/none.zip")
