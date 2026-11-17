"""§29 — max_hold_minutes süre limiti ÖLÇÜMÜ (2026-11-16): DEĞİŞTİRME.

SORU: `max_duration` (-1,13%) ve `plan_sure_doldu` (-0,95%) zarar ediyor.
Süre limitini uzatsak bu işlemler toparlanır mı?

YÖNTEM (work/rise/holdlimit.py): Canlı 1.792 işlemin giriş zamanı/sembolü ve
GERÇEK SL/TP geometrisi alındı, 5m barlarla yeniden oynatıldı. Sadece
"süreyle kapananlar" değil TÜM işlemler — çünkü süre uzarsa bazıları TP'ye
ulaşır, bazıları SL'ye döner.

SONUÇ — mevcut geometri (ratio yok):
  horizon   NET ort    kaz%    TP    SL
   60 dk    -0,787%   39,7%   553   600
  120 dk    -0,843%   41,1%   615   696
  240 dk    -0,803%   43,9%   692   782
  480 dk    -0,795%   45,3%   764   833
 1440 dk    -0,791%   46,9%   825   909
 2880 dk    -0,775%   47,4%   846   926

SONUÇ — üretim ayarı (ratio=0,40):
   30 dk    -0,355%   29,2%   365  1049
  120 dk    -0,381%   28,1%   428  1202
  480 dk    -0,366%   28,1%   477  1267
 1440 dk    -0,386%   27,3%   485  1293

DÜZ ÇİZGİ. 30 dakika ile 48 saat arasında anlamlı fark YOK.

İSTATİSTİK: 60 dk (-0,787%, hata ±0,073) vs 120 dk (-0,843%, hata ±0,076)
→ fark +0,056%, ortak hata 0,105 → ANLAMSIZ (2 hatanın altında).

MEKANİZMA: süre uzadıkça TP ve SL AYNI hızda artıyor (TP/SL oranı 0,35-0,37
sabit). Beklemek yeni kazanan üretmiyor, sadece SL'ye gidenleri geciktiriyor.

YORUM: Süre-dolumu zararları BELİRTİ, SEBEP DEĞİL. O işlemler süre dolduğu
için zarar etmiyor — zaten zararda oldukları için süre doluyor. Limiti
kaldırsan SL'ye gidiyorlar. Bu yüzden limit DOKUNULMAZ (120 dk kalır).
"""
import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "app" / "config.py"


def test_max_hold_minutes_unchanged():
    """Süre limiti 120 dk'da kalmalı — ölçüm değiştirmeyi desteklemiyor."""
    txt = CONFIG.read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r'AUTO_PAPER_MAX_HOLD_MINUTES\s*=\s*float\(os\.getenv\(\s*"AUTO_PAPER_MAX_HOLD_MINUTES"\s*,\s*"([0-9.]+)"',
        txt,
    )
    assert m, "AUTO_PAPER_MAX_HOLD_MINUTES tanımı bulunamadı"
    assert float(m.group(1)) == 120.0, (
        f"varsayılan {m.group(1)} — 120 bekleniyordu. "
        "§29 ölçümü süre limitinin ETKİSİZ olduğunu gösterdi; "
        "değiştirmeden önce yeni kanıt gerekir."
    )


def test_config_documents_hold_sweep():
    """Kod yorumunda süre taraması kanıtı olmalı."""
    txt = CONFIG.read_text(encoding="utf-8", errors="replace")
    i = txt.find("AUTO_PAPER_MAX_HOLD_MINUTES")
    assert i > 0
    block = txt[max(0, i - 1300):i]
    assert "süre" in block or "Süre" in block or "sure" in block.lower()
    assert "ETKİSİZ" in block or "etkisiz" in block, "ölçüm sonucu belgelenmemiş"
