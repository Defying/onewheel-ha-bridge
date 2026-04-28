from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time

from .bridge import OnewheelBridge
from .config import BridgeConfig
from .models import FirmwareInfo, TelemetrySnapshot
from .scanner import VescTcpEndpoint, board_id_for_endpoint, discover_vesc_tcp_endpoints

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class BoardRuntime:
    key: str
    bridge: OnewheelBridge
    discovered: bool = False


class MultiBoardBridge:
    """Run one or more board bridges in a single process.

    The configured board keeps the historical topics/device IDs. Auto-discovered
    boards are additional MQTT devices with suffixed topics, unique client IDs,
    and controls disabled unless explicitly enabled for discovered boards.
    """

    def __init__(self, config: BridgeConfig):
        self.config = config
        self._boards: dict[str, BoardRuntime] = {}
        self._last_discovery_scan = 0.0

    @staticmethod
    def endpoint_key(host: str, port: int) -> str:
        return f"{host}:{port}"

    def _make_discovered_config(self, endpoint: VescTcpEndpoint) -> BridgeConfig:
        board_id = board_id_for_endpoint(endpoint)
        short = board_id.replace("vesc_", "", 1)[:8]
        hardware = endpoint.firmware.hardware_name or "VESC"
        name = f"{self.config.home_assistant.device_name} {hardware} {short}".strip()
        return self.config.for_discovered_board(board_id, endpoint.host, endpoint.port, name=name)

    def _known_identity_keys(self) -> set[str]:
        identities: set[str] = set()
        for runtime in self._boards.values():
            firmware = runtime.bridge._cached_firmware
            if firmware:
                identities.add(VescTcpEndpoint(runtime.bridge.config.vesc.host, runtime.bridge.config.vesc.port, firmware).identity_key)
        return identities

    def _add_board(self, key: str, config: BridgeConfig, *, discovered: bool, firmware: FirmwareInfo | None = None) -> BoardRuntime:
        if key in self._boards:
            return self._boards[key]
        bridge = OnewheelBridge(config)
        if firmware:
            bridge._cached_firmware = firmware
        runtime = BoardRuntime(key=key, bridge=bridge, discovered=discovered)
        self._boards[key] = runtime
        bridge.connect()
        LOG.info("registered %sboard %s at %s:%s", "discovered " if discovered else "", config.home_assistant.device_id, config.vesc.host, config.vesc.port)
        return runtime

    def connect(self) -> None:
        primary_key = self.endpoint_key(self.config.vesc.host, self.config.vesc.port)
        self._add_board(primary_key, self.config, discovered=False)
        try:
            self.scan_once()
        except Exception as exc:  # noqa: BLE001 - discovery must not prevent primary telemetry
            LOG.exception("initial VESC TCP discovery scan failed: %s", exc)

    def scan_once(self) -> list[VescTcpEndpoint]:
        self._last_discovery_scan = time.time()
        endpoints = discover_vesc_tcp_endpoints(self.config.discovery, self.config.vesc)
        primary_key = self.endpoint_key(self.config.vesc.host, self.config.vesc.port)
        known_identities = self._known_identity_keys()
        for endpoint in endpoints:
            key = endpoint.key
            if key == primary_key or key in self._boards or endpoint.identity_key in known_identities:
                continue
            self._add_board(key, self._make_discovered_config(endpoint), discovered=True, firmware=endpoint.firmware)
            known_identities.add(endpoint.identity_key)
        return endpoints

    def _maybe_scan(self) -> None:
        if not self.config.discovery.enabled:
            return
        interval = max(self.config.discovery.scan_interval_seconds, 1.0)
        if time.time() - self._last_discovery_scan >= interval:
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001 - discovery should never kill telemetry
                LOG.exception("VESC TCP discovery scan failed: %s", exc)

    def poll_runtime_once(self, runtime: BoardRuntime) -> TelemetrySnapshot | None:
        return runtime.bridge.poll_cycle()

    def poll_once(self) -> dict[str, TelemetrySnapshot | None]:
        self._maybe_scan()
        return {key: self.poll_runtime_once(runtime) for key, runtime in list(self._boards.items())}

    def print_once(self, raw: bool = False) -> None:
        payload: dict[str, object] = {}
        for key, snapshot in self.poll_once().items():
            if snapshot is None:
                payload[key] = None
            else:
                payload[key] = snapshot.to_raw_dict() if raw else snapshot.to_state_dict()
        print(json.dumps(payload, indent=2, sort_keys=True))

    def run(self) -> None:
        self.connect()
        while True:
            self.poll_once()
            time.sleep(max(self.config.vesc.poll_interval_seconds, 0.1))

    def close(self) -> None:
        for runtime in list(self._boards.values()):
            try:
                runtime.bridge.close()
            except Exception:  # noqa: BLE001 - shutdown best effort
                LOG.debug("board bridge close failed for %s", runtime.key, exc_info=True)
