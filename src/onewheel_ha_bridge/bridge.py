from __future__ import annotations

import json
import logging
import queue
import time
from dataclasses import dataclass

from .config import BridgeConfig
from .models import TelemetrySnapshot
from .mqtt_bridge import HomeAssistantPublisher
from .protocol import VescProtocolError, VescTcpClient

LOG = logging.getLogger(__name__)

ALLOWED_CONTROL_ACTIONS = {
    "allow_charging",
    "disable_charging",
    "allow_balancing",
    "disable_balancing",
}


@dataclass(frozen=True, slots=True)
class ControlCommand:
    action: str
    received_at: float


class OnewheelBridge:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.client = VescTcpClient(config.vesc)
        self._command_queue: queue.Queue[ControlCommand] = queue.Queue()
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
        if action not in ALLOWED_CONTROL_ACTIONS:
            LOG.warning("ignoring unknown control action %r", action)
            self.publisher.publish_command_status(action, "rejected", "unknown action")
            return
        if not self.config.controls.enabled:
            LOG.warning("ignoring control action %s because controls are disabled", action)
            self.publisher.publish_command_status(action, "rejected", "controls disabled")
            return
        self._command_queue.put(ControlCommand(action=action, received_at=time.time()))
        self.publisher.publish_command_status(action, "queued", "waiting for bridge loop")

    def refresh_static_info(self, force: bool = False) -> None:
        if force or self._cached_firmware is None:
            self._cached_firmware = self.client.get_fw_version()
        if force or not self._cached_can_nodes or self._poll_count % max(self.config.vesc.static_refresh_every_polls, 1) == 0:
            self._cached_can_nodes = self.client.ping_can()
        if force or self._cached_refloat_info is None:
            self._cached_refloat_info = self.client.get_refloat_info(self.config.vesc.thor_can_id)
        if force or not self._cached_refloat_ids:
            self._cached_refloat_ids = self.client.get_refloat_ids(self.config.vesc.thor_can_id)

    def poll_once(self) -> TelemetrySnapshot:
        snapshot = TelemetrySnapshot()
        snapshot.firmware = self._cached_firmware
        snapshot.can_nodes = list(self._cached_can_nodes)
        snapshot.refloat_info = self._cached_refloat_info
        snapshot.refloat_ids = self._cached_refloat_ids

        successes = 0
        for name, func in (
            ("controller", lambda: self.client.get_controller_values(self.config.vesc.thor_can_id)),
            ("bms", self.client.get_bms_values),
            ("refloat", lambda: self.client.get_refloat_realtime(self.config.vesc.thor_can_id, self._cached_refloat_ids)),
        ):
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

        if successes == 0:
            raise VescProtocolError("all telemetry queries failed")
        return snapshot

    def _snapshot_for_control(self) -> TelemetrySnapshot:
        # Use fresh-ish telemetry if available; otherwise poll before any write.
        if self._last_snapshot and time.time() - self._last_snapshot.collected_at.timestamp() <= 10:
            return self._last_snapshot
        snapshot = self.poll_once()
        snapshot.firmware = self._cached_firmware
        snapshot.can_nodes = list(self._cached_can_nodes)
        snapshot.refloat_info = self._cached_refloat_info
        snapshot.refloat_ids = self._cached_refloat_ids
        self._last_snapshot = snapshot
        return snapshot

    def _validate_control_snapshot(self, action: str, snapshot: TelemetrySnapshot) -> None:
        if not snapshot.connected:
            raise VescProtocolError("telemetry unavailable")
        if not self.config.controls.require_safe_state:
            return
        if not snapshot.bms:
            raise VescProtocolError("BMS telemetry unavailable")
        if not snapshot.refloat_realtime:
            raise VescProtocolError("Refloat telemetry unavailable; cannot verify board is idle")

        state = snapshot.to_state_dict()
        if state.get("running"):
            raise VescProtocolError("board is RUNNING")
        speed = state.get("speed_mph")
        if speed is not None and abs(float(speed)) > self.config.controls.max_control_speed_mph:
            raise VescProtocolError(f"speed {speed} mph exceeds control limit")
        if snapshot.controller and snapshot.controller.fault_code:
            raise VescProtocolError(f"controller fault {snapshot.controller.fault_code} active")
        if snapshot.refloat_realtime.alerts_active and action.startswith("allow_"):
            raise VescProtocolError("alerts/faults active; refusing allow action")

    def _execute_control_command(self, command: ControlCommand) -> None:
        now = time.time()
        cooldown = max(self.config.controls.command_cooldown_seconds, 0.0)
        if now - self._last_command_at < cooldown:
            raise VescProtocolError("command cooldown active")

        snapshot = self._snapshot_for_control()
        self._validate_control_snapshot(command.action, snapshot)

        if command.action == "allow_charging":
            self.client.set_bms_charge_allowed(True)
            message = "charging allowed"
        elif command.action == "disable_charging":
            self.client.set_bms_charge_allowed(False)
            message = "charging disabled"
        elif command.action in {"allow_balancing", "disable_balancing"}:
            if not snapshot.bms or not snapshot.bms.cells_v:
                raise VescProtocolError("cell list unavailable; cannot target balance overrides")
            override = 0 if command.action == "allow_balancing" else 1
            for cell_index in range(len(snapshot.bms.cells_v)):
                self.client.set_bms_balance_override(cell_index, override)
                time.sleep(0.02)
            message = f"balancing {'allowed' if override == 0 else 'disabled'} for {len(snapshot.bms.cells_v)} cells"
        else:  # pragma: no cover - protected by enqueue validation
            raise VescProtocolError(f"unknown action {command.action}")

        self._last_command_at = time.time()
        LOG.warning("executed guarded BMS control action: %s", command.action)
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

    def run(self) -> None:
        self.publisher.connect()
        self.publisher.publish_availability(False)
        self.refresh_static_info(force=True)
        self.publisher.publish_discovery(
            TelemetrySnapshot(
                firmware=self._cached_firmware,
                can_nodes=self._cached_can_nodes,
                refloat_info=self._cached_refloat_info,
                refloat_ids=self._cached_refloat_ids,
            )
        )
        self._discovery_published = True

        while True:
            self._poll_count += 1
            try:
                self.process_control_commands()
                if self._poll_count % max(self.config.vesc.static_refresh_every_polls, 1) == 0:
                    self.refresh_static_info(force=True)
                snapshot = self.poll_once()
                snapshot.firmware = self._cached_firmware
                snapshot.can_nodes = list(self._cached_can_nodes)
                snapshot.refloat_info = self._cached_refloat_info
                snapshot.refloat_ids = self._cached_refloat_ids
                self._last_snapshot = snapshot
                if not self._discovery_published or self._poll_count % max(self.config.vesc.static_refresh_every_polls, 1) == 0:
                    self.publisher.publish_discovery(snapshot)
                    self._discovery_published = True
                self.publisher.publish_snapshot(snapshot)
                self.publisher.publish_availability(True)
            except Exception as exc:  # noqa: BLE001 - long-running service loop
                LOG.exception("poll cycle failed: %s", exc)
                self.publisher.publish_availability(False)
            time.sleep(self.config.vesc.poll_interval_seconds)

    def close(self) -> None:
        self.publisher.disconnect()
