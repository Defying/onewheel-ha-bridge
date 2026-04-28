from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onewheel_ha_bridge.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_discovery_config_from_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                """
[discovery]
enabled = true
hosts = ["192.0.2.10"]
networks = ["192.0.2.0/30"]
ports = [65102, 65103]
controls_enabled_for_discovered = false
""".strip()
            )
            config = load_config(path)

        self.assertTrue(config.discovery.enabled)
        self.assertEqual(config.discovery.hosts, ("192.0.2.10",))
        self.assertEqual(config.discovery.networks, ("192.0.2.0/30",))
        self.assertEqual(config.discovery.ports, (65102, 65103))
        self.assertFalse(config.discovery.controls_enabled_for_discovered)

    def test_env_discovery_lists_are_csv(self) -> None:
        env = {
            "OWHB_DISCOVERY_ENABLED": "true",
            "OWHB_DISCOVERY_HOSTS": "192.0.2.10,192.0.2.11",
            "OWHB_DISCOVERY_PORTS": "65102,65103",
        }
        with patch.dict(os.environ, env, clear=False):
            config = load_config()
        self.assertTrue(config.discovery.enabled)
        self.assertEqual(config.discovery.hosts, ("192.0.2.10", "192.0.2.11"))
        self.assertEqual(config.discovery.ports, (65102, 65103))


if __name__ == "__main__":
    unittest.main()
