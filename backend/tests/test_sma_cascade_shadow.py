import unittest

from app.sma_cascade_shadow import CascadeState, SmaCascadeShadow, crossed_up


def bars_for(closes):
    return {
        "timestamps": [index * 60_000 for index in range(len(closes))],
        "closes": list(map(float, closes)),
        "highs": [float(value) + 1 for value in closes],
        "lows": [float(value) - 1 for value in closes],
    }


class SmaCascadeShadowTests(unittest.TestCase):
    def test_crossed_up_requires_the_previous_bar_to_be_below(self):
        self.assertTrue(crossed_up(99, 100, 101, 100))
        self.assertFalse(crossed_up(101, 100, 102, 100))

    def test_detects_ordered_cascade_then_breakout_and_30m_outcome(self):
        # The initial ordering is 7 < 25 < 99.  The following closes make
        # 7>25, then 7>99, then 25>99 in separate closed one-minute bars.
        closes = [108.0] * 75 + [105.0] * 19 + [100.0] * 6
        observer = SmaCascadeShadow(max_sequence_minutes=10, breakout_window_minutes=30,
                                    outcome_window_minutes=30)
        self.assertEqual(observer.process("TESTTRY", bars_for(closes)), [])

        events = []
        for close in [138.0, 140.0, 140.0]:
            closes.append(close)
            events.extend(observer.process("TESTTRY", bars_for(closes)))
        cascades = [event for event in events if event["type"] == "cascade_detected"]
        self.assertEqual(len(cascades), 1)
        self.assertLess(cascades[0]["first_cross_at_ms"], cascades[0]["second_cross_at_ms"])
        self.assertLess(cascades[0]["second_cross_at_ms"], cascades[0]["cascade_at_ms"])

        closes.append(145.0)
        breakouts = observer.process("TESTTRY", bars_for(closes))
        self.assertEqual([event["type"] for event in breakouts], ["breakout_observed"])

        outcome_events = []
        for _ in range(30):
            closes.append(146.0)
            outcome_events.extend(observer.process("TESTTRY", bars_for(closes)))
        outcomes = [event for event in outcome_events if event["type"] == "outcome_30m"]
        self.assertEqual(len(outcomes), 1)
        self.assertGreater(outcomes[0]["return_pct"], 0)

    def test_expired_first_cross_cannot_be_combined_with_later_crosses(self):
        observer = SmaCascadeShadow(max_sequence_minutes=1)
        state = observer.states.setdefault("TESTTRY", CascadeState())
        state.first_cross_at_ms = 60_000
        state.sequence_high = 101.0
        state.sequence_low = 99.0
        closes = [100.0] * 100
        result = observer.process("TESTTRY", bars_for(closes))
        self.assertEqual(result, [])
        self.assertIsNone(state.first_cross_at_ms)
