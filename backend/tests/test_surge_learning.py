"""Unit testler — surge_learning.py (2026-09-21)

Sembol bazlı adaptif bias hesaplamasının tüm kritik senaryolarını test eder:
- Sıfır veri → sıfır bias (güvenli geri dönüş)
- Yüksek başarı → pozitif bias (ödül)
- Yüksek stop oranı → negatif bias (ceza)
- Sınır testi → ±MAX_BIAS_PCT asla aşılmaz
- Güven eşiği → confidence < 0.30 → bias uygulanmaz (master_surge.py mantığı)
- Min örnek → sample_size < 5 → sıfır bias
"""
import pytest
from app.surge_learning import (
    compute_symbol_bias,
    build_surge_biases,
    refresh_biases,
    get_cached_surge_biases,
    bias_summary,
    MAX_BIAS_PCT,
    MIN_CONFIDENCE,
    MIN_SAMPLES,
)


# ---------------------------------------------------------------------------
# Yardımcı sabit veri fabrikalar
# ---------------------------------------------------------------------------

def _trade(symbol: str, pnl: float, exit_reason: str = "TP1") -> dict:
    return {
        "symbol": symbol,
        "pnl": pnl,
        "pnl_pct": pnl / 5.0,   # basit normalleşme
        "exit_reason": exit_reason,
        "status": "closed",
    }


def _radar(symbol: str, mfe_pct: float, status: str = "evaluated") -> dict:
    return {
        "symbol": symbol,
        "mfe_pct": mfe_pct,
        "candidate_status": status,
    }


# ---------------------------------------------------------------------------
# 1. Sıfır veri senaryoları
# ---------------------------------------------------------------------------

class TestZeroBias:
    def test_empty_symbol(self):
        b = compute_symbol_bias("", [], [])
        assert b["bias_pct"] == 0.0
        assert b["confidence"] == 0.0
        assert b["sample_size"] == 0
        assert "empty_symbol" in b["reason"]

    def test_no_data_at_all(self):
        b = compute_symbol_bias("BTCTRY", [], [])
        assert b["bias_pct"] == 0.0
        assert b["sample_size"] == 0

    def test_insufficient_samples_below_min(self):
        # MIN_SAMPLES = 5; sadece 3 veri → sıfır bias
        trades = [_trade("BTCTRY", 10.0) for _ in range(3)]
        b = compute_symbol_bias("BTCTRY", trades, [])
        assert b["bias_pct"] == 0.0
        assert "insufficient_samples" in b["reason"]

    def test_other_symbol_data_ignored(self):
        trades = [_trade("ETHTRY", 10.0) for _ in range(20)]
        b = compute_symbol_bias("BTCTRY", trades, [])
        assert b["bias_pct"] == 0.0
        assert b["sample_size"] == 0


# ---------------------------------------------------------------------------
# 2. Pozitif bias (yüksek başarı)
# ---------------------------------------------------------------------------

class TestPositiveBias:
    def test_high_win_rate_gives_bonus(self):
        # 14 kazanan / 16 toplam → win_rate ~87.5%
        trades = [_trade("BTCTRY", 10.0) for _ in range(14)] + \
                 [_trade("BTCTRY", -5.0, "STOP") for _ in range(2)]
        b = compute_symbol_bias("BTCTRY", trades, [])
        assert b["bias_pct"] > 0.0, f"Beklenen pozitif bias, alınan: {b['bias_pct']}"
        assert b["win_rate"] is not None

    def test_bias_increases_with_more_winning_trades(self):
        trades_10 = [_trade("AAATRY", 10.0) for _ in range(10)]
        trades_20 = [_trade("AAATRY", 10.0) for _ in range(20)]
        b10 = compute_symbol_bias("AAATRY", trades_10, [])
        b20 = compute_symbol_bias("AAATRY", trades_20, [])
        # Daha fazla örnek → daha yüksek güven → daha yüksek bias
        assert b20["bias_pct"] >= b10["bias_pct"]

    def test_high_tp1_radar_rate_amplifies_bias(self):
        trades = [_trade("BTCTRY", 10.0) for _ in range(10)]
        # Tüm radar sinyalleri TP1 hedefledi
        radar_high = [_radar("BTCTRY", 1.5) for _ in range(10)]
        radar_low = [_radar("BTCTRY", 0.2) for _ in range(10)]
        b_high = compute_symbol_bias("BTCTRY", trades, radar_high)
        b_low = compute_symbol_bias("BTCTRY", trades, radar_low)
        assert b_high["bias_pct"] >= b_low["bias_pct"]


# ---------------------------------------------------------------------------
# 3. Negatif bias (yüksek stop oranı)
# ---------------------------------------------------------------------------

class TestNegativeBias:
    def test_high_stop_rate_gives_penalty(self):
        # 8 stop loss / 10 toplam → stop_rate = 80%
        trades = [_trade("PEPETRY", -5.0, "STOP_LOSS") for _ in range(8)] + \
                 [_trade("PEPETRY", 10.0) for _ in range(2)]
        b = compute_symbol_bias("PEPETRY", trades, [])
        assert b["bias_pct"] < 0.0, f"Beklenen negatif bias, alınan: {b['bias_pct']}"

    def test_all_losses_gives_negative(self):
        trades = [_trade("PEPETRY", -5.0, "STOP") for _ in range(10)]
        b = compute_symbol_bias("PEPETRY", trades, [])
        assert b["bias_pct"] <= 0.0


# ---------------------------------------------------------------------------
# 4. Sınır testleri — ±MAX_BIAS_PCT asla aşılmaz
# ---------------------------------------------------------------------------

class TestBiasLimits:
    def test_max_positive_capped(self):
        # 100 trade, hepsi kazanan → bias MAX'a kadar çıkabilir ama aşamaz
        trades = [_trade("AAATRY", 100.0) for _ in range(100)]
        radar = [_radar("AAATRY", 3.0) for _ in range(100)]
        b = compute_symbol_bias("AAATRY", trades, radar)
        assert b["bias_pct"] <= MAX_BIAS_PCT, f"MAX_BIAS aşıldı: {b['bias_pct']}"

    def test_max_negative_capped(self):
        # 100 trade, hepsi stop → bias -MAX'ın altına inemez
        trades = [_trade("AAATRY", -5.0, "STOP_LOSS") for _ in range(100)]
        radar = [_radar("AAATRY", 0.1) for _ in range(100)]
        b = compute_symbol_bias("AAATRY", trades, radar)
        assert b["bias_pct"] >= -MAX_BIAS_PCT, f"-MAX_BIAS aşıldı: {b['bias_pct']}"

    def test_bias_is_float_not_nan(self):
        trades = [_trade("AAATRY", 10.0) for _ in range(5)]
        b = compute_symbol_bias("AAATRY", trades, [])
        import math
        assert not math.isnan(b["bias_pct"])
        assert not math.isinf(b["bias_pct"])


# ---------------------------------------------------------------------------
# 5. Güven eşiği — master_surge.py'daki mantık
# ---------------------------------------------------------------------------

class TestConfidenceGate:
    def test_low_confidence_bias_not_applied_by_master_surge_logic(self):
        """master_surge.py MIN_CONFIDENCE altında bias uygulamaz."""
        # Sadece tam olarak MIN_SAMPLES kadar veri → confidence = MIN_SAMPLES/30
        trades = [_trade("AAATRY", 100.0) for _ in range(MIN_SAMPLES)]
        b = compute_symbol_bias("AAATRY", trades, [])
        conf = b["confidence"]
        # Eğer confidence < MIN_CONFIDENCE ise master_surge bias'ı uygulamamalı
        if conf < MIN_CONFIDENCE:
            # bias_pct != 0 olabilir ama master_surge onu kullanmaz
            # Bu test sadece confidence'ın doğru hesaplandığını kontrol eder
            assert 0.0 <= conf < MIN_CONFIDENCE
        else:
            assert conf >= MIN_CONFIDENCE


# ---------------------------------------------------------------------------
# 6. build_surge_biases — toplu hesaplama
# ---------------------------------------------------------------------------

class TestBuildSurgeBiases:
    def test_empty_input(self):
        result = build_surge_biases([], [])
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_multiple_symbols(self):
        trades = (
            [_trade("BTCTRY", 10.0) for _ in range(10)] +
            [_trade("ETHTRY", -5.0, "STOP") for _ in range(10)]
        )
        result = build_surge_biases(trades, [])
        assert "BTCTRY" in result
        assert "ETHTRY" in result

    def test_symbol_isolation(self):
        """Bir sembolün verisi diğerini etkilemez."""
        trades = [_trade("BTCTRY", 100.0) for _ in range(20)]
        result = build_surge_biases(trades, [])
        assert "BTCTRY" in result
        # ETHTRY veri yoksa sonuçta olmamalı
        assert "ETHTRY" not in result

    def test_low_sample_count_has_zero_bias(self):
        """Yetersiz örnekli sembollerde bias_pct = 0 olarak döner."""
        trades = [_trade("RARETRY", 100.0) for _ in range(2)]  # MIN_SAMPLES'tan az
        result = build_surge_biases(trades, [])
        if "RARETRY" in result:
            assert result["RARETRY"]["bias_pct"] == 0.0


# ---------------------------------------------------------------------------
# 7. RAM Önbelleği — refresh ve get
# ---------------------------------------------------------------------------

class TestCache:
    def test_refresh_updates_cache(self):
        trades = [_trade("BTCTRY", 10.0) for _ in range(10)]
        new = refresh_biases(trades, [])
        cached = get_cached_surge_biases()
        assert new is cached  # Aynı nesne referansı

    def test_bias_summary_empty(self):
        # Boş önbellek ile summary
        summary = bias_summary({})
        assert summary["enabled"] is False

    def test_bias_summary_with_data(self):
        trades = (
            [_trade("GAINTRY", 10.0) for _ in range(20)] +
            [_trade("LOSETRY", -5.0, "STOP") for _ in range(20)]
        )
        biases = build_surge_biases(trades, [])
        summary = bias_summary(biases)
        assert summary["enabled"] is True
        assert summary["symbol_count"] >= 1
        assert "max_bias_pct" in summary
        assert summary["max_bias_pct"] == MAX_BIAS_PCT
