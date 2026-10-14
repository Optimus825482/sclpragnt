"""KAĞIT ÇIKIŞ SİMÜLASYONU testleri (2026-10-12).

Kapsam: `app/paper_sim.py` — raporlardaki "gerçekleşebilir %" sütununun motoru.
Neden kritik: bu simülasyon MFE'nin (iyimser zirve) yanına DÜRÜST sayıyı koyar;
geometrisi otonom paper ile AYNI olmalı, yoksa yanıltıcı olur.

Kilitlenen davranışlar:
- `tp_pct_for` `combined_paper._plan_entry` ile BİREBİR aynı (parite).
- TP: taban %3, potansiyel<6 → %80, ≥6 → yarısı, potansiyeli aşmaz.
- Bar-içi belirsizlik KÖTÜMSER: stop, TP'den önce kabul edilir.
- Trailing aktifken sabit TP iptal edilir (kullanıcı kararı 2026-10-12).
- Kârsız süre doldu yalnız kâra GEÇMEMİŞSE (peak<=entry) kapatır.
- Net% komisyon & kayma dahil; `close_combined_paper_trade` ile aynı formül.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import paper_sim  # noqa: E402


def _bar(ot, h, l, c):
    return {"open_time": float(ot), "high": float(h), "low": float(l), "close": float(c)}


# ---------------------------------------------------------------------------
# tp_pct_for — parite
# ---------------------------------------------------------------------------
def test_tp_pct_for_matches_plan_entry_formula():
    from app.combined_paper import _plan_entry
    cash = 1000.0
    for pot in (None, 0, 1.0, 3.0, 5.9, 6.0, 9.0, 20.0):
        cand = {"symbol": "XTRY", "price": 10.0, "potential_pct": pot}
        plan = _plan_entry(cand, cash)
        assert plan is not None
        assert plan["tp_pct"] == paper_sim.tp_pct_for(pot, 3.0), f"pot={pot}"


def test_tp_pct_for_rules():
    assert paper_sim.tp_pct_for(None) == 3.0        # potansiyel yok → taban
    assert paper_sim.tp_pct_for(2.0) == 3.0         # 2*0.8=1.6 < taban → taban
    assert paper_sim.tp_pct_for(5.0) == 4.0         # 5*0.8 = 4.0
    assert paper_sim.tp_pct_for(6.0) == 3.0         # 6*0.5 = 3.0 (tabanla eşit)
    assert paper_sim.tp_pct_for(10.0) == 5.0        # yarısı
    assert paper_sim.tp_pct_for(4.0) == 3.2         # 4*0.8 = 3.2 > taban


# ---------------------------------------------------------------------------
# simulate_exit — çıkış kuralları
# ---------------------------------------------------------------------------
def test_stop_loss_hit():
    bars = [_bar(0, 100.0, 96.0, 97.0)]  # entry 100, %3 stop = 97 → dibi 96
    r = paper_sim.simulate_exit(bars, 100.0, sl_pct=3.0, commission_pct=0.0)
    assert r["reason"] == "stop_loss"
    assert r["sim_pct"] == -3.0


def test_take_profit_hit_when_no_trailing():
    # trigger %2'ye ULAŞMAYAN bir yükseliş (peak %1.5) → trailing yok → TP çalışır.
    bars = [_bar(0, 103.5, 100.0, 103.0)]  # peak %3.5 aslında trigger'ı geçer...
    # Trigger'ı çok yükseğe al ki trailing devreye girmesin.
    r = paper_sim.simulate_exit(bars, 100.0, tp_pct=3.0, trail_trigger_pct=50.0,
                                commission_pct=0.0)
    assert r["reason"] == "take_profit"
    assert r["sim_pct"] == 3.0


def test_pessimistic_stop_wins_over_tp_in_same_bar():
    # Tek mum hem TP (%3 → 103) hem stop (%3 → 97) seviyesini görüyor.
    bars = [_bar(0, 103.0, 97.0, 100.0)]
    r = paper_sim.simulate_exit(bars, 100.0, tp_pct=3.0, sl_pct=3.0,
                                trail_trigger_pct=50.0, commission_pct=0.0)
    assert r["reason"] == "stop_loss", "bar-içi belirsizlikte stop önce kabul edilmeli"
    assert r["sim_pct"] == -3.0


def test_trailing_locks_profit_and_cancels_tp():
    # %3 yüksel (peak 103 → trigger geçti, trailing aktif) sonra %1 geri çekil.
    bars = [
        _bar(0, 103.0, 101.0, 103.0),   # trailing aktif, stop ~101.9
        _bar(300, 103.2, 101.5, 101.6), # >%1 tepe'den geri → trailing stop
    ]
    r = paper_sim.simulate_exit(bars, 100.0, tp_pct=3.0, sl_pct=3.0,
                                trail_trigger_pct=2.0, trail_gap_pct=1.0,
                                cancel_tp_on_trail=True, commission_pct=0.0)
    assert r["reason"] == "trailing_stop"
    assert r["sim_pct"] > 0, "trailing kârı kilitlemeli (pozitif)"


def test_no_profit_timeout_only_after_no_gain():
    # 40 dk hiç kâra geçmeyen (peak<=entry) pozisyon → kârsız süre doldu.
    bars = [_bar(i * 300, 100.0, 98.0, 99.0) for i in range(1, 10)]
    r = paper_sim.simulate_exit(bars, 100.0, entry_time=100.0, no_profit_min=30.0,
                                max_hold_min=120.0, sl_pct=50.0, trail_trigger_pct=50.0,
                                commission_pct=0.0)
    assert r["reason"] == "no_profit_timeout"
    assert r["sim_pct"] < 0


def test_no_profit_timeout_skipped_if_was_in_profit():
    # Bir an kâra geçti (peak 102) ama sonra 100'e döndü → kârsız kural UYGULANMAZ.
    bars = [_bar(0, 102.0, 99.5, 100.0)] + \
           [_bar(i * 300, 100.2, 99.8, 100.0) for i in range(1, 30)]
    r = paper_sim.simulate_exit(bars, 100.0, entry_time=1.0, no_profit_min=30.0,
                                max_hold_min=120.0, sl_pct=50.0, trail_trigger_pct=50.0,
                                commission_pct=0.0)
    assert r["reason"] == "max_duration"


def test_max_duration_close():
    bars = [_bar(i * 300, 100.4, 99.6, 100.1) for i in range(1, 30)]
    r = paper_sim.simulate_exit(bars, 100.0, entry_time=1.0, max_hold_min=60.0,
                                no_profit_min=0.0, sl_pct=50.0, trail_trigger_pct=50.0,
                                commission_pct=0.0)
    assert r["reason"] == "max_duration"


def test_open_marked_at_last_close():
    bars = [_bar(0, 100.5, 99.9, 100.3)]
    r = paper_sim.simulate_exit(bars, 100.0, no_profit_min=0.0, max_hold_min=0.0,
                                sl_pct=50.0, trail_trigger_pct=50.0, commission_pct=0.0)
    assert r["reason"] == "open"
    assert r["sim_pct"] == 0.3


def test_commission_and_slippage_reduce_net():
    bars = [_bar(0, 103.0, 100.0, 103.0)]
    gross = paper_sim.simulate_exit(bars, 100.0, tp_pct=3.0, trail_trigger_pct=50.0,
                                    commission_pct=0.0, slippage_pct=0.0)
    net = paper_sim.simulate_exit(bars, 100.0, tp_pct=3.0, trail_trigger_pct=50.0,
                                  commission_pct=0.0015, slippage_pct=0.00025)
    assert net["sim_pct"] < gross["sim_pct"], "komisyon/kayma net%'yi düşürmeli"


def test_no_data_and_bad_entry():
    assert paper_sim.simulate_exit([], 100.0)["reason"] == "no_data"
    assert paper_sim.simulate_exit([_bar(0, 101, 99, 100)], 0)["sim_pct"] is None


def test_net_formula_matches_close_trade():
    """Komisyon düşülmüş formül `close_combined_paper_trade` ile aynı olmalı."""
    entry, exit_px = 100.0, 105.0
    comm, slip = 0.0015, 0.00025
    fill = exit_px * (1 - slip)
    expected = ((fill / entry - 1) - (1 + fill / entry) * comm) * 100
    bars = [_bar(0, 105.0, 100.0, 105.0)]
    r = paper_sim.simulate_exit(bars, entry, tp_pct=5.0, trail_trigger_pct=50.0,
                                commission_pct=comm, slippage_pct=slip)
    assert abs(r["sim_pct"] - round(expected, 2)) < 0.011
