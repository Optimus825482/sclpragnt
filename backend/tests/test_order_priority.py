"""Emir POST'ları okuma yoğunluğunda yuva beklemez."""
import threading

from app import binance_tr_private as btp


def test_order_posts_use_separate_semaphore():
    assert btp._semaphore_for("POST", "/open/v1/orders") is btp._ORDER_SEMAPHORE
    assert btp._semaphore_for("post", "/open/v1/orders/oco") is btp._ORDER_SEMAPHORE
    assert btp._semaphore_for("GET", "/open/v1/account/spot") is btp._PRIVATE_SEMAPHORE
    assert btp._semaphore_for("GET", "/open/v1/orders") is btp._PRIVATE_SEMAPHORE
    assert btp._semaphore_for("POST", "/open/v1/orders/cancel") is btp._PRIVATE_SEMAPHORE


def test_order_slot_free_when_read_slots_exhausted():
    held = [btp._PRIVATE_SEMAPHORE.acquire(timeout=1) for _ in range(btp.PRIVATE_MAX_CONCURRENCY)]
    try:
        got = []
        t = threading.Thread(target=lambda: got.append(btp._semaphore_for("POST", "/open/v1/orders").acquire(timeout=1)))
        t.start()
        t.join(2)
        assert got == [True]
        btp._ORDER_SEMAPHORE.release()
    finally:
        for ok in held:
            if ok:
                btp._PRIVATE_SEMAPHORE.release()
