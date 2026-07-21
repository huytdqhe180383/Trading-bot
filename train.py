"""
Training Entrypoint – train.py
==============================
Trains each individual DRL algorithm on the BTC/ETH environment
and saves checkpoints.  The best model by episode reward is kept.

Usage:
    python train.py [--algo ALL | PPO | SAC] [--timesteps 500000]
"""

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from stable_baselines3 import PPO, SAC
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.evaluation import evaluate_policy
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.utils import set_random_seed
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    ALGORITHMS, ALGO_KWARGS, TOTAL_TIMESTEPS, CHECKPOINT_FREQ,
    PROCESSED_DATA_DIR, MODELS_DIR, LOGS_DIR, SYMBOLS,
    TRAIN_DEVICE, REQUIRE_GPU_FOR_TRAINING, TRAIN_VALIDATION_FRACTION, TRAIN_SEED,
    ENSEMBLE_METHOD, LOOKBACK_WINDOW,
)
from environment.trading_env import SpotPortfolioEnv


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


def split_train_validation(
    data: dict[str, pd.DataFrame],
    validation_fraction: float,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    fraction = float(min(max(validation_fraction, 0.05), 0.5))
    first = next(iter(data.values()))
    split_idx = max(1, min(len(first) - 1, int(len(first) * (1.0 - fraction))))
    train_data = {sym: frame.iloc[:split_idx].copy() for sym, frame in data.items()}
    validation_data = {sym: frame.iloc[split_idx:].copy() for sym, frame in data.items()}
    return train_data, validation_data


def build_rolling_validation_windows(
    data: dict[str, pd.DataFrame],
    *,
    n_windows: int = 5,
    min_rows: int = 0,
) -> list[dict[str, pd.DataFrame]]:
    """Split validation data into distinct chronological windows for non-duplicate evals."""
    if not data:
        return []

    first = next(iter(data.values()))
    total_rows = len(first)
    minimum = int(min_rows or (LOOKBACK_WINDOW + 2))
    if total_rows == 0:
        return []
    if total_rows <= minimum:
        return [{sym: frame.copy() for sym, frame in data.items()}]

    requested = max(1, int(n_windows))
    effective_windows = max(1, min(requested, total_rows // max(1, minimum)))
    if effective_windows == 1:
        return [{sym: frame.copy() for sym, frame in data.items()}]

    boundaries = np.linspace(0, total_rows, effective_windows + 1, dtype=int)
    windows: list[dict[str, pd.DataFrame]] = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        if end - start < minimum:
            continue
        windows.append({sym: frame.iloc[start:end].copy() for sym, frame in data.items()})
    return windows or [{sym: frame.copy() for sym, frame in data.items()}]


def summarize_validation_windows(windows: list[dict[str, pd.DataFrame]]) -> list[dict[str, str | int]]:
    summaries: list[dict[str, str | int]] = []
    for idx, window in enumerate(windows, start=1):
        first = next(iter(window.values()))
        summaries.append(
            {
                "window": idx,
                "rows": int(len(first)),
                "start": str(first.index[0]) if len(first) else "",
                "end": str(first.index[-1]) if len(first) else "",
            }
        )
    return summaries


class RollingValidationCallback(BaseCallback):
    """Evaluate distinct validation windows and save the best mean-window checkpoint."""

    def __init__(
        self,
        *,
        validation_windows: list[dict[str, pd.DataFrame]],
        best_model_save_path: str | Path,
        algo: str,
        eval_freq: int,
        deterministic: bool = True,
        max_no_improvement_evals: int = 10,
        min_evals: int = 20,
        verbose: int = 1,
    ):
        super().__init__(verbose=verbose)
        self.validation_windows = validation_windows
        self.best_model_save_path = Path(best_model_save_path)
        self.algo = algo
        self.eval_freq = max(1, int(eval_freq))
        self.deterministic = deterministic
        self.max_no_improvement_evals = int(max_no_improvement_evals)
        self.min_evals = int(min_evals)
        self.best_mean_reward = -float("inf")
        self.no_improvement_evals = 0
        self.eval_count = 0
        self.evaluation_rows: list[dict[str, float | int | str]] = []

    def _on_step(self) -> bool:
        if self.n_calls % self.eval_freq != 0:
            return True
        if not self.validation_windows:
            return True

        window_rewards: list[float] = []
        window_lengths: list[int] = []
        for window_idx, window_data in enumerate(self.validation_windows, start=1):
            env = Monitor(SpotPortfolioEnv(window_data, mode="eval"))
            try:
                rewards, lengths = evaluate_policy(
                    self.model,
                    env,
                    n_eval_episodes=1,
                    deterministic=self.deterministic,
                    return_episode_rewards=True,
                    warn=False,
                )
            finally:
                env.close()
            reward = float(rewards[0]) if rewards else 0.0
            length = int(lengths[0]) if lengths else 0
            window_rewards.append(reward)
            window_lengths.append(length)
            self.evaluation_rows.append(
                {
                    "timesteps": int(self.num_timesteps),
                    "eval_count": int(self.eval_count + 1),
                    "window": int(window_idx),
                    "reward": reward,
                    "length": length,
                }
            )

        mean_reward = float(np.mean(window_rewards))
        std_reward = float(np.std(window_rewards, ddof=0))
        self.eval_count += 1
        if self.verbose:
            logger.info(
                f"{self.algo} rolling validation | steps={self.num_timesteps:,} "
                f"mean_reward={mean_reward:.2f} +/- {std_reward:.2f} "
                f"windows={len(window_rewards)}"
            )

        if mean_reward > self.best_mean_reward:
            self.best_mean_reward = mean_reward
            self.no_improvement_evals = 0
            self.best_model_save_path.mkdir(parents=True, exist_ok=True)
            self.model.save(str(self.best_model_save_path / "best_model.zip"))
            if self.verbose:
                logger.success(
                    f"New best {self.algo} rolling-validation mean reward: "
                    f"{mean_reward:.2f} -> {self.best_model_save_path / 'best_model.zip'}"
                )
        else:
            self.no_improvement_evals += 1

        if self.eval_count >= self.min_evals and self.no_improvement_evals > self.max_no_improvement_evals:
            if self.verbose:
                logger.warning(
                    f"Stopping {self.algo}: no rolling-validation improvement for "
                    f"{self.no_improvement_evals} evals."
                )
            return False
        return True

    def _on_training_end(self) -> None:
        if not self.evaluation_rows:
            return
        out = LOGS_DIR / self.algo / "rolling_validation_metrics.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(self.evaluation_rows).to_csv(out, index=False)


def _gpu_available() -> bool:
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _resolve_device(requested: str) -> str:
    requested = requested.lower()
    if requested == "auto":
        return "cuda" if _gpu_available() else "cpu"
    return requested


def _resolve_tensorboard_log_dir() -> str | None:
    if importlib.util.find_spec("tensorboard") is None:
        logger.warning("TensorBoard is not installed; training will run without TensorBoard logging.")
        return None
    return str(LOGS_DIR / "tensorboard")


def _candidate_resume_paths(algo: str, models_dir: Path = MODELS_DIR) -> list[Path]:
    algo_dir = Path(models_dir) / algo
    lower = algo.lower()
    return [
        algo_dir / "best_model.zip",
        algo_dir / f"{lower}_best.zip",
        algo_dir / f"{lower}_final.zip",
    ] + sorted(algo_dir.glob(f"{lower}_*_steps.zip"), reverse=True)


def _resolve_resume_checkpoint(
    algo: str,
    explicit: Path | None = None,
    models_dir: Path = MODELS_DIR,
) -> Path | None:
    if explicit is not None:
        if explicit.is_file():
            return explicit
        if explicit.is_dir():
            lower = algo.lower()
            dir_candidates = [
                explicit / algo / "best_model.zip",
                explicit / algo / f"{lower}_best.zip",
                explicit / f"{lower}_best.zip",
                explicit / f"{lower}_final.zip",
            ]
            for p in dir_candidates:
                if p.exists():
                    return p
            step_ckpts = sorted(explicit.glob(f"**/{lower}_*_steps.zip"), reverse=True)
            if step_ckpts:
                return step_ckpts[0]
            return None
        return None

    for path in _candidate_resume_paths(algo, models_dir=models_dir):
        if path.exists():
            return path
    return None


def _load_resumed_model(
    cls,
    *,
    checkpoint: str | Path,
    env,
    device: str,
    tensorboard_log: str | None,
    seed: int,
):
    model = cls.load(
        str(checkpoint),
        env=env,
        device=device,
        tensorboard_log=tensorboard_log,
    )
    if hasattr(model, "set_random_seed"):
        model.set_random_seed(seed)
    return model


def train_algo(
    algo: str,
    timesteps: int,
    *,
    device: str,
    seed: int,
    validation_fraction: float,
    resume: bool = False,
    resume_from: Path | None = None,
    models_dir: Path = MODELS_DIR,
    enable_eval_callback: bool = True,
    validation_windows: int = 5,
    progress_bar: bool = False,
):
    """Train a single algorithm and save the best model."""
    logger.info(f"\n{'='*50}\n  Training: {algo} | Steps: {timesteps:,}\n{'='*50}")

    full_train_data = load_data("train")
    train_data, eval_data = split_train_validation(full_train_data, validation_fraction)
    logger.info(
        f"{algo} split | fit_rows={len(next(iter(train_data.values()))):,} "
        f"validation_rows={len(next(iter(eval_data.values()))):,} seed={seed}"
    )
    eval_windows = build_rolling_validation_windows(eval_data, n_windows=validation_windows)
    logger.info(f"{algo} rolling validation windows: {summarize_validation_windows(eval_windows)}")
    set_random_seed(seed)

    # ── Environment setup ────────────────────────────────────────────────
    def make_train_env():
        env = SpotPortfolioEnv(train_data, mode="train")
        return Monitor(env, str(LOGS_DIR / algo))

    if algo == "SAC":
        # SB3 off-policy MLP training is more stable with one synchronous env here;
        # SubprocVecEnv can wedge during long SAC resume runs on this Windows setup.
        n_envs = 1
        train_vec_cls = DummyVecEnv
    else:
        n_envs = max(1, min(8, (os.cpu_count() or 1)))
        train_vec_cls = SubprocVecEnv
    train_env = make_vec_env(make_train_env, n_envs=n_envs, seed=seed, vec_env_cls=train_vec_cls)

    # ── Callbacks ────────────────────────────────────────────────────────
    model_root = Path(models_dir)
    model_dir = model_root / algo
    model_dir.mkdir(parents=True, exist_ok=True)
    
    checkpoint_freq = CHECKPOINT_FREQ.get(algo, 50_000) if isinstance(CHECKPOINT_FREQ, dict) else CHECKPOINT_FREQ

    checkpoint_cb = CheckpointCallback(
        save_freq=checkpoint_freq,
        save_path=str(model_dir),
        name_prefix=algo.lower(),
        verbose=1,
    )

    callbacks = [checkpoint_cb]
    if enable_eval_callback and eval_windows:
        eval_cb = RollingValidationCallback(
            validation_windows=eval_windows,
            best_model_save_path=model_dir,
            algo=algo,
            eval_freq=max(1, checkpoint_freq // n_envs),
            deterministic=True,
            max_no_improvement_evals=10,
            min_evals=20,
            verbose=1,
        )
        callbacks.append(eval_cb)

    # ── Model ────────────────────────────────────────────────────────────
    cls    = ALGO_CLS[algo]
    kwargs = ALGO_KWARGS[algo].copy()
    tensorboard_log = _resolve_tensorboard_log_dir()

    # On-policy algorithms (PPO) need the env at init time;
    # off-policy (SAC) take it too but also accept replay buffers.
    if resume:
        checkpoint = _resolve_resume_checkpoint(algo, explicit=resume_from, models_dir=model_root)
        if checkpoint is not None:
            logger.info(f"Resuming {algo} from checkpoint: {checkpoint}")
            model = _load_resumed_model(
                cls,
                checkpoint=checkpoint,
                env=train_env,
                device=device,
                tensorboard_log=tensorboard_log,
                seed=seed,
            )
        else:
            logger.warning(f"Resume requested for {algo}, but no checkpoint was found. Starting fresh.")
            model = cls(
                "MlpPolicy",
                train_env,
                device=device,
                seed=seed,
                tensorboard_log=tensorboard_log,
                **kwargs,
            )
    else:
        model = cls(
            "MlpPolicy",
            train_env,
            device=device,
            seed=seed,
            tensorboard_log=tensorboard_log,
            **kwargs,
        )

    try:
        model.learn(
            total_timesteps=timesteps,
            callback=callbacks,
            tb_log_name=algo,
            progress_bar=progress_bar,
            reset_num_timesteps=not resume,
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
        logger.warning(f"No best_model.zip found for {algo}; saving final weights to {algo_best}.")
        model.save(str(algo_best))

    train_env.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train ensemble DRL agents for BTC/ETH trading.")
    parser.add_argument(
        "--algo", default="ALL",
        choices=["ALL"] + ALGORITHMS,
        help="Algorithm to train (default: ALL)",
    )
    parser.add_argument("--timesteps", type=int, default=None, help="Override default timesteps for all algorithms")
    parser.add_argument("--device", default=TRAIN_DEVICE, help="PyTorch device: auto|cpu|cuda|cuda:0")
    parser.add_argument("--seed", type=int, default=TRAIN_SEED, help="Deterministic seed for SB3 and vector envs.")
    parser.add_argument(
        "--validation-fraction",
        type=float,
        default=TRAIN_VALIDATION_FRACTION,
        help="Chronological fraction of the training split reserved for EvalCallback.",
    )
    parser.add_argument(
        "--validation-windows",
        type=int,
        default=5,
        help="Number of distinct chronological validation windows used by rolling evaluation.",
    )
    parser.add_argument(
        "--require-gpu",
        action="store_true",
        default=REQUIRE_GPU_FOR_TRAINING,
        help="Fail fast if GPU is not available.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the latest checkpoint for each selected algorithm.",
    )
    parser.add_argument(
        "--resume-from",
        default=None,
        help="Optional checkpoint file or directory to resume from.",
    )
    parser.add_argument(
        "--disable-eval-callback",
        action="store_true",
        help="Train without EvalCallback and promote final weights directly to the algo best checkpoint.",
    )
    parser.add_argument(
        "--progress-bar",
        action="store_true",
        help="Enable the SB3 rich progress bar.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=MODELS_DIR,
        help="Directory where trained checkpoints are read/written.",
    )
    parser.add_argument(
        "--skip-backtest",
        dest="post_training_backtest",
        action="store_false",
        default=True,
        help="Skip the automatic post-training backtest.",
    )
    parser.add_argument(
        "--post-backtest-pipeline",
        default="rl_only",
        choices=["rl_only", "rl_kronos", "rl_tradingagents", "rl_full"],
        help="Pipeline used by the automatic post-training backtest.",
    )
    parser.add_argument(
        "--post-backtest-realism-profile",
        default="live_like",
        choices=["baseline", "live_like"],
        help="Realism profile used by the automatic post-training backtest.",
    )
    parser.add_argument(
        "--post-backtest-method",
        default=ENSEMBLE_METHOD,
        choices=["mean", "voting", "weighted", "dynamic_weighted", "regime_weighted", "imca"],
        help="Ensemble method used by the automatic post-training backtest.",
    )
    return parser


def build_post_training_backtest_command(args: argparse.Namespace) -> list[str]:
    return [
        "backtest.py",
        "--pipeline",
        args.post_backtest_pipeline,
        "--realism-profile",
        args.post_backtest_realism_profile,
        "--method",
        args.post_backtest_method,
        "--model-dir",
        str(args.models_dir),
    ]


def run_post_training_backtest(args: argparse.Namespace) -> None:
    command = build_post_training_backtest_command(args)
    logger.info("Running post-training backtest: " + " ".join(command))
    subprocess.run([sys.executable, *command], cwd=Path(__file__).resolve().parent, check=True)


def main():
    parser = build_parser()
    args = parser.parse_args()

    device = _resolve_device(args.device)
    if args.require_gpu and not _gpu_available():
        raise RuntimeError("GPU was required but torch.cuda.is_available() is False.")
    logger.info(f"Training device resolved to: {device}")

    algos = ALGORITHMS if args.algo == "ALL" else [args.algo]
    resume_from_path = Path(args.resume_from).resolve() if args.resume_from else None

    for algo in algos:
        # Determine specific timesteps for the algorithm
        timesteps = args.timesteps if args.timesteps is not None else TOTAL_TIMESTEPS.get(algo, 500_000)
        train_algo(
            algo,
            timesteps,
            device=device,
            seed=args.seed,
            validation_fraction=args.validation_fraction,
            resume=args.resume,
            resume_from=resume_from_path,
            models_dir=args.models_dir,
            enable_eval_callback=not args.disable_eval_callback,
            validation_windows=args.validation_windows,
            progress_bar=args.progress_bar,
        )

    logger.success("Training complete for: " + ", ".join(algos))
    if args.post_training_backtest:
        run_post_training_backtest(args)


if __name__ == "__main__":
    main()
