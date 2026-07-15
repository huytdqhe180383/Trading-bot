import re
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from tradingbot.analyst.models import AnalystEvent, AnalystStatus
from ui.app import UIAppContext, create_app


def _write_live_decisions(results_dir: Path, run_date: str = "2026-05-31", session: str = "1") -> None:
    session_dir = results_dir / "daily" / run_date / session
    session_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "timestamp_utc": "2026-05-30T17:10:12+00:00",
                "cycle": 1,
                "nav": 10000.0,
                "pnl_pct": 0.0,
                "btc_weight": 0.50,
                "eth_weight": 0.49,
                "cash_weight": 0.01,
                "orders_submitted": 0,
                "orders_filled": 0,
                "status": "ok",
            },
            {
                "timestamp_utc": "2026-05-30T18:10:12+00:00",
                "cycle": 2,
                "nav": 10120.0,
                "pnl_pct": 1.2,
                "btc_weight": 0.51,
                "eth_weight": 0.48,
                "cash_weight": 0.01,
                "orders_submitted": 1,
                "orders_filled": 1,
                "status": "ok",
            },
        ]
    ).to_csv(session_dir / "live_trade_decisions_okx_testnet.csv", index=False)


def _write_compact_report(reports_dir: Path, report_date: str = "2026-05-31") -> None:
    day_dir = reports_dir / "daily" / report_date
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "live_report_2026-05-31_asia_bangkok.md").write_text("# report\n", encoding="utf-8")


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if not match:
        raise AssertionError("CSRF token not found in HTML response")
    return match.group(1)


class UIAppTest(unittest.TestCase):
    def _build_client(self, *, controls_enabled: bool = False) -> tuple[TestClient, TemporaryDirectory]:
        tmp = TemporaryDirectory()
        base = Path(tmp.name)
        results_dir = base / "results"
        reports_dir = base / "report"
        logs_dir = base / "logs"
        audit_log = logs_dir / "ui_audit.jsonl"
        logs_dir.mkdir(parents=True, exist_ok=True)
        _write_live_decisions(results_dir)
        _write_compact_report(reports_dir)
        (logs_dir / "live_stderr.log").write_text("stderr line 1\nstderr line 2\n", encoding="utf-8")
        (logs_dir / "live_stdout.log").write_text("stdout line 1\n", encoding="utf-8")

        def fake_status_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="ActiveState=active\nSubState=running\nMainPID=123\nExecMainStartTimestamp=Sat 2026-05-31 09:00:00 +07\n",
                stderr="",
            )

        def fake_journal_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout="service line 1\n", stderr="")

        def fake_control_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

        ctx = UIAppContext(
            username="admin",
            password="secret-pass",
            session_secret="unit-test-secret",
            results_dir=results_dir,
            reports_dir=reports_dir,
            logs_dir=logs_dir,
            controls_enabled=controls_enabled,
            audit_log_path=audit_log,
            status_runner=fake_status_runner,
            journal_runner=fake_journal_runner,
            control_runner=fake_control_runner,
        )
        return TestClient(create_app(ctx)), tmp

    def _login(self, client: TestClient) -> str:
        login_page = client.get("/login")
        csrf = _extract_csrf(login_page.text)
        response = client.post(
            "/login",
            data={"username": "admin", "password": "secret-pass", "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        return csrf

    def _build_tailscale_client(self, *, controls_enabled: bool = False) -> tuple[TestClient, TemporaryDirectory]:
        tmp = TemporaryDirectory()
        base = Path(tmp.name)
        results_dir = base / "results"
        reports_dir = base / "report"
        logs_dir = base / "logs"
        audit_log = logs_dir / "ui_audit.jsonl"
        logs_dir.mkdir(parents=True, exist_ok=True)
        _write_live_decisions(results_dir)
        _write_compact_report(reports_dir)
        (logs_dir / "live_stderr.log").write_text("stderr line 1\nstderr line 2\n", encoding="utf-8")
        (logs_dir / "live_stdout.log").write_text("stdout line 1\n", encoding="utf-8")

        def fake_status_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="ActiveState=active\nSubState=running\nMainPID=123\nExecMainStartTimestamp=Sat 2026-05-31 09:00:00 +07\n",
                stderr="",
            )

        def fake_journal_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout="service line 1\n", stderr="")

        def fake_control_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

        ctx = UIAppContext(
            username="owner",
            password="owner-secret",
            session_secret="unit-test-secret",
            results_dir=results_dir,
            reports_dir=reports_dir,
            logs_dir=logs_dir,
            controls_enabled=controls_enabled,
            audit_log_path=audit_log,
            status_runner=fake_status_runner,
            journal_runner=fake_journal_runner,
            control_runner=fake_control_runner,
            trust_tailscale_headers=True,
            allowed_tailscale_users=frozenset({"owner@example.com", "friend@example.com"}),
            admin_tailscale_users=frozenset({"owner@example.com"}),
        )
        return TestClient(create_app(ctx)), tmp

    def test_dashboard_redirects_when_unauthenticated(self):
        client, tmp = self._build_client()
        with tmp:
            response = client.get("/", follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/login")

    def test_api_requires_authentication(self):
        client, tmp = self._build_client()
        with tmp:
            response = client.get("/api/status")
            self.assertEqual(response.status_code, 401)

    def test_login_requires_csrf(self):
        client, tmp = self._build_client()
        with tmp:
            response = client.post("/login", data={"username": "admin", "password": "secret-pass"})
            self.assertEqual(response.status_code, 403)

    def test_login_rejects_bad_credentials(self):
        client, tmp = self._build_client()
        with tmp:
            login_page = client.get("/login")
            csrf = _extract_csrf(login_page.text)
            response = client.post("/login", data={"username": "admin", "password": "wrong", "csrf_token": csrf})
            self.assertEqual(response.status_code, 401)
            self.assertIn("Invalid credentials", response.text)

    def test_login_success_enables_dashboard_and_note(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Strategy NAV excludes non-strategy assets such as OKB.", response.text)
            self.assertIn("Live bot status", response.text)
            self.assertIn("Today Unrealized PnL", response.text)
            self.assertIn("No new cycle has been recorded", response.text)

    def test_logout_invalidates_session(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            dashboard = client.get("/")
            csrf = _extract_csrf(dashboard.text)
            response = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            after = client.get("/", follow_redirects=False)
            self.assertEqual(after.status_code, 303)
            self.assertEqual(after.headers["location"], "/login")

    def test_login_rate_limit_triggers(self):
        client, tmp = self._build_client()
        with tmp:
            for _ in range(5):
                login_page = client.get("/login")
                csrf = _extract_csrf(login_page.text)
                response = client.post("/login", data={"username": "admin", "password": "wrong", "csrf_token": csrf})
                self.assertEqual(response.status_code, 401)
            login_page = client.get("/login")
            csrf = _extract_csrf(login_page.text)
            response = client.post("/login", data={"username": "admin", "password": "wrong", "csrf_token": csrf})
            self.assertEqual(response.status_code, 429)

    def test_logs_page_and_api_fail_closed_for_invalid_source(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            page = client.get("/logs", params={"source": "invalid"})
            self.assertEqual(page.status_code, 400)
            api = client.get("/api/logs", params={"source": "invalid"})
            self.assertEqual(api.status_code, 400)

    def test_report_file_route_blocks_hidden_files(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            response = client.get("/reports/file/2026-05-31/.env")
            self.assertEqual(response.status_code, 400)

    def test_report_file_route_serves_compact_report(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            response = client.get("/reports/file/2026-05-31/live_report_2026-05-31_asia_bangkok.md")
            self.assertEqual(response.status_code, 200)
            self.assertIn("# report", response.text)

    def test_reports_page_labels_unrealized_pnl(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            response = client.get("/reports")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Unrealized PnL USD", response.text)
            self.assertIn("Unrealized PnL %", response.text)

    def test_history_page_shows_stale_cycle_warning(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            response = client.get("/history")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Latest recorded cycle is stale", response.text)

    def test_control_endpoint_rejects_when_disabled(self):
        client, tmp = self._build_client(controls_enabled=False)
        with tmp:
            self._login(client)
            dashboard = client.get("/")
            csrf = _extract_csrf(dashboard.text)
            response = client.post("/api/control/start", headers={"x-csrf-token": csrf})
            self.assertEqual(response.status_code, 403)

    def test_control_endpoint_rejects_invalid_action_even_when_enabled(self):
        client, tmp = self._build_client(controls_enabled=True)
        with tmp:
            self._login(client)
            dashboard = client.get("/")
            csrf = _extract_csrf(dashboard.text)
            response = client.post("/api/control/reload", headers={"x-csrf-token": csrf})
            self.assertEqual(response.status_code, 400)

    def test_tailscale_allowed_user_can_view_without_password_login(self):
        client, tmp = self._build_tailscale_client()
        with tmp:
            response = client.get("/", headers={"Tailscale-User-Login": "friend@example.com"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("friend@example.com", response.text)

    def test_tailscale_allowed_user_is_redirected_from_login_page(self):
        client, tmp = self._build_tailscale_client()
        with tmp:
            response = client.get(
                "/login",
                headers={"Tailscale-User-Login": "owner@example.com"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/")

    def test_tailscale_disallowed_user_is_forbidden(self):
        client, tmp = self._build_tailscale_client()
        with tmp:
            response = client.get("/", headers={"Tailscale-User-Login": "intruder@example.com"})
            self.assertEqual(response.status_code, 403)

    def test_tailscale_trust_without_allowlist_falls_back_to_login(self):
        client, tmp = self._build_client()
        with tmp:
            app_ctx = client.app.state.ctx
            app_ctx.trust_tailscale_headers = True
            app_ctx.allowed_tailscale_users = frozenset()
            app_ctx.admin_tailscale_users = frozenset()
            response = client.get("/", headers={"Tailscale-User-Login": "friend@example.com"}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/login")

    def test_tailscale_viewer_cannot_use_control_endpoint(self):
        client, tmp = self._build_tailscale_client(controls_enabled=True)
        with tmp:
            dashboard = client.get("/", headers={"Tailscale-User-Login": "friend@example.com"})
            csrf = _extract_csrf(dashboard.text)
            response = client.post(
                "/api/control/start",
                headers={"Tailscale-User-Login": "friend@example.com", "x-csrf-token": csrf},
            )
            self.assertEqual(response.status_code, 403)

    def test_tailscale_admin_can_use_control_endpoint(self):
        client, tmp = self._build_tailscale_client(controls_enabled=True)
        with tmp:
            dashboard = client.get("/", headers={"Tailscale-User-Login": "owner@example.com"})
            csrf = _extract_csrf(dashboard.text)
            response = client.post(
                "/api/control/status",
                headers={"Tailscale-User-Login": "owner@example.com", "x-csrf-token": csrf},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("ok", response.text)

    def test_analyst_api_requires_authentication(self):
        client, tmp = self._build_client()
        with tmp:
            response = client.get("/api/analyst/status")
            self.assertEqual(response.status_code, 401)

    def test_analyst_api_exposes_public_event_shape(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            fake = _FakeAnalystService()
            client.app.state.ctx.analyst_service = fake

            response = client.post("/api/analyst/run", json={"symbol": "BTCUSDT"})

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["recommendation"], "HOLD")
            self.assertNotIn("private_balances", str(data))
            self.assertNotIn("exchange_credentials", str(data))

    def test_analyst_budget_endpoint_uses_service_budget(self):
        client, tmp = self._build_client()
        with tmp:
            self._login(client)
            fake = _FakeAnalystService()
            client.app.state.ctx.analyst_service = fake

            response = client.get("/api/analyst/budget")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["interactive_limit"], 12)

    def test_market_candles_endpoint_uses_public_okx_shape(self):
        client, tmp = self._build_client()
        with tmp, patch("ui.app.fetch_public_candles") as fetch:
            self._login(client)
            fetch.return_value = [
                {
                    "time": 1800000000,
                    "timestamp_ms": 1800000000000,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 12.0,
                    "symbol": "BTCUSDT",
                    "source": "okx_public",
                }
            ]

            response = client.get("/api/market/candles?symbol=BTCUSDT&interval=1h&limit=50")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["source"], "okx_public")
            self.assertEqual(data["candles"][0]["close"], 100.5)
            self.assertNotIn("api_key", str(data).lower())
            fetch.assert_called_once_with(symbol="BTCUSDT", interval="1h", limit=50)

    def test_market_candles_rejects_unsupported_inputs(self):
        client, tmp = self._build_client()
        with tmp, patch("ui.app.fetch_public_candles", side_effect=ValueError("Unsupported symbol.")):
            self._login(client)

            response = client.get("/api/market/candles?symbol=DOGEUSDT&interval=1h")

            self.assertEqual(response.status_code, 400)


class _FakeBudget:
    def snapshot(self):
        return {
            "day": "2026-07-11",
            "background_used": 0,
            "background_limit": 8,
            "interactive_used": 0,
            "interactive_limit": 12,
        }


class _FakeAnalystService:
    def __init__(self):
        self.budget = _FakeBudget()
        self.event = AnalystEvent(
            event_type="analysis",
            status="ok",
            title="BTC analyst update",
            message="No decisive edge.",
            symbol="BTCUSDT",
            role="main_analyst",
            recommendation="HOLD",
            payload={"private_balances": {"USDT": 1}, "public": True},
        )

    def status(self):
        return AnalystStatus(enabled=True, events_count=1, budgets=self.budget.snapshot(), latest_event=self.event.to_public_dict())

    def run_update(self, **kwargs):
        return self.event

    def ask(self, **kwargs):
        return self.event

    def validate(self, **kwargs):
        return self.event

    def explain(self, **kwargs):
        return self.event

    def latest_news(self, **kwargs):
        return self.event

    def events(self, limit=None):
        return [self.event.to_public_dict()]

    def signals(self, limit=None):
        return [self.event.to_public_dict()]


if __name__ == "__main__":
    unittest.main()
