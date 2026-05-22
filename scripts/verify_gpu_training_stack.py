"""
Report whether this machine is ready for AMD ROCm-backed RL training.

The script is diagnostic only. It does not install drivers, mutate the Python
environment, or require ROCm to be present.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Callable


def _load_torch() -> Any | None:
    # This avoids a known duplicate OpenMP runtime abort in the current
    # Anaconda environment while keeping the workaround scoped to this process.
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    try:
        import torch
    except Exception:
        return None
    return torch


def build_gpu_training_report(
    *,
    torch_module: Any | None = None,
    command_lookup: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Build a GPU readiness report for AMD/ROCm PyTorch training."""
    torch = torch_module if torch_module is not None else _load_torch()

    torch_version = None
    torch_gpu_available = False
    torch_hip_version = None
    torch_cuda_version = None
    gpu_name = None

    if torch is not None:
        torch_version = getattr(torch, "__version__", None)
        torch_cuda = getattr(torch, "cuda", None)
        if torch_cuda is not None:
            torch_gpu_available = bool(torch_cuda.is_available())
            if torch_gpu_available:
                try:
                    gpu_name = torch_cuda.get_device_name(0)
                except Exception:
                    gpu_name = "unknown"
        torch_version_obj = getattr(torch, "version", None)
        torch_hip_version = getattr(torch_version_obj, "hip", None)
        torch_cuda_version = getattr(torch_version_obj, "cuda", None)

    rocminfo_on_path = command_lookup("rocminfo") is not None
    hipcc_on_path = command_lookup("hipcc") is not None

    ready = bool(torch_gpu_available and torch_hip_version)
    recommendation = (
        "ROCm PyTorch appears available for training."
        if ready
        else "Use WSL2/Linux ROCm for RX6700XT training, then rerun this verifier."
    )

    return {
        "torch_installed": torch is not None,
        "torch_version": torch_version,
        "torch_gpu_available": torch_gpu_available,
        "torch_hip_version": torch_hip_version,
        "torch_cuda_version": torch_cuda_version,
        "gpu_name": gpu_name,
        "rocminfo_on_path": rocminfo_on_path,
        "hipcc_on_path": hipcc_on_path,
        "ready_for_rocm_training": ready,
        "recommendation": recommendation,
    }


def print_report(report: dict[str, Any]) -> None:
    print("GPU training stack report")
    print(f"  torch installed: {report['torch_installed']}")
    print(f"  torch version: {report['torch_version']}")
    print(f"  torch GPU available: {report['torch_gpu_available']}")
    print(f"  torch HIP version: {report['torch_hip_version']}")
    print(f"  torch CUDA version: {report['torch_cuda_version']}")
    print(f"  GPU name: {report['gpu_name']}")
    print(f"  rocminfo on PATH: {report['rocminfo_on_path']}")
    print(f"  hipcc on PATH: {report['hipcc_on_path']}")
    print(f"  ready for ROCm training: {report['ready_for_rocm_training']}")
    print(f"  recommendation: {report['recommendation']}")


def main() -> None:
    print_report(build_gpu_training_report())


if __name__ == "__main__":
    main()
