# UI Deployment And Shared Access Status

## What Was Completed

Server-side progress completed on the DigitalOcean Droplet:

- uploaded the new UI package and runner files
- updated `requirements-live.txt` dependencies on the server venv
- seeded UI environment variables into `/home/deploy/trading-bot/.env`
- started the UI process manually as `deploy`
- added a user-level `crontab` keepalive and `@reboot` entry as an interim
  non-root persistence layer
- verified:
  - `GET /health` returns `{"status":"ok"}`
  - password login succeeds
  - dashboard renders successfully after login

Code-level progress completed in the repo:

- optional trusted Tailscale identity auth
- explicit Tailscale allowlist
- admin vs viewer role separation
- admin-only control gating
- phone-usable control forms with confirmation prompts
- shared-access guide and updated deployment docs

## Current Server Runtime State

Current UI process:

- command: `python scripts/run_ui.py`
- bind: `127.0.0.1:8080`
- user: `deploy`

Current status:

- the UI is available locally on the Droplet
- it has a non-root cron-based keepalive fallback
- the existing trading bot remains running
- the UI is **not yet exposed to friends** because the final Tailscale auth
  step has not been approved in the browser yet
- there is now a rootless Tailscale fallback that does not require root to
  start `tailscaled` in userspace mode

## Blocking Condition

The cleanest production-sharing path still benefits from privileged access:

1. install Tailscale
2. configure `tailscale serve`
3. install or enable a persistent `trading-bot-ui` service with `systemd`
4. optionally add `sudoers` allowlisting for safe start/stop/restart control

The repo now includes scripted versions of those steps:

- [install_private_ui_root.sh](../../../scripts/server/install_private_ui_root.sh)
- [install_tailscale_ui_root.sh](../../../scripts/server/install_tailscale_ui_root.sh)
- [trading-bot-ui.sudoers.example](../../../scripts/server/trading-bot-ui.sudoers.example)
- [start_rootless_tailscale_ui.sh](../../../scripts/server/start_rootless_tailscale_ui.sh)
- [enable_rootless_tailscale_serve.sh](../../../scripts/server/enable_rootless_tailscale_serve.sh)

The current SSH user `deploy` can now:

- inspect the server
- run the UI manually
- start rootless `tailscaled`
- capture the Tailscale login URL into
  `/home/deploy/trading-bot/.tailscale/auth_url.txt`

The remaining required step for the rootless path is:

1. open the saved Tailscale login URL in the browser
2. finish authentication into the target tailnet
3. run `enable_rootless_tailscale_serve.sh`

## Follow-Up UX Fix

After enabling trusted Tailscale headers, allowed users no longer need to type
the fallback UI password on `/login`.

The UI now auto-redirects an allowed Tailscale identity from `/login` to `/`,
which removes the confusing "Invalid credentials" path for normal tailnet
access from the phone browser.

## Security-Safe Recommendation

Do not expose the UI publicly on `0.0.0.0` as a workaround.

The intended and documented deployment path is:

- keep app bound to localhost
- use Tailscale Serve for friend access
- use Tailscale identity allowlists for viewer/admin roles

## Related Docs

- [shared_private_ui_tailscale_guide.md](../../../docs/shared_private_ui_tailscale_guide.md)
- [digitalocean_private_ui_deployment_guide.md](../../../docs/digitalocean_private_ui_deployment_guide.md)
- [secure_private_ui_security_baseline.md](../../important/secure_private_ui_security_baseline.md)
