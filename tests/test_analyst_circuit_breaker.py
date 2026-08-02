import unittest

from tradingbot.analyst.circuit_breaker import LLMCircuitBreaker, LLMCircuitOpen
from tradingbot.analyst.llm import LLMProviderError


class AnalystCircuitBreakerTest(unittest.TestCase):
    def test_cooldown_is_per_scope_and_success_resets_the_lane(self):
        now = [100.0]
        breaker = LLMCircuitBreaker(
            failure_threshold=2,
            cooldown_secs=10,
            now_func=lambda: now[0],
        )

        breaker.record_failure("screening", LLMProviderError("first"))
        breaker.record_failure("screening", LLMProviderError("second"))

        with self.assertRaises(LLMCircuitOpen) as blocked:
            breaker.check("screening")
        self.assertEqual(blocked.exception.retry_after_secs, 10)
        breaker.check("interactive")

        now[0] += 10
        breaker.check("screening")
        with self.assertRaises(LLMCircuitOpen):
            breaker.check("screening")

        breaker.record_success("screening")
        breaker.check("screening")
        self.assertEqual(breaker.snapshot()["screening"]["state"], "closed")
        self.assertEqual(breaker.snapshot()["screening"]["consecutive_failures"], 0)

    def test_failed_half_open_probe_restarts_the_full_cooldown(self):
        now = [50.0]
        breaker = LLMCircuitBreaker(failure_threshold=1, cooldown_secs=30, now_func=lambda: now[0])
        breaker.record_failure("screening", LLMProviderError("down"))

        now[0] += 30
        breaker.check("screening")
        breaker.record_failure("screening", LLMProviderError("still down"))

        with self.assertRaises(LLMCircuitOpen) as blocked:
            breaker.check("screening")
        self.assertEqual(blocked.exception.retry_after_secs, 30)


if __name__ == "__main__":
    unittest.main()
