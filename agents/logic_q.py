import numpy as np
from config import N_ASSETS

class LogicQSketch:
    """
    Logic-Q Post-Hoc Program Sketch.
    Evaluates recent market trajectory and injects a massive negative scalar bias
    into risk asset logits to favor cash if a rapid descent is identified.
    """
    def __init__(self, return_threshold: float = -0.05, vol_threshold: float = 0.02, penalty: float = -100.0):
        self.return_threshold = return_threshold
        self.vol_threshold = vol_threshold
        self.penalty = penalty
        self.history = []

    def update(self, market_return: float):
        """Update recent market trajectory."""
        self.history.append(market_return)
        if len(self.history) > 24:  # Keep a small window, e.g., 24 periods
            self.history.pop(0)

    def evaluate(self, current_return: float = None, current_volatility: float = None) -> np.ndarray:
        """
        Evaluate the sketch logic.
        Returns a bias vector to be added to the raw logits (N_ASSETS,).
        If 'rapid descent' is identified, risk assets get a large negative bias.
        """
        # If no explicit values are passed, try to estimate from history
        if current_return is None:
            if not self.history:
                current_return = 0.0
            else:
                # Cumulative return over recent history as a proxy
                current_return = sum(self.history)
                
        if current_volatility is None:
            if len(self.history) < 2:
                current_volatility = 0.0
            else:
                current_volatility = np.std(self.history)

        bias = np.zeros(N_ASSETS, dtype=np.float32)

        # "rapid descent" condition
        if current_return < self.return_threshold and current_volatility > self.vol_threshold:
            # Inject a massive negative scalar bias directly into the risk asset logits
            bias -= abs(self.penalty)

        return bias
