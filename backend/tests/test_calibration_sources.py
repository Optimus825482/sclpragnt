"""Kalibrasyonun otonom paper işlemlerini de öğrendiğini doğrular (2026-11-25).

NEDEN: kalibrasyon yalnız `trades` tablosunu okuyordu (≈20 satır) → kova tablosu
hep boştu ("[Calibration] 0 kova"). Binlerce kapanmış `auto_paper_trades` satırı
öğrenmeye girmiyordu.
"""
import time

from app import calibration


def _row(pnl, entry_offset_sec, **extra):
    base = time.time() - entry_offset_sec
    return {"pnl": pnl, "entry_time": base, "exit_time": base + 600, **extra}


def test_adapt_skips_invalid_rows():
    rows = [
        _row(10.0, 3600),
        {"pnl": 5.0, "entry_time": None},
        {"pnl": 5.0, "entry_time": "abc"},
        {"pnl": 5.0},
    ]
    out = calibration.adapt_auto_paper_trades(rows)
    assert len(out) == 1
    assert out[0]["strategy"] == "AUTO_PAPER"
    assert out[0]["entry_context"] == {}


def test_auto_paper_trades_fill_buckets():
    """300 işlem → en az bir kova MIN_BUCKET_SAMPLES eşiğini geçmeli."""
    rows = [_row(10.0 if i % 3 else -8.0, (i + 1) * 1800) for i in range(300)]
    trades = calibration.adapt_auto_paper_trades(rows)
    buckets = calibration.build_buckets(trades)

    assert buckets, "kova üretilmeli"
    informative = [b for b in buckets.values()
                   if b["samples"] >= calibration.MIN_BUCKET_SAMPLES]
    assert informative, "en az bir karar-verebilir kova olmalı"
    assert sum(b["samples"] for b in buckets.values()) == 300


def test_mixed_sources_share_bucket_space():
    manual = [{"pnl": 5.0, "entry_time": time.time() - 3600, "strategy": "SCALP", "entry_context": {}}]
    auto = calibration.adapt_auto_paper_trades([_row(7.0, 7200)])
    buckets = calibration.build_buckets(manual + auto)
    strategies = {key[0] for key in buckets}
    assert "SCALP" in strategies and "AUTO_PAPER" in strategies


def test_live_entry_falls_back_to_unknown_volume_bucket():
    """Canlı girişte hacim bandı dolu olsa da tarih kovası 'unknown' ise eşleşmeli."""
    rows = [{"pnl": -10.0, "entry_time": time.time() - 3600, "strategy": "AUTO_PAPER",
             "entry_context": {}} for _ in range(20)]
    buckets = calibration.build_buckets(rows)
    hour = calibration.datetime.now(calibration.BUCKET_TZ).hour

    exact = calibration.confidence_multiplier(
        buckets, strategy="AUTO_PAPER", hour=hour, volume_ratio=1.4)
    unknown = calibration.confidence_multiplier(
        buckets, strategy="AUTO_PAPER", hour=hour, volume_ratio=None)

    assert unknown == calibration.MIN_MULTIPLIER, "kötü kova boyutu küçültmeli"
    assert exact == unknown, "hacim bandı yoksa 'unknown' kovası kullanılmalı"


def test_adapt_uses_recorded_volume_ratio_for_band():
    """Giriş hacim oranı kayıtlıysa kova GERÇEK hacim bandına düşer."""
    rows = [{"pnl": -5.0, "entry_time": time.time() - 1800, "entry_volume_ratio": 0.2},
            {"pnl": -5.0, "entry_time": time.time() - 3600, "entry_volume_ratio": None}]
    adapted = calibration.adapt_auto_paper_trades(rows)
    assert adapted[0]["entry_context"]["volume_ratio"] == 0.2
    assert adapted[1]["entry_context"] == {}, "veri yoksa uydurma hacim yazılmamalı"

    buckets = calibration.build_buckets(adapted)
    volume_bands = {key[2] for key in buckets}
    assert "very_low" in volume_bands, "0,2 oranı very_low bandına düşmeli"
    assert "unknown" in volume_bands
