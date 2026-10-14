"""Chat intent tespiti: sembol+analiz isteği trade niyetine çevrilmemeli."""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _detect_intent(last_text: str) -> dict:
    """_strategies_chat içindeki intent regex'lerini birebir yansıtır."""
    text = last_text.lower()
    analysis_only = bool(re.search(
        r"(analiz|incele|değerlendir|degerlendir|yorumla|durum|ne\s+olabilir|ne\s+olur|görünüm|gorunum|bakalım|bakalim|özetle|ozetle|gidişat|gidisat)",
        text))
    trade = bool(re.search(
        r"(işlem|islem|pozisyon|paper|trade|coin|sembol|emir|market|limit|stop|oco).*(aç|ac|açar|acar|aktif|ekle|giriş|giris|kur|kullan)|\b(aç|ac|aktif|ekle|kur|kullan)\b.*(işlem|islem|pozisyon|paper|trade|coin|sembol|emir|market|limit|stop|oco)",
        text))
    research = bool(re.search(
        r"(geriye\s*dönük|geriye\s*donuk|backtest|back-test|tarihsel|geçmiş.*test|gecmis.*test|kaç\s+işlem.*olurdu|kaç\s+islem.*olurdu|simüle|simule|varsayımsal|varsayimsal)",
        text))
    requested_symbols = [t.upper() for t in re.findall(r"\b[A-Za-z]{2,12}TRY\b", last_text.upper())]
    trade_verb = bool(re.search(
        r"(aç|ac|açar|acar|aktifleştir|aktiflestir|ekle|kur|kullan|al\b|sat\b|gir\b|long\b|short\b|stop\s+koy|hedef\s+koy)",
        text))
    if requested_symbols:
        trade = True
    if analysis_only and not trade_verb:
        trade = False
    elif requested_symbols and not trade_verb:
        trade = False
    elif trade_verb:
        trade = True
    if research:
        trade = False
    return {"trade_intent": trade, "requested_symbols": requested_symbols,
            "analysis_only": analysis_only, "has_trade_verb": trade_verb}


class ChatIntentTests(unittest.TestCase):
    def test_symbol_plus_analiz_is_not_trade(self):
        self.assertFalse(_detect_intent("EGLDTRY ANALİZ")["trade_intent"])

    def test_bare_symbol_is_not_trade(self):
        self.assertFalse(_detect_intent("EGLDTRY")["trade_intent"])

    def test_symbol_plus_durum_is_not_trade(self):
        self.assertFalse(_detect_intent("BTCUSDT ne olabilir")["trade_intent"])
        self.assertFalse(_detect_intent("ETHUSDT durum nedir")["trade_intent"])

    def test_verbatim_open_position_stays_trade(self):
        self.assertTrue(_detect_intent("EGLDTRY long aç")["trade_intent"])
        self.assertTrue(_detect_intent("BTCUSDT al")["trade_intent"])
        self.assertTrue(_detect_intent("EGLDTRY paper pozisyon aç")["trade_intent"])

    def test_research_stays_non_trade(self):
        self.assertFalse(_detect_intent("EGLDTRY backtest yap")["trade_intent"])

    def test_plain_question_not_symbol_not_trade(self):
        self.assertFalse(_detect_intent("en iyi strateji hangisi")["trade_intent"])


if __name__ == "__main__":
    unittest.main()
