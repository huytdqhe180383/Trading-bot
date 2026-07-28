# OKX testnet multi-agent Discord confirmation integration

Date: 2026-07-28
Mode: OKX demo/testnet only

## Outcome

Added a native OKX V5 private-account and demo-order boundary. The existing
analyst service now exposes its two contextual background roles to a separate
execution planner without changing the advisory LLM schema. The planner sees
private account context (balances, open spot orders, and positions), current
instrument/ticker/order-book data, news, and the contextual agent views.

`/suggest` creates a short-lived, user-bound suggestion. Discord posts Confirm
and Reject buttons. Confirm re-fetches all relevant state, verifies capacity,
instrument precision, minimum/maximum notional, visible depth, and slippage,
then submits only to OKX demo trading. It uses OKX's `x-simulated-trading: 1`
header, signed V5 requests, `expTime`, and `slippagePct` for market orders.
The account snapshot is private data sent to the configured `LLM_BASE_URL` for
planning; credentials themselves are never sent to the LLM or Discord.

Implementation links:

- [OKX demo client](../../../tradingbot/execution/okx_client.py)
- [execution planner and confirmation gate](../../../tradingbot/execution/service.py)
- [Discord commands and buttons](../../../tradingbot/analyst/discord_bot.py)
- [configuration template](../../../.env.example)
- [focused execution tests](../../../tests/test_okx_execution.py)

## Verification

- Read-only private OKX demo call succeeded with the credentials already in
  `.env`: 4 non-zero balance rows, 0 open spot orders, and 0 open positions.
- Read-only BTC-USDT market context succeeded: live instrument metadata and 20
  bid/ask levels were returned.
- Focused tests: 23 passed.
- Ruff and Pyflakes: passed for changed files.
- Discord module import: passed without starting the bot or posting messages.
- Full test discovery was attempted, but the available runtime is missing
  pre-existing repository dependencies (`ccxt`, `fastapi`, and `uvicorn` in
  different environment paths); 6 suite modules failed at import for that
  environment reason. The focused tests and existing analyst-service tests
  passed.

The non-secret read-only verification snapshot is stored at
[okx_testnet_read_only_verification.json](../../../results/daily/2026-07-28/okx_testnet_read_only_verification.json).
