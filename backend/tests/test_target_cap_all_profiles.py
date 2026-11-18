"""§30 — max_target_pct TÜM profillere uygulanır (2026-11-18).

CANLI HATA: `max_target_pct=2.0` panelde ayarlıydı ama canlıda plan profiline
HİÇ uygulanmıyordu. Sebep `_exit_resolve_target` içindeki muafiyet:

    if plan_exit is not None:
        target_pct = plan_exit["target_pct"]      # plan hedefi tavanı EZİYORDU

Canlı kanıt: `plan` profili 232 işlemde TP ort +3,58% — tavan 2,0% olmasına
rağmen. Bu, `max_sl_tp_ratio` için düzelttiğimiz P0'ın AYNI hata sınıfı
(dokümante panel parametresi canlıda no-op).

ÖLÇÜM (düzeltilmiş bar replay, 1.798 canlı işlem, maliyet 0,275% dahil):
  ratio=0,40  tavan YOK   ort -0,421%  med -1,475%  kaz %26,6
  ratio=0,40  TP<=2,0%    ort -0,325%  med -1,075%  kaz %27,0   (+0,096 puan)
  ratio=0,40  TP<=1,5%    ort -0,300%  med -0,875%  kaz %27,5   (+0,121 puan)

Not: tavan TP'yi kısaltınca `max_sl_tp_ratio` SL'yi de orantılı daraltır
(SL = TP*ratio), yani R:R korunur — işlem sadece daha küçük hareketi hedefler.
"""
import asyncio
from app.routers import auto_paper as ap


def _resolve(target_pct, plan_exit=None, max_target=2.0):
    return ap._exit_resolve_target(
        "XTRY", {}, target_pct, {"max_target_pct": max_target}, plan_exit)


def test_plain_target_is_capped():
    """Plan yokken tavan çalışır (eski davranış korunur)."""
    assert _resolve(5.0) == 2.0


def test_plan_target_is_now_capped():
    """P0: plan hedefi artık tavana tabi (muafiyet kaldırıldı)."""
    got = _resolve(5.0, plan_exit={"target_pct": 3.58})
    assert got == 2.0, f"plan hedefi {got} — tavan 2.0 uygulanmadı (P0 geri gelmiş)"


def test_plan_target_below_cap_untouched():
    """Tavanın altındaki plan hedefi DEĞİŞMEZ (asla genişletmez)."""
    assert _resolve(5.0, plan_exit={"target_pct": 1.2}) == 1.2


def test_plan_cap_matches_live_measured_geometry():
    """Canlı plan TP'si +3,58% idi -> tavanla 2,0% olmalı."""
    assert _resolve(5.0, plan_exit={"target_pct": 3.58}) == 2.0


def test_zero_means_unlimited_for_plan():
    """0 = sınırsız: plan hedefi korunur."""
    assert _resolve(5.0, plan_exit={"target_pct": 9.9}, max_target=0.0) == 9.9


def test_tp2_runner_still_plan_exempt():
    """TP2 runner yalnız plan YOKKEN devreye girer (mevcut davranış)."""
    got = ap._exit_resolve_target(
        "XTRY", {"tp2_runner_pct": 4.5}, 1.0, {"max_target_pct": 2.0}, None)
    assert got == 2.0          # 4.5 runner alındı ama tavan 2.0'a çekti
    got2 = ap._exit_resolve_target(
        "XTRY", {"tp2_runner_pct": 4.5}, 1.0, {"max_target_pct": 2.0},
        {"target_pct": 1.5})
    assert got2 == 1.5         # plan varsa runner yok sayılır


def test_default_max_target_is_measured():
    """Varsayılan 2.0 olmalı — ölçülmüş tavan."""
    d = asyncio.run(ap.get_default_settings())
    assert d["max_target_pct"] == 2.0
