from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from onewheel_ha_bridge.bridge import ALLOWED_CONTROL_ACTIONS, OnewheelBridge, UNSUPPORTED_CONTROL_ACTIONS
from onewheel_ha_bridge.config import BridgeConfig, ControlsConfig, HomeAssistantConfig, MqttConfig, VescConfig
from onewheel_ha_bridge.discovery import build_discovery_payloads, command_status_topic, command_topic
from onewheel_ha_bridge.models import BmsValues, RefloatInfo, RefloatLights, RefloatRealtime, TelemetrySnapshot
from onewheel_ha_bridge.protocol import VescProtocolError, VescTcpClient


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
        values={"motor.speed": 0.0},
        runtime_values={},
        charging_values={},
        active_alert_mask_low=0,
        active_alert_mask_high=0,
        firmware_fault_code=0,
    )


def ready_bms(can_id: int = 4) -> BmsValues:
    return BmsValues(
        pack_voltage_v=122.0,
        charge_voltage_v=122.0,
        current_a=0.0,
        current_ic_a=0.0,
        amp_hours=0.0,
        watt_hours=0.0,
        cells_v=[4.0],
        balancing_state=[False],
        temps_c=[],
        temp_ic_c=0.0,
        temp_humidity_c=0.0,
        humidity_pct=0.0,
        temp_max_cell_c=0.0,
        soc_ratio=0.5,
        soh_ratio=1.0,
        can_id=can_id,
        amp_hours_charged_total=0.0,
        watt_hours_charged_total=0.0,
        amp_hours_discharged_total=0.0,
        watt_hours_discharged_total=0.0,
    )


def running_refloat_realtime() -> RefloatRealtime:
    realtime = ready_refloat_realtime()
    realtime.package_state = "RUNNING"
    return realtime


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
        snapshot = TelemetrySnapshot(
            can_nodes=[3, 4],
            refloat_info=supported_refloat_info(),
            refloat_realtime=ready_refloat_realtime(),
        )
        bridge._cached_can_nodes = [3, 4]
        bridge._cached_refloat_info = snapshot.refloat_info

        with (
            patch.object(bridge, "refresh_static_info"),
            patch.object(bridge, "poll_once", return_value=snapshot),
            patch.object(bridge.client, "set_refloat_leds", return_value=RefloatLights(True, False, 1)) as set_leds,
        ):
            bridge.enqueue_control_command("refloat_leds_on")
            bridge.process_control_commands()

        set_leds.assert_called_once_with(True, can_id=3, info=bridge._last_snapshot.refloat_info)
        self.assertEqual([status for _, status, _ in fake.statuses], ["queued", "ok"])

    def test_refloat_led_control_does_not_require_bms_can_validation(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3, bms_can_id=4),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True, refloat_led_controls_enabled=True, command_cooldown_seconds=0),
            )
        )
        fake = FakePublisher()
        bridge.publisher = fake  # type: ignore[assignment]
        snapshot = TelemetrySnapshot(
            can_nodes=[3],
            refloat_info=supported_refloat_info(),
            refloat_realtime=ready_refloat_realtime(),
        )
        bridge._cached_can_nodes = [3]
        bridge._cached_refloat_info = snapshot.refloat_info

        with (
            patch.object(bridge, "refresh_static_info"),
            patch.object(bridge, "poll_once", return_value=snapshot),
            patch.object(bridge.client, "set_refloat_leds", return_value=RefloatLights(True, False, 1)) as set_leds,
        ):
            bridge.enqueue_control_command("refloat_leds_on")
            bridge.process_control_commands()

        set_leds.assert_called_once()
        self.assertEqual([status for _, status, _ in fake.statuses], ["queued", "ok"])

    def test_control_always_repolls_before_write(self) -> None:
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
        fresh = TelemetrySnapshot(
            can_nodes=[3, 4],
            refloat_info=supported_refloat_info(),
            refloat_realtime=running_refloat_realtime(),
        )
        bridge._cached_can_nodes = [3, 4]
        bridge._cached_refloat_info = fresh.refloat_info

        with (
            patch.object(bridge, "refresh_static_info"),
            patch.object(bridge, "poll_once", return_value=fresh),
            patch.object(bridge.client, "set_refloat_leds") as set_leds,
        ):
            bridge.enqueue_control_command("refloat_leds_on")
            bridge.process_control_commands()

        set_leds.assert_not_called()
        self.assertEqual([status for _, status, _ in fake.statuses], ["queued", "rejected"])
        self.assertIn("RUNNING", fake.statuses[-1][2])

    def test_control_rejects_when_speed_cannot_be_verified(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3, bms_can_id=4),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True, command_cooldown_seconds=0),
            )
        )
        fake = FakePublisher()
        bridge.publisher = fake  # type: ignore[assignment]
        realtime = ready_refloat_realtime()
        realtime.values.clear()
        snapshot = TelemetrySnapshot(
            can_nodes=[3, 4],
            bms=ready_bms(4),
            refloat_realtime=realtime,
        )

        with (
            patch.object(bridge, "_snapshot_for_control", return_value=snapshot),
            patch.object(bridge.client, "set_bms_charge_allowed") as set_allowed,
        ):
            bridge.enqueue_control_command("allow_charging")
            bridge.process_control_commands()

        set_allowed.assert_not_called()
        self.assertEqual([status for _, status, _ in fake.statuses], ["queued", "rejected"])
        self.assertIn("speed telemetry unavailable", fake.statuses[-1][2])

    def test_control_rejects_when_speed_exceeds_limit_without_controller_values(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3, bms_can_id=4),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True, max_control_speed_mph=0.5, command_cooldown_seconds=0),
            )
        )
        fake = FakePublisher()
        bridge.publisher = fake  # type: ignore[assignment]
        realtime = ready_refloat_realtime()
        realtime.values["motor.speed"] = 10.0
        snapshot = TelemetrySnapshot(
            can_nodes=[3, 4],
            bms=ready_bms(4),
            refloat_realtime=realtime,
        )

        with (
            patch.object(bridge, "_snapshot_for_control", return_value=snapshot),
            patch.object(bridge.client, "set_bms_charge_allowed") as set_allowed,
        ):
            bridge.enqueue_control_command("allow_charging")
            bridge.process_control_commands()

        set_allowed.assert_not_called()
        self.assertEqual([status for _, status, _ in fake.statuses], ["queued", "rejected"])
        self.assertIn("exceeds control limit", fake.statuses[-1][2])

    def test_bms_write_uses_reported_bms_can_when_config_differs(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3, bms_can_id=4),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True, require_safe_state=False, command_cooldown_seconds=0),
            )
        )
        fake = FakePublisher()
        bridge.publisher = fake  # type: ignore[assignment]
        snapshot = TelemetrySnapshot(can_nodes=[3, 5], bms=Mock(can_id=5))

        with (
            patch.object(bridge, "_snapshot_for_control", return_value=snapshot),
            patch.object(bridge.client, "set_bms_charge_allowed") as set_allowed,
        ):
            bridge.enqueue_control_command("allow_charging")
            bridge.process_control_commands()

        set_allowed.assert_called_once_with(True, can_id=5)
        self.assertEqual(bridge.config.vesc.bms_can_id, 5)
        self.assertEqual([status for _, status, _ in fake.statuses], ["queued", "ok"])

    def test_bms_write_rejects_when_reported_bms_can_absent(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3, bms_can_id=4),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(enabled=True, require_safe_state=False, command_cooldown_seconds=0),
            )
        )
        fake = FakePublisher()
        bridge.publisher = fake  # type: ignore[assignment]
        snapshot = TelemetrySnapshot(can_nodes=[3, 4], bms=Mock(can_id=5))

        with (
            patch.object(bridge, "_snapshot_for_control", return_value=snapshot),
            patch.object(bridge.client, "set_bms_charge_allowed") as set_allowed,
        ):
            bridge.enqueue_control_command("allow_charging")
            bridge.process_control_commands()

        set_allowed.assert_not_called()
        self.assertEqual([status for _, status, _ in fake.statuses], ["queued", "rejected"])
        self.assertIn("BMS telemetry CAN 5 not present", fake.statuses[-1][2])

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

    def test_controller_read_resolves_board_specific_can_id(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(),
            )
        )
        bridge._cached_can_nodes = [7]
        expected = object()

        def get_controller_values(can_id: int):
            if can_id == 7:
                return expected
            raise VescProtocolError(f"no controller at CAN {can_id}")

        with patch.object(bridge.client, "get_controller_values", side_effect=get_controller_values) as read:
            self.assertIs(bridge._read_controller_values(), expected)

        self.assertEqual([call.args[0] for call in read.call_args_list], [3, 7])
        self.assertEqual(bridge.config.vesc.thor_can_id, 7)

    def test_static_refresh_resolves_board_specific_refloat_can_id(self) -> None:
        bridge = OnewheelBridge(
            BridgeConfig(
                vesc=VescConfig(thor_can_id=3),
                mqtt=MqttConfig(),
                home_assistant=HomeAssistantConfig(),
                controls=ControlsConfig(),
            )
        )

        def get_refloat_info(can_id: int):
            if can_id == 8:
                return supported_refloat_info()
            raise VescProtocolError(f"no Refloat at CAN {can_id}")

        with (
            patch.object(bridge.client, "get_fw_version", return_value=None),
            patch.object(bridge.client, "ping_can", return_value=[8]),
            patch.object(bridge.client, "get_refloat_info", side_effect=get_refloat_info) as info,
            patch.object(bridge.client, "get_refloat_ids", return_value={"realtime": [], "runtime": []}) as ids,
        ):
            bridge.refresh_static_info(force=True)

        self.assertEqual([call.args[0] for call in info.call_args_list], [3, 8])
        ids.assert_called_once_with(8)
        self.assertEqual(bridge.config.vesc.thor_can_id, 8)

    def test_control_queue_is_bounded(self) -> None:
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

        for _ in range(17):
            bridge.enqueue_control_command("allow_charging")

        self.assertEqual(bridge._command_queue.qsize(), 16)
        self.assertEqual(fake.statuses[-1], ("allow_charging", "rejected", "command queue full"))

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
