"""Tests for the outbound per-address send limiter (vrchat_osc.SendRateLimiter).

The invariant the latency budget relies on: the cap only delays CONSECUTIVE
rapid sends, never the first after idle — and (the regression this class
exists to fix) the TERMINAL value of a burst is never silently dropped; it
flushes once the window expires. Pure + clock-injected, no sockets.
"""

from vrchat_osc import SendRateLimiter


class TestAllow:
    def test_first_send_is_immediate(self):
        lim = SendRateLimiter(20.0)
        assert lim.allow("/p", 0.5, now=100.0) is True

    def test_first_send_after_idle_is_immediate(self):
        lim = SendRateLimiter(20.0)
        lim.allow("/p", 0.5, now=100.0)
        assert lim.allow("/p", 0.6, now=200.0) is True  # long idle gap

    def test_rapid_second_send_is_suppressed(self):
        lim = SendRateLimiter(20.0)          # 50 ms window
        assert lim.allow("/p", 0.5, now=100.0) is True
        assert lim.allow("/p", 0.6, now=100.016) is False

    def test_send_after_window_is_allowed(self):
        lim = SendRateLimiter(20.0)
        lim.allow("/p", 0.5, now=100.0)
        assert lim.allow("/p", 0.6, now=100.051) is True

    def test_addresses_are_independent(self):
        lim = SendRateLimiter(20.0)
        lim.allow("/a", 0.5, now=100.0)
        assert lim.allow("/b", 0.5, now=100.001) is True


class TestTrailingFlush:
    def test_terminal_value_of_burst_flushes(self):
        # Regression: motor steps X -> 0.0 within one window; the 0.0 was
        # dropped forever and the avatar parameter stuck at X.
        lim = SendRateLimiter(20.0)
        lim.allow("/p", 0.8, now=100.0)
        assert lim.allow("/p", 0.0, now=100.016) is False
        assert lim.poll_flush(now=100.030) == []          # window not up yet
        assert lim.poll_flush(now=100.051) == [("/p", 0.0)]
        assert lim.has_pending() is False

    def test_flush_is_latest_wins(self):
        lim = SendRateLimiter(20.0)
        lim.allow("/p", 0.8, now=100.0)
        lim.allow("/p", 0.5, now=100.01)
        lim.allow("/p", 0.2, now=100.02)
        lim.allow("/p", 0.0, now=100.03)
        assert lim.poll_flush(now=100.06) == [("/p", 0.0)]

    def test_allowed_send_clears_stale_pending(self):
        # If a NEW value goes out normally after the window, the older
        # suppressed value must not flush afterwards (it would regress the
        # parameter backwards in time).
        lim = SendRateLimiter(20.0)
        lim.allow("/p", 0.8, now=100.0)
        lim.allow("/p", 0.5, now=100.01)                  # suppressed
        assert lim.allow("/p", 0.9, now=100.06) is True   # fresh send
        assert lim.poll_flush(now=100.2) == []            # 0.5 never resurfaces

    def test_flush_restarts_the_window(self):
        lim = SendRateLimiter(20.0)
        lim.allow("/p", 0.8, now=100.0)
        lim.allow("/p", 0.0, now=100.01)
        assert lim.poll_flush(now=100.051) == [("/p", 0.0)]
        # The flushed send counts as a send: an immediate follow-up is
        # suppressed again rather than doubling the wire rate.
        assert lim.allow("/p", 0.3, now=100.06) is False

    def test_multiple_addresses_flush_independently(self):
        lim = SendRateLimiter(20.0)
        lim.allow("/a", 1.0, now=100.0)
        lim.allow("/b", 1.0, now=100.02)
        lim.allow("/a", 0.0, now=100.03)                  # suppressed
        lim.allow("/b", 0.0, now=100.03)                  # suppressed
        # Only /a's window has expired at 100.055.
        assert lim.poll_flush(now=100.055) == [("/a", 0.0)]
        assert lim.poll_flush(now=100.075) == [("/b", 0.0)]
