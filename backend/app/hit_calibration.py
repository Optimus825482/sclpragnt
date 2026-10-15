"""Radar skorunu kalibre edilmiş isabet olasılığına (p_hit) çevirir.

Heuristik `scan_score` tek başına "bu aday ne kadar güvenilir" sorusunu
yanıtlamaz. Bu modül, geçmiş ölçülmüş adaylarda skor -> gerçek hit oranı
ilişkisini izotonik regresyonla öğrenir: skor arttıkça olasılık ASLA
düşmez (monoton), sınırların dışında son değerde sabit kalır (clip).

Tasarım:
  * Model, sklearn'ün `IsotonicRegression` çıktısının eşik noktaları
    (X_thresholds_, y_thresholds_) olarak saklanır; yükleme `np.interp` ile
    yapılır. Pickle gerekmez, JSON'a yazılabilir.
  * Yeterli veri yoksa (`MIN_FIT_ROWS` altı) model `ready=False` kalır ve
    `predict` None döner; çağıran taraf heuristik skora düşmelidir.
  * Bu modül VERİTABANINA ERİŞMEZ. DB satırlarını `fit_from_rows` alır;
    satırları okuyan taraf çağırana aittir.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression

# Bu sayıdan az ölçülmüş satırla izotonik model kurulmaz (aşırı uydurma).
MIN_FIT_ROWS = 50

_SCHEMA_VERSION = 1


class HitCalibrator:
    """Skor -> isabet olasılığı izotonik kalibratörü."""

    def __init__(self) -> None:
        self.n: int = 0
        self.fitted_at: str | None = None
        self.ready: bool = False
        self.X_thresholds_: np.ndarray | None = None
        self.y_thresholds_: np.ndarray | None = None

    def fit(self, scores: list[float], hits: list[bool]) -> "HitCalibrator":
        """Skorları ve isabet bayraklarını öğrenir.

        `None` veya sonlu olmayan skor ya da `None` isabet içeren çiftler atlanır.
        Kalan çift sayısı `MIN_FIT_ROWS` altındaysa `ready=False` kalır.
        """
        if len(scores) != len(hits):
            raise ValueError("scores ve hits aynı uzunlukta olmalı")

        xs: list[float] = []
        ys: list[float] = []
        for score, hit in zip(scores, hits):
            if score is None or hit is None:
                continue
            value = float(score)
            if not math.isfinite(value):
                continue
            xs.append(value)
            ys.append(1.0 if hit else 0.0)

        self.n = len(xs)
        self.fitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if self.n < MIN_FIT_ROWS:
            self.ready = False
            self.X_thresholds_ = None
            self.y_thresholds_ = None
            return self

        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
        self.X_thresholds_ = np.asarray(iso.X_thresholds_, dtype=float)
        self.y_thresholds_ = np.asarray(iso.y_thresholds_, dtype=float)
        self.ready = True
        return self

    def predict(self, score: float | None) -> float | None:
        """Tek bir skor için p_hit döndürür; model hazır değilse None."""
        if not self.ready or score is None:
            return None
        value = float(score)
        if not math.isfinite(value):
            return None
        return float(np.clip(np.interp(value, self.X_thresholds_, self.y_thresholds_),
                             0.0, 1.0))

    def predict_many(self, scores: list[float]) -> list[float | None]:
        """Birden çok skor için `predict` (hazır değilse hepsi None)."""
        return [self.predict(s) for s in scores]

    def to_dict(self) -> dict[str, Any]:
        """JSON'a yazılabilir durum. Model hazır değilse eşik listeleri boştur."""
        has_model = self.ready and self.X_thresholds_ is not None
        return {
            "schema": _SCHEMA_VERSION,
            "n": self.n,
            "fitted_at": self.fitted_at,
            "ready": self.ready,
            "min_fit_rows": MIN_FIT_ROWS,
            "X_thresholds": [float(v) for v in self.X_thresholds_] if has_model else [],
            "y_thresholds": [float(v) for v in self.y_thresholds_] if has_model else [],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HitCalibrator":
        """`to_dict` çıktısından kalibratörü yeniden kurar (pickle yok)."""
        cal = cls()
        cal.n = int(data.get("n", 0) or 0)
        cal.fitted_at = data.get("fitted_at")
        xs = [float(v) for v in (data.get("X_thresholds") or [])]
        ys = [float(v) for v in (data.get("y_thresholds") or [])]
        if len(xs) != len(ys):
            raise ValueError("X_thresholds ve y_thresholds uzunlukları eşit değil")
        if bool(data.get("ready")) and xs:
            cal.X_thresholds_ = np.asarray(xs, dtype=float)
            cal.y_thresholds_ = np.asarray(ys, dtype=float)
            cal.ready = True
        return cal


def reliability_table(scores: list[float], hits: list[bool], bins: int = 10,
                      calibrator: HitCalibrator | None = None) -> list[dict]:
    """Kalibrasyon (güvenilirlik) tablosu: eşit sayılı skor dilimleri.

    Her dilim için: bin (1'den başlar), n, score_lo, score_hi, mean_score,
    observed_rate (gerçek hit oranı) ve predicted_rate (dilimdeki
    kalibre p_hit ortalaması).

    `calibrator` verilmezse aynı verilerle in-sample izotonik model kurulur;
    bu durumda predicted_rate eğitim verisine göre iyimser olabilir.
    Model hazır değilse predicted_rate None'dır. Tüm dilimlerin n toplamı,
    None olmayan (skor ve isabet dolu) satır sayısına eşittir.
    """
    if bins < 1:
        raise ValueError("bins en az 1 olmalı")
    if len(scores) != len(hits):
        raise ValueError("scores ve hits aynı uzunlukta olmalı")

    pairs: list[tuple[float, float]] = []
    for score, hit in zip(scores, hits):
        if score is None or hit is None:
            continue
        value = float(score)
        if not math.isfinite(value):
            continue
        pairs.append((value, 1.0 if hit else 0.0))
    if not pairs:
        return []

    pairs.sort(key=lambda p: p[0])
    xs = np.asarray([p[0] for p in pairs], dtype=float)
    ys = np.asarray([p[1] for p in pairs], dtype=float)

    cal = calibrator if calibrator is not None else HitCalibrator().fit(
        list(xs), [bool(y) for y in ys])

    table: list[dict] = []
    chunks = np.array_split(np.arange(xs.size), min(bins, xs.size))
    for i, idx in enumerate(chunks):
        if idx.size == 0:
            continue
        s = xs[idx]
        y = ys[idx]
        preds = [p for p in cal.predict_many([float(v) for v in s]) if p is not None]
        table.append({
            "bin": i + 1,
            "n": int(idx.size),
            "score_lo": float(s[0]),
            "score_hi": float(s[-1]),
            "mean_score": float(s.mean()),
            "observed_rate": float(y.mean()),
            "predicted_rate": float(np.mean(preds)) if preds else None,
        })
    return table


def _coerce_hit(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "t", "1"}:
        return True
    if text in {"false", "f", "0"}:
        return False
    return None


def fit_from_rows(rows: list[dict]) -> HitCalibrator:
    """DB satırlarından (`scan_score`, `hit` anahtarları) kalibratör kurar.

    `scan_score` veya `hit` boş olan satırlar atlanır.
    """
    scores: list[float | None] = []
    hits: list[bool | None] = []
    for row in rows:
        raw_score = row.get("scan_score")
        try:
            score = None if raw_score is None or raw_score == "" else float(raw_score)
        except (TypeError, ValueError):
            score = None
        scores.append(score)
        hits.append(_coerce_hit(row.get("hit")))

    keep = [i for i, (s, h) in enumerate(zip(scores, hits)) if s is not None and h is not None]
    return HitCalibrator().fit([scores[i] for i in keep], [hits[i] for i in keep])
