# Seed Audit + Champion Overlay Report

## Scope
- Added automatic best-model preservation when a backtest clears `> 70%` total return.
- Audited the Phase 1 identical-seed failure.
- Evaluated deterministic post-policy overlays on the protected `107.06%` champion without retraining.

## Protection Outcome
- The protected champion was re-run from `results/important/model_backups/2026-05-24_107pct_baseline/models`.
- Autosave is now live in `backtest.py` and preserved qualifying runs under `models/best/2026-05-27/`.
- New baseline-preservation snapshots were created at:
  - `models/best/2026-05-27/1`
  - `models/best/2026-05-27/2`
  - `models/best/2026-05-27/3`

## Phase 1 Seed Audit
Evidence file: [`../../../results/daily/2026-05-27/phase1_seed_policy_audit.csv`](../../../results/daily/2026-05-27/phase1_seed_policy_audit.csv)

Findings:
- Phase 1 metrics were exactly identical across seeds `42`, `1337`, and `2026`.
- Checkpoint archive hashes differed across seeds, so this was not a file-copy bug.
- PPO policy digests were identical across all 3 seeds.
- SAC policy digests were identical across all 3 seeds.
- First-step deterministic actions and implied weights were also identical across all 3 seeds.

Interpretation:
- The different seed runs produced different archive containers, but not different effective policies.
- The most likely cause was resume-path determinism: resumed SB3 models were loaded from checkpoint without explicitly reapplying the requested seed to the loaded model state.
- In a deterministic environment, that makes a seed sweep much less meaningful because action sampling / replay sampling can effectively continue from the same RNG path.

Fix applied:
- `train.py` now routes resume loading through `_load_resumed_model(...)` and explicitly calls `model.set_random_seed(seed)` after `cls.load(...)`.
- This is a forward fix. I did not rerun the full Phase 1 matrix in this pass.

## Champion Overlay Experiments
Summary file: [`../../../results/daily/2026-05-27/champion_overlay_summary.csv`](../../../results/daily/2026-05-27/champion_overlay_summary.csv)

Backtest sessions:
- Baseline champion: [`../../../results/daily/2026-05-27/1`](../../../results/daily/2026-05-27/1)
- Combined overlay: [`../../../results/daily/2026-05-27/2`](../../../results/daily/2026-05-27/2)
- Turnover-only overlay: [`../../../results/daily/2026-05-27/3`](../../../results/daily/2026-05-27/3)
- Vol-target no-op `0.05`: [`../../../results/daily/2026-05-27/4`](../../../results/daily/2026-05-27/4)
- Vol-target no-op `0.02`: [`../../../results/daily/2026-05-27/5`](../../../results/daily/2026-05-27/5)
- Vol-target active `0.003`: [`../../../results/daily/2026-05-27/6`](../../../results/daily/2026-05-27/6)

Key results:
- Baseline champion remains the best result in this pass: `107.06%` return, `0.8492` Sharpe, `-36.78%` max drawdown.
- Combined overlay failed badly: `-7.68%` return, `-0.1035` Sharpe, `-42.58%` max drawdown.
- Turnover-persistence-only failed badly: `-12.79%` return, `-0.1809` Sharpe, `-44.80%` max drawdown.
- Vol-target-only at `0.05` and `0.02` was an exact no-op because the realized hourly volatility proxy was too low to trigger scaling.
- Realized proxy stats from the baseline run:
  - mean `0.0040`
  - p95 `0.0072`
- Vol-target-only became active at `0.003`, reducing average risk-on and turnover, but still hurt the champion materially: `31.47%` return, `0.3753` Sharpe, `-35.17%` max drawdown.

Interpretation:
- This champion depends on relatively aggressive, unconstrained reallocations.
- Hard post-policy turnover smoothing is not compatible with its learned control law.
- Always-on absolute volatility targeting is too blunt: loose thresholds do nothing, while active thresholds suppress the edge faster than they improve drawdown.
- The current best model should not be promoted behind these overlays.

## Recommendation
Do not continue with hard post-policy overlays as the main improvement path for the current champion.

Better next ideas:
1. Re-run the seed experiments after the resume-seed fix so future comparisons are valid.
2. Move turnover control back into training-time incentives rather than a hard post-policy cap.
3. Replace absolute volatility targeting with regime-conditioned activation, using thresholds anchored to the observed `0.0040 / 0.0072` proxy distribution.
4. Explore ensemble diversification or regime-conditioned model selection, instead of forcing one champion policy through a deterministic external clamp.
