from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UIDeployAssetsTest(unittest.TestCase):
    def test_root_install_script_exists_and_mentions_sudoers(self):
        path = ROOT / "scripts" / "server" / "install_private_ui_root.sh"
        text = path.read_text(encoding="utf-8")
        self.assertIn("visudo -cf", text)
        self.assertIn("UI_CONTROL_USE_SUDO", text)
        self.assertIn("systemctl enable", text)

    def test_tailscale_install_script_exists_and_mentions_serve(self):
        path = ROOT / "scripts" / "server" / "install_tailscale_ui_root.sh"
        text = path.read_text(encoding="utf-8")
        self.assertIn("tailscale up", text)
        self.assertIn("tailscale serve --bg --https=443", text)

    def test_rootless_tailscale_scripts_exist(self):
        start_path = ROOT / "scripts" / "server" / "start_rootless_tailscale_ui.sh"
        serve_path = ROOT / "scripts" / "server" / "enable_rootless_tailscale_serve.sh"
        start_text = start_path.read_text(encoding="utf-8")
        serve_text = serve_path.read_text(encoding="utf-8")
        self.assertIn("--tun=userspace-networking", start_text)
        self.assertIn('tailscale_${TS_VERSION}_${TS_ARCH}.tgz', start_text)
        self.assertIn("--json", start_text)
        self.assertIn("AUTH_URL_FILE", start_text)
        self.assertIn("--timeout=", start_text)
        self.assertIn("PYTHON_BIN", start_text)
        self.assertIn("BackendState", start_text)
        self.assertIn("status --json", start_text)
        self.assertIn("BackendState", serve_text)
        self.assertIn("serve --bg --https=443", serve_text)

    def test_sudoers_example_is_exact_allowlist(self):
        path = ROOT / "scripts" / "server" / "trading-bot-ui.sudoers.example"
        text = path.read_text(encoding="utf-8")
        self.assertIn("/bin/systemctl start trading-bot", text)
        self.assertIn("/bin/systemctl restart trading-bot", text)
        self.assertNotIn("*", text)


if __name__ == "__main__":
    unittest.main()
