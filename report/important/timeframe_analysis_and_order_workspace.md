# Timeframe Analysis and Order Workspace

## Delivered architecture

- The embedded analyst runtime now polls OKX for newly confirmed 1m, 15m, 1h,
  and 4h candles. Its work key is the exchange candle timestamp rather than
  process uptime.
- A single priority-aware orchestrator runs higher timeframes first, cancels
  lower lanes at safe boundaries, and discards a lower result if it was
  cancelled while an HTTP request was in flight.
- Fresh lower-timeframe evidence is compacted into higher lanes. Context older
  than `ANALYST_TIMEFRAME_CONTEXT_TTL_SECS` is excluded from higher and manual
  prompts.
- The 1m, 15m, and 1h lanes use the lower-provider route (with an optional
  second key fallback); 4h and `MANUAL_MODEL` use the primary route. Canonical
  environment names are listed in `.env.example` and no secret `.env` values
  were inspected. Routes are fail-closed: a missing URL, key, or model emits a
  lane-specific configuration error and never borrows another lane's setting.
- Discord receives significant 15m/1h alerts only. Every successful 4h
  analysis is delivered to `DISCORD_ANALYST_CHANNEL_ID`, including neutral
  sentiment.

## Operator workflow

- The chart toolbar has an explicit high stacking layer, so the Indicators
  menu renders over the chart.
- The dashboard now separates analysis from **Orders & journal**. The order
  tab reads the existing SQLite-backed suggestion lifecycle and creates a
  bounded order plan. A pending plan still needs an explicit local demo
  confirmation; no real order is introduced by this change.
- The **Analysis** workspace now has independent boxes: a filtered BTC
  closed-candle timeframe feed and a manual-chat history. Automatic analysis
  is no longer drawn as repeated chart markers or inserted into manual chat.
- The timeframe box provides a Stop/Resume control. Stopping pauses future
  work without shutting down the web service or deleting events.
- The **Reset UI** control schedules the repository's local restart script
  after returning its acknowledgement. It restarts both the API/timeframe
  process and the Next.js frontend, then reloads the dashboard.

## Provider diagnosis (2026-08-02)

The lower lanes were corrected to use the explicit Google OpenAI-compatible
base (`.../v1beta/openai`) without an extra `/v1` suffix. The Google key was
accepted and its model catalog was queried without exposing credentials.
Saved display labels were replaced with valid API identifiers:
`gemma-4-31b-it`, `gemini-3.5-flash-lite`, and `gemini-3.6-flash`.

The 1m and 15m lanes subsequently completed successfully. The 1h lane uses an
explicit 60-second timeout, since its former inherited 20-second timeout was
insufficient. The primary ShopAI variable is accepted as `SHOPAI_KEY` (an alias
for the 4h/manual primary key) so it no longer needs to be duplicated as
`LLM_API_KEY`.

## Verification

- `next build` completed successfully.
- `tests.test_analyst_service` and `tests.test_analyst_scanner` completed
  successfully (18 tests).
- The broader test suite has pre-existing optional dependency failures in this
  UI virtual environment (`ccxt`, `loguru`, `gymnasium`, and `httpx2`).
