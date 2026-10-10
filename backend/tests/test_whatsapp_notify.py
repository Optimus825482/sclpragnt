"""WhatsApp bildirim modülü testleri (2026-10-10).

Kapsam:
- Yapılandırma yoksa `send_whatsapp` fail-safe (False, hata fırlatmaz).
- `format_scan_report` boş liste + sıralama (both üstte, potansiyel'e göre).
- Config varsayılanı KAPALI.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import config  # noqa: E402
from app import whatsapp_notify as wn  # noqa: E402


def test_whatsapp_default_off():
    assert config.config.WHATSAPP_NOTIFY_ENABLED is False


def test_whatsapp_disabled_is_noop():
    """Yapılandırma yoksa gönderim sessizce başarısız olmalı (hata fırlatmaz)."""
    import asyncio
    assert wn.whatsapp_enabled() is False
    assert asyncio.run(wn.send_whatsapp("test")) is False


def test_format_empty():
    out = wn.format_scan_report([])
    assert "aday bulunamadı" in out.lower()


def test_format_orders_both_first():
    rows = [
        {"symbol": "AAATRY", "price": 1.0, "ceiling_pct": 5, "potential_pct": 10, "strategy": "short_squeeze"},
        {"symbol": "BBBTRY", "price": 2.0, "ceiling_pct": 5, "potential_pct": 20, "strategy": "both"},
        {"symbol": "CCCTRY", "price": 3.0, "ceiling_pct": 5, "potential_pct": 90, "strategy": "daily_momentum"},
    ]
    out = wn.format_scan_report(rows)
    # 'both' en üstte olmalı (BBB), sonra potansiyele göre CCC, sonra AAA
    assert out.index("BBB") < out.index("CCC") < out.index("AAA")


def test_format_contains_values():
    out = wn.format_scan_report([
        {"symbol": "MINATRY", "price": 4.68, "ceiling_pct": 3.8, "potential_pct": 81, "strategy": "both"}])
    assert "MINA" in out            # TRY eki kaldırıldı
    assert "+%81" in out            # potansiyel
    assert "+%4" in out             # hedef (round 3.8 -> 4)
    assert "```" in out             # monospace tablo


def test_tracking_table_empty():
    out = wn.format_tracking_table([])
    assert "aday yok" in out.lower()


def test_tracking_table_sorted_desc():
    rows = [
        {"symbol": "AAA", "entry_price": 1.0, "current_price": 0.98, "change_pct": -2.0},
        {"symbol": "BBB", "entry_price": 1.0, "current_price": 1.10, "change_pct": 10.0},
        {"symbol": "CCC", "entry_price": 1.0, "current_price": 1.05, "change_pct": 5.0},
    ]
    out = wn.format_tracking_table(rows)
    # en iyi (BBB +%10) en üstte, sonra CCC, sonra AAA
    assert out.index("BBB") < out.index("CCC") < out.index("AAA")
    assert "```" in out  # monospace blok


def test_hourly_default_off():
    assert config.config.WHATSAPP_HOURLY_ENABLED is False


def test_hourly_interval_default_30():
    """Kullanıcı kararı (2026-10-10): gönderim aralığı 30 dk."""
    assert config.config.WHATSAPP_HOURLY_INTERVAL_MIN == 30


def test_tracking_table_has_summary_and_no_try_suffix():
    """Tablo: sembolden TRY eki kaldırılır + özet satırı olur."""
    out = wn.format_tracking_table([
        {"symbol": "MAGICTRY", "entry_price": 5.0, "current_price": 5.2, "change_pct": 4.0},
        {"symbol": "MINATRY", "entry_price": 4.0, "current_price": 3.9, "change_pct": -2.5},
    ])
    assert "MAGIC" in out and "MAGICTRY" not in out   # TRY eki kaldırıldı
    assert "yükselen" in out and "düşen" in out        # özet satırı
    assert "```" in out                                 # monospace blok


def test_scan_report_emoji_legend_and_no_emoji_in_rows():
    """Emoji YALNIZCA açıklama satırında + strateji etiketinde; veri satırlarında yok.

    Emoji genişliği monospace'te sabit olmadığı için rakam sütunlarını bozar;
    bu yüzden veri satırlarında emoji bulunmamalı (etiket sonda).
    """
    out = wn.format_scan_report([
        {"symbol": "MINATRY", "price": 4.68, "ceiling_pct": 3.8,
         "potential_pct": 81, "strategy": "both"},
    ])
    assert "🎯" in out and "🚀" in out          # emoji açıklama satırı var
    # veri satırı: emoji yok, yalnız sondaki strateji etiketi
    data_line = next(ln for ln in out.splitlines() if ln.startswith("MINA"))
    assert "🎯" not in data_line and "🚀" not in data_line and "🪙" not in data_line
    assert data_line.rstrip().endswith("📈")    # strateji etiketi en sonda


def test_tracking_table_emoji_legend_present():
    """Takip tablosu: emoji açıklama satırı olmalı, veri satırlarında emoji olmamalı."""
    out = wn.format_tracking_table([
        {"symbol": "MAGIC", "entry_price": 5.0, "current_price": 5.2, "change_pct": 4.0},
    ])
    assert "🪙" in out and "💵" in out and "📈" in out   # açıklama (başlık) satırı
    data_line = next(ln for ln in out.splitlines() if ln.startswith("MAGIC"))
    assert "🪙" not in data_line and "💵" not in data_line and "📈" not in data_line


def test_tracking_table_top5_and_avg_vs_1130():
    """Kullanıcı isteği: takip tablosu raporla AYNI ilk 5'i gösterir ve en altta
    bu 5'in 11:30'a göre ortalama % değişimi yazılır."""
    rows = [
        {"symbol": f"C{i}TRY", "entry_price": 1.0, "current_price": 1.0 + i * 0.01,
         "change_pct": float(i), "potential_pct": 90 - i, "target_probability": 60,
         "strategy": "daily_momentum"}
        for i in range(8)
    ]
    out = wn.format_tracking_table(rows)
    data_rows = [ln for ln in out.splitlines() if ln.startswith("C") and "%" in ln]
    assert len(data_rows) == 5                     # yalnızca ilk 5 (rapordaki gibi)
    assert "11:30'a göre ort. değişimi" in out     # ortalama değişim satırı
    assert "```" in out


def test_tracking_table_same_selection_as_report():
    """Aynı aday kümesi → raporda ve takip tablosunda aynı ilk 5 sembol."""
    cands = [
        {"symbol": "AAATRY", "price": 1.0, "ceiling_pct": 3, "potential_pct": 200,
         "target_probability": 10, "strategy": "daily_momentum"},   # puan 20
        {"symbol": "BBBTRY", "price": 2.0, "ceiling_pct": 4, "potential_pct": 90,
         "target_probability": 80, "strategy": "daily_momentum"},   # puan 72
        {"symbol": "CCCTRY", "price": 3.0, "ceiling_pct": 5, "potential_pct": 50,
         "target_probability": 60, "strategy": "short_squeeze"},    # puan 30
    ]
    rep = wn.format_scan_report(cands)
    track = wn.format_tracking_table([
        {"symbol": c["symbol"], "entry_price": c["price"], "current_price": c["price"],
         "change_pct": 0.0, "potential_pct": c["potential_pct"],
         "target_probability": c["target_probability"], "strategy": c["strategy"]}
        for c in cands
    ])
    order_rep = [s for s in ("AAA", "BBB", "CCC") if s in rep]
    order_rep.sort(key=rep.index)
    order_trk = [s for s in ("AAA", "BBB", "CCC") if s in track]
    order_trk.sort(key=track.index)
    assert order_rep == order_trk == ["BBB", "CCC", "AAA"]


def test_select_top_shared_criterion():
    """`select_top` tek ölçüt: 'both' önce, sonra ihtimal×potansiyel; ilk n."""
    rows = [
        {"symbol": "A", "potential_pct": 200, "target_probability": 10},   # 20
        {"symbol": "B", "potential_pct": 90, "target_probability": 80},    # 72
        {"symbol": "C", "potential_pct": 50, "target_probability": 60},    # 30
        {"symbol": "D", "potential_pct": 100, "target_probability": 50,
         "strategy": "both"},                                              # both önde
        {"symbol": "E", "potential_pct": 10, "target_probability": 50},    # 5
    ]
    top = wn.select_top(rows, 3)
    assert [c["symbol"] for c in top] == ["D", "B", "C"]
    assert wn.select_top(rows, 5)[0]["symbol"] == "D"


def test_scan_report_limits_to_top5_and_avg_line():
    """Kullanıcı kararı: ilk 5 sembol + altında ortalama yükselme beklentisi."""
    rows = [{"symbol": f"C{i}TRY", "price": 1.0 + i, "ceiling_pct": 3.0 + i,
             "potential_pct": 90 - i, "strategy": "daily_momentum"} for i in range(10)]
    out = wn.format_scan_report(rows)
    data_rows = [ln for ln in out.splitlines() if ln.startswith("C") and "%" in ln]
    assert len(data_rows) == 5                     # yalnızca ilk 5
    assert "ort. potansiyel" in out and "ort. hedef" in out   # ortalama satırı
    assert "```" in out


def test_scan_report_shows_probability_and_sorted_by_score():
    """İhtimal kolonu gösterilir; sıralama ihtimal×potansiyel birleşik puanına göre."""
    rows = [
        # yüksek potansiyel ama düşük ihtimal -> düşük puan
        {"symbol": "LOWPTRY", "price": 1.0, "ceiling_pct": 9, "potential_pct": 200,
         "target_probability": 10, "strategy": "daily_momentum"},
        # orta potansiyel ama yüksek ihtimal -> en yüksek puan (80*90/100=72)
        {"symbol": "TOPTRY", "price": 2.0, "ceiling_pct": 4, "potential_pct": 90,
         "target_probability": 80, "strategy": "daily_momentum"},
    ]
    out = wn.format_scan_report(rows)
    assert "%80" in out and "%10" in out            # ihtimal kolonu
    assert "🎲" in out                              # emoji açıklamasında ihtimal ikonu
    assert out.index("TOP") < out.index("LOWP")     # birleşik puana göre TOP önde
    assert "ort. ihtimal" in out
