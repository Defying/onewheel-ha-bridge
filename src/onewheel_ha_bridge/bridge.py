from __future__ import annotations

import json
import logging
import queue
import time
from dataclasses import dataclass

from .config import BridgeConfig
from .models import TelemetrySnapshot
from .mqtt_bridge import HomeAssistantPublisher
from .protocol import VescProtocolError, VescTcpClient, refloat_lights_control_supported

LOG = logging.getLogger(__name__)

MAX_CONTROL_QUEUE_SIZE = 16

ALLOWED_CONTROL_ACTIONS = {
    "allow_charging",
    "allow_balancing",
    "refloat_leds_on",
    "refloat_leds_off",
}

REFLOAT_LED_CONTROL_ACTIONS = {
    "refloat_leds_on",
    "refloat_leds_off",
}

UNSUPPORTED_CONTROL_ACTIONS = {
    "disable_charging": "disable charging is not supported by the verified ENNOID command path",
    "disable_balancing": "disable balancing is not supported by the verified ENNOID command path",
}


@dataclass(frozen=True, slots=True)
class ControlCommand:
    action: str
    received_at: float


class OnewheelBridge:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.client = VescTcpClient(config.vesc)
        self._command_queue: queue.Queue[ControlCommand] = queue.Queue(maxsize=MAX_CONTROL_QUEUE_SIZE)
        self.publisher = HomeAssistantPublisher(config, self.enqueue_control_command)
        self._cached_firmware = None
        self._cached_can_nodes: list[int] = []
        self._cached_refloat_info = None
        self._cached_refloat_ids: dict[str, list[str]] = {}
        self._poll_count = 0
        self._discovery_published = False
        self._last_snapshot: TelemetrySnapshot | None = None
        self._last_command_at = 0.0

    def enqueue_control_command(self, action: str) -> None:
        LOG.warning("guarded control request received: action=%s enabled=%s", action, self.config.controls.enabled)
        if action in UNSUPPORTED_CONTROL_ACTIONS:
            message = UNSUPPORTED_CONTROL_ACTIONS[action]
            LOG.warning("rejecting unsupported control action %s: %s", action, message)
            self.publisher.publish_command_status(action, "rejected", message)
            return
        if action not in ALLOWED_CONTROL_ACTIONS:
            LOG.warning("ignoring unknown control action %r", action)
            self.publisher.publish_command_status(action, "rejected", "unknown action")
            return
        if not self.config.controls.enabled:
            LOG.warning("ignoring control action %s because controls are disabled", action)
            self.publisher.publish_command_status(action, "rejected", "controls disabled")
            return
        if action in REFLOAT_LED_CONTROL_ACTIONS and not self.config.controls.refloat_led_controls_enabled:
            LOG.warning("ignoring Refloat LED control action %s because LED controls are disabled", action)
            self.publisher.publish_command_status(action, "rejected", "Refloat LED controls disabled")
            return
        try:
            self._command_queue.put_nowait(ControlCommand(action=action, received_at=time.time()))
        except queue.Full:
            LOG.warning("rejecting control action %s because command queue is full", action)
            self.publisher.publish_command_status(action, "rejected", "command queue full")
            return
        self.publisher.publish_command_status(action, "queued", "waiting for bridge loop")

    def _thor_can_candidates(self) -> list[int]:
        candidates: list[int] = []

        def add(can_id: int) -> None:
            if can_id not in candidates:
                candidates.append(can_id)

        add(self.config.vesc.thor_can_id)
        for can_id in self._cached_can_nodes:
            add(can_id)
        return candidates

    def _read_with_thor_can_candidates(self, label: str, reader):  # noqa: ANN001, ANN202
        last_error: Exception | None = None
        for can_id in self._thor_can_candidates():
            try:
                value = reader(can_id)
            except Exception as exc:  # noqa: BLE001 - try alternate CAN roles
                last_error = exc
                LOG.debug("%s read failed for CAN %s: %s", label, can_id, exc)
                continue
            if can_id != self.config.vesc.thor_can_id:
                LOG.info("resolved %s CAN ID for %s from %s to %s", label, self.config.home_assistant.device_id, self.config.vesc.thor_can_id, can_id)
                self.config.vesc.thor_can_id = can_id
            return value
        raise VescProtocolError(f"{label} failed for CAN candidates {self._thor_can_candidates()}: {last_error}")

    def _read_controller_values(self):
        return self._read_with_thor_can_candidates("controller telemetry", self.client.get_controller_values)

    def _read_refloat_info(self):
        return self._read_with_thor_can_candidates("Refloat INFO", self.client.get_refloat_info)

    def _read_refloat_ids(self):
        return self._read_with_thor_can_candidates("Refloat IDs", self.client.get_refloat_ids)

    def _read_refloat_realtime(self):
        return self._read_with_thor_can_candidates(
            "Refloat realtime",
            lambda can_id: self.client.get_refloat_realtime(can_id, self._cached_refloat_ids),
        )

    def _read_refloat_lights(self):
        return self._read_with_thor_can_candidates(
            "Refloat lights",
            lambda can_id: self.client.get_refloat_lights(can_id, self._cached_refloat_info),
        )

    def refresh_static_info(self, force: bool = False, best_effort: bool = False) -> None:
        def run(label: str, func) -> None:  # noqa: ANN001
            try:
                func()
            except Exception as exc:
                if not best_effort:
                    raise
                LOG.warning("%s static telemetry refresh failed: %s", label, exc)

        if force or self._cached_firmware is None:
            run("firmware", lambda: setattr(self, "_cached_firmware", self.client.get_fw_version()))
        if force or not self._cached_can_nodes or self._poll_count % max(self.config.vesc.static_refresh_every_polls, 1) == 0:
            run("CAN node", lambda: setattr(self, "_cached_can_nodes", self.client.ping_can()))
        if force or self._cached_refloat_info is None:
            run("Refloat info", lambda: setattr(self, "_cached_refloat_info", self._read_refloat_info()))
        if force or not self._cached_refloat_ids:
            run("Refloat IDs", lambda: setattr(self, "_cached_refloat_ids", self._read_refloat_ids()))

    def poll_once(self) -> TelemetrySnapshot:
        snapshot = TelemetrySnapshot()
        snapshot.firmware = self._cached_firmware
        snapshot.can_nodes = list(self._cached_can_nodes)
        snapshot.refloat_info = self._cached_refloat_info
        snapshot.refloat_ids = self._cached_refloat_ids

        successes = 0
        telemetry_queries = [
            ("controller", self._read_controller_values),
            ("bms", self.client.get_bms_values),
            ("refloat", self._read_refloat_realtime),
        ]
        for name, func in telemetry_queries:
            try:
                value = func()
                if name == "controller":
                    snapshot.controller = value
                elif name == "bms":
                    snapshot.bms = value
                else:
                    snapshot.refloat_realtime = value
                successes += 1
            except Exception as exc:  # noqa: BLE001 - per-section telemetry resilience
                snapshot.errors[name] = str(exc)
                LOG.warning("%s poll failed: %s", name, exc)

        if self.config.controls.refloat_led_controls_enabled and refloat_lights_control_supported(self._cached_refloat_info):
            try:
                snapshot.refloat_lights = self._read_refloat_lights()
            except Exception as exc:  # noqa: BLE001 - optional Refloat lights telemetry
                snapshot.errors["refloat_lights"] = str(exc)
                LOG.warning("Refloat lights poll failed: %s", exc)

        if successes == 0:
            raise VescProtocolError("all telemetry queries failed")
        return snapshot

    def _snapshot_for_control(self) -> TelemetrySnapshot:
        # Never execute a write against cached telemetry. Re-check static info
        # and live telemetry immediately before control validation.
        self.refresh_static_info(force=True)
        snapshot = self._attach_static_info(self.poll_once())
        self._last_snapshot = snapshot
        return snapshot

    def _effective_bms_can_id(self, snapshot: TelemetrySnapshot) -> int:
        configured = self.config.vesc.bms_can_id
        if snapshot.bms:
            reported = snapshot.bms.can_id
            if reported not in snapshot.can_nodes:
                raise VescProtocolError(f"BMS telemetry CAN {reported} not present in CAN node list")
            if reported != configured:
                LOG.info("resolved BMS CAN ID for %s from %s to %s", self.config.home_assistant.device_id, configured, reported)
                self.config.vesc.bms_can_id = reported
            return reported
        if configured not in snapshot.can_nodes:
            raise VescProtocolError(f"configured BMS CAN {configured} not present in CAN node list")
        return configured

    def _validate_control_snapshot(self, action: str, snapshot: TelemetrySnapshot) -> None:
        if not snapshot.connected:
            raise VescProtocolError("telemetry unavailable")
        if not self.config.controls.require_safe_state:
            return
        if action in {"allow_charging", "allow_balancing"} and not snapshot.bms:
            raise VescProtocolError("BMS telemetry unavailable")
        if not snapshot.refloat_realtime:
            raise VescProtocolError("Refloat telemetry unavailable; cannot verify board is idle")
        if action in REFLOAT_LED_CONTROL_ACTIONS and not snapshot.refloat_info:
            raise VescProtocolError("Refloat package info unavailable; cannot verify LED command support")

        state = snapshot.to_state_dict()
        if state.get("running"):
            raise VescProtocolError("board is RUNNING")
        speed = state.get("speed_mph")
        if speed is None:
            raise VescProtocolError("speed telemetry unavailable; cannot verify board is stationary")
        if speed is not None and abs(float(speed)) > self.config.controls.max_control_speed_mph:
            raise VescProtocolError(f"speed {speed} mph exceeds control limit")
        if snapshot.controller and snapshot.controller.fault_code:
            raise VescProtocolError(f"controller fault {snapshot.controller.fault_code} active")
        if snapshot.refloat_realtime.alerts_active:
            raise VescProtocolError("alerts/faults active; refusing control action")

    def _execute_control_command(self, command: ControlCommand) -> None:
        now = time.time()
        cooldown = max(self.config.controls.command_cooldown_seconds, 0.0)
        if now - self._last_command_at < cooldown:
            raise VescProtocolError("command cooldown active")

        snapshot = self._snapshot_for_control()
        self._validate_control_snapshot(command.action, snapshot)

        if command.action == "allow_charging":
            bms_can_id = self._effective_bms_can_id(snapshot)
            self.client.set_bms_charge_allowed(True, can_id=bms_can_id)
            message = f"charging allowed via BMS CAN {bms_can_id}"
        elif command.action == "allow_balancing":
            bms_can_id = self._effective_bms_can_id(snapshot)
            self.client.force_bms_balance(True, can_id=bms_can_id)
            message = f"force balancing enabled via BMS CAN {bms_can_id}"
        elif command.action == "refloat_leds_on":
            result = self.client.set_refloat_leds(True, can_id=self.config.vesc.thor_can_id, info=snapshot.refloat_info)
            message = f"Refloat LEDs on via Thor CAN {self.config.vesc.thor_can_id}; flags={result.raw_flags}"
        elif command.action == "refloat_leds_off":
            result = self.client.set_refloat_leds(False, can_id=self.config.vesc.thor_can_id, info=snapshot.refloat_info)
            message = f"Refloat LEDs off via Thor CAN {self.config.vesc.thor_can_id}; flags={result.raw_flags}"
        else:  # pragma: no cover - protected by enqueue validation
            raise VescProtocolError(f"unknown action {command.action}")

        self._last_command_at = time.time()
        LOG.warning("executed guarded control action: %s", command.action)
        self.publisher.publish_command_status(command.action, "ok", message)

    def process_control_commands(self) -> None:
        while True:
            try:
                command = self._command_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._execute_control_command(command)
            except Exception as exc:  # noqa: BLE001 - report command failures into HA
                LOG.exception("control command %s failed: %s", command.action, exc)
                self.publisher.publish_command_status(command.action, "rejected", str(exc))

    def print_snapshot(self, snapshot: TelemetrySnapshot, raw: bool = False) -> None:
        payload = snapshot.to_raw_dict() if raw else snapshot.to_state_dict()
        print(json.dumps(payload, indent=2, sort_keys=True))

    def _static_snapshot(self) -> TelemetrySnapshot:
        return TelemetrySnapshot(
            firmware=self._cached_firmware,
            can_nodes=self._cached_can_nodes,
            refloat_info=self._cached_refloat_info,
            refloat_ids=self._cached_refloat_ids,
        )

    def _attach_static_info(self, snapshot: TelemetrySnapshot) -> TelemetrySnapshot:
        snapshot.firmware = self._cached_firmware
        snapshot.can_nodes = list(self._cached_can_nodes)
        snapshot.refloat_info = self._cached_refloat_info
        snapshot.refloat_ids = self._cached_refloat_ids
        return snapshot

    def connect(self) -> None:
        self.publisher.connect()
        self.publisher.publish_availability(False)
        try:
            self.refresh_static_info(force=True)
        except Exception as exc:  # noqa: BLE001 - keep service alive when board is offline
            LOG.warning("initial static telemetry refresh failed; bridge will retry in loop: %s", exc)
        self.publisher.publish_discovery(self._static_snapshot())
        self._discovery_published = True

    def poll_cycle(self) -> TelemetrySnapshot | None:
        self._poll_count += 1
        try:
            self.process_control_commands()
            if self._poll_count % max(self.config.vesc.static_refresh_every_polls, 1) == 0:
                self.refresh_static_info(force=True, best_effort=True)
            snapshot = self._attach_static_info(self.poll_once())
            self._last_snapshot = snapshot
            if not self._discovery_published or self._poll_count % max(self.config.vesc.static_refresh_every_polls, 1) == 0:
                self.publisher.publish_discovery(snapshot)
                self._discovery_published = True
            self.publisher.publish_snapshot(snapshot)
            self.publisher.publish_availability(True)
            return snapshot
        except Exception as exc:  # noqa: BLE001 - long-running service loop
            LOG.exception("poll cycle failed: %s", exc)
            self.publisher.publish_availability(False)
            return None

    def run(self) -> None:
        self.connect()
        while True:
            self.poll_cycle()
            time.sleep(self.config.vesc.poll_interval_seconds)

    def close(self) -> None:
        self.publisher.disconnect()
