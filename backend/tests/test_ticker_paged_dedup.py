"""`_ticker_paged` tekrarlı sembolleri BİRLEŞTİRİR.

Hata (2026-10-16, canlı kopya üzerinde ölçüldü): `/api/daily-rising/live` 60 satırlık (51 benzersiz sembol)
listeyi `_batch_prices` ile istiyordu. Aynı sembol listede tekrar edince Binance TR HTTP 400 dönüyor,
kod "tek tek kurtar" yoluna giriyor ve 60 isteği ARDIŞIK atıyordu: 0.5 sn yerine ~20 sn. Ana sayfanın
dört isteği birlikte beklediği için "Son bildirimler" de bu süre boyunca boş görünüyordu.
"""
import asyncio

from app import binance_tr_public as btp


def _run(symbols):
    calls: list[list[str]] = []

    def fake_get_json(path, params):
        calls.append(str(params.get("symbols")))
        return [{"symbol": "X", "price": "1"}]

    original = btp._get_json
    btp._get_json = fake_get_json
    try:
        asyncio.run(btp._ticker_paged("/api/v3/ticker/price", symbols))
    finally:
        btp._get_json = original
    return calls


def test_duplicates_are_collapsed_into_one_request():
    calls = _run(["BTCTRY", "ETHTRY", "BTCTRY", "ETHTRY", "SOLTRY"])
    assert len(calls) == 1
    sent = calls[0]
    assert sent.count("BTCTRY") == 1 and sent.count("ETHTRY") == 1 and "SOLTRY" in sent


def test_order_of_first_occurrence_is_kept():
    calls = _run(["ETHTRY", "BTCTRY", "ETHTRY"])
    assert calls[0].index("ETHTRY") < calls[0].index("BTCTRY")


def test_case_differences_are_the_same_symbol():
    calls = _run(["btctry", "BTCTRY"])
    assert calls[0].upper().count("BTCTRY") == 1


def test_sixty_rows_with_fifty_one_unique_use_two_chunks_not_sixty_calls():
    syms = [f"S{i:02d}TRY" for i in range(51)] + [f"S{i:02d}TRY" for i in range(9)]
    assert len(syms) == 60
    assert len(_run(syms)) <= 2
