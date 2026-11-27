from pytest import approx

from app.large_move_paper import MINUTE, Tracker, mark_exit, read_book, trailing_level


def warmed_tracker():
    tracker = Tracker()
    for i in range(1, 31):
        assert tracker.observe(i * MINUTE, 100, True) is None
    return tracker


def test_watch_and_entry_share_a_prior_only_seed_and_do_not_repeat():
    tracker = warmed_tracker()
    assert tracker.observe(31 * MINUTE, 103, True) is None
    watch = tracker.observe(32 * MINUTE, 110, True)
    assert (watch.level, watch.base, watch.seed, watch.stamp) == (10, 100, 31 * MINUTE, 33 * MINUTE)
    assert tracker.observe(33 * MINUTE, 115, False) is None
    entry = tracker.observe(34 * MINUTE, 115, True)
    assert (entry.level, entry.seed, entry.stamp) == (15, watch.seed, 35 * MINUTE)
    assert tracker.observe(34 * MINUTE, 130, True) is None
    assert tracker.observe(35 * MINUTE, 130, True) is None


def test_gap_rewarm_and_direct_jump():
    tracker = warmed_tracker()
    assert tracker.observe(32 * MINUTE, 140, True) is None
    for i in range(33, 62):
        assert tracker.observe(i * MINUTE, 100, True) is None
    assert tracker.observe(62 * MINUTE, 117, True).level == 15


def test_exit_walk_uses_bids_and_round_trip_cost():
    book = read_book({"bids": [["102", "5"], ["100", "6"]], "asks": [["103", "10"]]})
    price, net, pct = mark_exit(book[0], 10, 1002, .002)
    assert price == 101
    assert net == approx(5.98)
    assert pct == approx(100 * net / 1002)
    assert mark_exit(book[0], 12, 1002, .002) is None
    assert read_book({"bids": [[110, 100]], "asks": [[109, 100]]}) is None


def test_trailing_activates_at_net_profit_and_never_backs_off():
    assert trailing_level(1.99, None, None) == (1.99, None)
    assert trailing_level(2, 1.99, None) == (2, .75)
    assert trailing_level(5, 2, .75) == approx((5, 4.2))
    assert trailing_level(4.3, 5, 4.2) == approx((5, 4.2))
    assert trailing_level(7, 5, 4.2) == approx((7, 6.5))
    assert trailing_level(12, 7, 6.5) == approx((12, 11.5))
