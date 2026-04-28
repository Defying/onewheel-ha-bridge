from __future__ import annotations

import unittest
from unittest.mock import patch

from onewheel_ha_bridge.bridge import ALLOWED_CONTROL_ACTIONS, OnewheelBridge, UNSUPPORTED_CONTROL_ACTIONS
from onewheel_ha_bridge.config import BridgeConfig, ControlsConfig, HomeAssistantConfig, MqttConfig, VescConfig
from onewheel_ha_bridge.discovery import build_discovery_payloads, command_status_topic, command_topic
from onewheel_ha_bridge.models import RefloatInfo, RefloatLights, RefloatRealtime, TelemetrySnapshot
from onewheel_ha_bridge.protocol import VescTcpClient


class FakePublisher:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str, str]] = []

    def publish_command_status(self, action: str, status: str, message: str) -> None:
        self.statuses.append((action, status, message))


def supported_refloat_info() -> RefloatInfo:
    return RefloatInfo(
        package_name="Refloat",
        command_version=2,
        package_version="1.2.0-beta3",
        git_hash="8b880d64",
        tick_rate_hz=10_000,
        capabilities=0x1,
        extra_flags=0,
    )


def supported_refloat_snapshot() -> TelemetrySnapshot:
    return TelemetrySnapshot(refloat_info=supported_refloat_info())


def unsupported_refloat_snapshot() -> TelemetrySnapshot:
    return TelemetrySnapshot(
        refloat_info=RefloatInfo(
            package_name="Refloat",
            command_version=2,
            package_version="1.1.1",
            git_hash="deadbeef",
            tick_rate_hz=10_000,
            capabilities=0x1,
            extra_flags=0,
        )
    )


def ready_refloat_realtime() -> RefloatRealtime:
    return RefloatRealtime(
        mask=0,
        extra_flags=0,
        time_ticks=0,
        package_state="READY",
        package_mode="NORMAL",
        footpad_state="NONE",
        charging=False,
        darkride=False,
        wheelslip=False,
        stop_condition="NONE",
        sat="NONE",
        alert_reason="NONE",
        values={},
        runtime_values={},
        charging_values={},
        active_alert_mask_low=0,
        active_alert_mask_high=0,
        firmware_fault_code=0,
    )


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

    def test_discovery_adds_refloat_led_buttons_only_with_second_opt_in_and_supported_info(self) -> None:
        ha = HomeAssistantConfig(device_id="custom_onewheel")
        without_led_opt_in = build_discovery_payloads(
            ha,
            snapshot=supported_refloat_snapshot(),
            controls_config=ControlsConfig(enabled=True),
        )
        self.assertEqual(sum(1 for topic, _ in without_led_opt_in if "/button/" in topic), 2)

        unsupported = build_discovery_payloads(
            ha,
            snapshot=unsupported_refloat_snapshot(),
            controls_config=ControlsConfig(enabled=True, refloat_led_controls_enabled=True),
        )
        self.assertEqual(sum(1 for topic, _ in unsupported if "/button/" in topic), 2)

        payloads = build_discovery_payloads(
            ha,
            snapshot=supported_refloat_snapshot(),
            controls_config=ControlsConfig(enabled=True, refloat_led_controls_enabled=True),
        )
        button_payloads = [payload for topic, payload in payloads if "/button/" in topic]
        self.assertEqual(len(button_payloads), 4)
        self.assertEqual(
            {payload["payload_press"] for payload in button_payloads},
            {"allow_charging", "allow_balancing", "refloat_leds_on", "refloat_leds_off"},
        )

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

    def test_refloat_led_actions_require_second_opt_in_before_queue(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True, refloat_led_controls_enabled=False),
            )
        )
        fake = FakePublisher()
        bridge.publisher = fake  # type: ignore[assignment]

        bridge.enqueue_control_command("refloat_leds_on")

        self.assertTrue(bridge._command_queue.empty())
        self.assertEqual(fake.statuses, [("refloat_leds_on", "rejected", "Refloat LED controls disabled")])
        self.assertIn("refloat_leds_on", ALLOWED_CONTROL_ACTIONS)
        self.assertIn("refloat_leds_off", ALLOWED_CONTROL_ACTIONS)

    def test_refloat_led_control_executes_with_safe_snapshot(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True, refloat_led_controls_enabled=True, command_cooldown_seconds=0),
            )
        )
        fake = FakePublisher()
        bridge.publisher = fake  # type: ignore[assignment]
        bridge._last_snapshot = TelemetrySnapshot(
            can_nodes=[3, 4],
            refloat_info=supported_refloat_info(),
            refloat_realtime=ready_refloat_realtime(),
        )

        with patch.object(bridge.client, "set_refloat_leds", return_value=RefloatLights(True, False, 1)) as set_leds:
            bridge.enqueue_control_command("refloat_leds_on")
            bridge.process_control_commands()

        set_leds.assert_called_once_with(True, can_id=3, info=bridge._last_snapshot.refloat_info)
        self.assertEqual([status for _, status, _ in fake.statuses], ["queued", "ok"])

    def test_refloat_lights_poll_requires_second_opt_in(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True, refloat_led_controls_enabled=False),
            )
        )
        bridge._cached_refloat_info = supported_refloat_info()
        with (
            patch.object(bridge.client, "get_controller_values", return_value=None),
            patch.object(bridge.client, "get_bms_values", return_value=None),
            patch.object(bridge.client, "get_refloat_realtime", return_value=ready_refloat_realtime()),
            patch.object(bridge.client, "get_refloat_lights") as get_lights,
        ):
            bridge.poll_once()

        get_lights.assert_not_called()

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
