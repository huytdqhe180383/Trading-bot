import re
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from fastapi.testclient import TestClient

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


if __name__ == "__main__":
    unittest.main()
