import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tradingbot.analyst.rl_evidence import (
    RLEvidenceEnvelope,
    build_evidence_from_backtest,
    load_rl_evidence,
)


class RLEvidenceTest(unittest.TestCase):
    def test_missing_evidence_file_fails_closed(self):
        with TemporaryDirectory() as tmp_name:
            evidence = load_rl_evidence(Path(tmp_name) / "missing.json")

        self.assertEqual(evidence["status"], "ABSTAIN")
        self.assertIn("missing_evidence_artifact", evidence["reasons"])

    def test_executable_fields_are_stripped_from_llm_payload(self):
        raw = RLEvidenceEnvelope(
            status="CAUTION",
            summary="usable but bounded",
            metrics={"sharpe_ratio": 0.4},
            provenance={
                "target_weights": {"BTC": 0.5},
                "nested": {"order": "buy"},
                "safe": "kept",
            },
        ).to_dict()

        self.assertNotIn("target_weights", raw["provenance"])
        self.assertNotIn("order", raw["provenance"]["nested"])
        self.assertEqual(raw["provenance"]["safe"], "kept")

    def test_verified_evidence_expires_to_abstain(self):
        with TemporaryDirectory() as tmp_name:
            path = Path(tmp_name) / "rl_evidence.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "rl_evidence.v1",
                        "status": "VERIFIED",
                        "as_of_utc": "2026-07-21T00:00:00+00:00",
                        "reasons": [],
                        "provenance": {"promotion_expires_utc": "2026-07-21T01:00:00+00:00"},
                    }
                ),
                encoding="utf-8",
            )

            evidence = load_rl_evidence(
                path,
                now=datetime(2026, 7, 21, 2, tzinfo=timezone.utc),
                max_age_secs=86_400,
            )

        self.assertEqual(evidence["status"], "ABSTAIN")
        self.assertIn("promotion_status_expired", evidence["reasons"])

    def test_build_from_backtest_requires_all_promotion_gates(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            metrics_path = base / "backtest_metrics.csv"
            out_path = base / "rl_evidence.json"
            metrics_path.write_text(
                ",value\n"
                "total_return_pct,4.02\n"
                "sharpe_ratio,0.2759\n"
                "max_drawdown_pct,-6.67\n"
                "target_weights,forbidden\n",
                encoding="utf-8",
            )

            evidence = build_evidence_from_backtest(
                metrics_path=metrics_path,
                output_path=out_path,
                now=datetime(2026, 7, 21, tzinfo=timezone.utc),
            )

            self.assertEqual(evidence["status"], "ABSTAIN")
            self.assertIn("statistical_gates_missing", evidence["reasons"])
            self.assertEqual(evidence["metrics"]["total_return_pct"], 4.02)
            self.assertNotIn("target_weights", evidence["metrics"])
            self.assertTrue(out_path.exists())

    def test_build_from_backtest_can_emit_verified_when_all_gates_pass(self):
        with TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            metrics_path = base / "backtest_metrics.csv"
            metrics_path.write_text(",value\nsharpe_ratio,1.2\n", encoding="utf-8")
            now = datetime(2026, 7, 21, tzinfo=timezone.utc)

            evidence = build_evidence_from_backtest(
                metrics_path=metrics_path,
                now=now,
                promoted=True,
                promotion_expires_utc=(now + timedelta(days=7)).isoformat(),
                causal_integrity_passed=True,
                statistical_gates_passed=True,
                calibration_passed=True,
                prospective_shadow_passed=True,
            )

        self.assertEqual(evidence["status"], "VERIFIED")
        self.assertEqual(evidence["reasons"], [])


if __name__ == "__main__":
    unittest.main()
