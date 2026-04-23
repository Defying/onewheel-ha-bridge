from __future__ import annotations

import json
import logging
import time

from .config import BridgeConfig
from .models import TelemetrySnapshot
from .mqtt_bridge import HomeAssistantPublisher
from .protocol import VescProtocolError, VescTcpClient

LOG = logging.getLogger(__name__)


class OnewheelBridge:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.client = VescTcpClient(config.vesc)
        self.publisher = HomeAssistantPublisher(config)
        self._cached_firmware = None
        self._cached_can_nodes: list[int] = []
        self._cached_refloat_info = None
        self._cached_refloat_ids: dict[str, list[str]] = {}
        self._poll_count = 0
        self._discovery_published = False

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
                if self._poll_count % max(self.config.vesc.static_refresh_every_polls, 1) == 0:
                    self.refresh_static_info(force=True)
                snapshot = self.poll_once()
                snapshot.firmware = self._cached_firmware
                snapshot.can_nodes = list(self._cached_can_nodes)
                snapshot.refloat_info = self._cached_refloat_info
                snapshot.refloat_ids = self._cached_refloat_ids
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
