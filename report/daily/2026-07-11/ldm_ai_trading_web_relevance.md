# LDM_AI_Trading_Web Pull And Relevance Review

Date: 2026-07-11

## Requested Repository

- URL: `https://github.com/ManhLD-LDM/LDM_AI_Trading_Web.git`
- Local inspection clone: `C:\Users\qhuy0\AppData\Local\Temp\codex_external_repos\LDM_AI_Trading_Web`
- Branch: `main`
- Inspected commit: `765f25079f3f3d8f07f05f05ba1aead52838b47b`
- Commit subject: `Completed v1.0`
- Commit date: `2026-06-05T22:20:18+07:00`

The repository was cloned successfully after local Git/GitHub Desktop setup. The clone was intentionally kept outside this project tree so the external source does not become a nested repository or accidental vendored dependency.

## What The Repository Is

`LDM_AI_Trading_Web` is a full-stack web trading dashboard, not a direct reinforcement-learning trading engine.

High-level shape:

- **Backend**: FastAPI service with JWT auth, MongoDB/Motor persistence, WebSocket broadcasting, rate limiting, Binance public market-data fetches, webhook signal ingestion, simple paper trading, and basic backtest endpoints.
- **Frontend**: Next.js app with `lightweight-charts`, drawing tools, technical-indicator overlays, an AI-events sidebar, auth modal, settings page, and backtest controls.
- **Model layer**: bundled ONNX/PyTorch artifacts for LSTM, TCN, and Transformer variants, plus optional XGBoost support. The code labels this layer as `Kronos`, but it is not the same source-based Kronos integration used by this BTC/ETH project.
- **Agent layer**: Gemini/Gemma-backed Technical, Sentiment, and Trader agents that convert model/trend output and news into BUY/SELL/HOLD messages.
- **Trading scope**: Binance spot-style symbols and public candles/websocket data; no verified live exchange order execution layer was found.

Main external files inspected:

- `backend/main.py`
- `backend/agents.py`
- `backend/kronos_onnx.py`
- `backend/backtest_engine.py`
- `backend/routers/backtest.py`
- `backend/routers/paper.py`
- `backend/binance_api.py`
- `backend/news_analyzer.py`
- `frontend/src/app/page.tsx`
- `frontend/src/components/Chart.tsx`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/components/Toolbar.tsx`
- `frontend/src/lib/indicatorsRegistry.ts`

## Key Capabilities Found

### Web App And UX

- Next.js frontend, currently using Next `16.2.6`, React `19.2.4`, Zustand, Tailwind, and `lightweight-charts`.
- Live chart loads candles directly from Binance REST and streams candles from Binance WebSocket.
- Chart supports drawing persistence through backend `/api/drawings/{symbol}` routes.
- Indicator registry includes many client-side technical indicators through `technicalindicators`.
- AI sidebar displays backend WebSocket events and marks non-HOLD Trader Agent decisions on the chart.
- Backtest tab allows MACD Crossover and RSI Mean Reversion backtests for selected symbols/timeframes.

### Backend Services

- FastAPI app titled `LDM AI Trading Backend`.
- Auth endpoints for register/login/profile/preferences using JWT and MongoDB.
- WebSocket endpoint `/ws` requires a JWT token.
- Analysis queue endpoint `/api/analysis/run` schedules asynchronous analysis workers.
- Signal webhook endpoint `/api/webhook/signals` accepts external bot signals via `X-API-Key` and stores/broadcasts them.
- Paper trading endpoint persists simulated balances/positions per user in MongoDB.

### AI/Model Pipeline

The analysis flow is:

1. Fetch recent candles from Binance.
2. Run `ModelEnsemble.predict(...)`.
3. Broadcast a `Kronos` trend/confidence message.
4. Run Technical and Sentiment agents concurrently.
5. Ask Trader Agent for a BUY/SELL/HOLD JSON decision.
6. Broadcast and optionally store the decision in MongoDB.

Important detail: if model files are not found or dependencies are unavailable, the model layer can return a mock trend based on recent price direction, with randomized confidence. That means external signals from this repo should not be treated as production-grade alpha without validation.

### Backtesting

The backtest engine is simple single-asset strategy simulation:

- MACD crossover strategy.
- RSI mean-reversion strategy.
- ATR-derived stop loss / take profit.
- fixed fractional risk sizing.
- slippage and taker fee assumptions.
- summary metrics: final equity, ROI, win rate, profit factor, max drawdown, Sharpe, trades, sampled equity curve.

This is useful as a UI/demo backtest, but it is not comparable to this project’s PPO/SAC portfolio backtest matrix.

## Fit With Our BTC/ETH Trading Project

Current local project baseline:

- [README](../../../README.md)
- [Project context](../../../CONTEXT.md)
- [Architecture](../../../docs/architecture.md)
- [TradingAgents adapter](../../../adapters/tradingagents_adapter.py)
- [LLM risk gate adapter](../../../adapters/llm_risk_gate_adapter.py)
- [Kronos adapter](../../../adapters/kronos_adapter.py)
- [Private UI app](../../../ui/app.py)

Our project is an OKX-first BTC/ETH spot allocation research and operations system:

- PPO/SAC base policy for BTC/ETH/USDT portfolio weights.
- fallback-safe Kronos, TradingAgents, and local LLM risk-gate overlays.
- `MetaFusionAgent` combines RL outputs and optional overlays.
- backtest/live artifacts are stored through canonical daily result/report helpers.
- private FastAPI/Jinja UI monitors runs, reports, logs, and controlled service actions.

## Relevance Assessment

### High Relevance

- **Charting UX**: the external `frontend/src/components/Chart.tsx` is the most immediately useful reference. Its `lightweight-charts` setup, live candles, marker rendering, drawing tools, and indicator overlays could inform a richer private UI for our project.
- **AI event timeline**: the sidebar pattern is a good UI idea for showing Kronos, TradingAgents, LLM risk-gate, and RL decision traces.
- **Drawing persistence**: save/load chart annotations could be useful for operator notes during live review.
- **Webhook signal ingestion**: the `/api/webhook/signals` pattern could inspire a safe external-alert ingestion route, if we ever want TradingView/monitor alerts inside our UI.
- **Paper-trade state UX**: the frontend/backend shape is useful for user-facing paper account displays, though not as-is.

### Medium Relevance

- **Auth/preferences persistence**: JWT + MongoDB user preferences are reusable design inspiration, but our private Tailscale/password-based UI is intentionally simpler.
- **Backtest display widgets**: final equity, ROI, drawdown, Sharpe, trades, and sampled equity curve cards could be adapted to our existing richer backtest outputs.
- **Frontend stack option**: a Next.js frontend could eventually replace or complement our current server-rendered FastAPI/Jinja UI if we want a more interactive dashboard.
- **Agent log streaming**: the WebSocket broadcast loop is relevant as a pattern, but our current runtime artifacts and logs should remain canonical.

### Low Relevance

- **Core strategy logic**: it does not contain PPO/SAC portfolio allocation, OKX execution controls, or our risk-first allocation model.
- **Exchange runtime**: it is Binance-public-data-first and does not match the OKX-first live/testnet runtime.
- **LLM provider model**: it uses Gemini/Gemma trade-decision prompting, while our architecture intentionally keeps local LLMs as low-cadence risk gates or fallback-safe overlays.
- **Model naming**: its `Kronos` naming is misleading relative to our source-based `shiyu-coder/Kronos` adapter.
- **Backtest realism**: its single-symbol MACD/RSI simulation is much shallower than our ablation/realism backtest matrix.

## Risks And Caveats

- Backend CORS is effectively wide open through `allow_origin_regex=".*"` while `allow_credentials=True` is enabled. This should not be copied into our private UI.
- The model layer can silently fall back to dynamic mock signals; importing this behavior would contaminate research results.
- Frontend settings include Gemini/Binance API key fields; avoid client-side secret collection unless there is a secure storage and threat model.
- The repo stores model artifacts directly in Git. That is convenient for demos but not ideal for larger model governance.
- Several comments/strings show encoding issues from Vietnamese text; any user-facing reuse should normalize file encoding and copy.
- No robust live-order execution or exchange-risk governor was found.

## Integration Recommendation

Do not merge or vendor the repository into this project.

Instead, treat it as a UI/reference repository and selectively extract ideas:

1. Prototype an interactive chart panel for our private UI using `lightweight-charts`.
2. Add chart markers for our existing live decisions and overlay signals.
3. Add an AI/risk event timeline fed from our canonical runtime artifacts.
4. Consider drawing/annotation persistence for operator review.
5. Reuse only concepts, not strategy/model code, unless a specific component is isolated behind tests and adapted to OKX-first, fallback-safe semantics.

## Suggested Next Work

- Create a design note for an upgraded private UI chart and AI-decision timeline.
- Build a small proof of concept that reads our existing `live_decisions.csv` / daily session artifacts and renders markers on a BTC/ETH chart.
- Keep the external repo clone outside this project unless we intentionally add a Git submodule or documented external dependency.

## Completion Notes

- External repo was cloned and inspected successfully.
- Clone was stored outside this repository under the local temp directory.
- No preserved result snapshots were generated.
- This report is stored in the canonical daily report folder.
