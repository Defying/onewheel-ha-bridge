from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from onewheel_ha_bridge.config import BridgeConfig, ControlsConfig, HomeAssistantConfig, MqttConfig, VescConfig
from onewheel_ha_bridge.mqtt_bridge import HomeAssistantPublisher


class MqttBridgeTests(unittest.TestCase):
    def test_retained_command_message_is_ignored(self) -> None:
        config = BridgeConfig(
            vesc=VescConfig(),
            mqtt=MqttConfig(),
            home_assistant=HomeAssistantConfig(),
            controls=ControlsConfig(enabled=True),
        )
        received: list[str] = []
        publisher = HomeAssistantPublisher(config, received.append)

        publisher._on_message(  # noqa: SLF001 - regression for MQTT callback behavior
            None,
            None,
            SimpleNamespace(topic="onewheel/custom_xr/command", payload=b"allow_charging", retain=True),
        )

        self.assertEqual(received, [])

    def test_non_retained_command_message_is_dispatched(self) -> None:
        config = BridgeConfig(
            vesc=VescConfig(),
            mqtt=MqttConfig(),
            home_assistant=HomeAssistantConfig(),
            controls=ControlsConfig(enabled=True),
        )
        received: list[str] = []
        publisher = HomeAssistantPublisher(config, received.append)

        publisher._on_message(  # noqa: SLF001 - regression for MQTT callback behavior
            None,
            None,
            SimpleNamespace(topic="onewheel/custom_xr/command", payload=b"allow_charging", retain=False),
        )

        self.assertEqual(received, ["allow_charging"])

    def test_command_status_payload_includes_board_identity(self) -> None:
        config = BridgeConfig(
            vesc=VescConfig(),
            mqtt=MqttConfig(),
            home_assistant=HomeAssistantConfig(device_id="custom_onewheel_vesc_child", base_topic="onewheel/custom_xr/vesc_child"),
            controls=ControlsConfig(enabled=True),
        )
        publisher = HomeAssistantPublisher(config)
        publisher._client.publish = Mock()  # type: ignore[method-assign]

        publisher.publish_command_status("allow_charging", "queued", "waiting")

        topic, payload = publisher._client.publish.call_args.args[:2]
        self.assertEqual(topic, "onewheel/custom_xr/vesc_child/command_status")
        decoded = json.loads(payload)
        self.assertEqual(decoded["device_id"], "custom_onewheel_vesc_child")
        self.assertEqual(decoded["base_topic"], "onewheel/custom_xr/vesc_child")
        self.assertEqual(decoded["action"], "allow_charging")


if __name__ == "__main__":
    unittest.main()
