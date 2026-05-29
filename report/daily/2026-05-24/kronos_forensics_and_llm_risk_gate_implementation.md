# Kronos Forensics + LLM Risk Gate Implementation (MA Ignored)

Date: 2026-05-24

## What Was Implemented

1. Kronos failure forensics pipeline (deterministic)
- Added `scripts/kronos_failure_forensics.py`.
- Compares `rl_only` vs `rl_kronos` decision logs step-by-step.
- Produces:
  - allocation drift deltas (`delta_target_btc/eth/cash`)
  - turnover/cost delta contributions
  - gap accumulation by month
  - top loss events with Kronos tilt/scores/confidence + risk-governor state + post-constraint target
  - mechanism labels (`kronos_de_risk`, `kronos_re_risk`, `constraint_clipped`, `high_churn_no_gain`)

2. Fusion diagnostics instrumentation (code-level)
- Extended per-step diagnostics with:
  - per-symbol Kronos directional score/confidence
  - per-symbol Kronos tilt
  - pre/post-constraint weights
  - turnover pre/post clip and clip ratio
  - constraint-clipped flag
  - mechanism label
- Added guardrail metrics:
  - `% steps external overlay changes action > 0.02`
  - `% reversals within 3 steps`

3. LLM Risk Gate architecture (local Ollama only)
- Added `adapters/llm_risk_gate_adapter.py`.
- Added `rl_llm_risk_gate` pipeline.
- Behavior:
  - RL remains base allocator.
  - LLM emits only `allow | de-risk | block`.
  - low-cadence cache + daily call budget.
  - if unavailable/timeout, fallback is `allow` (no override).
- Critical fix applied:
  - when LLM signal is `allow` (or timeout fallback to `allow`) and no other overlays are active, fusion returns RL unchanged.

4. Config/interface additions
- `LLM_RISK_GATE_ENABLED`
- `LLM_RISK_GATE_CADENCE`
- `LLM_RISK_GATE_CACHE_TTL`
- `LLM_RISK_GATE_MAX_CALLS_PER_DAY`
- `LLM_RISK_GATE_MODE`
- `LLM_RISK_GATE_TIMEOUT_SECS`
- `LLM_RISK_GATE_MAX_RETRIES`
- `LLM_RISK_GATE_DECISION_LOG_PATH`

## Validation Runs (live_like + dynamic_weighted)

- `rl_only`: `results/daily/2026-05-24/8`
- `rl_kronos`: `results/daily/2026-05-24/9`
- `rl_llm_risk_gate`: `results/daily/2026-05-24/10`

Consolidated matrix artifacts:
- `results/daily/2026-05-24/risk_gate_matrix_eval/risk_gate_matrix_metrics.csv`
- `results/daily/2026-05-24/risk_gate_matrix_eval/risk_gate_matrix_delta_vs_rl_only.csv`
- `results/daily/2026-05-24/risk_gate_matrix_eval/risk_gate_churn_check.csv`
- `results/daily/2026-05-24/risk_gate_matrix_eval/risk_gate_matrix_equity_curve.png`

## Key Results

1. Kronos degradation remains large and structural
- `rl_only`: `107.06%` return, Sharpe `0.8492`, max DD `-36.78%`.
- `rl_kronos`: `-7.82%` return, Sharpe `-0.1053`, max DD `-43.14%`.
- Delta vs RL-only: `-114.88` pts return, `+34.19%` turnover, `+34.15%` tx-cost term.

2. Risk-gate fallback safety verified
- `rl_llm_risk_gate` matches `rl_only` within floating-point noise.
- Churn check confirms no LLM-induced execution churn:
  - `action_delta_l1 > 0.01` rate = `0.0`
  - max action delta = `3.23e-07`

3. LLM runtime behavior observed
- Ollama timed out for cadence calls in this run.
- Gate degraded safely to `allow`; `llm_risk_applied_count = 0`.
- Call/cache telemetry still worked:
  - attempt count = `125`
  - cache-hit count = `20809`

## Kronos Forensics Artifacts

- `results/daily/2026-05-24/kronos_failure_forensics/kronos_step_attribution.csv`
- `results/daily/2026-05-24/kronos_failure_forensics/kronos_monthly_gap_accumulation.csv`
- `results/daily/2026-05-24/kronos_failure_forensics/kronos_mechanism_summary.csv`
- `results/daily/2026-05-24/kronos_failure_forensics/kronos_top_loss_events.csv`
- `results/daily/2026-05-24/kronos_failure_forensics/kronos_forensics_summary.json`

Locked findings from latest forensics run:
- Kronos changed targets on `20934/20934` steps.
- Avg target cash shift: `+0.1349`.
- Lower risk-on on `93.79%` of steps.
- Final NAV gap vs RL-only: `-55.48%`.
- Step-level attribution reconstruction error: `0.0` (exact nav-gap consistency).
