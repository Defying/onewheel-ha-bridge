from __future__ import annotations

import unittest

from onewheel_ha_bridge.config import HomeAssistantConfig
from onewheel_ha_bridge.discovery import availability_topic, build_discovery_payloads, raw_topic, state_topic


class DiscoveryTests(unittest.TestCase):
    def test_topics(self) -> None:
        config = HomeAssistantConfig(base_topic="onewheel/custom_xr", device_id="custom_onewheel")
        self.assertEqual(state_topic(config), "onewheel/custom_xr/state")
        self.assertEqual(raw_topic(config), "onewheel/custom_xr/raw")
        self.assertEqual(availability_topic(config), "onewheel/custom_xr/availability")

    def test_discovery_payloads(self) -> None:
        config = HomeAssistantConfig(device_id="custom_onewheel", device_name="Custom Onewheel")
        payloads = build_discovery_payloads(config)
        self.assertGreaterEqual(len(payloads), 20)
        topic, payload = payloads[0]
        self.assertIn("homeassistant/", topic)
        self.assertEqual(payload["device"]["name"], "Custom Onewheel")
        self.assertEqual(payload["availability_topic"], "onewheel/custom_xr/availability")
        self.assertEqual(payload["state_topic"], "onewheel/custom_xr/state")


if __name__ == "__main__":
    unittest.main()
