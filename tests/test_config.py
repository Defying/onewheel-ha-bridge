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
allow_public_networks = false
""".strip()
            )
            config = load_config(path)

        self.assertTrue(config.discovery.enabled)
        self.assertEqual(config.discovery.hosts, ("192.0.2.10",))
        self.assertEqual(config.discovery.networks, ("192.0.2.0/30",))
        self.assertEqual(config.discovery.ports, (65102, 65103))
        self.assertFalse(config.discovery.allow_public_networks)

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

    def test_env_booleans_accept_explicit_false_values(self) -> None:
        for value in ("0", "false", "no", "off"):
            with self.subTest(value=value), patch.dict(os.environ, {"OWHB_CONTROLS_REQUIRE_SAFE_STATE": value}, clear=True):
                config = load_config()
            self.assertFalse(config.controls.require_safe_state)

    def test_env_boolean_typos_fail_closed(self) -> None:
        with patch.dict(os.environ, {"OWHB_CONTROLS_REQUIRE_SAFE_STATE": "flase"}, clear=True):
            with self.assertRaisesRegex(ValueError, "OWHB_CONTROLS_REQUIRE_SAFE_STATE"):
                load_config()

    def test_mqtt_tls_blank_paths_normalize_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                """
[mqtt]
tls_enabled = true
tls_ca_certs = ""
tls_certfile = ""
tls_keyfile = ""
""".strip()
            )
            config = load_config(path)

        self.assertTrue(config.mqtt.tls_enabled)
        self.assertIsNone(config.mqtt.tls_ca_certs)
        self.assertIsNone(config.mqtt.tls_certfile)
        self.assertIsNone(config.mqtt.tls_keyfile)


if __name__ == "__main__":
    unittest.main()
