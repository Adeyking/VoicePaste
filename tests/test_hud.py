import unittest
from unittest.mock import MagicMock, patch
from voicepaste.hud import FloatingHUD
from voicepaste.defaults import DEFAULT_HUD_ENABLED
from voicepaste.engine import VoicePasteConfig


class TestFloatingHUD(unittest.TestCase):

    def test_hud_defaults(self):
        self.assertTrue(DEFAULT_HUD_ENABLED)

    def test_hud_initialization_disabled(self):
        hud = FloatingHUD(enabled=False)
        self.assertFalse(hud.enabled)
        hud.show_status("RECORDING")
        self.assertEqual(hud._target_text, "")
        hud.close()

    @patch("voicepaste.engine.FloatingHUD")
    def test_engine_hud_toggle(self, mock_hud_cls):
        mock_hud_inst = MagicMock()
        mock_hud_cls.return_value = mock_hud_inst

        cfg = VoicePasteConfig.from_dict({
            "HUD_ENABLED": True,
            "STT_URL": "http://localhost:8770",
            "OLLAMA_URL": "http://localhost:11434"
        })
        self.assertTrue(cfg.hud_enabled)

        # Verify roundtrip
        d = cfg.to_json_dict()
        self.assertIn("HUD_ENABLED", d)
        self.assertTrue(d["HUD_ENABLED"])

        d["HUD_ENABLED"] = False
        cfg2 = VoicePasteConfig.from_dict(d)
        self.assertFalse(cfg2.hud_enabled)


if __name__ == "__main__":
    unittest.main()
