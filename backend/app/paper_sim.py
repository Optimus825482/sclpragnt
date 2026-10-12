"""KAĞIT ÇIKIŞ SİMÜLASYONU (2026-10-12).

NEDEN BU MODÜL VAR:
    "Gönderilen Listeler — Ortalama Yükselme" tablosundaki **Gerçekleşen %**
    bir MFE'dir (listeye girdikten sonra ulaşılan EN YÜKSEK nokta,
    `database.evaluate_daily_rising_report`). MFE YAPISAL OLARAK İYİMSERDİR:
    "tepeyi tam sat" varsayımıdır ve 24 saate kadar ölçülebilir. Otonom paper
    (`app/combined_paper.py`) ise gerçek çıkış kurallarıyla işlem yapar (stop /
    kâr kilidi-trailing / trailing'de TP iptali / kârsız-süre / maks-tutma) ve
    komisyon + kayma öder; 120 dk sonra kapanır. İkisi YAN YANA konunca liste
    "+%30" derken portföy ekside görünebilir — çünkü aynı şeyi ölçmezler.

    Bu modül BİR LİSTENİN adaylarını otonom paper'ın **GERÇEK** kurallarıyla aynı
    5m mumlar üzerinde yeniden oynatır ve "gerçekleşebilir %" üretir. Böylece
    iyimser MFE'nin yanında dürüst bir sayı olur; ayar kararları bu sayıya dayanır.

TASARIM:
    * Saf fonksiyonlar; DB/ağ/global durum YOK → birim testle kilitlenebilir.
    * `tp_pct_for` TEK KAYNAK: `combined_paper._plan_entry` de bunu kullanır →
      simülasyon ile canlı paper'ın TP geometrisi AYRIŞAMAZ.
    * Bar-içi belirsizlik (aynı mumda hem TP hem SL görülmesi) KÖTÜMSER çözülür:
      stop önce kabul edilir → "gerçekleşebilir %" bir taban (floor) olur, tavan
      değil. Bu proje geçmişte iyimser sayılarla yanıldı; burada bilinçli tersi.
"""
from __future__ import annotations

_5M_SEC = 300.0


def tp_pct_for(potential, base: float = 3.0) -> float:
    """Adayın yükselme potansiyelinden otonom paper TP%'sini türet.

    KURAL (`combined_paper._plan_entry` ile BİREBİR aynı olmalı):
      * taban = `base` (%3.0),
      * potansiyel >= %6 ise potansiyelin YARISI (trend sürsün diye erken kapatma),
      * potansiyel < %6 ise potansiyelin %80'i,
      * hiçbiri potansiyelin kendisini aşmaz.
    """
    try:
        pot = float(potential)
    except (TypeError, ValueError):
        pot = None
    if not pot or pot <= 0:
        return float(base)
    inner = pot * 0.5 if pot >= 6.0 else pot * 0.8
    return round(max(float(base), min(pot, inner)), 2)


def _finish(exit_price: float, reason: str, entry: float,
            commission_pct: float, slippage_pct: float) -> dict:
    """`combined_paper.close_combined_paper_trade` ile AYNI net% formülü.

    pnl% = (fill/entry - 1) - (1 + fill/entry)·komisyon ; fill = exit·(1-kayma).
    """
    fill = exit_price * (1.0 - slippage_pct)
    net_pct = ((fill / entry - 1.0) - (1.0 + fill / entry) * commission_pct) * 100.0
    return {"sim_pct": round(net_pct, 2), "reason": reason,
            "exit_price": round(fill, 10)}


def simulate_exit(bars, entry: float, *, entry_time: float = 0.0,
                  tp_pct: float = 3.0, sl_pct: float = 3.0,
                  trail_trigger_pct: float = 2.0, trail_gap_pct: float = 1.0,
                  cancel_tp_on_trail: bool = True, no_profit_min: float = 30.0,
                  max_hold_min: float = 120.0, commission_pct: float = 0.0015,
                  slippage_pct: float = 0.0) -> dict:
    """Adayı otonom paper kurallarıyla mum-mum oynat; gerçekleşebilir net% ver.

    `bars`: ARTAN zaman sıralı, her biri {"open_time": sn, "high","low","close"}.
    `entry_time`: pozisyonun açıldığı epoch (sn) — süre kuralları buna göre.
    Dönen: {"sim_pct": float|None, "reason": str, "exit_price": float|None}.
    Çıkış olmazsa (pozisyon hâlâ açık) son kapanışa göre işaretlenir (`reason="open"`).
    """
    try:
        entry = float(entry)
    except (TypeError, ValueError):
        entry = 0.0
    if entry <= 0 or not bars:
        return {"sim_pct": None, "reason": "no_data", "exit_price": None}

    tp_price = entry * (1.0 + tp_pct / 100.0) if tp_pct and tp_pct > 0 else None
    base_sl = entry * (1.0 - sl_pct / 100.0) if sl_pct and sl_pct > 0 else None
    # Kâr kilidi tabanı: gidiş-dönüş komisyon + pay (net pozitif) — canlı ile aynı.
    cost_floor = entry * (1.0 + 2.0 * commission_pct + 0.002)

    peak = entry
    trailing_active = False
    trailing_stop = 0.0
    last_close = entry

    for b in bars:
        try:
            high = float(b.get("high") or 0.0)
            low = float(b.get("low") or 0.0)
            close = float(b.get("close") or 0.0)
        except (TypeError, ValueError):
            continue
        if high <= 0 or close <= 0:
            continue
        last_close = close
        bar_open = float(b.get("open_time") or 0.0)
        # Mum kapanış zamanı (5m) — süre kuralları için.
        bar_close_t = bar_open + _5M_SEC if bar_open > 0 else 0.0
        hold_min = ((bar_close_t - entry_time) / 60.0) if (entry_time > 0 and bar_close_t > 0) else 0.0

        # 1) Tepe + kâr kilidi/trailing (canlı mantığın aynısı).
        if high > peak:
            peak = high
        peak_gain_pct = (peak / entry - 1.0) * 100.0
        if trail_trigger_pct > 0 and peak_gain_pct >= trail_trigger_pct:
            trail_price = max(peak * (1.0 - trail_gap_pct / 100.0), cost_floor)
            # İlk aktivasyonda stop fiyatın ALTINDA kalmalı (anında kapanma yok).
            if not trailing_active and trail_price >= close:
                trail_price = close * (1.0 - min(trail_gap_pct, 1.0) / 100.0)
            trailing_active = True
            trailing_stop = max(trailing_stop, trail_price)

        eff_stop = base_sl
        if trailing_active:
            eff_stop = max(eff_stop or 0.0, trailing_stop) if eff_stop else trailing_stop

        # 2) STOP (kötümser: bar içinde stop, TP'den ÖNCE kabul edilir).
        if eff_stop is not None and low <= eff_stop:
            reason = "trailing_stop" if trailing_active else "stop_loss"
            return _finish(eff_stop, reason, entry, commission_pct, slippage_pct)

        # 3) TP — trailing aktifken iptal (kullanıcı kararı 2026-10-12).
        if tp_price is not None and high >= tp_price and not (cancel_tp_on_trail and trailing_active):
            return _finish(tp_price, "take_profit", entry, commission_pct, slippage_pct)

        # 4) Kârsız süre doldu: kâra geçmediyse (peak<=entry) kapat.
        if no_profit_min > 0 and hold_min >= no_profit_min and peak <= entry:
            return _finish(close, "no_profit_timeout", entry, commission_pct, slippage_pct)

        # 5) Maks tutma süresi doldu.
        if max_hold_min > 0 and hold_min >= max_hold_min:
            return _finish(close, "max_duration", entry, commission_pct, slippage_pct)

    # Hiçbir çıkış tetiklenmedi → son kapanışa göre işaretle (pozisyon hâlâ açık).
    return _finish(last_close, "open", entry, commission_pct, slippage_pct)
