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

    def test_sudoers_example_is_exact_allowlist(self):
        path = ROOT / "scripts" / "server" / "trading-bot-ui.sudoers.example"
        text = path.read_text(encoding="utf-8")
        self.assertIn("/bin/systemctl start trading-bot", text)
        self.assertIn("/bin/systemctl restart trading-bot", text)
        self.assertNotIn("*", text)


if __name__ == "__main__":
    unittest.main()
