"""§28 — max_sl_tp_ratio taraması (2026-11-16): 0,64 -> 0,40.

YÖNTEM (kritik): İlk simülasyon YANILTICIYDI — sadece `stop_loss` çıkışlarını
yeniden hesaplıyordu, "dar SL daha SIK vurulur" gerçeğini yok sayıyordu.
Doğru yöntem: canlı 2.048 işlemin giriş zamanını/sembolünü alıp 5m barlarla
YENİDEN OYNAT (work/rise/rrreal.py). Böylece SL-vurulma sayısı da değişir.

SONUÇ — ⚠ 2026-11-18 DÜZELTİLMİŞ harness (ilk ölçüm ÜÇ hata içeriyordu:
bar eşleştirmesi bir bar kayıyordu, veri bitiminden sonraki işlemler son bara
kilitleniyordu, bar boşlukları eski bara düşürüyordu):
  taban      -> ort -0,724% med -2,371% kaz %47,9 TP 846 SL  891
  ratio 0,64 -> ort -0,609% med -2,083% kaz %34,1 TP 603 SL 1168
  ratio 0,55 -> ort -0,522% med -1,918% kaz %31,9 TP 565 SL 1211
  ratio 0,50 -> ort -0,504% med -1,775% kaz %30,0 TP 532 SL 1247
  ratio 0,45 -> ort -0,477% med -1,625% kaz %28,1 TP 499 SL 1281
  ratio 0,40 -> ort -0,421% med -1,475% kaz %26,6 TP 472 SL 1310
  ratio 0,35 -> ort -0,387% med -1,375% kaz %24,6 TP 439 SL 1349
  ratio 0,30 -> ort -0,336% med -1,229% kaz %22,9 TP 408 SL 1381

Yön doğrulandı: 0,64 -> 0,40 = +0,188 puan (ilk tahmin +0,111 idi, gerçek
daha BÜYÜK). Monoton: daraltma ortalamayı iyileştiriyor, kazanma oranını
düşürüyor. 0,40 denge noktası (iyileşmenin ~%60'ı, kazanan %26,6).

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
    for needle in ("0,64", "0,50", "0,40", "-0,609", "-0,421", "DÜZELTME"):
        assert needle in block, f"kanıt bloğunda {needle!r} yok"


def test_config_states_no_ratio_is_profitable():
    """Dürüstlük kilidi: kod, hiçbir oranın kâra geçmediğini YAZMALI.

    Bu satır silinirse biri 'daraltma kâr getiriyor' sanıp daha da sıkılaştırır.
    """
    i = _cfg().find("AUTO_PAPER_MAX_SL_TP_RATIO")
    block = _cfg()[max(0, i - 1400):i]
    assert "kâra geçmiyor" in block or "kâra geçmi" in block
    assert "AZALTIYOR" in block or "AZALT" in block
