from __future__ import annotations

import unittest
from unittest.mock import patch

from onewheel_ha_bridge.bridge import ALLOWED_CONTROL_ACTIONS, OnewheelBridge, UNSUPPORTED_CONTROL_ACTIONS
from onewheel_ha_bridge.config import BridgeConfig, ControlsConfig, HomeAssistantConfig, MqttConfig, VescConfig
from onewheel_ha_bridge.discovery import build_discovery_payloads, command_status_topic, command_topic
from onewheel_ha_bridge.protocol import VescTcpClient


class FakePublisher:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str, str]] = []

    def publish_command_status(self, action: str, status: str, message: str) -> None:
        self.statuses.append((action, status, message))


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
        self.assertEqual(len(button_payloads), 2)
        self.assertEqual(
            {payload["payload_press"] for payload in button_payloads},
            {"allow_charging", "allow_balancing"},
        )
        self.assertTrue(all(payload["command_topic"] == "onewheel/custom_xr/command" for payload in button_payloads))

    def test_discovery_omits_buttons_when_disabled(self) -> None:
        payloads = build_discovery_payloads(HomeAssistantConfig(), controls_config=ControlsConfig(enabled=False))
        self.assertFalse(any("/button/" in topic for topic, _ in payloads))

    def test_disable_actions_are_hard_rejected_before_queue(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True),
            )
        )
        fake = FakePublisher()
        bridge.publisher = fake  # type: ignore[assignment]

        bridge.enqueue_control_command("disable_charging")
        bridge.enqueue_control_command("disable_balancing")

        self.assertTrue(bridge._command_queue.empty())
        self.assertEqual([status for _, status, _ in fake.statuses], ["rejected", "rejected"])
        self.assertTrue(all("not supported" in message for _, _, message in fake.statuses))
        self.assertNotIn("disable_charging", ALLOWED_CONTROL_ACTIONS)
        self.assertNotIn("disable_balancing", ALLOWED_CONTROL_ACTIONS)
        self.assertIn("disable_charging", UNSUPPORTED_CONTROL_ACTIONS)
        self.assertIn("disable_balancing", UNSUPPORTED_CONTROL_ACTIONS)

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

    def test_bms_write_payloads_can_forwarded(self) -> None:
        client = VescTcpClient(VescConfig())
        with patch.object(client, "send") as send:
            client.set_bms_charge_allowed(True, can_id=5)
            client.set_bms_charge_allowed(False, can_id=5)
            client.set_bms_balance_override(31, 0, can_id=5)
            client.set_bms_balance_override(31, 1, can_id=5)
            client.force_bms_balance(True, can_id=5)
            client.force_bms_balance(False, can_id=5)
        self.assertEqual(
            [call.args[0] for call in send.call_args_list],
            [
                bytes([34, 5, 97, 1]),
                bytes([34, 5, 97, 0]),
                bytes([34, 5, 98, 31, 0]),
                bytes([34, 5, 98, 31, 1]),
                bytes([34, 5, 100, 1]),
                bytes([34, 5, 100, 0]),
            ],
        )


if __name__ == "__main__":
    unittest.main()
