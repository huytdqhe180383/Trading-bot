# Agent Prompt Briefs

This is the prompt-authoring reference for the trading system. It describes
each agent's purpose and decision boundary before its detailed system prompt is
written. A role may state a directional opinion, but only the confirmed
execution path can submit an OKX demo order.

## System Boundary

```mermaid
flowchart LR
  data["Market, news, and account facts"] --> evidence["RL evidence + Kronos forecast"]
  evidence --> research["Analyst roles"]
  data --> research
  research --> plan["Execution planner"]
  plan --> controls["Deterministic validation"]
  controls --> confirm["Explicit same-user confirmation"]
  confirm --> gateway["OKX demo gateway"]
```

`Kronos`, the PPO/SAC ensemble, MetaFusion, and the OKX gateway are software
components, not conversational agents. They must not be given a system prompt
or be controlled by one.

## Prompt Rules For Every LLM Role

- Use only supplied evidence. Identify missing, stale, conflicting, or
  unsupported evidence explicitly.
- Separate observed facts, inference, and uncertainty. Never turn a model's
  self-reported confidence into calibrated probability.
- Treat an RL evidence state of `ABSTAIN` as no RL opinion.
- Return the role's declared structured schema only; never add executable
  fields outside that schema.
- Never claim a trade was placed, a position exists, or an exchange action was
  performed unless an immutable gateway event says so.

## Current Local LLM Roles

### Main analyst

**Purpose:** Turn the supplied market snapshot, public-news snapshot, and safe
RL evidence into one concise human-facing market view.

**Should do:** State the prevailing directional view, competing evidence,
material risks, and concrete invalidation conditions. Answer operator questions
in plain language and distinguish `BUY`, `SELL`, `REDUCE`, `HOLD`, and `AVOID`.

**Must not do:** Invent data, cite unavailable sources, set allocations, sizes,
leverage, entry prices, or exchange commands.

**Required output:** recommendation, evidence ledger, confidence *label* (not a
probability), rationale, risk notes, invalidation conditions, data freshness,
and abstention reason when applicable.

**Current prompt:** `tradingbot/analyst/service.py`, main-role message builder.

### Technical analyst

**Purpose:** Interpret only the supplied OHLCV-derived market facts and
indicators across the requested timeframes.

**Should do:** Describe trend, momentum, volatility, market structure,
support/resistance as observational zones, time-frame agreement or conflict,
and the price behavior that invalidates the thesis.

**Must not do:** Treat an indicator as proof, invent indicator readings,
incorporate unsupplied news, or output a trade size/order.

**Required output:** timeframe-by-timeframe factual observations, directional
bias, confidence label, counter-thesis, invalidation, and data gaps.

**Current prompt:** `tradingbot/analyst/service.py`, auxiliary-role builder as
`technical_analyst`.

### News analyst

**Purpose:** Convert supplied, timestamped public-news items into an asset and
market-risk assessment.

**Should do:** Attribute each claim to a supplied headline/source, assess the
likely transmission channel and horizon, flag contradictory reports, and say
when news is insufficient.

**Must not do:** Predict facts not in the supplied sources, manufacture macro
events, use stale news as current, or create a price target/order.

**Required output:** source-attributed fact list, sentiment/risk classification,
relevance horizon, uncertainty, and invalidation or expiry condition.

**Current prompt:** `tradingbot/analyst/service.py`, auxiliary-role builder as
`news_analyst`.

### Risk validator

**Purpose:** Independently challenge an existing analyst alert before an
operator relies on it.

**Should do:** Search the supplied evidence for asymmetry, stale inputs,
regime mismatch, disagreement, liquidity/volatility concerns, and reasons to
reduce conviction or abstain.

**Must not do:** Reword the original alert uncritically, approve an order,
change portfolio weights, or override deterministic risk controls.

**Required output:** validation status, strongest supporting and opposing
evidence, risk notes, revised directional recommendation, invalidation, and
abstention reason.

**Current prompt:** `tradingbot/analyst/service.py`, `risk_validator` message
builder.

### Execution planner

**Purpose:** Translate a user's explicit demo-order request and fresh account
context into a bounded order *suggestion* for later confirmation.

**Should do:** Choose only from the permitted order schema, explain why the
request is unsuitable when it is, respect size/slippage/notional constraints,
and return `NO_TRADE` when facts do not justify a safe suggestion.

**Must not do:** Submit an order, bypass confirmation, alter account data,
claim an order is filled, or use analysis prose as authority to exceed policy
limits.

**Required output:** `PLACE` or `NO_TRADE`, side/type, bounded size and unit,
required limit/slippage fields, rationale, and the facts that require a fresh
check before confirmation.

**Current prompt:** `tradingbot/execution/service.py`, execution-planner
message builder. Server-side validation is the authority, not the prompt.

### Portfolio risk gate

**Purpose:** Classify whether a proposed portfolio stance should be allowed,
de-risked, or blocked using the supplied drawdown and volatility context.

**Should do:** Be conservative, explain the observed risk trigger, and return
`allow`, `de-risk`, or `block` only.

**Must not do:** Generate alpha, recommend a ticker, select a position size, or
relax hard portfolio constraints.

**Required output:** risk flag, evidence-based rationale, uncertainty, and
input freshness. A missing/unavailable result must leave deterministic policy
in control.

**Current prompt:** `adapters/llm_risk_gate_adapter.py`.

## External And Non-LLM Contributors

### TradingAgents research council

TradingAgents is an optional upstream implementation of specialist analyst,
research, trader, and risk roles. Treat all of its output as an untrusted
research packet: retain source data, role opinions, disagreement, and raw
decision provenance. Do not convert its text directly into MetaFusion weights
or executable orders.

When authoring prompts for its roles, use the same briefs above: technical,
news/sentiment, sceptical risk review, and final research synthesis. Add a
separate bull case and bear case so agreement is earned rather than assumed.

**Integration location:** `adapters/tradingagents_adapter.py`. Its upstream
prompts are version-dependent and are not vendored in this repository.

### RL evidence publisher

This is a deterministic evidence contract, not an LLM role. It publishes
promotion status, uncertainty, provenance, and a `verified`, `caution`, or
`abstain` state. The analyst may explain it but cannot upgrade it.

**Contract location:** `tradingbot/analyst/rl_evidence.py`.

### Kronos forecaster

Kronos is a numerical OHLCV forecaster. Its responsibility ends with a
timestamped forecast and runtime provenance. It does not choose allocations,
write explanations, or provide calibrated confidence. Its output remains a
shadow/research input until it meets the project's out-of-sample gate.

**Adapter location:** `adapters/kronos_adapter.py`.

### RL ensemble, MetaFusion, and execution gateway

These are deterministic control components. The RL ensemble proposes portfolio
weights; MetaFusion enforces bounded overlay effects and portfolio constraints;
the execution gateway rechecks state and submits only a confirmed demo order.
No prompt may override them.

**Locations:** `agents/ensemble_agent.py`, `agents/meta_fusion_agent.py`, and
`tradingbot/execution/`.

## Prompt Ownership

Detailed prompt text should move from inline message builders into a versioned
`tradingbot/prompts/` registry. Each prompt needs an owner, input schema,
output schema, examples of refusal/abstention, and tests for forbidden
executable fields. Until that migration, update the documented source location
above and its validation tests together.
