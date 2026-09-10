"""MACD alarm kanıt katmanı — istatistik gruplama + lift + MFE/MAE testleri.

Neden var
---------
Erken sıçrama alarmı üç bağımsız öncünün eşit ağırlıklı VEYA'sıdır
(`approach` / `m1` / `dip`, bkz. `routers/macd_monitor.py`). Uzun süre
istatistikler YALNIZCA `kind` bazında gruplanıyordu → "hangi öncü işe
yarıyor?" sorusu veriyle cevaplanamıyordu ve her iyileştirme tahmine
dayanıyordu. Bu testler öncü bazlı kırılımı kilitler.

Ayrıca A2/A3 katmanı kilitlenir: `avg_pct` tek başına iyi/kötü demez, karar
metriği **lift**'tir (aynı 5m kovasındaki evren ortalamasına göre fark). MFE/MAE
ise "kâr potansiyeli vs maksimum ters hareket" ölçüsüdür.

Test edilen davranış:
  - `_alert_bucket_add` / `_alert_bucket_out` saf yardımcılarının matematiği
    (ortalama, isabet oranı, eksik ufkun atlanması, skor ortalaması).
  - Lift/hit-lift: taban verilmediğinde alan HİÇ çıkmaz (uydurma yok), taban
    verildiğinde fark doğru hesaplanır.
  - MFE/MAE ortalamaları ve `_baseline_summary` indirgemesi.
  - Öncü kırılımının **çoklu etiket** semantiği: bir alarm birden fazla
    öncüyle geldiyse her birine sayılır (kotalar toplanabilir → `n` toplamı
    alarm sayısından büyük olabilir). Bu bilinçli bir karardır.
"""
import unittest

from app import database as db


def _empty() -> dict:
    """Production ile AYNI boş kova (kopya tutmak test kaymasına yol açıyordu)."""
    return db._new_alert_bucket()


class AlertBucketMathTests(unittest.TestCase):
    def test_bucket_averages_and_hit_rate(self):
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.10, "outcome_15m_pct": 0.30,
                                      "outcome_30m_pct": 0.50})
        db._alert_bucket_add(bucket, {"outcome_5m_pct": -0.05, "outcome_15m_pct": -0.20,
                                      "outcome_30m_pct": -0.40})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(2, out["n"])
        # 5m: (0.10 + -0.05)/2 = 0.025 ; isabet 1/2
        self.assertEqual(0.025, out["5m"]["avg_pct"])
        self.assertEqual(0.5, out["5m"]["hit_rate"])
        # 15m: 0.05 ; 30m: 0.05
        self.assertEqual(0.05, out["15m"]["avg_pct"])
        self.assertEqual(0.05, out["30m"]["avg_pct"])

    def test_missing_horizon_is_skipped_not_zeroed(self):
        """Ufuk verisi yoksa kovaya HİÇ girmez — 0 sayılırsa ortalama bozulur."""
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.2, "outcome_15m_pct": None,
                                      "outcome_30m_pct": None})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(1, out["5m"]["n"])
        self.assertNotIn("15m", out, "Veri olmayan ufuk rapor edilmemeli")
        self.assertNotIn("30m", out)

    def test_zero_return_counts_as_miss(self):
        """0 getiri pozitif DEĞİLDİR (isabet eşiği > 0)."""
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.0, "outcome_15m_pct": None,
                                      "outcome_30m_pct": None})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(0.0, out["5m"]["hit_rate"])

    def test_avg_score_only_reported_when_present(self):
        bucket = _empty()
        db._alert_bucket_add(bucket, {"score": 70, "outcome_5m_pct": 0.1})
        db._alert_bucket_add(bucket, {"score": 60, "outcome_5m_pct": 0.2})
        self.assertEqual(65.0, db._alert_bucket_out(bucket)["avg_score"])
        # Skorsuz kovada alan hiç çıkmamalı (erken alarmlarda score None).
        empty_score = _empty()
        db._alert_bucket_add(empty_score, {"score": None, "outcome_5m_pct": 0.1})
        self.assertNotIn("avg_score", db._alert_bucket_out(empty_score))

    def test_totals_are_rounded_to_three_decimals(self):
        bucket = _empty()
        for value in (0.111111, 0.222222, 0.333333):
            db._alert_bucket_add(bucket, {"outcome_5m_pct": value})
        self.assertEqual(0.222, db._alert_bucket_out(bucket)["5m"]["avg_pct"])


class AlertLiftTests(unittest.TestCase):
    """A2 — lift: alarm getirisi eksi aynı kovadaki evren ortalaması."""

    def test_no_baseline_means_no_lift_fields(self):
        """Taban yoksa uydurma yapılmaz: `avg_lift` alanı HİÇ çıkmaz."""
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.4})
        out = db._alert_bucket_out(bucket)
        self.assertNotIn("avg_lift", out["5m"])
        self.assertNotIn("hit_lift", out["5m"])
        self.assertNotIn("base_hit_rate", out["5m"])

    def test_lift_is_difference_from_baseline(self):
        # Alarm 0.40 getirdi, evren aynı pencerede 0.10 → lift +0.30
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.40}, {"5m": {"avg_pct": 0.10}})
        db._alert_bucket_add(bucket, {"outcome_5m_pct": -0.20}, {"5m": {"avg_pct": 0.10}})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(0.1, out["5m"]["avg_pct"])
        # (0.40-0.10) + (-0.20-0.10) = 0 → ortalama lift 0.
        # ÖNEMLİ DERS: `avg_pct` +0.1 GÖRÜNÜRKEN lift 0'dır, yani piyasadan
        # fark yoktur. Bu yüzden karar metriği lift'tir, avg_pct değil.
        self.assertEqual(0.0, out["5m"]["avg_lift"])

    def test_lift_matches_avg_when_baseline_is_zero(self):
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.40}, {"5m": {"avg_pct": 0.0}})
        db._alert_bucket_add(bucket, {"outcome_5m_pct": -0.20}, {"5m": {"avg_pct": 0.0}})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(out["5m"]["avg_pct"], out["5m"]["avg_lift"])

    def test_negative_lift_when_alarm_worse_than_market(self):
        """Alarm pozitif ama evren daha iyi → lift NEGATİF (asıl karar sinyali)."""
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.05}, {"5m": {"avg_pct": 0.20}})
        out = db._alert_bucket_out(bucket)
        self.assertGreater(out["5m"]["avg_pct"], 0)
        self.assertLess(out["5m"]["avg_lift"], 0)

    def test_hit_lift_uses_baseline_hit_rate(self):
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.3},
                             {"5m": {"avg_pct": 0.0, "hit_rate": 0.40}})
        db._alert_bucket_add(bucket, {"outcome_5m_pct": -0.3},
                             {"5m": {"avg_pct": 0.0, "hit_rate": 0.40}})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(0.4, out["5m"]["base_hit_rate"])
        self.assertEqual(0.1, out["5m"]["hit_lift"], "0.50 isabet - 0.40 taban")

    def test_baseline_for_other_horizon_does_not_leak(self):
        """15m tabanı varken 5m lift hesaplanmamalı (ufuk karışması yasak)."""
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.5}, {"15m": {"avg_pct": 0.1}})
        self.assertNotIn("avg_lift", db._alert_bucket_out(bucket)["5m"])

    def test_baseline_without_avg_pct_is_tolerated(self):
        """Bozuk/eksik taban alanı çökertmez, yalnız lift yazılmaz."""
        bucket = _empty()
        db._alert_bucket_add(bucket, {"outcome_5m_pct": 0.5}, {"5m": {"hit_rate": 0.4}})
        out = db._alert_bucket_out(bucket)
        self.assertNotIn("avg_lift", out["5m"])
        self.assertEqual(0.4, out["5m"]["base_hit_rate"])


class AlertMfeMaeTests(unittest.TestCase):
    """A3 — MFE/MAE: kâr potansiyeli ve maksimum ters hareket."""

    def test_mfe_mae_averages_reported(self):
        bucket = _empty()
        db._alert_bucket_add(bucket, {"mfe_pct": 1.0, "mae_pct": -0.5})
        db._alert_bucket_add(bucket, {"mfe_pct": 0.4, "mae_pct": -0.9})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(0.7, out["avg_mfe"])
        self.assertEqual(-0.7, out["avg_mae"])

    def test_missing_mfe_mae_are_not_counted_as_zero(self):
        """Kayıt yoksa 0 sayılmaz — aksi halde MFE/MAE yapay küçülür."""
        bucket = _empty()
        db._alert_bucket_add(bucket, {"mfe_pct": 1.0, "mae_pct": None})
        db._alert_bucket_add(bucket, {"mfe_pct": None, "mae_pct": None})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(1.0, out["avg_mfe"])
        self.assertNotIn("avg_mae", out)

    def test_zero_mfe_is_still_reported(self):
        """0.0 gerçek bir ölçümdür (fiyat hiç yukarı gitmedi) → rapor edilir."""
        bucket = _empty()
        db._alert_bucket_add(bucket, {"mfe_pct": 0.0, "mae_pct": -0.2})
        out = db._alert_bucket_out(bucket)
        self.assertEqual(0.0, out["avg_mfe"])


class BaselineSummaryTests(unittest.TestCase):
    """`_baseline_summary` — kova tabanlarını ufuk bazında tek satıra indirger."""

    def test_averages_across_buckets_per_horizon(self):
        summary = db._baseline_summary({
            100: {"5m": {"avg_pct": 0.10, "med_pct": 0.0, "hit_rate": 0.40, "n_symbols": 50}},
            200: {"5m": {"avg_pct": 0.30, "med_pct": 0.0, "hit_rate": 0.60, "n_symbols": 80}},
        })
        self.assertEqual(2, summary["5m"]["buckets"])
        self.assertEqual(0.2, summary["5m"]["avg_pct"])
        self.assertEqual(0.5, summary["5m"]["hit_rate"])
        self.assertEqual(80, summary["5m"]["symbols"], "en geniş evren raporlanır")

    def test_empty_input_yields_empty_summary(self):
        self.assertEqual({}, db._baseline_summary({}))

    def test_bucket_missing_a_horizon_is_skipped_for_that_horizon(self):
        summary = db._baseline_summary({
            100: {"5m": {"avg_pct": 0.10, "med_pct": 0.0, "hit_rate": 0.4, "n_symbols": 50}},
            200: {},
        })
        self.assertEqual(1, summary["5m"]["buckets"])
        self.assertNotIn("15m", summary)


class PrecursorBreakdownSemanticsTests(unittest.TestCase):
    """Öncü kırılımının çoklu-etiket davranışı (belgelenmiş karar)."""

    def _fan_out(self, alarms: list[dict]) -> dict[str, dict]:
        """`macd_monitor_alert_stats` içindeki öncü dağıtım mantığının aynısı.

        `signals` JSONB'den gelebileceği için bozuk/eksik payload'a karşı
        production'daki `isinstance(..., dict)` gardı burada da birebir uygulanır.
        """
        precursors: dict[str, dict] = {}
        for entry in alarms:
            signals = entry.get("signals")
            labels = signals.get("early_signals") if isinstance(signals, dict) else None
            for label in labels or []:
                db._alert_bucket_add(precursors.setdefault(str(label), _empty()), entry)
        return {k: db._alert_bucket_out(v) for k, v in precursors.items()}

    def test_alarm_with_two_precursors_counts_in_both(self):
        out = self._fan_out([
            {"signals": {"early_signals": ["approach", "dip"]}, "outcome_5m_pct": 0.4},
            {"signals": {"early_signals": ["dip"]}, "outcome_5m_pct": -0.2},
        ])
        # dip: iki alarmda da var → n=2, ortalama (0.4 + -0.2)/2 = 0.1
        self.assertEqual(2, out["dip"]["n"])
        self.assertEqual(0.1, out["dip"]["5m"]["avg_pct"])
        # approach: yalnız ilkinde → n=1
        self.assertEqual(1, out["approach"]["n"])
        self.assertEqual(0.4, out["approach"]["5m"]["avg_pct"])

    def test_alarm_without_precursor_labels_is_ignored(self):
        """Jump alarmında `early_signals` yoktur; öncü kovası oluşmamalı."""
        self.assertEqual({}, self._fan_out([
            {"signals": {"strength": 9.1}, "outcome_5m_pct": 0.5},
        ]))

    def test_missing_or_broken_signals_payload_does_not_crash(self):
        self.assertEqual({}, self._fan_out([
            {"signals": None, "outcome_5m_pct": 0.5},
            {"signals": "bozuk", "outcome_5m_pct": 0.5},
            {"signals": {}, "outcome_5m_pct": 0.5},
        ]))

    def test_empty_label_list_yields_no_buckets(self):
        self.assertEqual({}, self._fan_out([{"signals": {"early_signals": []}}]))


if __name__ == "__main__":
    unittest.main()
