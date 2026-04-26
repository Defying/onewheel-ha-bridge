from __future__ import annotations

import unittest
from unittest.mock import patch

from onewheel_ha_bridge.config import ControlsConfig, HomeAssistantConfig, VescConfig
from onewheel_ha_bridge.discovery import build_discovery_payloads, command_status_topic, command_topic
from onewheel_ha_bridge.protocol import VescTcpClient


class ControlsTests(unittest.TestCase):
    def test_command_topics_default_to_base_topic(self) -> None:
        ha = HomeAssistantConfig(base_topic="onewheel/custom_xr")
        controls = ControlsConfig(enabled=True)
        self.assertEqual(command_topic(ha, controls), "onewheel/custom_xr/command")
        self.assertEqual(command_status_topic(ha, controls), "onewheel/custom_xr/command_status")

    def test_discovery_adds_guarded_buttons_when_enabled(self) -> None:
        ha = HomeAssistantConfig(device_id="custom_onewheel")
        payloads = build_discovery_payloads(ha, controls_config=ControlsConfig(enabled=True))
        button_payloads = [payload for topic, payload in payloads if "/button/" in topic]
        self.assertEqual(len(button_payloads), 4)
        self.assertEqual(
            {payload["payload_press"] for payload in button_payloads},
            {"allow_charging", "disable_charging", "allow_balancing", "disable_balancing"},
        )
        self.assertTrue(all(payload["command_topic"] == "onewheel/custom_xr/command" for payload in button_payloads))

    def test_discovery_omits_buttons_when_disabled(self) -> None:
        payloads = build_discovery_payloads(HomeAssistantConfig(), controls_config=ControlsConfig(enabled=False))
        self.assertFalse(any("/button/" in topic for topic, _ in payloads))

    def test_bms_write_payloads(self) -> None:
        client = VescTcpClient(VescConfig())
        with patch.object(client, "send") as send:
            client.set_bms_charge_allowed(True)
            client.set_bms_charge_allowed(False)
            client.set_bms_balance_override(31, 0)
            client.set_bms_balance_override(31, 1)
        self.assertEqual(
            [call.args[0] for call in send.call_args_list],
            [bytes([97, 1]), bytes([97, 0]), bytes([98, 31, 0]), bytes([98, 31, 1])],
        )


if __name__ == "__main__":
    unittest.main()
