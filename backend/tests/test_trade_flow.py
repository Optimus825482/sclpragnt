"""2026-10-17: tarihsel işlem akışı (aggTrades) — ayrıştırma, dakikalık toplama, büyük işlem kademeleri."""
import datetime as dt

import numpy as np

from scripts.backfill_trade_flow import (
    COLUMNS,
    aggregate_minutes,
    date_range,
    day_bounds_ms,
    parse_agg_csv,
    parse_checksum,
    rest_trades_to_arrays,
    rows_from_agg,
    to_ms,
)

MIN = 60_000
T0 = 1_792_022_400_000  # dakika sınırında bir ms (T0 % 60000 == 0)


def test_t0_is_minute_aligned():
    assert T0 % MIN == 0


def test_to_ms_detects_micro_and_milli():
    assert to_ms(np.array([1_792_022_402_455_985]))[0] == 1_792_022_402_455
    assert to_ms(np.array([1_792_022_402_455]))[0] == 1_792_022_402_455
    mixed = to_ms(np.array([1_792_022_402_455, 1_792_022_402_455_985]))
    assert mixed.tolist() == [1_792_022_402_455, 1_792_022_402_455]


def test_parse_csv_micro_timestamps_and_maker_mapping():
    csv = (
        "75328142,4030152.00000000,0.00017000,81761429,81761429,1792022402455985,False,True\n"
        "75328143,4030483.00000000,0.00003000,81761430,81761430,1792022405216160,True,True\n"
    ).encode()
    a = parse_agg_csv(csv)
    assert a["id"].tolist() == [75328142, 75328143]
    assert a["t_ms"].tolist() == [1_792_022_402_455, 1_792_022_405_216]
    # is_buyer_maker=True => SATIŞ agresörü
    assert a["is_sell"].tolist() == [False, True]
    assert abs(a["price"][0] - 4030152.0) < 1e-9 and abs(a["qty"][0] - 0.00017) < 1e-12


def test_parse_csv_millis_header_single_row_and_empty():
    ms_csv = b"1,10.0,2.0,1,1,1792022402455,True,True\n"
    a = parse_agg_csv(ms_csv)  # tek satır → 1-boyutlu dizi
    assert a["t_ms"].tolist() == [1_792_022_402_455] and a["is_sell"].tolist() == [True]
    with_header = b"agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker,is_best_match\n" + ms_csv
    assert parse_agg_csv(with_header)["id"].tolist() == [1]
    assert parse_agg_csv(b"")["id"].size == 0
    assert parse_agg_csv(b"\n").id.size == 0 if False else parse_agg_csv(b"  \n")["id"].size == 0


def test_aggregate_buy_sell_split_vwap_and_ids():
    ids = [10, 11, 12, 13]
    price = [100.0, 102.0, 101.0, 50.0]
    qty = [1.0, 2.0, 3.0, 4.0]
    t = [T0 + 1_000, T0 + 30_000, T0 + 59_999, T0 + MIN + 5]
    sell = [False, True, False, True]
    g = aggregate_minutes(ids, price, qty, t, sell)
    assert g["minute_open_ms"].tolist() == [T0, T0 + MIN]
    assert g["n_trades"].tolist() == [3, 1]
    assert g["buy_base"].tolist() == [4.0, 0.0] and g["sell_base"].tolist() == [2.0, 4.0]
    assert g["buy_quote"].tolist() == [100.0 + 303.0, 0.0]
    assert g["sell_quote"].tolist() == [204.0, 200.0]
    assert abs(g["vwap"][0] - (100.0 + 204.0 + 303.0) / 6.0) < 1e-9
    assert g["max_trade_quote"].tolist() == [303.0, 200.0]
    assert g["first_agg_id"].tolist() == [10, 13] and g["last_agg_id"].tolist() == [12, 13]


def test_aggregate_order_independent():
    ids = [3, 1, 2]
    price = [10.0, 10.0, 10.0]
    qty = [1.0, 2.0, 3.0]
    t = [T0 + MIN + 1, T0 + 1, T0 + MIN + 2]
    g = aggregate_minutes(ids, price, qty, t, [False, True, False])
    assert g["minute_open_ms"].tolist() == [T0, T0 + MIN]
    assert g["sell_base"].tolist() == [2.0, 0.0] and g["buy_base"].tolist() == [0.0, 4.0]


def test_big_and_whale_tiers_inclusive_and_nested():
    # quote: 9_999.99 (altında), 10_000 (big, sınır dahil), 49_999 (big), 50_000 (whale+big), 120_000 sat (whale+big)
    price = [9_999.99, 10_000.0, 49_999.0, 50_000.0, 120_000.0]
    qty = [1.0] * 5
    sell = [False, False, False, False, True]
    g = aggregate_minutes([1, 2, 3, 4, 5], price, qty, [T0 + i for i in range(5)], sell)
    assert g["big_buy_n"].tolist() == [3] and g["big_sell_n"].tolist() == [1]
    assert g["big_buy_quote"].tolist() == [10_000.0 + 49_999.0 + 50_000.0]
    assert g["big_sell_quote"].tolist() == [120_000.0]
    assert g["whale_buy_quote"].tolist() == [50_000.0] and g["whale_sell_quote"].tolist() == [120_000.0]
    assert g["max_trade_quote"].tolist() == [120_000.0]


def test_empty_and_rows_shape():
    assert aggregate_minutes([], [], [], [], [])["minute_open_ms"].size == 0
    g = aggregate_minutes([1], [2.0], [3.0], [T0], [False])
    rows = rows_from_agg("ABCTRY", g)
    assert len(rows) == 1 and len(rows[0]) == len(COLUMNS)
    assert rows[0][0] == "ABCTRY" and rows[0][1] == T0 and rows[0][2] == 1
    assert isinstance(rows[0][2], int) and isinstance(rows[0][-1], int)
    zero = aggregate_minutes([1], [2.0], [0.0], [T0], [False])  # miktar 0 → vwap NaN → None
    assert rows_from_agg("ABCTRY", zero)[0][COLUMNS.index("vwap")] is None


def test_rest_arrays_match_csv_contract():
    trades = [{"a": 7, "p": "2.5", "q": "4.0", "T": 1_792_022_402_455, "m": True},
              {"a": 8, "p": "2.5", "q": "1.0", "T": 1_792_022_402_999, "m": False}]
    a = rest_trades_to_arrays(trades)
    assert a["is_sell"].tolist() == [True, False] and a["t_ms"].tolist() == [1_792_022_402_455, 1_792_022_402_999]
    assert rest_trades_to_arrays([])["id"].size == 0


def test_checksum_and_dates():
    h = "a" * 64
    assert parse_checksum(h + "  X-aggTrades-2026-10-15.zip\n") == h
    assert parse_checksum("not a hash") is None and parse_checksum("") is None
    days = date_range(dt.date(2026, 7, 19), dt.date(2026, 10, 16))
    assert len(days) == 90 and date_range(dt.date(2026, 1, 2), dt.date(2026, 1, 1)) == []
    a, b = day_bounds_ms(dt.date(2026, 10, 15))
    assert b - a == 86_400_000 and a % 86_400_000 == 0
