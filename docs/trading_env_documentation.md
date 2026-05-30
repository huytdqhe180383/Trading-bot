# FinRL-X Trading Environment Documentation

Here is a detailed breakdown of the FinRL-X Trading Environment's structure, specifically focusing on its action space, environment observations, and the reward system designed for generic BTC/ETH/USDT spot portfolio trading.

## High-Level Summary
The `SpotPortfolioEnv` is a custom `gymnasium` environment designed to train Reinforcement Learning agents for multi-asset spot trading (BTC and ETH) alongside a cash (USDT) buffer. Instead of discrete buy/sell units, the agent outputs continuous portfolio weight allocations for each step. 

The environment tackles several common RL trading pitfalls (turtling, hyperactive trading, and catastrophic drawdowns) via hardcoded action smoothing, deadband filtering, synthetic trailing stops, and a multi-objective reward structure.

---

## Step-by-Step Walkthrough

### 1. The Environment Observation Space
The observation space provides the agent with context of market history and its own current position.
- **Features**: It flattens a `LOOKBACK_WINDOW` of pre-computed historical features (ATR, MACD, returns, etc.) for every asset.
- **Portfolio State**: It appends the current allocation state: weights for each asset plus the remaining cash ratio.
- **Optimization**: To prevent slowdowns during RL episode loops, `pandas` `.loc` and `.iloc` lookups are avoided entirely. Dataframes are converted into pre-cached continuous NumPy arrays before training begins.

### 2. The Action Space & Processing
The action space is defined as `Box([-1, -1], [1, 1])`, representing raw allocation logits for the two assets.

1. **Mapping and Normalization**: Because this is a Spot environment (no shorting), weights are forced $\ge 0$. A custom `_softmax_weights` function shifts `[-1.0, 1.0]` exactly into `[0.0, 1.0]`. If the sum exceeds $1.0$, it normalizes them relative to each other. Any remaining proportion goes to `USDT` cash.
2. **Action Smoothing (Temporal Decay)**: To stop erratic flipping, the environment smooths the agent's raw chosen actions using an exponentially weighted average of the previous step: $Action_t = (1 - \alpha) \times Action_{t-1} + \alpha \times RawAction_t$.
3. **Deadband Rebalancing Threshold**: Micro-adjustments burn capital on exchange fees. If the total change in allocations is $\le 3\%$, the environment ignores the agent's request entirely and holds the previous allocations.

### 3. The Multi-Objective Reward System
The reward signal relies on a linear combination of four major objectives, combined with hard-stops to guide safer behavior.

```python
# Linear Combination of 4 Core Objectives
reward = (1.0 * profit_t) - (2.0 * drawdown_t) - (0.5 * turnover_t) - (1.5 * opportunity_cost)
```

1. **Profit ($w=1.0$)**: The step's log return, calculated strictly after fees/slippage. $\log(\max(R_{net}, 1e-6))$
2. **Drawdown ($w=2.0$)**: Measured against a 100-step rolling window. Highly penalizes giving back recent localized gains, forcing conservative compounding. 
3. **Turnover ($w=0.5$)**: Explicitly penalizes transaction costs/slippage incurred during rebalancing.
4. **Opportunity Cost ($w=1.5$)**: "Curing Turtling." If the market is in a confirmed macro uptrend (average 1D MACD Z-score $> 1.0$) and the agent holds $> 80\%$ cash, the agent suffers a continuous opportunity penalty proportional to the MACD signal strength.

---

## Pitfalls, Edge Cases, & Hardcoded Interventions

*   **Dynamic ATR Trailing Stops (Hard-Coded)**: The environment tracks synthetic peak prices internally. If the price falls from a local peak beyond a dynamic threshold `(4% + ATR_Z * 0.01)`, the environment *forces liquidation* to cash, regardless of the agent's requested weight.
*   **Maximum Absolute Drawdown "Kill Switch"**: If the absolute drawdown from the session peak ever crashes past **-15%**, the reward gets slapped with an immediate $-5.0$ penalty, and the training episode terminates early. This bounds bad exploration runs and prevents the algorithm from trying to optimize unrecoverable states.
*   **Spot Constraints**: Since weights are strictly positive `[0, 1]`, the agent fundamentally cannot synthesize short exposure. The maximum downside risk mitigation is a 100% allocation to USDT (cash).
