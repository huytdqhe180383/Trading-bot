"""
Data Pipeline – Step 2: Preprocessing & Feature Engineering
============================================================
Loads raw parquet data, computes technical indicators using
pandas-ta, aligns multi-asset frames, and splits into
train / test sets ready for the RL environment.

Usage:
    python -m data.preprocess
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (
    SYMBOLS, BASE_TIMEFRAME, MTF_TIMEFRAMES,
    TRAIN_START, TRAIN_END, BACKTEST_START, BACKTEST_END,
    RAW_DATA_DIR, PROCESSED_DATA_DIR, LOOKBACK_WINDOW,
)


# ──────────────────────────────────────────
# INDICATOR COMPUTATION
# ──────────────────────────────────────────

def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Append essential technical and ICT indicators to *df*."""

    # 1. Essential Momentum & Trend
    df["rsi_14"] = ta.rsi(df["close"], length=14)

    # Fix 3-C: use canonical column names — positional iloc breaks across pandas_ta versions.
    _MACD_F, _MACD_S, _MACD_SIG = 12, 26, 9
    macd = ta.macd(df["close"], fast=_MACD_F, slow=_MACD_S, signal=_MACD_SIG)
    if macd is not None and not macd.empty:
        df["macd"]        = macd.get(f"MACD_{_MACD_F}_{_MACD_S}_{_MACD_SIG}")
        df["macd_signal"] = macd.get(f"MACDs_{_MACD_F}_{_MACD_S}_{_MACD_SIG}")
        df["macd_hist"]   = macd.get(f"MACDh_{_MACD_F}_{_MACD_S}_{_MACD_SIG}")
    
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14) / df["close"]

    # Distance metrics & Macro Anchors
    df["sma_200"] = ta.sma(df["close"], length=200)
    df["dist_sma_200"] = (df["close"] / df["sma_200"]) - 1.0
    
    bb = ta.bbands(df["close"], length=20, std=2.0)
    if bb is not None and not bb.empty:
        df["bb_width"] = (bb.iloc[:, 2] - bb.iloc[:, 0]) / (bb.iloc[:, 1] + 1e-9)
        df["dist_bbu"] = (df["close"] / bb.iloc[:, 2]) - 1.0
        df["dist_bbl"] = (df["close"] / bb.iloc[:, 0]) - 1.0

    obvs = ta.obv(df["close"], df["volume"])
    if obvs is not None:
        # Fix 3-B: shift OBV and its rolling stats by 1 so that at decision time t
        # the agent only sees OBV information confirmed through close_{t-1}.
        obvs_lag   = obvs.shift(1)
        obv_mean   = obvs_lag.rolling(20).mean()
        obv_std    = obvs_lag.rolling(20).std().replace(0, 1e-9)
        df["obv_norm"] = (obvs_lag - obv_mean) / obv_std

    # 2. ICT: Fair Value Gap (FVG)
    # FVG occurs when the shadow of candle i does not overlap with candle i-2.
    # We normalise by price. Positive gap = Bullish. Negative = Bearish.
    bull_fvg = df["low"] - df["high"].shift(2)
    bear_fvg = df["high"] - df["low"].shift(2)
    df["fvg"] = np.where(bull_fvg > 0, bull_fvg, np.where(bear_fvg < 0, bear_fvg, 0)) / df["close"]

    # 3. ICT: Liquidity Sweeps
    # Sweep of rolling 20-period High/Low, measuring rejection depth normalised by price
    recent_high = df["high"].shift(1).rolling(20).max()
    recent_low = df["low"].shift(1).rolling(20).min()
    df["sweep_high"] = np.where(df["high"] > recent_high, df["high"] - recent_high, 0) / df["close"]
    df["sweep_low"]  = np.where(df["low"] < recent_low, recent_low - df["low"], 0) / df["close"]

    # Log return 
    df["log_return"] = np.log(df["close"] / df["close"].shift(1))

    return df


# ──────────────────────────────────────────
# NORMALISATION
# ──────────────────────────────────────────

def _rolling_z_score(df: pd.DataFrame, window: int = 500) -> pd.DataFrame:
    """
    Normalise numeric columns using a rolling z-score so values
    remain stationary and the RL agent sees comparable scale.
    Price levels (raw OHLCV) are replaced by relative counterparts.
    """
    # Keep a reference to non-numeric columns
    cols = df.select_dtypes(include=[np.number]).columns
    # Fix 1-B: require a full window of history before emitting a z-score.
    # Rows with fewer than `window` preceding samples produce NaN and are
    # removed by the dropna() call in load_and_process(), preventing the
    # first ~300-candle warm-up artefact from polluting the training split.
    mu    = df[cols].rolling(window, min_periods=window).mean()
    sigma = df[cols].rolling(window, min_periods=window).std().replace(0, 1e-9)
    df[cols] = (df[cols] - mu) / sigma
    return df


# ──────────────────────────────────────────
# MAIN PREPROCESSING LOGIC
# ──────────────────────────────────────────

def load_and_process() -> dict[str, pd.DataFrame]:
    """Return dict mapping symbol → processed MTF DataFrame."""
    processed = {}

    for symbol in SYMBOLS:
        logger.info(f"Processing {symbol} across MTFs...")
        
        mtf_dfs = {}
        for ivl in MTF_TIMEFRAMES:
            raw_path = RAW_DATA_DIR / f"{symbol}_{ivl}.parquet"
            if not raw_path.exists():
                logger.error(f"Raw data not found: {raw_path}. Run download_historical.py first.")
                continue

            df = pd.read_parquet(raw_path)
            df.index = pd.to_datetime(df.index, utc=True)
            df.sort_index(inplace=True)

            # Compute indicators on this specific timeframe naturally
            df = _add_indicators(df)

            # Prevent lookahead bias for higher timeframes: 
            # A 1H candle "labelled" at 09:00 doesn't actually finish forming until 10:00.
            # We shift higher timeframe data forward by 1 time step, meaning 09:00's features are only 
            # available on the 10:00 timestamp (which maps to 10:00, 10:05, 10:10 etc. safely!).
            if ivl != BASE_TIMEFRAME:
                df = df.shift(1)

            # Keep only indicators, dropping the raw OHLCV prices
            drop_cols = ["open", "high", "low", "volume", "close", "quote_asset_volume", 
                         "taker_buy_base_volume", "taker_buy_quote_volume", "num_trades"]
            if "close_time" in df.columns:
                drop_cols.append("close_time")
            
            if ivl != BASE_TIMEFRAME:
                # Log return target should only exist for the base timeframe!
                drop_cols.append("log_return")
                
            cols_to_keep = [c for c in df.columns if c not in drop_cols]
            df_clean = df[cols_to_keep].copy()

            # Prefix the feature names logically
            if ivl != BASE_TIMEFRAME:
                df_clean.columns = [f"{c}_{ivl}" for c in df_clean.columns]
                
            mtf_dfs[ivl] = df_clean

        # ── Merging DataFrames onto Base Timeframe Index ──────────────────────
        base_df = mtf_dfs.get(BASE_TIMEFRAME)
        if base_df is None:
            continue

        for ivl in MTF_TIMEFRAMES:
            if ivl == BASE_TIMEFRAME: 
                continue
            
            higher_df = mtf_dfs[ivl].dropna(how="all")
            # merge_asof backward matches our 1H candles up to the latest completed 4H/1D candle!
            base_df = pd.merge_asof(
                base_df, higher_df, 
                left_index=True, right_index=True, 
                direction="backward"
            )

        base_df.dropna(inplace=True)

        # ── Z-Score Normalisation ─────────────────────────────────────────────
        # Detach log target and raw macro anchors before normalisation
        log_ret = base_df.pop("log_return")
        
        macro_cols = {}
        for col in ["dist_sma_200_1d", "atr_14_1d"]:
            if col in base_df.columns:
                macro_cols[f"raw_{col}"] = base_df[col].copy()

        # Rolling standardisation over equivalent of roughly 10 lookback windows (e.g. 50 hours of 5m)
        base_df = _rolling_z_score(base_df, window=LOOKBACK_WINDOW * 10)
        
        # Restore raw log return target and macro rules
        base_df["log_return_1h"] = log_ret
        for name, series in macro_cols.items():
            base_df[name] = series
        
        base_df.dropna(inplace=True)

        processed[symbol] = base_df
        logger.info(f"  {symbol}: {len(base_df):,} total aggregated rows | {len(base_df.columns)} MTF features!")

    return processed


def split_and_save(processed: dict[str, pd.DataFrame]):
    """Split into train/test and save to PROCESSED_DATA_DIR."""
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    for symbol, df in processed.items():
        train = df.loc[TRAIN_START:TRAIN_END]
        test  = df.loc[BACKTEST_START:BACKTEST_END]

        train_path = PROCESSED_DATA_DIR / f"{symbol}_train.parquet"
        test_path  = PROCESSED_DATA_DIR / f"{symbol}_test.parquet"

        train.to_parquet(train_path)
        test.to_parquet(test_path)
        logger.info(f"  {symbol} → train: {len(train):,} rows | test: {len(test):,} rows")


def main():
    logger.info("Starting data preprocessing pipeline...")
    processed = load_and_process()
    if processed:
        split_and_save(processed)
        logger.info("Preprocessing complete.")
    else:
        logger.error("No data processed. Aborting.")


if __name__ == "__main__":
    main()
