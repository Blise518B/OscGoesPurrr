"""Tests for the controller queue's collect-and-coalesce phase
(queue_drain.drain_and_coalesce) — the invariants main.process_async_queue
relies on, previously untestable inside the app class.
"""

import queue

from queue_drain import drain_and_coalesce


def _q(*msgs):
    q = queue.Queue()
    for m in msgs:
        q.put(m)
    return q


class TestCoalescing:
    def test_latest_wins_per_device_motor(self):
        q = _q(
            ("osc_haptic_update", ("Toy", 0.2, 0)),
            ("osc_haptic_update", ("Toy", 0.5, 0)),
            ("osc_haptic_update", ("Toy", 0.9, 0)),
        )
        events, haptic = drain_and_coalesce(q, 100)
        assert events == []
        assert haptic == {("Toy", 0): ("Toy", 0.9, 0)}

    def test_distinct_motors_kept_separately(self):
        q = _q(
            ("osc_haptic_update", ("Toy", 0.2, 0)),
            ("osc_haptic_update", ("Toy", 0.7, 1)),
            ("osc_haptic_update", ("Other", 0.4, 0)),
        )
        _, haptic = drain_and_coalesce(q, 100)
        assert haptic[("Toy", 0)] == ("Toy", 0.2, 0)
        assert haptic[("Toy", 1)] == ("Toy", 0.7, 1)
        assert haptic[("Other", 0)] == ("Other", 0.4, 0)


class TestOrderPreservation:
    def test_non_haptic_relative_order_survives_interleaved_haptics(self):
        # connection_status must still land before devices_found even with
        # haptic updates woven between them.
        q = _q(
            ("connection_status", (True, "ws://x")),
            ("osc_haptic_update", ("Toy", 0.5, 0)),
            ("devices_found", {0: {"name": "Toy"}}),
            ("osc_haptic_update", ("Toy", 0.6, 0)),
            ("ui_update", "hello"),
        )
        events, haptic = drain_and_coalesce(q, 100)
        assert [e[0] for e in events] == [
            "connection_status", "devices_found", "ui_update"]
        assert haptic[("Toy", 0)][1] == 0.6


class TestBatchCap:
    def test_cap_leaves_the_rest_queued(self):
        q = _q(*[("ui_update", i) for i in range(10)])
        events, _ = drain_and_coalesce(q, 4)
        assert [e[1] for e in events] == [0, 1, 2, 3]
        assert q.qsize() == 6              # leftovers for the next tick

    def test_haptic_updates_count_against_the_cap(self):
        q = _q(
            ("osc_haptic_update", ("Toy", 0.1, 0)),
            ("osc_haptic_update", ("Toy", 0.2, 0)),
            ("ui_update", "late"),
        )
        events, haptic = drain_and_coalesce(q, 2)
        assert events == []                # cap hit before the ui_update
        assert haptic[("Toy", 0)][1] == 0.2
        assert q.qsize() == 1


class TestMalformedMessages:
    def test_non_tuples_pass_through_unraised(self):
        q = _q("garbage", None, 42, ("ui_update", "ok"))
        events, haptic = drain_and_coalesce(q, 100)
        assert events == ["garbage", None, 42, ("ui_update", "ok")]
        assert haptic == {}

    def test_empty_queue_returns_empty(self):
        events, haptic = drain_and_coalesce(queue.Queue(), 100)
        assert events == [] and haptic == {}
