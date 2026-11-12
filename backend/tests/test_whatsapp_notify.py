"""WhatsApp köprü testleri (2026-10-11 — KOMBİNE tek kanal).

Kapsam:
- Config: WhatsApp varsayılan KAPALI; yapılandırılmadıkça gönderim no-op.
- `send_whatsapp` yapılandırma yoksa False (fail-safe).
- Yeni formatlayıcılar: `format_combined_list` / `format_combined_status`.
- Paylaşılan sıralama ölçütü `select_top` + `_combined_score` (state sayfası da kullanır).
- Eski formatlayıcılar (format_scan_report / format_tracking_table /
  format_delta_report) KALDIRILDI (tek kanal ilkesi).
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
    import asyncio
    assert wn.whatsapp_enabled() is False
    assert asyncio.run(wn.send_whatsapp("test")) is False


def test_legacy_formatters_removed():
    """Tek kanal: eski formatlayıcılar kaldırıldı."""
    for gone in ("format_scan_report", "format_tracking_table", "format_delta_report"):
        assert not hasattr(wn, gone), f"eski formatlayıcı hâlâ var: {gone}"


def test_combined_list_empty_and_fields():
    assert "aday bulunamadı" in wn.format_combined_list([])
    rows = [{
        "symbol": "OGNTRY", "price": 0.1023, "target_probability": 62.0,
        "ceiling_pct": 4.0, "potential_pct": 18.0, "scan_score": 74.3,
    }]
    out = wn.format_combined_list(rows, n=3)
    assert "OGN" in out and "%62" in out and "+%4" in out and "+%18" in out
    assert "İHTİMAL" in out and "PUAN" in out


def test_combined_list_footer_averages():
    """Kullanıcı isteği (2026-10-11): alt satırda puan açıklaması yerine yükselme
    miktarı (hedef) ortalaması + potansiyel ortalaması yazılır."""
    rows = [
        {"symbol": "AAATRY", "price": 1, "ceiling_pct": 4.0, "potential_pct": 10.0, "scan_score": 80},
        {"symbol": "BBBTRY", "price": 1, "ceiling_pct": 6.0, "potential_pct": 20.0, "scan_score": 70},
    ]
    out = wn.format_combined_list(rows, n=3)
    assert "ort. yükselme miktarı +%5.0" in out     # (4+6)/2
    assert "ort. potansiyel +%15.0" in out          # (10+20)/2
    assert "Puan = sinyal gücü" not in out          # eski açıklama KALDIRILDI


def test_combined_list_limits_top_n():
    """n=3 → en yüksek puanlı 3 aday seçilir (sıralama puana göre)."""
    rows = [{"symbol": f"S{i}TRY", "price": i + 1, "scan_score": 50 - i} for i in range(6)]
    out = wn.format_combined_list(rows, n=3)
    # Puanlar 50,49,48,47,46,45 → en yüksek 3: S0,S1,S2.
    assert "S0" in out and "S1" in out and "S2" in out
    assert "S3" not in out


def test_combined_list_sorts_by_score_desc():
    """Kullanıcı isteği (2026-10-11): liste PUANA GÖRE sıralı — en yüksek üstte.
    Girdi KARIŞIK sırada verilse bile çıktı puana göre azalan olmalı."""
    rows = [
        {"symbol": "LOWTRY", "price": 1.0, "scan_score": 20},
        {"symbol": "HIGHTRY", "price": 1.0, "scan_score": 90},
        {"symbol": "MIDTRY", "price": 1.0, "scan_score": 55},
    ]
    out = wn.format_combined_list(rows, n=3)
    assert out.index("HIGH") < out.index("MID") < out.index("LOW")


def test_combined_status_avg_line():
    rows = [
        {"symbol": "AAATRY", "entry_price": 1.0, "current_price": 1.02, "change_pct": 2.0},
        {"symbol": "BBBTRY", "entry_price": 1.0, "current_price": 0.96, "change_pct": -4.0},
    ]
    out = wn.format_combined_status(rows, title="T", baseline_label="12:00")
    assert "ORT. DEĞİŞİM" in out
    assert "-1.00%" in out        # (2.0 - 4.0)/2


def test_select_top_shared_criterion():
    """`select_top` tek ölçüt: 'both' önce, sonra ihtimal×potansiyel; ilk n."""
    rows = [
        {"symbol": "A", "strategy": "daily_momentum", "potential_pct": 10, "target_probability": 50},
        {"symbol": "B", "strategy": "daily_momentum", "potential_pct": 20, "target_probability": 60},
        {"symbol": "D", "strategy": "both", "potential_pct": 5, "target_probability": 30},
    ]
    top = wn.select_top(rows, 3)
    assert top[0]["symbol"] == "D"           # 'both' önce
    assert wn.select_top(rows, 2)[0]["symbol"] == "D"


def test_combined_score_formula():
    assert wn._combined_score({"potential_pct": 20.0, "target_probability": 60.0}) == 12.0
    # ihtimal yoksa nötr taban %50
    assert wn._combined_score({"potential_pct": 10.0}) == 5.0


def test_send_skips_when_url_empty_but_flag_enabled(monkeypatch):
    """Regresyon (2026-11-10): köprü servisi kaldırıldı ama bayrak açık kaldıysa
    `url` boş kalır; `f"{url}/send"` -> "/send" olup urllib'in DNS çözümlemesi
    "Temporary failure in name resolution" üretiyordu (her turda log + deneme).

    Beklenen: hiç ağ denemesi yapılmadan False dönmek.
    """
    import asyncio

    monkeypatch.delenv("WHATSAPP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("WHATSAPP_GROUP_ID", raising=False)
    monkeypatch.setenv("WHATSAPP_NOTIFY_ENABLED", "true")

    calls: list[str] = []

    def _boom(url, payload, headers):  # noqa: ANN001
        calls.append(url)
        raise AssertionError("boş URL ile ağ isteği denenmemeliydi")

    monkeypatch.setattr(wn, "_post_sync", _boom)

    async def _run():
        # Hem genel gönderim hem numaraya gönderim aynı gövdeyi kullanır.
        return (await wn.send_whatsapp("metin"),
                await wn.send_whatsapp_to_number("metin", "905551112233"))

    assert asyncio.run(_run()) == (False, False)
    assert calls == [], f"beklenmeyen ağ denemesi: {calls}"


def test_send_skips_when_url_missing_via_underscore(monkeypatch):
    """`_send_whatsapp` doğrudan çağrıldığında da boş URL korumalı olmalı."""
    import asyncio

    monkeypatch.delenv("WHATSAPP_BRIDGE_URL", raising=False)
    monkeypatch.setenv("WHATSAPP_NOTIFY_ENABLED", "true")
    monkeypatch.setattr(wn, "_post_sync", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("ağ isteği olmamalı")))
    assert asyncio.run(wn._send_whatsapp(to="905551112233@s.whatsapp.net", text="x")) is False
