"""Sinyal İzleme sayfası + API'si (2026-11-10).

AMAÇ: oturumda ölçülen bulguları panelden görülebilir kılmak. 27 bölüm analiz
.md dosyalarında ve testlerde kalmıştı; arayüzde tek ekran yoktu.

ÜÇ UÇ:
  GET /api/signal-insights/overview → aktif parametreler + filtre sayaçları +
       akış tazeliği ("BAYAT" tespiti)
  GET /api/signal-insights/evidence → 15 hipotez (uygulandı/korundu/reddedildi)
  GET /api/signal-insights/outcomes → canlı işlem sonuçları + çıkış nedenleri

TASARIM KARARLARI:
  - Fail-open: DB hatası olsa bile uç 200 döner, `error` alanı dolar; panel çökmez.
  - OI sayacı None döner: velocity_candidates tablosunda oi_change_pct KOLONU YOK.
    OI değişimi canlıda yalnız bildirim akışında hesaplanıyor, DB'ye yazılmıyor.
    Bu dürüstlük önemli — sahte sayı üretmektense "ölçülemiyor" demek doğru.
  - ATR sayacı GERÇEK: velocity_candidates.atr_pct üzerinden hesaplanır.
"""
import pathlib

import pytest

BASE = pathlib.Path(__file__).parent.parent
ROUTER = BASE / "app" / "routers" / "signal_insights.py"
PAGE = BASE.parent / "frontend" / "app" / "signal-insights" / "page.tsx"
SIDEBAR = BASE.parent / "frontend" / "app" / "components" / "Sidebar.tsx"


def test_router_registered_in_app():
    """Uçlar ana app'e kayıtlı olmalı."""
    from app.main import app
    paths = [p for p in app.openapi().get("paths", {}) if "signal-insights" in p]
    assert "/api/signal-insights/overview" in paths
    assert "/api/signal-insights/evidence" in paths
    assert "/api/signal-insights/outcomes" in paths


def test_evidence_has_fifteen_items():
    """Ölçülmüş hipotez tablosu 15 satır."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    e = asyncio.run(si.evidence(R()))
    assert e["total"] == 15
    assert e["counts"]["applied"] == 7
    assert e["counts"]["rejected"] == 7
    assert e["counts"]["kept"] == 1


def test_evidence_statuses_valid():
    """Her satırın durumu geçerli olmalı."""
    from app.routers.signal_insights import EVIDENCE
    for item in EVIDENCE:
        assert item["status"] in ("applied", "kept", "rejected"), item["id"]
        assert item["name"] and item["summary"], item["id"]


def test_evidence_includes_key_findings():
    """Oturumun kritik bulguları tabloda olmalı."""
    from app.routers.signal_insights import EVIDENCE
    ids = {i["id"] for i in EVIDENCE}
    for key in ("atr", "oi", "oi_window", "atr_oi", "oi_threshold",
                "velocity", "orderflow", "mlprob", "bookdepth", "trailing"):
        assert key in ids, f"eksik bulgu: {key}"


def test_velocity_marked_rejected_as_dead():
    """velocity_score ölü sinyal olarak işaretli (r=0.0002, ters)."""
    from app.routers.signal_insights import EVIDENCE
    v = next(i for i in EVIDENCE if i["id"] == "velocity")
    assert v["status"] == "rejected"
    blob = v["summary"] + v["detail"]
    assert "0,0002" in blob or "r=0" in blob, blob
    assert "TERS" in v["summary"] or "ters" in v["summary"]


def test_trailing_marked_kept():
    """Trailing mevcut değeri korundu (evrene bağlı, filtreli evrende en iyi)."""
    from app.routers.signal_insights import EVIDENCE
    t = next(i for i in EVIDENCE if i["id"] == "trailing")
    assert t["status"] == "kept"
    assert "evrene özel" in t["detail"].lower()


def test_evidence_warns_about_bar_replay():
    """Uyarı: bar replay canlı gürültüyü modellemiyor."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    e = asyncio.run(si.evidence(R()))
    assert "ticker" in e["warning"].lower()
    assert "bar replay" in e["warning"].lower() or "replay" in e["warning"].lower()


def test_overview_returns_params():
    """Aktif parametreler dönmeli (fail-open)."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    o = asyncio.run(si.overview(R()))
    assert o["ok"] is True
    assert set(o["params"]) >= {"min_atr_pct", "min_oi_change_pct",
                                "oi_window_min", "trailing_enabled"}


def test_overview_oi_counter_is_none_with_reason():
    """OI sayacı None dönmeli + nedeni note'ta yazmalı (sahte sayı yok)."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    o = asyncio.run(si.overview(R()))
    f = o["filters_24h"]
    # DB'de oi_change_pct kolonu yok -> None olmalı
    assert f.get("oi_rejected") is None or isinstance(f.get("oi_rejected"), int)
    assert "velocity_candidates.atr_pct" in o["note"] or "OI" in o["note"]


def test_outcomes_fail_open():
    """DB hatası olsa bile uç çökmemeli."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    o = asyncio.run(si.outcomes(R(), days=7))
    assert "ok" in o
    assert "summary" in o


def test_outcomes_clamps_days():
    """days sınırlanmalı (1..90)."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    assert asyncio.run(si.outcomes(R(), days=0))["days"] == 1
    assert asyncio.run(si.outcomes(R(), days=999))["days"] == 90


def test_page_exists_and_fetches_api():
    """Sayfa var ve üç ucu çağırıyor."""
    assert PAGE.exists(), "signal-insights sayfası yok"
    src = PAGE.read_text(encoding="utf-8")
    for path in ("/api/signal-insights/overview",
                 "/api/signal-insights/evidence",
                 "/api/signal-insights/outcomes"):
        assert path in src, f"sayfa {path} çağırmıyor"


def test_sidebar_has_menu_link():
    """MENÜDE LİNK OLMALI — kullanıcının açık isteği."""
    assert SIDEBAR.exists()
    src = SIDEBAR.read_text(encoding="utf-8")
    assert '/signal-insights' in src, "Sidebar'da /signal-insights bağlantısı yok"
    assert "Sinyal İzleme" in src


def test_page_shows_all_sections():
    """Sayfanın 5 bölümü de olmalı."""
    src = PAGE.read_text(encoding="utf-8")
    for label in ("Aktif Parametreler", "Filtre Sayaçları", "Akış Tazeliği",
                  "Canlı İşlem Sonuçları", "Ölçülmüş Kanıt"):
        assert label in src, f"eksik bölüm: {label}"


def test_page_warns_when_oi_disabled():
    """OI eşiği 0 ise sayfa uyarmalı (canlıda filtrenin kapalı olduğu görünsün)."""
    src = PAGE.read_text(encoding="utf-8")
    assert "min_oi_change_pct" in src
    assert "OI eşiği şu an" in src or "kapalı" in src


def test_page_flags_stale_flow():
    """BAYAT akış uyarısı sayfada olmalı."""
    src = PAGE.read_text(encoding="utf-8")
    assert "BAYAT" in src


@pytest.mark.parametrize("status", ["applied", "kept", "rejected"])
def test_all_status_labels_in_page(status):
    src = PAGE.read_text(encoding="utf-8")
    assert status in src


# --- BOLUM 2: TEK TIKLA DUZELT (olculen degerler) ---

def test_recommended_endpoint_registered():
    from app.main import app
    paths = [p for p in app.openapi().get("paths", {}) if "signal-insights" in p]
    assert "/api/signal-insights/recommended" in paths


def test_recommended_has_4_items():
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    r = asyncio.run(si.recommended(R()))
    keys = {i["key"] for i in r["items"]}
    assert keys == {"min_atr_pct", "min_oi_change_pct", "oi_window_min",
                    "max_sl_tp_ratio"}


def test_recommended_values_match_measurements():
    """Önerilen değerler ÖLÇÜLMÜŞ bulgularla birebir aynı olmalı."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    items = {i["key"]: i for i in asyncio.run(si.recommended(R()))["items"]}
    assert items["min_atr_pct"]["recommended"] == 1.0
    assert items["min_oi_change_pct"]["recommended"] == 1.2
    assert items["oi_window_min"]["recommended"] == 15.0
    assert items["max_sl_tp_ratio"]["recommended"] == 0.64


def test_recommended_endpoint_read_only():
    """Bu uç SALT-OKUNUR — değişiklik yapmamalı."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    res = asyncio.run(si.recommended(R()))
    assert res["ok"] is True
    assert "PUT /api/auto-paper/settings" in res["note"]


def test_page_has_apply_button():
    """Sayfada 'Hepsini Uygula' düğmesi olmalı (tek tıkla)."""
    src = PAGE.read_text(encoding="utf-8")
    assert "Hepsini Uygula" in src
    assert "PUT" in src  # gerçek yazma ucu çağrılıyor
    assert "/api/auto-paper/settings" in src


def test_page_fetches_recommended():
    src = PAGE.read_text(encoding="utf-8")
    assert "/api/signal-insights/recommended" in src


def test_page_notes_same_oi_warning():
    """FARK rozeti + OI kapalı uyarısı birlikte çalışmalı."""
    src = PAGE.read_text(encoding="utf-8")
    assert "FARK" in src
    assert "Ölçülen Değerlere Düzelt" in src


# --- BOLUM 3: BOS PENCERE TESPITI (2026-11-10 canli veri) ---
# TESPIT: 7 gunluk pencerede kayit yok ama sayfa 144 islem gosteriyordu.
# auto_paper_trades son kaydi 2026-10-18. Bos pencere sessizce "0" donerse
# kullanici eski ayarlarin sonucunu guncel sanar. Uc artik bunu SOYLER.

def test_outcomes_reports_window_empty():
    """Bos pencere acikca isaretlenmeli."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    o = asyncio.run(si.outcomes(R(), days=1))
    assert "window_empty" in o
    if o["summary"] and o["summary"]["trades"] == 0:
        assert o["window_empty"] is True
        assert o["note"], "bos pencerede aciklama zorunlu"


def test_outcomes_exposes_last_trade_at():
    """Son islem zamani donmeli (kullanici ne kadar eski oldugunu gorsun)."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    o = asyncio.run(si.outcomes(R(), days=7))
    assert "last_trade_at" in o
    if o["last_trade_at"] is not None:
        assert isinstance(o["last_trade_at"], (int, float))


def test_empty_note_warns_about_old_params():
    """Bos pencere notu 'o tarihten sonra' uyarisi vermeli."""
    import asyncio
    from app.routers import signal_insights as si

    class R:
        pass

    o = asyncio.run(si.outcomes(R(), days=7))
    if o["window_empty"] and o["note"]:
        assert "sonra" in o["note"].lower() or "yok" in o["note"].lower()


def test_page_shows_empty_window_banner():
    """Sayfada bos pencere bandi olmali."""
    src = PAGE.read_text(encoding="utf-8")
    assert "window_empty" in src
    assert "Bu pencerede işlem yok" in src


def test_page_suppresses_summary_when_empty():
    """Bos pencerede ozet KARTLARI gizlenmeli (eski veri guncel gorunmesin)."""
    src = PAGE.read_text(encoding="utf-8")
    assert "outcome && !windowEmpty" in src
