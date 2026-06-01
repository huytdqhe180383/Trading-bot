# Secure Private UI Security Baseline

## Purpose

This document defines the security contract for the trading-bot private UI.
It is the baseline for the read-only release and the gate for any later control
features.

Canonical runtime posture:

- private use only
- Tailscale-only access
- phone-friendly browser or PWA shell
- no public ingress
- admin-only service controls
- no arbitrary shell access

## Assets To Protect

Primary assets:

- exchange credentials
- `.env` and session secrets
- trading-bot runtime control
- Tailscale allowlists and role mapping
- bot logs and reports
- live strategy visibility

Secondary assets:

- system journal visibility
- local filesystem layout
- service names and operational metadata

## Threat Model

### In-scope threats

- an unauthenticated user reaching the UI
- a tailnet user not in the UI allowlist trying to browse reports/logs
- CSRF against any state-changing endpoint
- brute-force login attempts
- path traversal against logs/report download routes
- accidental exposure of `.env` or arbitrary files
- accidental public exposure through a reverse proxy or open firewall
- command injection through bot-control endpoints

### Out-of-scope threats

- full Droplet compromise by root or cloud-provider compromise
- malware already running as the `deploy` user
- theft of the user’s unlocked phone/browser session

These are still operational risks, but they are not solved by this UI alone.

## Trust Boundaries

### Boundary 1: Public internet -> Droplet

Policy:

- UI must not be reachable from the public internet in v1
- no public DNS
- no public reverse proxy
- no Funnel

Expected configuration:

- app bound to `127.0.0.1` or a Tailscale-only interface
- access brokered only by Tailscale

### Boundary 2: Tailnet user -> UI session

Policy:

- Tailscale presence is necessary but not sufficient
- UI requires app-layer authentication or an explicit trusted Tailscale identity
- trusted identities must be allowlisted

Mechanisms:

- `UI_USERNAME`
- `UI_PASSWORD`
- signed session cookie
- HTTP-only cookie
- optional `Tailscale-User-Login` trust when the app is bound to localhost and
  fronted by Tailscale Serve

### Boundary 3: Authenticated user -> State-changing endpoints

Current policy:

- viewer sessions are read-only
- admin sessions may use start/stop/restart/status only
- Tailscale friends should remain viewer-only unless explicitly promoted

Protection model:

- auth required
- CSRF token required
- rate limiting required
- exact action allowlist required

### Boundary 4: UI app -> Filesystem / process control

Policy:

- read only from known report/log locations
- never expose `.env`
- never provide arbitrary file reads
- never execute arbitrary commands

Allowed read locations:

- `results/daily/`
- `report/daily/`
- `logs/live_stdout.log`
- `logs/live_stderr.log`
- service status and journal adapters

Future control boundary:

- exact-command allowlist only
- `systemctl status trading-bot`
- `systemctl start trading-bot`
- `systemctl stop trading-bot`
- `systemctl restart trading-bot`

## Failure Modes And Expected Behavior

### Bad credentials

Expected behavior:

- reject login
- do not reveal which field was wrong
- write audit event

### Excessive login attempts

Expected behavior:

- return rate-limit response
- do not create session
- write audit event

### Missing or invalid CSRF token

Expected behavior:

- reject POST request
- do not perform state change

### Invalid report or log selector

Expected behavior:

- fail closed
- return `400` or `404`
- do not leak arbitrary file contents

### Missing log/report artifact

Expected behavior:

- UI should remain usable
- page/API returns an unavailable message instead of crashing

### Bot service stopped

Expected behavior:

- dashboard still loads
- status surface shows inactive state
- reports/history continue to load from artifacts

## Lockout Behavior

Read-only release lockout is temporary, not permanent.

Policy:

- repeated bad logins are rate-limited
- valid credentials should work again after the rate-limit window expires
- no automatic account disabling in v1

Reasoning:

- single private operator use
- better operational resilience during paper-trading week
- lower risk of self-lockout while still slowing brute-force attempts

## Audit Logging

Runtime audit log:

- `logs/ui_audit.jsonl`

Events that must be logged:

- successful login
- successful Tailscale auto-auth
- failed login
- rate-limited login
- logout
- denied page access
- denied API access
- denied Tailscale auth
- control attempts

Retention note:

- runtime audit events stay under `logs/`
- this baseline document is the durable security record under `report/important/`
- incident summaries or postmortems derived from audit logs should be stored
  under `report/important/` or `report/daily/YYYY-MM-DD/` as appropriate

## Read-Only Release Checklist

Required before deployment:

1. bind only to localhost or Tailscale interface
2. Tailscale-only access path
3. app auth configured
4. session secret configured
5. control routes role-gated and exact-action only
6. invalid log/report paths fail closed
7. no `.env` or arbitrary file exposure
8. audit log writable
9. tests for auth, CSRF, path safety, and admin/viewer controls all passing

## Phase 3 Control Gate

Controls may remain enabled only while:

1. exact `sudoers` allowlist is installed
2. control actions stay limited to `start`, `stop`, `restart`, `status`
3. audit logging is verified for each control attempt
4. Tailscale allowlists are kept current
5. non-admin users remain viewer-only by default
