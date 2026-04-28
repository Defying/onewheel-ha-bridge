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

        payload_by_id = {payload["object_id"]: payload for _, payload in payloads}
        self.assertEqual(payload_by_id["custom_onewheel_controller_voltage_v"]["device_class"], "voltage")
        self.assertEqual(payload_by_id["custom_onewheel_controller_avg_motor_current_a"]["device_class"], "current")
        self.assertEqual(payload_by_id["custom_onewheel_refloat_leds_on"]["icon"], "mdi:led-strip-variant")

    def test_discovery_unique_ids_do_not_collide_when_refloat_led_buttons_are_enabled(self) -> None:
        from onewheel_ha_bridge.config import ControlsConfig
        from onewheel_ha_bridge.models import RefloatInfo, TelemetrySnapshot

        payloads = build_discovery_payloads(
            HomeAssistantConfig(),
            snapshot=TelemetrySnapshot(
                refloat_info=RefloatInfo(
                    package_name="Refloat",
                    command_version=2,
                    package_version="1.2.0-beta3",
                    git_hash="8b880d64",
                    tick_rate_hz=10_000,
                    capabilities=1,
                    extra_flags=0,
                )
            ),
            controls_config=ControlsConfig(enabled=True, refloat_led_controls_enabled=True),
        )
        unique_ids = [payload["unique_id"] for _, payload in payloads]
        self.assertEqual(len(unique_ids), len(set(unique_ids)))


if __name__ == "__main__":
    unittest.main()
