# Smooth Cap Trade Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a smooth NAV-based position-cap curve plus mild/moderate/aggressive trade profiles, then compare three `$100` backtests.

**Architecture:** Add a reusable helper for dynamic asset-cap scaling from account NAV, thread it into fusion/live decision paths, and expose trade-profile presets through the backtest CLI. Cover the new behavior with focused unit tests, then run the three experiment backtests and write a daily comparison report.

**Tech Stack:** Python, unittest, pandas, NumPy, existing backtest/live execution stack

---

### Task 1: Add failing tests for NAV-based cap scaling and profile parsing

**Files:**
- Modify: `K:\BTC-ETH Trading\tests\test_backtest_session_outputs.py`
- Modify: `K:\BTC-ETH Trading\tests\test_run_live_safety.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement the minimal code to pass**
- [ ] **Step 4: Run the tests to verify they pass**

### Task 2: Add dynamic cap helper and thread it into fusion/live paths

**Files:**
- Modify: `K:\BTC-ETH Trading\backtest.py`
- Modify: `K:\BTC-ETH Trading\agents\meta_fusion_agent.py`
- Modify: `K:\BTC-ETH Trading\scripts\run_live.py`
- Modify: `K:\BTC-ETH Trading\config.py`

- [ ] **Step 1: Add failing tests for the new helper behavior**
- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement the helper and call sites**
- [ ] **Step 4: Run the tests to verify they pass**

### Task 3: Add trade-profile presets to the backtest CLI

**Files:**
- Modify: `K:\BTC-ETH Trading\backtest.py`
- Modify: `K:\BTC-ETH Trading\tests\test_backtest_session_outputs.py`

- [ ] **Step 1: Add failing parser/profile tests**
- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement profile preset wiring**
- [ ] **Step 4: Run the tests to verify they pass**

### Task 4: Run experiment backtests and document comparison

**Files:**
- Create: `K:\BTC-ETH Trading\report\daily\2026-05-30\smooth_cap_trade_profile_comparison.md`
- Preserve: `K:\BTC-ETH Trading\results\daily\2026-05-30\`

- [ ] **Step 1: Run mild / moderate / aggressive `$100` backtests**
- [ ] **Step 2: Summarize metrics and trade-frequency changes**
- [ ] **Step 3: Save the daily report with working relative links**

