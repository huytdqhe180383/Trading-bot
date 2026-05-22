import unittest

from scripts.verify_gpu_training_stack import build_gpu_training_report


class _FakeTorchVersion:
    hip = None
    cuda = None


class _FakeCuda:
    @staticmethod
    def is_available():
        return False


class _FakeTorch:
    __version__ = "2.10.0+cpu"
    version = _FakeTorchVersion()
    cuda = _FakeCuda()


class GpuTrainingStackVerificationTest(unittest.TestCase):
    def test_reports_cpu_only_pytorch_without_failing(self):
        report = build_gpu_training_report(
            torch_module=_FakeTorch,
            command_lookup=lambda _: None,
        )

        self.assertEqual(report["torch_version"], "2.10.0+cpu")
        self.assertFalse(report["torch_gpu_available"])
        self.assertIsNone(report["torch_hip_version"])
        self.assertFalse(report["rocminfo_on_path"])
        self.assertIn("WSL2/Linux ROCm", report["recommendation"])


if __name__ == "__main__":
    unittest.main()
