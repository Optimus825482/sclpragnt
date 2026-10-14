"""D-06 (2026-09-14): gerçekleşen çıkış (exit_pct) + maliyet sonrası net (net_pct).

Bulgu: raporlarda tek başarı ölçütü MFE (max favorable excursion) idi. MFE
penceredeki TEPE'dir — ulaşılamaz. "Hedefe dokundu" demek için doğru, "kazandık"
demek için yanıltıcı: tepeye dokunup geri düşen hareket hâlâ pozitif görünür.

Eklenen ölçüm (additive; TAMAMEN/KISMI/BASARISIZ tanımı R3-04 DEĞİŞMEZ):
  exit_pct = ufuk sonundaki son kapanmış mumun CLOSE'u  -> gerçekleştirilebilir
  net_pct  = exit_pct - gidiş-dönüş maliyeti (komisyon + slippage, iki bacak)

Kural gereği her iddia mutasyonla doğrulanır (bkz. dosya sonu `_MUTATION_NOTES`).
"""
import inspect
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                      # noqa: E402
from app.routers.velocity import (                 # noqa: E402
    _exit_pct_from_window, _mfe_from_window, _post_signal_window,
    round_trip_cost_pct,
)


def _bar(open_ms, o, h, l, c, v=1.0):
    """[open_ms, open, high, low, close, volume] — klines sırası."""
    return [open_ms, o, h, l, c, v]


class ExitPctDefinitionTests(unittest.TestCase):
    """`_exit_pct_from_window` TEPE değil KAPANIŞ ölçer."""

    def test_exit_is_last_close_not_peak(self):
        """Tepeye dokunup geri düşen bar: MFE +5, gerçekleşen çıkış -1."""
        rows = [
            _bar(600_000, 100.0, 105.0, 98.0, 99.0),
            _bar(660_000, 99.0, 99.5, 97.0, 97.5),
        ]
        mfe = _mfe_from_window(rows, 100.0)
        exit_ = _exit_pct_from_window(rows, 100.0)
        self.assertAlmostEqual(5.0, mfe, places=6)
        self.assertAlmostEqual(-2.5, exit_, places=6)
        self.assertLess(exit_, mfe, "çıkış tepeyle aynı ölçülüyorsa MFE'nin kopyasıdır")

    def test_exit_never_exceeds_mfe_for_positive_series(self):
        """close <= high olduğundan exit her zaman MFE'den küçük/eşit olmalı."""
        rows = [
            _bar(600_000, 100.0, 103.0, 99.0, 102.0),
            _bar(660_000, 102.0, 104.0, 101.0, 103.5),
            _bar(720_000, 103.5, 106.0, 103.0, 104.0),
        ]
        self.assertLessEqual(_exit_pct_from_window(rows, 100.0),
                             _mfe_from_window(rows, 100.0))

    def test_monotone_rally_exit_tracks_close(self):
        rows = [
            _bar(600_000, 100.0, 100.2, 99.8, 100.1),
            _bar(660_000, 100.1, 101.0, 100.0, 100.8),
        ]
        self.assertAlmostEqual(0.8, _exit_pct_from_window(rows, 100.0), places=6)

    def test_uses_same_window_as_mfe(self):
        """Aynı `_post_signal_window` (R5-C4.4): parsiyel mum HARİÇ."""
        bar0_open = 600_000
        created = bar0_open + 50_000          # sinyal 10:00:50
        due = created + 5 * 60_000
        rows = [
            _bar(bar0_open, 100.0, 105.0, 99.5, 100.2),   # parsiyel (sinyal-öncesi spike)
            _bar(660_000, 100.2, 100.5, 100.0, 100.3),
            _bar(720_000, 100.3, 100.5, 100.1, 100.4),
            _bar(900_000, 100.4, 100.5, 100.2, 100.4),    # due'yu aşar -> hariç
        ]
        window = _post_signal_window(rows, created, due)
        self.assertEqual([660_000, 720_000], [int(r[0]) for r in window])
        # MFE 0.5 (spike hariç), çıkış 0.4 (son kapanış 100.4)
        self.assertAlmostEqual(0.5, _mfe_from_window(window, 100.0), places=6)
        self.assertAlmostEqual(0.4, _exit_pct_from_window(window, 100.0), places=6)

    def test_empty_and_bad_entry_are_safe(self):
        """Bozuk girdi 0 DEĞİL None (nötr gösterim kuralı)."""
        self.assertIsNone(_exit_pct_from_window([], 100.0))
        self.assertIsNone(_exit_pct_from_window([_bar(600_000, 100, 101, 99, 100)], 0.0))
        self.assertIsNone(_exit_pct_from_window([_bar(600_000, 100, 101, 99, 100)], -5.0))
        self.assertIsNone(_exit_pct_from_window([_bar(600_000, 100, 101, 99, 100)], None))


class RoundTripCostTests(unittest.TestCase):
    """Maliyet tek kaynaktan gelir: `config.round_trip_cost()`."""

    def test_default_cost_is_35_bps_in_percent(self):
        """(0.0015 + 0.00025) * 2 * 100 = %0.35"""
        self.assertAlmostEqual(0.35, round_trip_cost_pct(), places=9)

    def test_tracks_config_change(self):
        """Komisyon değişirse ölçüm de değişir (sabit yazılmadı)."""
        with patch.object(type(config), "COMMISSION_PCT", 0.003):
            self.assertAlmostEqual(0.65, round_trip_cost_pct(), places=9)

    def test_min_net_exit_pct_behaviour_preserved(self):
        """`round_trip_cost` refaktörü `min_net_exit_pct`'i DEĞİŞTİRMEDİ.

        W6 money-math kapısı: value<=0 dalı yalnızca komisyon+slippage döndürür.
        """
        self.assertAlmostEqual(config.round_trip_cost(),
                               config.COMMISSION_PCT * 2 + config.ESTIMATED_SLIPPAGE_PCT * 2,
                               places=12)
        # value<=0 -> saf maliyet (asgari net kâr terimi YOK)
        self.assertAlmostEqual(config.round_trip_cost(), config.min_net_exit_pct(-1.0), places=12)
        # value>0 -> maliyet + asgari net kâr / emir tutarı
        val = float(config.DEFAULT_ORDER_TRY)
        self.assertAlmostEqual(config.round_trip_cost() + config.MIN_EXPECTED_NET_PNL_TRY / val,
                               config.min_net_exit_pct(val), places=12)

    def test_net_is_exit_minus_cost(self):
        exit_pct = 1.0
        self.assertAlmostEqual(0.65, exit_pct - round_trip_cost_pct(), places=9)

    def test_marginally_positive_mfe_becomes_negative_net(self):
        """Gerçek vaka: MFE +0.4 (KISMİ görünür) ama net -0.05 -> zarar."""
        rows = [_bar(600_000, 100.0, 100.4, 99.9, 100.3)]
        mfe = _mfe_from_window(rows, 100.0)
        net = _exit_pct_from_window(rows, 100.0) - round_trip_cost_pct()
        self.assertAlmostEqual(0.4, mfe, places=6)
        self.assertAlmostEqual(-0.05, net, places=6)
        self.assertLess(net, 0.0, "maliyet düşülmeden 'başarı' sayılıyor")


class DatabaseSignatureTests(unittest.TestCase):
    """`mark_velocity_candidate_evaluated` yeni alanları kabul eder (opsiyonel)."""

    def test_accepts_exit_and_net_kwargs(self):
        from app import database
        sig = inspect.signature(database.mark_velocity_candidate_evaluated)
        for name in ("exit_pct", "net_pct"):
            self.assertIn(name, sig.parameters, f"{name} parametresi yok")
            # geriye dönük uyumluluk: varsayılan None
            self.assertIsNone(sig.parameters[name].default, f"{name} varsayılanı None olmalı")


# --------------------------------------------------------------------------
# Mutasyon notları (iddia -> kanıt). Her madde elle bozulup testin KIRILDIĞI
# gözlemlendi; aksi halde test yeşil kalıp hiçbir şeyi kanıtlamaz.
#
# 1) `_exit_pct_from_window` -> `max(r[2])` (MFE ile aynı):
#       test_exit_is_last_close_not_peak KIRILIR (-2.5 != 5.0).
# 2) `round_trip_cost_pct` -> tek bacak (x1):
#       test_default_cost_is_35_bps_in_percent KIRILIR (0.175 != 0.35).
# 3) `config.round_trip_cost` -> `min_net_exit_pct(0)` ile değiştirmek:
#       `0 or DEFAULT_ORDER_TRY` kısa devresi yüzünden asgari-net terimi ekler;
#       test_min_net_exit_pct_behaviour_preserved yakalar.
# 4) Bozuk girdide 0 döndürmek:
#       test_empty_and_bad_entry_are_safe KIRILIR (0 -> kazanç gibi boyanır).
# --------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
