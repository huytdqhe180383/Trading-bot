import numpy as np
import torch
import torch.nn as nn
from gymnasium import ActionWrapper

# 1. Action Smoothing by Aligning Actions with Predictions from Preceding States (ASAP)
class ASAPActionSmoother(ActionWrapper):
    """
    Penalizes high-frequency oscillations by aligning actions with predictions 
    from preceding states. Acts as a spatiotemporal continuous filter.
    """
    def __init__(self, env, smoothing_gamma=0.8):
        super().__init__(env)
        self.smoothing_gamma = smoothing_gamma
        self.last_action = None
        
    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        self.last_action = np.zeros(self.action_space.shape)
        return obs, info
        
    def action(self, act):
        # Blend current predicted action with previous action to mechanically kill erratic friction
        smoothed_action = (self.smoothing_gamma * self.last_action) + ((1 - self.smoothing_gamma) * act)
        self.last_action = smoothed_action
        return smoothed_action

# 2. Meta-Labeling Two-Part System
class PrimaryDirectionLSTM(nn.Module):
    """LSTM primary agent for directional prediction without sizing decisions."""
    def __init__(self, input_dim, hidden_dim, num_assets):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, batch_first=True)
        self.attention = nn.MultiheadAttention(embed_dim=hidden_dim, num_heads=4)
        self.fc = nn.Linear(hidden_dim, num_assets)
        
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        # Apply attention to temporal states
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        return torch.tanh(self.fc(attn_out[:, -1, :])) # [-1, 1] Directional certainty

class MetaLabelingSizer(nn.Module):
    """Secondary meta-agent for position sizing from direction + macro state."""
    def __init__(self, hidden_dim, num_assets):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(num_assets + hidden_dim, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, num_assets)
        )
        
    def forward(self, direction_pred, macro_state):
        x = torch.cat([direction_pred, macro_state], dim=-1)
        # Outputs [0, 1] scalar of how much capital to actually commit 
        # (effectively decoupling the sizing from the direction)
        return torch.sigmoid(self.net(x))

# 3. Spatiotemporal Curriculum Experience Replay Proxy
class FatTailReplayBuffer:
    def __init__(self):
        self.buffer = []
        
    def add_spatiotemporal_experience(self, transition, returns):
        # We classify temporal experiences by structural crash vs bull regimes
        # Prioritize sampling from regions of high variance (fat-tails) during the curriculum
        weight = np.abs(returns) * 1.5 if returns < -0.05 else 1.0
        self.buffer.append((transition, weight))
