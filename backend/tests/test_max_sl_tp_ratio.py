"""Regresyon: `max_sl_tp_ratio` — SL/TP oran tavanı (2026-11-10).

KANIT (docs/TARAMA_AILESI_ANALIZI_2026-11-10.md + gerçek 1m mum replay):
Gerçekleşmiş 1.757 işlemde ortalama SL %3,88 > ortalama TP %3,75 (oran 1,03).
Kazanma oranı %56,7 iken zarar (kazanç/kayıp 0,547, başabaş için 0,764 gerek).

GERÇEK MUM YOLU İLE ÖLÇÜM (1.200 işlem, giriş/hedef sabit, sadece SL daralır):

    oran    ort_net   medyan   kazanan   TP   SL
    mevcut  -0.796%   -3.300%   44.6%    527  640
    0.80    -0.748%   -2.700%   37.0%    437  737
    0.64    -0.724%   -2.284%   31.9%    377  802
    0.55    -0.641%   -2.084%   29.7%    350  833

DÜRÜST SONUÇ: SL daraltmak İYİLEŞTİRİYOR (+0.155 puan @0.55) ve medyanı
belirgin düzeltiyor (-3.300% -> -2.084%) AMA pozitife ÇEVİRMİYOR.
Kazanma oranı %44.6 -> %29.7'ye düşüyor (dar SL daha sık vuruyor).
Kök sorun asimetri değil, GİRİŞ KALİTESİ; `min_atr_pct` filtresi asıl kaldıraç.
"""
import asyncio
import inspect

import pytest

from app.routers import auto_paper as ap


def _sl(target_pct, sl_pct, ratio):
    """`_exit_apply_rr_ratio` doğrudan (kesir cinsinden) çalıştır."""
    settings = {"max_sl_tp_ratio": ratio}
    return ap._exit_apply_rr_ratio("XTRY", sl_pct / 100.0, target_pct, settings, None, None)


def test_default_is_disabled():
    """Varsayılan 0.0 — üretim davranışı sessizce değişmesin."""
    d = asyncio.run(ap.get_default_settings())
    assert d["max_sl_tp_ratio"] == 0.0


def test_disabled_keeps_sl():
    """0 iken SL'ye dokunulmamalı."""
    sl, tp = _sl(2.0, 4.0, 0.0)
    assert abs(sl - 0.04) < 1e-9
    assert abs(tp - 2.0) < 1e-9


def test_widens_nothing_when_already_tight():
    """Oran zaten sınırın altındaysa SL DEĞİŞMEZ (asla genişletmez)."""
    sl, tp = _sl(2.0, 1.0, 0.64)   # 1.0 < 2.0*0.64=1.28
    assert abs(sl - 0.01) < 1e-9


def test_tightens_when_ratio_exceeded():
    """Oran aşılırsa SL daraltılır: 4.0% -> 2.0*0.64 = 1.28%."""
    sl, tp = _sl(2.0, 4.0, 0.64)
    assert abs(sl - 0.0128) < 1e-9, f"SL daraltılmadı: {sl}"
    assert abs(tp - 2.0) < 1e-9, "hedef DEĞİŞMEMELİ"


def test_target_never_modified():
    """Kural: hedef asla değişmez, yalnız SL daralır."""
    for ratio in (0.3, 0.5, 0.64, 0.9):
        _sl_v, tp_v = _sl(3.0, 5.0, ratio)
        assert abs(tp_v - 3.0) < 1e-9


def test_user_plan_is_exempt():
    """Kullanıcı planı varsa dokunulmaz (kendi tutarlı hesabı)."""
    plan = {"target_pct": 2.0, "stop_pct": 4.0, "exit_at": 1e18, "grace_minutes": 5}
    sl, tp = ap._exit_apply_rr_ratio("XTRY", 0.04, 2.0, {"max_sl_tp_ratio": 0.5}, plan, None)
    assert abs(sl - 0.04) < 1e-9, "plan stop'u değiştirilmemeli"


def test_exit_profile_is_exempt():
    """Kural profili kendi SL/hedef geometrisini taşır."""
    prof = {"stop_loss_pct": 4.0}
    sl, _tp = ap._exit_apply_rr_ratio("XTRY", 0.04, 2.0, {"max_sl_tp_ratio": 0.5}, None, prof)
    assert abs(sl - 0.04) < 1e-9


def test_editable_and_clamped():
    """Panelden ayarlanabilmeli ve 0..3 aralığına sıkıştırılmalı."""
    src = inspect.getsource(ap.update_settings_endpoint)
    assert "max_sl_tp_ratio" in src
    assert "min(3.0" in src, "üst sınır yok"


def test_applied_after_widening_rules():
    """R:R sınırı EN SON uygulanmalı — ATR/PPO genişletmelerinden sonra.

    Sıra bozulursa ATR stopu genişletip asimetriyi geri getirir.
    """
    src = inspect.getsource(ap._calc_exit_plan)
    i_vol = src.find("_exit_volatility_sl")
    i_ppo = src.find("ppo_sl_pct is not None")
    i_rr = src.find("_exit_apply_rr_ratio")
    assert -1 < i_vol < i_rr and -1 < i_ppo < i_rr, "R:R sınırı genişletici kurallardan ÖNCE"


def test_honest_finding_recorded():
    """Dürüst sınır raporda yazılı olmalı: iyileştirir ama pozitife çevirmez."""
    import pathlib
    doc = (pathlib.Path(__file__).parent.parent.parent / "docs"
           / "TARAMA_AILESI_ANALIZI_2026-11-10.md").read_text(encoding="utf-8")
    assert "max_sl_tp_ratio" in doc, "parametre raporda yok"
    assert "pozitife" in doc.lower() or "POZITIF" in doc, "iyileştirme sınırı belirtilmemiş"
