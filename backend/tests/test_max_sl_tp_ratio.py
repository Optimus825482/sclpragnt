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


def _sl(target_pct, sl_pct, ratio, atr_floor=None):
    """`_exit_apply_rr_ratio` doğrudan (kesir cinsinden) çalıştır."""
    settings = {"max_sl_tp_ratio": ratio}
    return ap._exit_apply_rr_ratio("XTRY", sl_pct / 100.0, target_pct, settings, None, None,
                                   atr_floor_pct=atr_floor)


def test_default_active():
    """2026-11-10: ölçüm sonrası AKTİF varsayılan 0.64 (config'ten)."""
    d = asyncio.run(ap.get_default_settings())
    assert d["max_sl_tp_ratio"] == 0.64, "ölçülmüş varsayılan uygulanmamış"


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


# ---------------------------------------------------------------------------
# P0 HATA (2026-11-10): PPO volatilite birimi yanlıştı -> hedef %700
# ---------------------------------------------------------------------------
# BELİRTİ: `_calc_exit_plan` hedefi %1.98 yerine %700 döndürüyordu.
# KÖK NEDEN: `ppo_adaptive_policy.evaluate_ppo_adaptive_policy` girdi
#   `volatility_atr_pct`i YÜZDE alıyor (1.4 = %1.4) ama `base_tp = atr * 1.4`
#   hesabı KESİR üretmeliydi; atr kesire çevrilmediği için 100 kat büyüktü.
#   Ayrıca `_exit_apply_ppo` volatilite girdisi olarak `atr_pct` yerine
#   `sl_pct * 100` (= default SL %5, sabit) geçiyordu -> her işlemde %700.
# Bu testler birim sözleşmesini kilitler.


def test_ppo_returns_sane_tp_for_normal_atr():
    """ATR %1.4 -> TP kesir ~0.0196 (yüzde 1.96), %196 DEĞİL."""
    from app.ai_trading_suite import evaluate_ppo_adaptive_policy as ev
    a = ev(symbol="XTRY", volatility_atr_pct=1.4, daily_drawdown_pct=0.5)
    assert 0.005 < a.recommended_tp_pct < 0.10, f"TP kesir aralığı bozuk: {a.recommended_tp_pct}"
    assert a.recommended_tp_pct * 100 < 10.0, "TP yüzde 10'u aşmamalı"


def test_ppo_scales_with_atr():
    """ATR arttıkça TP artmalı (orantı ~1.4x), ama makul bantta kalmalı."""
    from app.ai_trading_suite import evaluate_ppo_adaptive_policy as ev
    lo = ev(symbol="XTRY", volatility_atr_pct=1.0, daily_drawdown_pct=0.5)
    hi = ev(symbol="XTRY", volatility_atr_pct=3.0, daily_drawdown_pct=0.5)
    assert hi.recommended_tp_pct > lo.recommended_tp_pct
    assert hi.recommended_tp_pct * 100 < 10.0


def test_ppo_worst_case_atr_stays_sane():
    """Aşırı ATR'de bile hedef %10 altında kalmalı (eski hata: %700)."""
    from app.ai_trading_suite import evaluate_ppo_adaptive_policy as ev
    for atr in (3.5, 5.0, 10.0):
        a = ev(symbol="XTRY", volatility_atr_pct=atr, daily_drawdown_pct=0.5)
        assert a.recommended_tp_pct * 100 < 10.0, f"atr={atr} -> {a.recommended_tp_pct * 100}%"


def test_ppo_uses_notification_atr_not_stop_loss():
    """`_exit_apply_ppo` volatilite girdisi olarak `atr_pct`'i kullanmalı.

    Eskiden `sl_pct * 100` (default %5, sabit) geçiliyordu -> ATR'den bağımsız
    hep aynı hedef. Kaynak kontrolü bunu kilitler.
    """
    src = inspect.getsource(ap._exit_apply_ppo)
    assert "atr_pct" in src, "atr_pct parametresi yok"
    assert "vol_in" in src, "gerçek ATR seçimi yok"
    psrc = inspect.getsource(ap._calc_exit_plan)
    assert 'atr_pct=notification.get("atr_pct")' in psrc, "çağrı yerinde ATR geçilmiyor"


def test_ppo_sanity_cap_present():
    """Absürt PPO TP önerisi YOK SAYILMALI (sağduyu tavanı)."""
    src = inspect.getsource(ap._exit_apply_ppo)
    assert "0.05 <= tp_pct <= 8.0" in src, "sağduyu tavanı yok"


def test_ppo_does_not_explode_target():
    """Uçtan uca: hedef %700'e fırlamamalı."""
    notif = {"symbol": "XTRY", "score": 80.0, "mode": "trend_devam",
             "source": "velocity", "atr_pct": 1.2, "price": 50.5, "target_pct": 1.978}
    settings = {"max_sl_tp_ratio": 0.0}
    settings.update(asyncio.run(ap.get_default_settings()))
    plan, block = asyncio.run(ap._calc_exit_plan("XTRY", notif, 50.5, settings, 1000.0))
    assert block is None
    assert plan["target_pct"] < 10.0, f"hedef hâlâ absürt: {plan['target_pct']}%"


# ---------------------------------------------------------------------------
# ATR TABANI (2026-11-10 çakışma düzeltmesi)
# ---------------------------------------------------------------------------
# `AUTO_PAPER_SL_PCT`=%5 kararı 30 gün / 3.214 bildirimlik gerçek replay'le
# alınmış ("sıkı stop 5 dk gürültüsünde kesiliyor"). R:R tavanı (%64) SL'yi
# ~%1,3'e indirip bu kararı TAMAMEN eziyordu -> eski "sıkı stop" hatası geri
# gelirdi. Taban: daraltma, ATR'nin 0,75 katının altına inemez.


def test_atr_floor_prevents_over_tightening():
    """ATR tabanı varsa SL tabanın altına inmemeli."""
    sl, _tp = _sl(2.0, 5.0, 0.64, atr_floor=0.015)   # naif sınır 1.28
    assert abs(sl - 0.015) < 1e-9, f"taban korunmadı: {sl}"


def test_atr_floor_never_widens():
    """Taban, mevcut SL'yi GENİŞLETMEZ (yalnız daraltmayı sınırlar)."""
    sl, _tp = _sl(2.0, 1.0, 0.64, atr_floor=0.03)   # taban 3% > SL 1%
    assert abs(sl - 0.01) < 1e-9, "taban SL'yi genişletti"


def test_no_floor_means_old_behavior():
    """Taban yoksa eski davranış (naif R:R sınırı)."""
    sl, _tp = _sl(2.0, 5.0, 0.64)
    assert abs(sl - 0.0128) < 1e-9


def test_plan_uses_atr_floor():
    """`_calc_exit_plan` ATR tabanını gerçekten geçirmeli (kaynak kontrolü)."""
    src = inspect.getsource(ap._calc_exit_plan)
    assert "atr_floor_pct" in src, "ATR tabanı plana bağlanmamış"
    assert "atr_floor_pct=atr_floor_pct" in src, "taban çağrıya geçmiyor"


def test_sl_scales_with_atr_end_to_end():
    """Uçtan uca: ATR arttıkça SL genişlemeli (sabit kalmamalı)."""
    base = asyncio.run(ap.get_default_settings())
    vals = []
    for atr in (2.0, 3.0, 4.5):
        notif = {"symbol": "XTRY", "score": 80.0, "mode": "trend_devam",
                 "source": "velocity", "atr_pct": atr, "price": 50.5, "target_pct": 2.0}
        plan, _b = asyncio.run(ap._calc_exit_plan("XTRY", notif, 50.5, base, 1000.0))
        vals.append((plan["fill_entry"] - plan["stop_loss_price"]) / plan["fill_entry"] * 100)
    assert vals[0] < vals[1] < vals[2], f"SL ATR ile ölçeklenmiyor: {vals}"


def test_min_atr_and_max_target_defaults_active():
    """Ölçülmüş varsayılanlar aktif olmalı (replay kanıtı)."""
    d = asyncio.run(ap.get_default_settings())
    assert d["min_atr_pct"] == 1.0, "ATR filtresi kapalı"
    assert d["max_target_pct"] == 2.0, "TP tavanı ayarlanmamış"
