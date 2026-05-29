# RL Pipeline Evaluation (Ollama + Dynamic Weighted)

Date: 2026-05-24  
Scope: Completed the remaining two pipelines and re-ran all four for apples-to-apples comparison under identical settings.

## Run Configuration

- realism_profile: `live_like`
- ensemble_method: `dynamic_weighted`
- provider mode for MA: `ollama` only
- compared pipelines:
  - `rl_only`
  - `rl_kronos`
  - `rl_tradingagents`
  - `rl_full`

## Canonical Artifacts

- Consolidated analysis folder: `../../../results/daily/2026-05-24/pipeline_evaluation_ollama_dynamic_weighted/`
- Source run folders:
  - `../../../results/daily/2026-05-24/2/` (`rl_tradingagents`)
  - `../../../results/daily/2026-05-24/3/` (`rl_full`)
  - `../../../results/daily/2026-05-24/4/` (`rl_only`)
  - `../../../results/daily/2026-05-24/5/` (`rl_kronos`)

## Headline Results

| Pipeline | Total Return | Sharpe | Max DD | Trades |
|---|---:|---:|---:|---:|
| rl_only | 107.06% | 0.8492 | -36.78% | 14,660 |
| rl_tradingagents | 107.06% | 0.8492 | -36.78% | 14,660 |
| rl_kronos | -7.82% | -0.1053 | -43.14% | 16,654 |
| rl_full | -7.82% | -0.1053 | -43.14% | 16,654 |

## Core Findings

1. TradingAgents overlay is currently a no-op in this setup.
- Evidence: `rl_only` and `rl_tradingagents` are numerically identical within floating point noise.
- Evidence: `tradingagents_available_rate = 0.0` and `fusion_has_trading_signal_rate = 0.0` for both TA-enabled pipelines.
- Interpretation: MA layer did not contribute actionable signals in these runs (effectively RL-only behavior).

2. Kronos overlay fully dominates the degradation.
- Evidence: `rl_kronos` and `rl_full` are numerically identical across all major KPIs.
- Evidence: `kronos_available_rate = 1.0`, `fusion_has_kronos_rate = 1.0` on Kronos-enabled runs.
- Delta vs RL-only:
  - return: `-114.88` percentage points
  - sharpe: `-0.9544`
  - max drawdown: `-6.36` percentage points worse
  - trades: `+1,994`
  - turnover: `+180.82` (34.2% higher)
  - cumulative transaction-cost term: `+0.5399` (34.1% higher)

3. Monthly behavior confirms persistent Kronos underperformance, not one isolated month.
- Evidence: Kronos underperformed RL-only in `27/28` months.
- Mean monthly delta (Kronos minus RL-only): `-2.94` percentage points.
- Worst month delta: `2024-11` at `-14.27` percentage points.

4. Stress window (Sep 2025 to Feb 2026): Kronos worsened drawdown period outcomes.
- `rl_only`: `-23.14%`
- `rl_kronos`: `-32.36%`
- Additional turnover/cost during this window:
  - turnover `95.35 -> 145.16` (+52.2%)
  - transaction-cost term `0.2853 -> 0.4337` (+52.0%)
- Both variants hit trough on `2026-02-06`, but Kronos path was materially lower.

5. Kronos changed allocation shape in a way that hurt net performance.
- Avg target cash weight:
  - RL-only: `3.45%`
  - Kronos-enabled: `16.94%`
- Actual avg cash weight:
  - RL-only: `32.05%`
  - Kronos-enabled: `38.60%`
- Interpretation: Kronos made the strategy less invested and more active simultaneously, which reduced upside capture and increased frictional drag.

## Root-Cause Hypothesis (Evidence-Backed)

Primary cause: Kronos overlay calibration mismatch to current RL policy/regime.

- Signal influence appears too strong or poorly aligned with realized return horizon.
- It increases rebalance churn and cost while not improving tail protection enough.
- This produces a structurally inferior risk-return path vs pure RL in the same environment.

Secondary cause: MA overlay unavailability means no compensating external signal.

- Because TA is no-op here, `rl_full` collapses to Kronos behavior, so there is no diversification benefit from MA.

## What This Means For Next Iteration

- Treat current Kronos fusion settings as failing in this configuration.
- Prioritize Kronos influence controls and gating diagnostics before relying on `rl_full`.
- Keep `rl_only` as operational baseline until Kronos deltas turn positive in out-of-sample checks.

## Files Produced In This Pass

Under `../../../results/daily/2026-05-24/pipeline_evaluation_ollama_dynamic_weighted/`:

- `pipeline_metrics_comparison.csv`
- `pipeline_delta_vs_rl_only.csv`
- `pipeline_monthly_returns.csv`
- `pipeline_monthly_returns_pivot.csv`
- `pipeline_monthly_returns_with_deltas.csv`
- `pipeline_sep2025_feb2026_focus.csv`
- `pipeline_drawdown_points.csv`
- `monthly_cumulative_gap_kronos_vs_rl_only.csv`
- `monthly_cumulative_gap_full_vs_tradingagents.csv`
- `equity_curve_all_pipelines.png`
- `turnover_transaction_cost_comparison.png`
