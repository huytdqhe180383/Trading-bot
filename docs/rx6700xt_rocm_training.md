# RX6700XT ROCm Training Guide

Last updated: 2026-05-22

This guide explains the practical path for using an AMD Radeon RX6700XT for
reinforcement learning training in this project.

## Recommendation

Use WSL2 Ubuntu or native Linux with ROCm for PyTorch acceleration. Treat
Windows-native GPU training as a non-primary path for this card.

Why:

- The RX6700XT is RDNA2/gfx1031.
- The current local Windows environment has CPU-only PyTorch:
  - `torch 2.10.0+cpu`
  - `torch.cuda.is_available() == False`
  - `torch.version.hip == None`
- AMD's Windows HIP SDK support table marks RX6700XT runtime support as present
  but HIP SDK support as unsupported.
- Official PyTorch ROCm setup remains strongest on Linux and Linux containers.

## Install Path: WSL2 Ubuntu

Install WSL2 and Ubuntu:

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
```

Inside Ubuntu, update packages:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
```

Install ROCm using AMD's current Linux instructions for your Ubuntu version.
After installation, confirm the GPU is visible:

```bash
rocminfo | grep -i gfx
```

For RX6700XT, expect a gfx1031-class device. Some ROCm/PyTorch builds may need
architecture compatibility handling for RDNA2 consumer cards. Do not assume a
ROCm install is valid until PyTorch verification passes.

## PyTorch ROCm Environment

Create a Linux virtual environment:

```bash
python3 -m venv .venv-rocm
source .venv-rocm/bin/activate
python -m pip install --upgrade pip wheel setuptools
```

Install PyTorch ROCm wheels using the version recommended by the PyTorch install
matrix for Linux + ROCm:

```bash
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/rocm7.2
```

If you choose a stable ROCm wheel instead of nightly, use the current command
from the PyTorch install matrix.

Verify:

```bash
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("gpu:", torch.cuda.is_available())
print("hip:", torch.version.hip)
print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
PY
```

The important signals are:

- `torch.cuda.is_available()` should be `True`.
- `torch.version.hip` should show a ROCm/HIP version.
- The device name should correspond to the AMD GPU.

From the project root, also run:

```bash
python scripts/verify_gpu_training_stack.py
```

## Docker Option

If bare-metal ROCm is fragile, use an AMD ROCm PyTorch container on Linux:

```bash
docker run -it \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  --ipc=host \
  --shm-size 8G \
  -v "$PWD":/workspace \
  -w /workspace \
  rocm/pytorch:latest
```

Inside the container, install the project dependencies that are not already in
the image:

```bash
pip install -r requirements.txt
python scripts/verify_gpu_training_stack.py
```

## Stable-Baselines3 Expectations

Stable-Baselines3 can use PyTorch devices through the `device` argument. This
project already uses `device="auto"` for SAC and CPU for PPO in `train.py`.

Expected behavior:

- SAC should benefit more from GPU because it performs replay-buffer gradient
  updates.
- PPO can remain CPU-heavy because rollout collection and vectorized
  environments dominate runtime.
- Multi-process environments can bottleneck on CPU, IPC, and pandas/numpy data
  access even when the neural network is on GPU.

Recommended tuning after ROCm works:

```powershell
python train.py --algo SAC --timesteps 300000
python train.py --algo PPO --timesteps 500000
```

Then compare:

- wall-clock training time
- TensorBoard training curves
- backtest metrics
- GPU utilization

## Troubleshooting

If `rocminfo` is missing:

- ROCm is not installed or not on PATH.

If `torch.version.hip` is `None`:

- You installed CPU or CUDA PyTorch, not ROCm PyTorch.

If `torch.cuda.is_available()` is `False` even with ROCm PyTorch:

- The ROCm runtime cannot see the GPU.
- The installed PyTorch ROCm wheel may not include a compatible code object for
  the RX6700XT architecture.
- Check AMD's current ROCm compatibility matrix and PyTorch ROCm wheel version.

If training is slower on GPU:

- Start with SAC rather than PPO.
- Reduce environment process count if CPU contention dominates.
- Profile rollout collection separately from neural-network updates.

