"""
Training Entrypoint – train.py
==============================
Trains each individual DRL algorithm on the BTC/ETH environment
and saves checkpoints.  The best model by episode reward is kept.

Usage:
    python train.py [--algo ALL | PPO | SAC] [--timesteps 500000]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from loguru import logger
from stable_baselines3 import PPO, SAC
from stable_baselines3.common.callbacks import (
    EvalCallback,
    StopTrainingOnNoModelImprovement,
)
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.monitor import Monitor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (
    ALGORITHMS, ALGO_KWARGS, TOTAL_TIMESTEPS, CHECKPOINT_FREQ,
    PROCESSED_DATA_DIR, MODELS_DIR, LOGS_DIR, SYMBOLS, BASE_TIMEFRAME as KLINE_INTERVAL,
)
from environment.trading_env import BinanceSpotEnv
from agents.vae_model import VAEAnomalyDetector
import numpy as np


ALGO_CLS = {"PPO": PPO, "SAC": SAC}


def load_data(split: str = "train") -> dict[str, pd.DataFrame]:
    """Load processed parquet files for the given split."""
    data = {}
    for sym in SYMBOLS:
        path = PROCESSED_DATA_DIR / f"{sym}_{split}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Processed data not found: {path}. Run data/preprocess.py first.")
        data[sym] = pd.read_parquet(path)
    return data


def train_vae_model():
    logger.info("Collecting observation data for VAE training...")
    train_data = load_data("train")
    env = BinanceSpotEnv(train_data, mode="train")
    
    obs_list = []
    
    # Reset environment to get initial observation
    # Handling both Gymnasium and Gym return formats
    reset_res = env.reset()
    obs = reset_res[0] if isinstance(reset_res, tuple) else reset_res
    obs_list.append(obs)
    
    done = False
    
    while not done:
        action = env.action_space.sample()
        step_res = env.step(action)
        
        # Unpack depending on gym vs gymnasium
        if len(step_res) == 5:
            obs, reward, terminated, truncated, _ = step_res
            done = terminated or truncated
        else:
            obs, reward, done, _ = step_res
            
        obs_list.append(obs)
        
    obs_array = np.array(obs_list)
    logger.info(f"Collected {len(obs_array)} observations of shape {obs_array.shape[1:]}. Training VAE...")
    
    input_dim = obs_array.shape[1]
    vae = VAEAnomalyDetector(input_dim=input_dim)
    vae.train(obs_array, epochs=10)
    
    vae_path = MODELS_DIR / "vae_model.pt"
    vae_path.parent.mkdir(parents=True, exist_ok=True)
    vae.save(str(vae_path))


def train_algo(algo: str, timesteps: int):
    """Train a single algorithm and save the best model."""
    logger.info(f"\n{'='*50}\n  Training: {algo} | Steps: {timesteps:,}\n{'='*50}")

    train_data = load_data("train")
    eval_data  = load_data("test")

    # ── Environment setup ────────────────────────────────────────────────
    def make_train_env():
        env = BinanceSpotEnv(train_data, mode="train")
        return Monitor(env, str(LOGS_DIR / algo))

    def make_eval_env():
        env = BinanceSpotEnv(eval_data, mode="eval")
        return Monitor(env, str(LOGS_DIR / f"{algo}_eval"))

    # Vectorize environments: Use SubprocVecEnv with 8 environments for massive speedup
    n_cpus = 8
    train_env = make_vec_env(make_train_env, n_envs=n_cpus, vec_env_cls=SubprocVecEnv)
    eval_env  = make_vec_env(make_eval_env, n_envs=1, vec_env_cls=SubprocVecEnv)

    # ── Callbacks ────────────────────────────────────────────────────────
    model_dir = MODELS_DIR / algo
    model_dir.mkdir(parents=True, exist_ok=True)
    
    checkpoint_freq = CHECKPOINT_FREQ.get(algo, 50_000) if isinstance(CHECKPOINT_FREQ, dict) else CHECKPOINT_FREQ

    early_stop_cb = StopTrainingOnNoModelImprovement(
        max_no_improvement_evals=10,
        min_evals=20,
        verbose=1,
    )

    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path=str(model_dir),
        log_path=str(LOGS_DIR / algo),
        eval_freq=max(1, checkpoint_freq // n_cpus),
        n_eval_episodes=5,
        deterministic=True,
        callback_after_eval=early_stop_cb,
        verbose=1,
    )
    # Rename the SB3 default "best_model" to an algo-specific name after training
    callbacks = [eval_cb]

    # ── Model ────────────────────────────────────────────────────────────
    cls    = ALGO_CLS[algo]
    kwargs = ALGO_KWARGS[algo].copy()

    # On-policy algorithms (PPO) need the env at init time;
    # off-policy (SAC) take it too but also accept replay buffers.
    model = cls(
        "MlpPolicy", 
        train_env, 
        device="auto" if algo != "PPO" else "cpu", 
        tensorboard_log=str(LOGS_DIR / "tensorboard"),
        **kwargs
    )

    try:
        model.learn(
            total_timesteps=timesteps, 
            callback=callbacks, 
            tb_log_name=algo,
            progress_bar=True
        )
    except KeyboardInterrupt:
        logger.warning(f"{algo} training interrupted by user.")

    # ── Rename best_model to algo-specific filename ──────────────────────
    sb3_best = model_dir / "best_model.zip"
    algo_best = model_dir / f"{algo.lower()}_best.zip"
    if sb3_best.exists():
        sb3_best.replace(algo_best)
        logger.success(f"Best {algo} model saved → {algo_best}")
    else:
        logger.warning(f"No best_model.zip found for {algo}; saving final model.")
        final_path = model_dir / f"{algo.lower()}_final.zip"
        model.save(str(final_path))

    train_env.close()
    eval_env.close()


def main():
    parser = argparse.ArgumentParser(description="Train ensemble DRL agents for BTC/ETH trading.")
    parser.add_argument(
        "--algo", default="ALL",
        choices=["ALL"] + ALGORITHMS,
        help="Algorithm to train (default: ALL)",
    )
    parser.add_argument("--timesteps", type=int, default=None, help="Override default timesteps for all algorithms")
    parser.add_argument("--train-vae", action="store_true", help="Train the VAE anomaly detector before RL training")
    args = parser.parse_args()

    if args.train_vae:
        train_vae_model()

    algos = ALGORITHMS if args.algo == "ALL" else [args.algo]

    for algo in algos:
        # Determine specific timesteps for the algorithm
        timesteps = args.timesteps if args.timesteps is not None else TOTAL_TIMESTEPS.get(algo, 500_000)
        train_algo(algo, timesteps)

    logger.success("Training complete for: " + ", ".join(algos))


if __name__ == "__main__":
    main()
