"""
Strategy Layer – Ensemble Agent
================================
Loads individual trained DRL models (PPO, SAC) and
combines their portfolio weight proposals using the configured
aggregation method.

Aggregation modes:
  "mean"     – arithmetic average of all agents' softmax weights
  "voting"   – each agent votes on the highest-conviction asset
  "weighted" – weights each agent by its validation Sharpe ratio
"""

import sys
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger
from stable_baselines3 import PPO, SAC

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ALGORITHMS, MODELS_DIR, ENSEMBLE_METHOD, N_ASSETS
from environment.trading_env import _softmax_weights

# ── Algorithm registry ──────────────────────────────────────────────────
ALGO_CLS = {
    "PPO":  PPO,
    "SAC":  SAC,
}


def load_agent(algo: str, path: Path) -> Any:
    """Load a single trained SB3 model from disk."""
    cls = ALGO_CLS[algo]
    model = cls.load(str(path))
    logger.info(f"Loaded {algo} model from {path}")
    return model


def load_ensemble(model_dir: Path = MODELS_DIR) -> dict[str, Any]:
    """
    Discover and load all best-checkpoint models from *model_dir*.
    Returns dict: algo → model.
    """
    ensemble = {}
    for algo in ALGORITHMS:
        algo_dir = model_dir / algo
        pattern = f"{algo.lower()}_best.zip"
        
        # Check subfolder first, fallback to root dir if old structure
        candidates = list(algo_dir.glob(pattern))
        if not candidates:
            candidates = list(model_dir.glob(pattern))
            
        if not candidates:
            logger.warning(f"No best model found for {algo} in {algo_dir} or {model_dir}")
            continue
        ensemble[algo] = load_agent(algo, candidates[0])
    if not ensemble:
        raise FileNotFoundError(
            f"No trained models found in {model_dir}. Run train.py first."
        )
    return ensemble


# ── Ensemble inference ───────────────────────────────────────────────────

def _softmax_clipped(raw: np.ndarray) -> np.ndarray:
    """Positive-only softmax (no shorting), incl. implicit cash weight."""
    clipped = np.clip(raw, 0.0, None)
    exp = np.exp(clipped - clipped.max())
    weights = exp / (exp.sum() + 1.0)
    cash = 1.0 - weights.sum()
    return np.append(weights, max(float(cash), 0.0)).astype(np.float32)


class EnsembleAgent:
    """
    Aggregates predictions from all sub-agents into a single
    portfolio allocation vector [w_BTC, w_ETH, w_USDT].
    """

    def __init__(
        self,
        ensemble: dict[str, Any],
        method: str = ENSEMBLE_METHOD,
        agent_sharpes: dict[str, float] | None = None,
    ):
        self.ensemble = ensemble
        self.method   = method
        # Sharpe scores used when method == "weighted"
        self._sharpes = agent_sharpes or {a: 1.0 for a in ensemble}

    def predict(self, obs: np.ndarray) -> np.ndarray:
        """Return combined portfolio weights (n_assets + 1,)."""
        proposals: list[np.ndarray] = []
        for algo, model in self.ensemble.items():
            raw_action, _ = model.predict(obs, deterministic=True)
            weights = _softmax_weights(raw_action)
            proposals.append(weights)

        if self.method == "mean":
            return np.mean(proposals, axis=0).astype(np.float32)

        elif self.method == "voting":
            # Each agent nominates the asset with the highest weight
            votes = np.zeros(N_ASSETS + 1, dtype=np.float32)
            for w in proposals:
                votes[np.argmax(w)] += 1.0
            votes /= votes.sum()
            return votes

        elif self.method == "weighted":
            total_sharpe = sum(max(self._sharpes.get(a, 1e-6), 1e-6) for a in self.ensemble)
            result = np.zeros(N_ASSETS + 1, dtype=np.float32)
            for algo, w in zip(self.ensemble.keys(), proposals):
                s = max(self._sharpes.get(algo, 1e-6), 1e-6)
                result += (s / total_sharpe) * w
            return result

        elif self.method in ["dynamic_weighted", "imca"]:
            # Uses _sharpes as dynamically updated weights from the outside
            total_weight = sum(max(self._sharpes.get(a, 1e-6), 1e-6) for a in self.ensemble)
            result = np.zeros(N_ASSETS + 1, dtype=np.float32)
            for algo, w in zip(self.ensemble.keys(), proposals):
                weight = max(self._sharpes.get(algo, 1e-6), 1e-6)
                result += (weight / total_weight) * w
            return result

        else:
            raise ValueError(f"Unknown ensemble method: {self.method}")
