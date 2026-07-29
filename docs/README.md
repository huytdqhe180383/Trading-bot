# Documentation Map

Documents are grouped by the decision they help you make. Start with the
repository map when you are looking for code and with the architecture overview
when you are changing behavior.

## Understand The System

- [Architecture overview](architecture.md)
- [Repository map](development/repository_map.md)
- [Operational persistence](architecture/persistence.md)
- [Runtime spine](architecture/runtime_spine.md)
- [Domain language](../CONTEXT.md)

## Make A Change

- [Contributing and verification](../CONTRIBUTING.md)
- [Scripts map](../scripts/README.md)
- [Trading environment](trading_env_documentation.md)

## Operate The System

- [Paper-trading command cheatsheet](digitalocean_paper_trading_command_cheatsheet.md)
- [Live deployment guide](digitalocean_live_deployment_guide.md)
- [Private UI deployment](digitalocean_private_ui_deployment_guide.md)
- [Shared Tailscale access](shared_private_ui_tailscale_guide.md)
- [RX6700XT ROCm training](rx6700xt_rocm_training.md)
- [ROCm runtime architecture](rocm_runtime_architecture.md)

## Decisions

- [ADR 0001: application spine and artifact runtime](adr/0001-application-spine-and-artifact-runtime.md)
- [ADR 0002: operational SQLite and artifact separation](adr/0002-operational-sqlite-and-artifact-separation.md)

## Session Reports

Current experiments, audits, and implementation summaries live under
`report/daily/YYYY-MM-DD/`. Durable decisions and security baselines live under
`report/important/`; they are evidence, not evergreen documentation.

Obsolete point-in-time audits, rubrics, completed implementation plans, and the
unmaintained research Word document were removed in July 2026. Git history
retains them if historical context is ever needed.
