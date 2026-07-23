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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    ENSEMBLE_METHOD, LOOKBACK_WINDOW, BINANCE_SPOT_FEE, SLIPPAGE,
)
from environment.trading_env import SpotPortfolioEnv


ALGO_CLS = {"PPO": PPO, "SAC": SAC}


@dataclass(frozen=True)
class ValidationCostProfile:
    label: str
    fee: float
    slippage: float


def parse_validation_cost_profiles(raw: str | None) -> list[ValidationCostProfile]:
    """Parse label:fee:slippage validation-cost profiles."""
    if raw is None or str(raw).strip() == "":
        return [ValidationCostProfile("env_default", float(BINANCE_SPOT_FEE), float(SLIPPAGE))]

    profiles: list[ValidationCostProfile] = []
    for part in str(raw).split(","):
        text = part.strip()
        if not text:
            continue
        pieces = [piece.strip() for piece in text.split(":")]
        if len(pieces) != 3:
            raise argparse.ArgumentTypeError(
                f"Invalid validation cost profile {text!r}; expected label:fee:slippage."
            )
        label, fee_raw, slippage_raw = pieces
        if not label:
            raise argparse.ArgumentTypeError(f"Invalid validation cost profile {text!r}; label is empty.")
        fee = float(fee_raw)
        slippage = float(slippage_raw)
        if fee < 0 or slippage < 0:
            raise argparse.ArgumentTypeError(
                f"Invalid validation cost profile {text!r}; fee and slippage must be non-negative."
            )
        profiles.append(ValidationCostProfile(label=label, fee=fee, slippage=slippage))
    if not profiles:
        raise argparse.ArgumentTypeError("At least one validation cost profile is required.")
    return profiles


def validation_selection_score(
    *,
    profile_mean_rewards: dict[str, float],
    all_rewards: list[float],
    mode: str,
) -> float:
    if not all_rewards:
        return -float("inf")
    if mode == "mean_reward":
        return float(np.mean(all_rewards))
    if mode == "worst_profile_mean":
        return float(min(profile_mean_rewards.values())) if profile_mean_rewards else -float("inf")
    if mode == "mean_minus_std":
        return float(np.mean(all_rewards) - np.std(all_rewards, ddof=0))
    raise ValueError(f"Unknown validation score mode: {mode}")


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
        cost_profiles: list[ValidationCostProfile] | None = None,
        env_kwargs: dict[str, Any] | None = None,
        score_mode: str = "mean_reward",
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
        self.cost_profiles = cost_profiles or parse_validation_cost_profiles(None)
        self.env_kwargs = dict(env_kwargs or {})
        self.score_mode = str(score_mode)
        self.deterministic = deterministic
        self.max_no_improvement_evals = int(max_no_improvement_evals)
        self.min_evals = int(min_evals)
        self.best_mean_reward = -float("inf")
        self.best_selection_score = -float("inf")
        self.no_improvement_evals = 0
        self.eval_count = 0
        self.evaluation_rows: list[dict[str, float | int | str]] = []

    def should_stop_early(self) -> bool:
        return (
            self.eval_count >= self.min_evals
            and self.no_improvement_evals >= self.max_no_improvement_evals
        )

    def _on_step(self) -> bool:
        if self.n_calls % self.eval_freq != 0:
            return True
        if not self.validation_windows:
            return True

        window_rewards: list[float] = []
        profile_rewards: dict[str, list[float]] = {profile.label: [] for profile in self.cost_profiles}
        for profile in self.cost_profiles:
            for window_idx, window_data in enumerate(self.validation_windows, start=1):
                env_kwargs = dict(self.env_kwargs)
                env_kwargs.update(
                    {
                        "trading_fee": profile.fee,
                        "slippage": profile.slippage,
                    }
                )
                env = Monitor(
                    SpotPortfolioEnv(
                        window_data,
                        mode="eval",
                        **env_kwargs,
                    )
                )
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
                profile_rewards[profile.label].append(reward)
                self.evaluation_rows.append(
                    {
                        "timesteps": int(self.num_timesteps),
                        "eval_count": int(self.eval_count + 1),
                        "cost_profile": profile.label,
                        "fee": float(profile.fee),
                        "slippage": float(profile.slippage),
                        "window": int(window_idx),
                        "reward": reward,
                        "length": length,
                    }
                )

        mean_reward = float(np.mean(window_rewards))
        std_reward = float(np.std(window_rewards, ddof=0))
        profile_mean_rewards = {
            label: float(np.mean(rewards)) for label, rewards in profile_rewards.items() if rewards
        }
        selection_score = validation_selection_score(
            profile_mean_rewards=profile_mean_rewards,
            all_rewards=window_rewards,
            mode=self.score_mode,
        )
        self.eval_count += 1
        if self.verbose:
            profile_text = ", ".join(f"{label}={value:.2f}" for label, value in profile_mean_rewards.items())
            logger.info(
                f"{self.algo} rolling validation | steps={self.num_timesteps:,} "
                f"mean_reward={mean_reward:.2f} +/- {std_reward:.2f} "
                f"selection_score={selection_score:.2f} mode={self.score_mode} "
                f"windows={len(self.validation_windows)} profiles=[{profile_text}]"
            )

        if selection_score > self.best_selection_score:
            self.best_mean_reward = mean_reward
            self.best_selection_score = selection_score
            self.no_improvement_evals = 0
            self.best_model_save_path.mkdir(parents=True, exist_ok=True)
            self.model.save(str(self.best_model_save_path / "best_model.zip"))
            if self.verbose:
                logger.success(
                    f"New best {self.algo} rolling-validation score: "
                    f"{selection_score:.2f} (mean_reward={mean_reward:.2f}) "
                    f"-> {self.best_model_save_path / 'best_model.zip'}"
                )
        else:
            self.no_improvement_evals += 1

        if self.should_stop_early():
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
    validation_cost_profiles: list[ValidationCostProfile] | None = None,
    validation_score_mode: str = "mean_reward",
    training_fee: float | None = None,
    training_slippage: float | None = None,
    training_reward_turnover_weight: float | None = None,
    training_reward_action_delta_weight: float | None = None,
    training_reward_action_delta_deadband: float | None = None,
    training_reward_action_delta_scale: float | None = None,
    training_step_turnover_cap_enabled: bool | None = None,
    training_step_turnover_cap_normal: float | None = None,
    training_step_turnover_cap_stress: float | None = None,
    training_step_turnover_cap_crisis: float | None = None,
    validation_early_stop_patience: int = 10,
    validation_early_stop_min_evals: int = 20,
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
        env_kwargs = {}
        if training_fee is not None:
            env_kwargs["trading_fee"] = float(training_fee)
        if training_slippage is not None:
            env_kwargs["slippage"] = float(training_slippage)
        if training_reward_turnover_weight is not None:
            env_kwargs["reward_turnover_weight"] = float(training_reward_turnover_weight)
        if training_reward_action_delta_weight is not None:
            env_kwargs["reward_action_delta_weight"] = float(training_reward_action_delta_weight)
        if training_reward_action_delta_deadband is not None:
            env_kwargs["reward_action_delta_deadband"] = float(training_reward_action_delta_deadband)
        if training_reward_action_delta_scale is not None:
            env_kwargs["reward_action_delta_scale"] = float(training_reward_action_delta_scale)
        if training_step_turnover_cap_enabled is not None:
            env_kwargs["step_turnover_cap_enabled"] = bool(training_step_turnover_cap_enabled)
        if training_step_turnover_cap_normal is not None:
            env_kwargs["step_turnover_cap_normal"] = float(training_step_turnover_cap_normal)
        if training_step_turnover_cap_stress is not None:
            env_kwargs["step_turnover_cap_stress"] = float(training_step_turnover_cap_stress)
        if training_step_turnover_cap_crisis is not None:
            env_kwargs["step_turnover_cap_crisis"] = float(training_step_turnover_cap_crisis)
        env = SpotPortfolioEnv(train_data, mode="train", **env_kwargs)
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
            cost_profiles=validation_cost_profiles,
            env_kwargs={
                key: value
                for key, value in {
                    "reward_turnover_weight": training_reward_turnover_weight,
                    "reward_action_delta_weight": training_reward_action_delta_weight,
                    "reward_action_delta_deadband": training_reward_action_delta_deadband,
                    "reward_action_delta_scale": training_reward_action_delta_scale,
                    "step_turnover_cap_enabled": training_step_turnover_cap_enabled,
                    "step_turnover_cap_normal": training_step_turnover_cap_normal,
                    "step_turnover_cap_stress": training_step_turnover_cap_stress,
                    "step_turnover_cap_crisis": training_step_turnover_cap_crisis,
                }.items()
                if value is not None
            },
            score_mode=validation_score_mode,
            deterministic=True,
            max_no_improvement_evals=validation_early_stop_patience,
            min_evals=validation_early_stop_min_evals,
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
        "--validation-cost-profiles",
        type=parse_validation_cost_profiles,
        default=parse_validation_cost_profiles(None),
        help="Comma-separated validation cost profiles as label:fee:slippage.",
    )
    parser.add_argument(
        "--validation-score-mode",
        default="mean_reward",
        choices=["mean_reward", "worst_profile_mean", "mean_minus_std"],
        help="Checkpoint selection score computed from rolling validation rewards.",
    )
    parser.add_argument(
        "--validation-early-stop-patience",
        type=int,
        default=10,
        help="Stop after this many consecutive non-improving rolling validations once min evals is reached.",
    )
    parser.add_argument(
        "--validation-early-stop-min-evals",
        type=int,
        default=20,
        help="Minimum rolling-validation evaluations before early stopping can trigger.",
    )
    parser.add_argument(
        "--training-fee",
        type=float,
        default=None,
        help="Override the training environment fee.",
    )
    parser.add_argument(
        "--training-slippage",
        type=float,
        default=None,
        help="Override the training environment slippage.",
    )
    parser.add_argument(
        "--training-reward-turnover-weight",
        type=float,
        default=None,
        help="Override the training and rolling-validation reward turnover weight.",
    )
    parser.add_argument(
        "--training-reward-action-delta-weight",
        type=float,
        default=None,
        help="Override the training and rolling-validation action-delta penalty weight.",
    )
    parser.add_argument(
        "--training-reward-action-delta-deadband",
        type=float,
        default=None,
        help="Override the action-delta reward deadband.",
    )
    parser.add_argument(
        "--training-reward-action-delta-scale",
        type=float,
        default=None,
        help="Override the action-delta reward scale.",
    )
    parser.add_argument(
        "--training-step-turnover-cap",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable a per-step turnover cap in training and rolling validation.",
    )
    parser.add_argument(
        "--training-step-turnover-cap-normal",
        type=float,
        default=None,
        help="Training per-step turnover cap in normal regimes.",
    )
    parser.add_argument(
        "--training-step-turnover-cap-stress",
        type=float,
        default=None,
        help="Training per-step turnover cap in stress regimes.",
    )
    parser.add_argument(
        "--training-step-turnover-cap-crisis",
        type=float,
        default=None,
        help="Training per-step turnover cap in crisis regimes.",
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
    command = [
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
    if getattr(args, "training_step_turnover_cap", None) is True:
        command.append("--step-turnover-cap-enabled")
    elif getattr(args, "training_step_turnover_cap", None) is False:
        command.append("--no-step-turnover-cap-enabled")
    for flag, attr in [
        ("--step-turnover-cap-normal", "training_step_turnover_cap_normal"),
        ("--step-turnover-cap-stress", "training_step_turnover_cap_stress"),
        ("--step-turnover-cap-crisis", "training_step_turnover_cap_crisis"),
    ]:
        value = getattr(args, attr, None)
        if value is not None:
            command.extend([flag, str(value)])
    return command


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
    if args.training_fee is not None and args.training_fee < 0:
        raise ValueError("--training-fee must be non-negative")
    if args.training_slippage is not None and args.training_slippage < 0:
        raise ValueError("--training-slippage must be non-negative")
    if args.validation_early_stop_patience < 1:
        raise ValueError("--validation-early-stop-patience must be at least 1")
    if args.validation_early_stop_min_evals < 1:
        raise ValueError("--validation-early-stop-min-evals must be at least 1")
    non_negative_options = [
        "training_reward_turnover_weight",
        "training_reward_action_delta_weight",
        "training_reward_action_delta_deadband",
        "training_reward_action_delta_scale",
        "training_step_turnover_cap_normal",
        "training_step_turnover_cap_stress",
        "training_step_turnover_cap_crisis",
    ]
    for option in non_negative_options:
        value = getattr(args, option)
        if value is not None and value < 0:
            raise ValueError(f"--{option.replace('_', '-')} must be non-negative")
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
            validation_cost_profiles=args.validation_cost_profiles,
            validation_score_mode=args.validation_score_mode,
            training_fee=args.training_fee,
            training_slippage=args.training_slippage,
            training_reward_turnover_weight=args.training_reward_turnover_weight,
            training_reward_action_delta_weight=args.training_reward_action_delta_weight,
            training_reward_action_delta_deadband=args.training_reward_action_delta_deadband,
            training_reward_action_delta_scale=args.training_reward_action_delta_scale,
            training_step_turnover_cap_enabled=args.training_step_turnover_cap,
            training_step_turnover_cap_normal=args.training_step_turnover_cap_normal,
            training_step_turnover_cap_stress=args.training_step_turnover_cap_stress,
            training_step_turnover_cap_crisis=args.training_step_turnover_cap_crisis,
            validation_early_stop_patience=args.validation_early_stop_patience,
            validation_early_stop_min_evals=args.validation_early_stop_min_evals,
            progress_bar=args.progress_bar,
        )

    logger.success("Training complete for: " + ", ".join(algos))
    if args.post_training_backtest:
        run_post_training_backtest(args)


if __name__ == "__main__":
    main()
