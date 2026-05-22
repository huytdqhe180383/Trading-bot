import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from loguru import logger

class VAE(nn.Module):
    def __init__(self, input_dim: int, latent_dim: int = 8):
        super().__init__()
        # Encoder
        self.fc1 = nn.Linear(input_dim, 64)
        self.fc2 = nn.Linear(64, 32)
        self.fc_mu = nn.Linear(32, latent_dim)
        self.fc_logvar = nn.Linear(32, latent_dim)
        
        # Decoder
        self.fc3 = nn.Linear(latent_dim, 32)
        self.fc4 = nn.Linear(32, 64)
        self.fc5 = nn.Linear(64, input_dim)
        
        self.relu = nn.ReLU()
        
    def encode(self, x):
        h1 = self.relu(self.fc1(x))
        h2 = self.relu(self.fc2(h1))
        return self.fc_mu(h2), self.fc_logvar(h2)

    def reparameterize(self, mu, logvar):
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z):
        h3 = self.relu(self.fc3(z))
        h4 = self.relu(self.fc4(h3))
        return self.fc5(h4)

    def forward(self, x):
        mu, logvar = self.encode(x)
        z = self.reparameterize(mu, logvar)
        return self.decode(z), mu, logvar


def loss_function(recon_x, x, mu, logvar):
    MSE = nn.functional.mse_loss(recon_x, x, reduction='sum')
    KLD = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())
    return MSE + KLD


class VAEAnomalyDetector:
    def __init__(self, input_dim: int, latent_dim: int = 8, device="cpu"):
        self.device = torch.device(device)
        self.model = VAE(input_dim, latent_dim).to(self.device)
        self.threshold = None
    
    def train(self, data: np.ndarray, epochs: int = 50, batch_size: int = 128, lr: float = 1e-3):
        logger.info(f"Training VAE on {len(data)} samples...")
        dataset = TensorDataset(torch.FloatTensor(data))
        dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
        optimizer = optim.Adam(self.model.parameters(), lr=lr)
        
        self.model.train()
        for epoch in range(epochs):
            for batch in dataloader:
                x = batch[0].to(self.device)
                optimizer.zero_grad()
                recon_batch, mu, logvar = self.model(x)
                loss = loss_function(recon_batch, x, mu, logvar)
                loss.backward()
                optimizer.step()
        
        # Compute threshold (99th percentile of reconstruction error)
        self.model.eval()
        errors = []
        with torch.no_grad():
            for batch in dataloader:
                x = batch[0].to(self.device)
                recon_batch, _, _ = self.model(x)
                mse = nn.functional.mse_loss(recon_batch, x, reduction='none').mean(dim=1)
                errors.extend(mse.cpu().numpy())
                
        self.threshold = float(np.percentile(errors, 99))
        logger.info(f"VAE training complete. 99th percentile threshold: {self.threshold:.6f}")
        
    def compute_error(self, obs: np.ndarray) -> float:
        self.model.eval()
        with torch.no_grad():
            x = torch.FloatTensor(obs).unsqueeze(0).to(self.device) if obs.ndim == 1 else torch.FloatTensor(obs).to(self.device)
            recon_x, _, _ = self.model(x)
            mse = nn.functional.mse_loss(recon_x, x, reduction='none').mean(dim=-1)
        return mse.item() if mse.numel() == 1 else mse.cpu().numpy()

    def save(self, path: str):
        torch.save({'state_dict': self.model.state_dict(), 'threshold': self.threshold}, path)
        logger.success(f"Saved VAE model to {path}")
        
    def load(self, path: str):
        if os.path.exists(path):
            checkpoint = torch.load(path, map_location=self.device)
            self.model.load_state_dict(checkpoint['state_dict'])
            self.threshold = checkpoint['threshold']
            logger.info(f"Loaded VAE from {path} with threshold {self.threshold}")
        else:
            logger.warning(f"VAE model not found at {path}")
