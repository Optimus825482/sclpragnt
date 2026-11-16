"""§28 — max_sl_tp_ratio taraması (2026-11-16): 0,64 -> 0,40.

YÖNTEM (kritik): İlk simülasyon YANILTICIYDI — sadece `stop_loss` çıkışlarını
yeniden hesaplıyordu, "dar SL daha SIK vurulur" gerçeğini yok sayıyordu.
Doğru yöntem: canlı 2.048 işlemin giriş zamanını/sembolünü alıp 5m barlarla
YENİDEN OYNAT (work/rise/rrreal.py). Böylece SL-vurulma sayısı da değişir.

SONUÇ (TP sabit %4, 24s horizon, maliyet 0,275% dahil):
  ratio 0,64 (SL 2,56%) -> ort -0,382% kazanan %37,5 SL-vurulma 1255
  ratio 0,55 (SL 2,20%) -> ort -0,339% kazanan %34,7 SL-vurulma 1323
  ratio 0,50 (SL 2,00%) -> ort -0,330% kazanan %32,7 SL-vurulma 1367
  ratio 0,45 (SL 1,80%) -> ort -0,310% kazanan %30,7 SL-vurulma 1409
  ratio 0,40 (SL 1,60%) -> ort -0,271% kazanan %28,9 SL-vurulma 1449
  ratio 0,35 (SL 1,40%) -> ort -0,212% kazanan %27,3 SL-vurulma 1484

Monoton: daraltma ortalamayı iyileştiriyor AMA kazanma oranını düşürüyor.
0,35 en iyi ortalama; 0,40 denge noktası seçildi.

DÜRÜST KISIT: HİÇBİR ratio kâra geçmiyor. Daraltma kaybı AZALTIR, sıfırlamaz.
Bu bir "kâr kaynağı" değil, bir "hasar sınırlayıcı"dır — öyle belgelenmeli.
"""
import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "app" / "config.py"


def _cfg() -> str:
    return CONFIG.read_text(encoding="utf-8", errors="replace")


def test_default_ratio_is_040():
    """Ölçülmüş varsayılan 0.40 olmalı."""
    m = re.search(
        r'AUTO_PAPER_MAX_SL_TP_RATIO\s*=\s*float\(os\.getenv\(\s*"AUTO_PAPER_MAX_SL_TP_RATIO"\s*,\s*"([0-9.]+)"',
        _cfg(),
    )
    assert m, "AUTO_PAPER_MAX_SL_TP_RATIO tanımı bulunamadı"
    assert float(m.group(1)) == 0.40, f"varsayılan {m.group(1)}, 0.40 bekleniyordu"


def test_config_documents_sweep_evidence():
    """Kod yorumunda tarama kanıtı olmalı — gelecekteki 'neden 0.40?' sorusu."""
    txt = _cfg()
    i = txt.find("AUTO_PAPER_MAX_SL_TP_RATIO")
    assert i > 0
    block = txt[max(0, i - 1400):i]
    for needle in ("0,64", "0,50", "0,40", "-0,382", "-0,271"):
        assert needle in block, f"kanıt bloğunda {needle!r} yok"


def test_config_states_no_ratio_is_profitable():
    """Dürüstlük kilidi: kod, hiçbir oranın kâra geçmediğini YAZMALI.

    Bu satır silinirse biri 'daraltma kâr getiriyor' sanıp daha da sıkılaştırır.
    """
    i = _cfg().find("AUTO_PAPER_MAX_SL_TP_RATIO")
    block = _cfg()[max(0, i - 1400):i]
    assert "kâra geçmiyor" in block or "kâra geçmi" in block
    assert "AZALTIYOR" in block or "AZALT" in block
