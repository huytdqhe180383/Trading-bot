# Secure Private UI Read-Only Release

## Summary

Implemented the first private UI release for bot management with a
security-first posture:

- FastAPI + Jinja2 + HTMX-friendly server-rendered UI
- read-only dashboard, reports, history, and logs pages
- login-protected access
- CSRF protection on POST routes
- rate limiting on login and control attempts
- control routes present but disabled by default
- safe report-file and log-source handling
- audit logging to `logs/ui_audit.jsonl`

This release is intentionally **read-only first**. The control surface is not
part of the deployment default.

## Repo Changes

Primary implementation files:

- [ui/app.py](../../../ui/app.py)
- [ui/services.py](../../../ui/services.py)
- [ui/templates/base.html](../../../ui/templates/base.html)
- [ui/templates/login.html](../../../ui/templates/login.html)
- [ui/templates/dashboard.html](../../../ui/templates/dashboard.html)
- [ui/templates/reports.html](../../../ui/templates/reports.html)
- [ui/templates/history.html](../../../ui/templates/history.html)
- [ui/templates/logs.html](../../../ui/templates/logs.html)
- [ui/static/app.css](../../../ui/static/app.css)
- [ui/static/app.js](../../../ui/static/app.js)
- [ui/static/manifest.webmanifest](../../../ui/static/manifest.webmanifest)
- [scripts/run_ui.py](../../../scripts/run_ui.py)
- [scripts/server/trading-bot-ui.service.example](../../../scripts/server/trading-bot-ui.service.example)

Tests added:

- [tests/test_ui_services.py](../../../tests/test_ui_services.py)
- [tests/test_ui_app.py](../../../tests/test_ui_app.py)

Configuration updates:

- [config.py](../../../config.py)
- [.env.example](../../../.env.example)
- [requirements-live.txt](../../../requirements-live.txt)
- [requirements.txt](../../../requirements.txt)

## Security Baseline

Canonical security document:

- [secure_private_ui_security_baseline.md](../../important/secure_private_ui_security_baseline.md)

Deployment guide:

- [digitalocean_private_ui_deployment_guide.md](../../../docs/digitalocean_private_ui_deployment_guide.md)

## Verification

Targeted UI test suite:

```text
python -m unittest tests.test_ui_services tests.test_ui_app
```

Status:

- passed: `18` tests

Key behaviors covered:

- login required
- invalid credentials rejected
- logout invalidates session
- login rate limit enforced
- invalid log/report selectors fail closed
- hidden report files blocked
- controls rejected while disabled
- invalid control verbs rejected
- strategy NAV note rendered

## Notes

- The UI is ready for a private read-only deployment on the Droplet.
- The correct server posture for the upcoming paper-trading week is:
  - Tailscale only
  - `UI_BIND_HOST=127.0.0.1`
  - `UI_ENABLE_CONTROLS=false`
