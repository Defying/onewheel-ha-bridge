from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from onewheel_ha_bridge.config import BridgeConfig, ControlsConfig, HomeAssistantConfig, MqttConfig, VescConfig
from onewheel_ha_bridge.mqtt_bridge import HomeAssistantPublisher


class MqttBridgeTests(unittest.TestCase):
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
