# Building a BTC/ETH Auto-Trading System with FinRL-X and Binance

This document outlines the top-down plan, requirements, and setup for an automated Ensemble Deep Reinforcement Learning (DRL) trading system using FinRL-X and Binance.

## System Overview & Explanations

### 1. The Mean: FinRL-X Ensemble System
**What it is:** FinRL-X is an AI-native quantitative trading framework designed to bridge the gap between simulation and real-world deployment. 
**Ensemble Strategy:** Instead of relying on a single algorithm, the Strategy Layer will utilize an **Ensemble System**. We will train multiple diverse agents (e.g., PPO, A2C, DDPG, SAC) and combine their outputs (via voting, weighted averaging, or a meta-agent) to yield more stable and robust performance.

### 2. The Platform & Setup: Binance Spot (Local Execution)
**What it is:** We will connect to the Binance API to trade on the **Spot Market** (buying and holding actual BTC/ETH, taking long or cash positions).
**Requirements & Setup:**
- **Execution Environment:** The system will run locally on your PC. We will incorporate robust error handling and logging to protect against local network disconnects or API downtime.
- **Accounts:** A standard Binance account for live trading, and a Binance Testnet account for paper trading.
- **Security:** API keys must only have "Reading" and "Spot Trading" permissions enabled. Keys will be securely loaded via a local `.env` file.

### 3. The Data Pipeline
**Data Range:** Data from **2020-onward is highly sufficient and ideal**. It captures major macroeconomic shifts, the massive 2021 bull run, and the 2022 crypto winter. Pre-2020 crypto data has fundamentally different market microstructures and much lower institutional volume, which can introduce noisy patterns rather than generalized signals.
**Data Retrieval:**
- **Historical:** We will use Binance bulk data platform (`data.binance.vision`) to rapidly download 2020+ daily/hourly CSV datasets without hitting REST API rate limits.
- **Live Trading:** Real-time data will be streamed directly via the Binance REST/WebSocket API.

### 4. Architecture
The system features a modular four-layer architecture:
1. **Data Layer:** Fetches and preprocesses data, calculating technical indicators (RSI, MACD) and normalizing inputs.
2. **Strategy Layer (Ensemble):** Houses multiple DRL agents observing the data to propose target allocations (BTC, ETH, Cash). The ensemble logic aggregates these into final portfolio weights.
3. **Backtesting Layer:** Simulates execution on hold-out data using professional-grade tools, applying Binance's 0.1% spot fee.
4. **Broker-Execution Layer:** Translates target weights into exact algorithmic Buy/Sell orders via the Binance wrapper.

### 5. Performance Metrics
A robust quantitative evaluation is critical. We will track:
- **Profitability:** Win Rate, Profit Factor, Expectancy, and *Average Win/Loss Ratio*.
- **Risk:** Maximum Drawdown, Sharpe Ratio, Sortino Ratio, Calmar Ratio, and *Average Drawdown Duration*.
- **Operational:** Execution Latency and Slippage (simulated during backtests, tracked during live).
- **Additional (Suggested):** We'll also track *Time in Market (Exposure %)* to evaluate if the agent unnecessarily holds assets during flat markets, and *Information Ratio* to compare performance directly against a simple Buy-and-Hold benchmark.

### 6. The Pipeline
1. **Training:** Train the ensemble of agents on the 2020-2023 dataset.
2. **Evaluation:** Evaluate each agent individually to select the strongest models for the ensemble.
3. **Backtesting:** Run the combined ensemble over the out-of-sample data (2024-present) to generate the quantitative metrics.
4. **Live Run (Demo):** Deploy locally on Binance Testnet for forward-testing.
5. **Live Run (Production):** Execute locally on the main Binance Spot market.

## User Review Required
> [!IMPORTANT]
> The plan has been updated to include your constraints (Local Execution, Spot Trading, 2020+ Data, Ensemble System, Comprehensive Metrics). Please review the updated plan. Once approved, we can transition to **Execution** mode and begin setting up the codebase.
