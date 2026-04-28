from __future__ import annotations

import unittest
from unittest.mock import patch

from onewheel_ha_bridge.config import BridgeConfig, ControlsConfig, HomeAssistantConfig, MqttConfig, VescConfig, VescDiscoveryConfig
from onewheel_ha_bridge.discovery import availability_topic, build_discovery_payloads, state_topic
from onewheel_ha_bridge.models import FirmwareInfo
from onewheel_ha_bridge.multibridge import MultiBoardBridge
from onewheel_ha_bridge.scanner import VescTcpEndpoint


def firmware(uuid: str = "abcdef0123456789abcdef01") -> FirmwareInfo:
    return FirmwareInfo(
        major=6,
        minor=5,
        hardware_name="VESC Express",
        uuid=uuid,
        pairing_done=True,
    )


class MultiBridgeTests(unittest.TestCase):
    def test_discovered_board_gets_isolated_topics_client_id_and_disabled_controls(self) -> None:
        config = BridgeConfig(
            vesc=VescConfig(host="192.0.2.1", port=65102),
            mqtt=MqttConfig(client_id="onewheel-ha-bridge"),
            home_assistant=HomeAssistantConfig(base_topic="onewheel/custom_xr", device_id="custom_onewheel", device_name="Custom Onewheel"),
            controls=ControlsConfig(enabled=True, refloat_led_controls_enabled=True),
            discovery=VescDiscoveryConfig(enabled=True, hosts=("192.0.2.2",)),
        )
        endpoint = VescTcpEndpoint("192.0.2.2", 65102, firmware())

        with (
            patch("onewheel_ha_bridge.multibridge.discover_vesc_tcp_endpoints", return_value=[endpoint]) as discover,
            patch("onewheel_ha_bridge.mqtt_bridge.HomeAssistantPublisher.connect"),
            patch("onewheel_ha_bridge.mqtt_bridge.HomeAssistantPublisher.publish_availability"),
            patch("onewheel_ha_bridge.mqtt_bridge.HomeAssistantPublisher.publish_discovery"),
            patch("onewheel_ha_bridge.bridge.OnewheelBridge.refresh_static_info"),
        ):
            bridge = MultiBoardBridge(config)
            bridge.connect()
            discover.return_value = [VescTcpEndpoint("vesc-board.local", 65102, firmware())]
            bridge.scan_once()

        self.assertIn("192.0.2.1:65102", bridge._boards)
        self.assertEqual(len(bridge._boards), 2)
        discovered = bridge._boards["192.0.2.2:65102"].bridge.config
        self.assertEqual(discovered.home_assistant.device_id, "custom_onewheel_vesc_abcdef012345")
        self.assertEqual(discovered.home_assistant.base_topic, "onewheel/custom_xr/vesc_abcdef012345")
        self.assertEqual(discovered.mqtt.client_id, "onewheel-ha-bridge-vesc_abcdef012345")
        self.assertFalse(discovered.controls.enabled)
        self.assertFalse(discovered.controls.refloat_led_controls_enabled)
        self.assertIsNone(discovered.controls.command_topic)
        self.assertIsNone(discovered.controls.status_topic)
        self.assertFalse(discovered.discovery.enabled)

    def test_discovered_board_discovery_payloads_are_unique(self) -> None:
        base = BridgeConfig(
            vesc=VescConfig(host="192.0.2.1"),
            mqtt=MqttConfig(),
            home_assistant=HomeAssistantConfig(base_topic="onewheel/custom_xr", device_id="custom_onewheel"),
            controls=ControlsConfig(enabled=True),
            discovery=VescDiscoveryConfig(enabled=True),
        )
        child = base.for_discovered_board("vesc_child", "192.0.2.55", 65102)

        base_payloads = build_discovery_payloads(base.home_assistant, controls_config=base.controls)
        child_payloads = build_discovery_payloads(child.home_assistant, controls_config=child.controls)
        base_ids = {payload["unique_id"] for _, payload in base_payloads}
        child_ids = {payload["unique_id"] for _, payload in child_payloads}

        self.assertFalse(base_ids & child_ids)
        self.assertEqual(state_topic(child.home_assistant), "onewheel/custom_xr/vesc_child/state")
        self.assertEqual(availability_topic(child.home_assistant), "onewheel/custom_xr/vesc_child/availability")

    def test_discovered_controls_require_explicit_discovery_opt_in(self) -> None:
        base = BridgeConfig(
            vesc=VescConfig(host="192.0.2.1"),
            mqtt=MqttConfig(),
            home_assistant=HomeAssistantConfig(),
            controls=ControlsConfig(
                enabled=True,
                refloat_led_controls_enabled=True,
                command_topic="onewheel/shared/command",
                status_topic="onewheel/shared/status",
            ),
            discovery=VescDiscoveryConfig(enabled=True, controls_enabled_for_discovered=True),
        )
        child = base.for_discovered_board("vesc_child", "192.0.2.55", 65102)
        self.assertTrue(child.controls.enabled)
        self.assertFalse(child.controls.refloat_led_controls_enabled)
        self.assertIsNone(child.controls.command_topic)
        self.assertIsNone(child.controls.status_topic)
        self.assertEqual(child.vesc.host, "192.0.2.55")


if __name__ == "__main__":
    unittest.main()
