"""binance_tr_user_stream._normalize_event birim testleri (ağ yok)."""
from app import binance_tr_user_stream as us


def _execution_report(**extra):
    payload = {"e": "executionReport", "E": 1, "s": "ADATRY", "c": "sa123", "S": "SELL", "o": "MARKET",
               "x": "EXPIRED", "X": "EXPIRED", "i": 42, "z": "0", "Z": "0"}
    payload.update(extra)
    return {"event": payload}


def test_execution_report_price_range_expiry_is_flagged():
    ev = us._normalize_event(_execution_report(eR="EXECUTION_RULE_PRICE_RANGE_EXCEEDED"))
    assert ev["event_type"] == "executionReport"
    assert ev["fields"]["status"] == "EXPIRED" and ev["fields"]["order_id"] == 42
    assert ev["fields"]["expiry_reason"] == "EXECUTION_RULE_PRICE_RANGE_EXCEEDED"
    assert ev["fields"]["price_range_exceeded"] is True


def test_execution_report_without_expiry_reason():
    ev = us._normalize_event(_execution_report(X="FILLED", x="TRADE"))
    assert ev["fields"]["expiry_reason"] is None
    assert ev["fields"]["price_range_exceeded"] is False


def test_other_expiry_reason_is_not_price_range():
    ev = us._normalize_event(_execution_report(eR="SOME_OTHER_REASON"))
    assert ev["fields"]["expiry_reason"] == "SOME_OTHER_REASON"
    assert ev["fields"]["price_range_exceeded"] is False


def test_account_position_balances_and_data_envelope():
    ev = us._normalize_event({"data": {"e": "outboundAccountPosition", "E": 5, "u": 6,
                                       "B": [{"a": "TRY", "f": "10", "l": "1"}, "bozuk"]}})
    assert ev["event_type"] == "outboundAccountPosition"
    assert ev["fields"]["balances"] == [{"asset": "TRY", "free": "10", "locked": "1"}]
    assert ev["fields"]["last_account_update_ms"] == 6


def test_unknown_events_are_ignored():
    assert us._normalize_event({"event": {"e": "listStatus"}}) is None
    assert us._normalize_event({"result": None, "id": "1"}) is None


def test_removed_dead_subscriber_api():
    for name in ("subscribe_user_stream", "unsubscribe_user_stream", "stream_snapshot"):
        assert not hasattr(us, name)
    assert us.stream_status("yok") == {"state": "stopped", "connected": False}
