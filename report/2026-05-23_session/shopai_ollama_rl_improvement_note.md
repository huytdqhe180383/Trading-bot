# ShopAI/Ollama Reconfiguration And RL Improvement Note

## What Changed

- TradingAgents provider order is now `shopai -> ollama`.
- ShopAI uses `SHOPAIKEY_API_KEY` and defaults to `https://api.shopaikey.com/v1`.
- TradingAgents no longer emits heuristic fallback trades.
- Kronos no longer emits heuristic fallback trades.
- If an overlay is unavailable, fusion receives no signal and the RL allocation remains the active policy.

## Why

The previous matrix showed that fallback heuristic signals were allowed to trade. That made the overlay ablations measure fallback behavior instead of real Kronos or TradingAgents value. This pass changes unavailable overlays into no-ops so future matrices isolate native overlay value cleanly.

## RL Layer Improvements

- Training model selection now uses a chronological validation slice from the training split instead of the final test/backtest split.
- Training has deterministic seed plumbing through config and CLI.
- Backtest episode output now includes per-model PPO/SAC proposal weights, ensemble weights, final target weights, overlay availability, and overlay source fields.
- Matrix rows now include turnover, transaction cost, cash exposure, risk-on exposure, and cost-drag diagnostics.
- Optional RL-only ensemble comparison can be run with:

```powershell
python backtest.py --compare-ensemble-methods --realism-profile live_like
```

## Next Evaluation

Run the ablation matrix after this change and verify:

- ShopAI attempts are visible in logs as `provider=shopai`.
- No new decision rows use `source="heuristic"`.
- Unavailable Kronos/TradingAgents overlays behave like RL-only for allocation.
- `results/backtest_rl_diagnostics.csv` explains turnover/cost/cash differences.

## Post-Implementation Results

The rerun matrix now shows unavailable overlays behaving as no-op layers:

| Pipeline | Return % | Sharpe | Max DD % | Trades |
| --- | ---: | ---: | ---: | ---: |
| `rl_only` | `10.42` | `0.0919` | `-58.45` | `8215` |
| `rl_kronos` | `10.42` | `0.0919` | `-58.45` | `8215` |
| `rl_tradingagents` | `10.42` | `0.0919` | `-58.45` | `8215` |
| `rl_full` | `10.42` | `0.0919` | `-58.45` | `8215` |

ShopAI calls are visible in `logs/matrix_run_shopai_ollama.out` as `provider=shopai`. ShopAI timed out after five attempts, then Ollama was attempted and returned connection errors. New decision-log rows use `signal: null`; no new `source="heuristic"` rows were produced.

The RL-only ensemble method comparison shows `dynamic_weighted` as the best current method:

| Method | Return % | Sharpe | Max DD % | Trades |
| --- | ---: | ---: | ---: | ---: |
| `mean` | `10.42` | `0.0919` | `-58.45` | `8215` |
| `weighted` | `10.42` | `0.0919` | `-58.45` | `8215` |
| `dynamic_weighted` | `28.30` | `0.2284` | `-56.56` | `7549` |
| `imca` | `-42.05` | `-0.5109` | `-65.47` | `9753` |
| `voting` | `-99.78` | `-5.4811` | `-99.81` | `3030` |

Recommended RL next step: promote `dynamic_weighted` as the default candidate for the next evaluation run, and treat `voting` and current `imca` as disabled until redesigned.
