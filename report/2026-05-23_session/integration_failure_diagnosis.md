# Kronos and TradingAgents Integration Failure Diagnosis

## Conclusion

The poor matrix results came from two related but distinct causes:

1. TradingAgents did not run as a native LLM decision engine during the matrix. It exhausted providers and degraded to the local heuristic path.
2. The fusion layer converted external signals into active portfolio tilts on every bar, increasing turnover and cash drift in a high-cost hourly backtest.

Kronos was available natively, but its small directional tilts did not produce enough edge to overcome the extra turnover and compounding fees. TradingAgents was worse because its fallback heuristic also pushed the portfolio materially more defensive during periods where the RL-only policy benefited from staying risk-on.

## Evidence From The Matrix

| Pipeline | Return % | Sharpe | Max DD % | Trades |
| --- | ---: | ---: | ---: | ---: |
| `rl_only` | `10.42` | `0.0919` | `-58.45` | `8215` |
| `rl_kronos` | `-43.17` | `-0.5471` | `-66.09` | `8444` |
| `rl_tradingagents` | `-40.71` | `-0.5389` | `-63.72` | `7929` |
| `rl_full` | `-40.79` | `-0.5401` | `-63.76` | `7945` |

## Provider Failure

`artifacts/logs/matrix_run.err` shows:

- Kronos initialized successfully with `NeoQuasar/Kronos-mini` on `cuda:0`.
- TradingAgents `openai` failed with `401 Invalid token`.
- TradingAgents `groq` failed with `429 rate_limit_exceeded` and `413 request too large`.
- TradingAgents `ollama` initialized with `qwen3.5:4b`, then timed out repeatedly at `45s`.
- After the provider chain was exhausted, TradingAgents used `heuristic`.

The decision log confirms this:

- `tradingagents_decisions.jsonl` rows inspected: `154,065`
- Native TradingAgents rows: `0`
- Heuristic rows: `154,065`

So `rl_tradingagents` and `rl_full` were not testing real TradingAgents intelligence. They were testing the fallback momentum/risk heuristic plus the fusion layer.

## Turnover And Cost Drag

The live-like profile uses fee `0.0012` plus slippage `0.0018`, so every traded weight unit costs about `0.003`.

Observed cumulative transaction-cost pressure:

| Pipeline | Turnover Sum | Transaction Cost Sum | Cost Multiplier |
| --- | ---: | ---: | ---: |
| `rl_only` | `896.92` | `2.6907` | `0.0678` |
| `rl_kronos` | `1096.63` | `3.2897` | `0.0372` |
| `rl_tradingagents` | `1017.73` | `3.0530` | `0.0472` |
| `rl_full` | `1017.69` | `3.0529` | `0.0472` |

The overlays increased cumulative transaction cost by roughly:

- Kronos: `+0.5990` cost units versus RL-only
- TradingAgents fallback: `+0.3623` cost units versus RL-only
- Full: `+0.3622` cost units versus RL-only

Because portfolio value is multiplied by `(1 - transaction_cost)` every step, these differences compound heavily across `18,930` bars.

## Gross Edge Was Not Enough

Estimated gross return before transaction cost:

| Pipeline | Net Return % | Estimated Gross Before Cost % |
| --- | ---: | ---: |
| `rl_only` | `10.42` | `1529.84` |
| `rl_kronos` | `-43.17` | `1427.51` |
| `rl_tradingagents` | `-40.71` | `1157.38` |
| `rl_full` | `-40.79` | `1155.69` |

Kronos was only slightly worse than RL-only before costs, but it paid much more turnover cost. TradingAgents fallback was worse both before and after costs.

## Allocation Drift

Compared with RL-only, the overlays increased cash and reduced crypto exposure:

| Pipeline | Average Cash | Average Cash Increase vs RL | Average Risk-On |
| --- | ---: | ---: | ---: |
| `rl_only` | `0.0759` | `0.0000` | `0.9241` |
| `rl_kronos` | `0.1077` | `0.0318` | `0.8923` |
| `rl_tradingagents` | `0.1474` | `0.0715` | `0.8526` |
| `rl_full` | `0.1473` | `0.0714` | `0.8527` |

That defensive drift hurt during the test period because the RL-only policy earned much of its edge by staying highly exposed during strong rebound months.

## Signal Timing Quality

The overlay tilts had almost no predictive alignment with next-bar returns:

| Pipeline | Mean Tilt Edge, bp/bar | Positive Tilt Edge Share |
| --- | ---: | ---: |
| `rl_kronos` | `0.0104` | `0.4911` |
| `rl_tradingagents` | `-0.0168` | `0.4909` |
| `rl_full` | `-0.0161` | `0.4901` |

Kronos produced a tiny positive raw tilt edge, but not enough to pay for churn. TradingAgents fallback produced negative tilt edge.

## Implementation Mechanism

The fusion layer in `agents/meta_fusion_agent.py` applies external signals directly:

- Kronos adds or removes up to `MAX_TILT_PER_SIGNAL = 0.05` per asset.
- TradingAgents shifts up to `0.05` between cash and assets.
- TradingAgents high-risk mode can force `cash_floor = 0.35` and `max_asset_weight = 0.45`.
- Global constraints then cap per-step turnover at `0.25`, but they do not require external signals to prove edge before modifying the RL policy.

This means low-quality or fallback signals are allowed to trade, not just annotate.

## Root Cause

The integration underperformed because the overlay layer was trusted too much relative to its verified predictive value.

Kronos:

- native backend worked
- signal edge was too small
- turnover cost overwhelmed the edge

TradingAgents:

- native backend did not work in the matrix
- fallback heuristic drove the result
- fallback increased cash exposure and added churn
- prompt/provider footprint is too large for current Groq/Ollama path

Full pipeline:

- behaved almost identically to TradingAgents fallback
- Kronos could not overcome the TradingAgents/risk-governor drag

## Recommended Fix Direction

1. Make overlays advisory-only by default in backtest.
2. Only allow external tilts when the signal source is native and recent.
3. Add a minimum expected-edge gate before any external tilt can trade.
4. Reduce `MAX_TILT_PER_SIGNAL` for backtests from `0.05` to a much smaller value such as `0.01`.
5. Add a turnover budget for external overlays separate from the RL base policy.
6. Compress TradingAgents input before using Groq/Ollama again.
7. Record Kronos and TradingAgents diagnostics into episode parquet so future matrix runs can explain performance without rerunning inference.
