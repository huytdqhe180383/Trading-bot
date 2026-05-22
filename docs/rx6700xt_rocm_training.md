# RX6700XT ROCm Training Guide

Last updated: 2026-05-22

This is a practical setup guide for using an AMD Radeon RX 6700 XT with this
Stable-Baselines3 trading project.

Important reality check: the RX 6700 XT is not listed in the current AMD ROCm
7.2.1 Radeon Linux, WSL, or Windows PyTorch support matrices. AMD's current
official Radeon support tables list newer cards such as RX 7700 XT, RX 7800 XT,
RX 7900 XT/XTX, RX 9070, and related PRO cards, but not RX 6700 XT. That means
this setup is best treated as an experimental research setup, not a guaranteed
officially supported production path.

The recommended route is:

1. Try WSL2 Ubuntu first because it keeps Windows intact.
2. If WSL2 cannot expose the RX 6700 XT to ROCm/PyTorch, use native Ubuntu
   22.04.5 or 24.04.4 on a separate partition or drive.
3. Keep CPU training available as the fallback.

## 1. Current Local Baseline

The current Windows Python environment reports:

```text
torch 2.10.0+cpu
torch.cuda.is_available() == False
torch.version.hip == None
rocminfo not on PATH
hipcc not on PATH
```

That means the project is currently CPU-only.

Run this local verifier any time:

```powershell
python scripts\verify_gpu_training_stack.py
```

The target success state is:

```text
torch GPU available: True
torch HIP version: <not None>
ready for ROCm training: True
```

## 2. Choose the Setup Path

Use this decision table before installing anything:

| Path | Use when | Support status | Risk |
| --- | --- | --- | --- |
| WSL2 Ubuntu 22.04/24.04 | You want to keep Windows as the host OS | Official WSL path exists, but RX 6700 XT is not listed | Medium/high |
| Native Ubuntu 22.04.5/24.04.4 | WSL2 does not detect the card or PyTorch cannot use HIP | Official Linux path exists, but RX 6700 XT is not listed | Medium |
| Windows-native PyTorch ROCm | You want no Linux layer | Windows PyTorch ROCm matrix does not list RX 6700 XT | High |
| CPU training | You need reproducibility immediately | Already works | Slow |

## 3. WSL2 Path

### Step 3.1: Install or update WSL2

Open PowerShell as Administrator:

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
wsl --update
wsl --shutdown
```

Ubuntu 22.04 and 24.04 are the WSL distributions listed by AMD's ROCm 7.2.1 WSL
matrix. Start with Ubuntu 22.04 because AMD's WSL PyTorch wheel instructions
provide Python 3.10 wheels for Ubuntu 22.04.

### Step 3.2: Install the AMD WSL driver on Windows

Install the AMD Software: Adrenalin Edition driver variant that AMD lists for
ROCm on WSL. For ROCm 7.2.1, AMD documents Adrenalin Edition 26.1.1 for WSL2.

After installing the driver:

```powershell
wsl --shutdown
Restart-Computer
```

### Step 3.3: Install ROCm packages inside WSL Ubuntu

Open Ubuntu:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y wget git python3 python3-pip python3-venv python3-setuptools python3-wheel
```

Install AMD's WSL installer package for Ubuntu 22.04:

```bash
wget https://repo.radeon.com/amdgpu-install/7.2/ubuntu/jammy/amdgpu-install_7.2.70200-1_all.deb
sudo apt install ./amdgpu-install_7.2.70200-1_all.deb
```

Install the WSL ROCm usecase:

```bash
sudo amdgpu-install --list-usecase
amdgpu-install -y --usecase=wsl,rocm --no-dkms
```

Verify ROCm sees an agent:

```bash
rocminfo
rocminfo | grep -E "Name:|Marketing Name:|gfx"
```

For RX 6700 XT, look for a gfx1031-class device. If `rocminfo` cannot see the
card, do not continue to PyTorch yet.

## 4. PyTorch ROCm Setup in WSL

AMD's ROCm 7.2 WSL guide recommends PyTorch 2.9.1 ROCm wheels and notes that
Python 3.12 is needed for Ubuntu 24.04 wheels while Python 3.10 is used for
Ubuntu 22.04 wheels.

Create a clean environment:

```bash
python3 -m venv .venv-rocm
source .venv-rocm/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install numpy==1.26.4
```

Download and install AMD's Ubuntu 22.04 ROCm wheels:

```bash
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2/torch-2.9.1%2Brocm7.2.0.lw.git7e1940d4-cp310-cp310-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2/torchvision-0.24.0%2Brocm7.2.0.gitb919bd0c-cp310-cp310-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2/triton-3.5.1%2Brocm7.2.0.gita272dfa8-cp310-cp310-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2/torchaudio-2.9.0%2Brocm7.2.0.gite3c6ee2b-cp310-cp310-linux_x86_64.whl
pip uninstall -y torch torchvision triton torchaudio
pip install \
  torch-2.9.1+rocm7.2.0.lw.git7e1940d4-cp310-cp310-linux_x86_64.whl \
  torchvision-0.24.0+rocm7.2.0.gitb919bd0c-cp310-cp310-linux_x86_64.whl \
  torchaudio-2.9.0+rocm7.2.0.gite3c6ee2b-cp310-cp310-linux_x86_64.whl \
  triton-3.5.1+rocm7.2.0.gita272dfa8-cp310-cp310-linux_x86_64.whl
```

AMD's WSL guide also removes PyTorch's bundled HSA runtime so WSL uses the WSL
runtime library:

```bash
location=$(pip show torch | grep Location | awk -F ": " '{print $2}')
cd "${location}/torch/lib/"
rm -f libhsa-runtime64.so*
```

Verify PyTorch:

```bash
python3 -c 'import torch' 2> /dev/null && echo Success || echo Failure
python3 -c "import torch; print(torch.cuda.is_available())"
python3 -c "import torch; print(torch.version.hip)"
python3 -c "import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
python3 -m torch.utils.collect_env
```

The required result is:

```text
Success
True
<HIP/ROCm version>
<AMD GPU name>
```

## 5. RX 6700 XT Experimental Compatibility Notes

Because RX 6700 XT is not in the current official support matrix, PyTorch may
fail even after `rocminfo` sees the GPU. Common failure modes include:

- `torch.cuda.is_available()` returns `False`.
- PyTorch raises an unsupported `gfx1031`/code object error.
- HIP runtime is present, but kernels cannot launch.

If that happens, try native Ubuntu before spending too long on WSL. If native
Ubuntu still sees `gfx1031` issues, an experimental compatibility override is
sometimes used by the community:

```bash
export HSA_OVERRIDE_GFX_VERSION=10.3.0
```

Use that only for a quick test:

```bash
HSA_OVERRIDE_GFX_VERSION=10.3.0 python3 - <<'PY'
import torch
print("torch:", torch.__version__)
print("hip:", torch.version.hip)
print("available:", torch.cuda.is_available())
if torch.cuda.is_available():
    x = torch.randn(4096, 4096, device="cuda")
    y = x @ x
    torch.cuda.synchronize()
    print(y.mean().item())
PY
```

If the quick test works, make the override explicit in the shell used for this
project, not globally:

```bash
echo 'export HSA_OVERRIDE_GFX_VERSION=10.3.0' >> .env.rocm-local
source .env.rocm-local
```

Do not hide this workaround in project code. It should stay visible because it
changes how ROCm identifies the GPU.

## 6. Native Ubuntu Path

Use this if WSL2 fails.

Install Ubuntu 22.04.5 Desktop with HWE or Ubuntu 24.04.4 Desktop with HWE on a
separate partition/drive. AMD's ROCm 7.2.1 Linux matrix lists those as supported
operating systems.

Install packages:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y wget git python3 python3-pip python3-venv python3-setuptools python3-wheel
```

Install AMD's Ubuntu 22.04 installer package:

```bash
wget https://repo.radeon.com/amdgpu-install/7.2.1/ubuntu/jammy/amdgpu-install_7.2.1.70201-1_all.deb
sudo apt install ./amdgpu-install_7.2.1.70201-1_all.deb
```

Install graphics + ROCm:

```bash
sudo amdgpu-install --list-usecase
amdgpu-install -y --usecase=graphics,rocm
sudo usermod -a -G render,video $LOGNAME
sudo reboot
```

After reboot:

```bash
groups
dkms status
rocminfo | grep -E "Name:|Marketing Name:|gfx"
clinfo | grep -E "Platform Name|Device Type|Board name"
```

Then repeat the PyTorch ROCm setup from section 4.

## 7. Connect This Repo to the ROCm Environment

Inside WSL2 or native Ubuntu:

```bash
cd /mnt/k/BTC-ETH\ Trading  # WSL path for this Windows drive
python3 -m venv .venv-rocm
source .venv-rocm/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
python scripts/verify_gpu_training_stack.py
```

If installing `requirements.txt` downgrades or replaces ROCm PyTorch, reinstall
the ROCm torch wheels afterward, then rerun:

```bash
python scripts/verify_gpu_training_stack.py
```

## 8. Train With GPU Awareness

This project currently sets:

- SAC: `device="auto"`
- PPO: `device="cpu"`

Expected behavior:

- SAC should benefit more from ROCm because replay-buffer updates perform many
  neural-network gradient steps.
- PPO can stay CPU-heavy because rollout collection and vectorized environments
  dominate runtime.
- If GPU setup works, start with SAC to prove acceleration.

Commands:

```bash
python train.py --algo SAC --timesteps 300000
python backtest.py --method mean
```

Then compare with CPU:

```bash
time python train.py --algo SAC --timesteps 50000
```

Track:

- wall-clock training time
- `torch.cuda.is_available()`
- GPU utilization with `watch -n 1 rocm-smi`
- TensorBoard reward curves
- `results/backtest_metrics.csv`

## 9. Troubleshooting

If `rocminfo` is missing:

- ROCm is not installed or not on PATH.
- Re-run the WSL or native Linux install steps.

If `rocminfo` shows no GPU:

- WSL: confirm the AMD WSL driver is installed and reboot Windows.
- Native Linux: confirm group membership and reboot after adding `render,video`.

If `torch.version.hip` is `None`:

- You installed CPU or CUDA PyTorch, not ROCm PyTorch.
- Reinstall the ROCm wheel set.

If `torch.cuda.is_available()` is `False` but `torch.version.hip` is set:

- PyTorch can see HIP but cannot use the RX 6700 XT.
- Try native Ubuntu.
- Try the temporary `HSA_OVERRIDE_GFX_VERSION=10.3.0` test.

If training is slower on GPU:

- Test SAC before PPO.
- Reduce vectorized environment process count if CPU contention dominates.
- Keep processed data on the Linux filesystem for WSL performance tests instead
  of repeatedly reading through `/mnt/k`.

## 10. Source Notes

Primary sources checked:

- AMD ROCm WSL compatibility matrix:
  `https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/wsl/wsl_compatibility.html`
- AMD ROCm Linux compatibility matrix:
  `https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/native_linux/native_linux_compatibility.html`
- AMD ROCm Windows compatibility matrix:
  `https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html`
- AMD Radeon WSL ROCm install guide:
  `https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/wsl/install-radeon.html`
- AMD Radeon WSL PyTorch install guide:
  `https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/wsl/install-pytorch.html`
- AMD Radeon Linux ROCm install guide:
  `https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/native_linux/install-radeon.html`
- PyTorch local install page:
  `https://pytorch.org/get-started/locally/`

