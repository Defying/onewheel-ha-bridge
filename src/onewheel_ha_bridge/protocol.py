from __future__ import annotations

import binascii
import logging
import math
import socket
import time
from typing import Iterable

from .config import VescConfig
from .models import BmsValues, ControllerValues, FirmwareInfo, RefloatInfo, RefloatLights, RefloatRealtime

LOG = logging.getLogger(__name__)

COMM_FW_VERSION = 0
COMM_GET_VALUES = 4
COMM_FORWARD_CAN = 34
COMM_CUSTOM_APP_DATA = 36
COMM_PING_CAN = 62
COMM_BMS_GET_VALUES = 96
COMM_BMS_SET_CHARGE_ALLOWED = 97
COMM_BMS_SET_BALANCE_OVERRIDE = 98
COMM_BMS_FORCE_BALANCE = 100

REFLOAT_INTERFACE_ID = 101
REFLOAT_INFO = 0
REFLOAT_LIGHTS_CONTROL = 20
REFLOAT_REALTIME_DATA = 31
REFLOAT_REALTIME_IDS = 32

REFLOAT_CAPABILITY_LEDS = 0x1
REFLOAT_CAPABILITY_EXTERNAL_LEDS = 0x2
REFLOAT_CAPABILITY_DATA_RECORDING = 0x80000000
REFLOAT_LIGHTS_CONTROL_MIN_VERSION = (1, 2, 0)

PACKAGE_STATE_MAP = {
    0: "DISABLED",
    1: "STARTUP",
    2: "READY",
    3: "RUNNING",
}
PACKAGE_MODE_MAP = {
    0: "NORMAL",
    1: "HANDTEST",
    2: "FLYWHEEL",
}
FOOTPAD_STATE_MAP = {
    0: "NONE",
    1: "LEFT",
    2: "RIGHT",
    3: "BOTH",
}
STOP_CONDITION_MAP = {
    0: "NONE",
    1: "PITCH",
    2: "ROLL",
    3: "SWITCH_HALF",
    4: "SWITCH_FULL",
    5: "REVERSE_STOP",
    6: "QUICKSTOP",
}
SAT_MAP = {
    0: "NONE",
    1: "CENTERING",
    2: "REVERSESTOP",
    5: "PB_SPEED",
    6: "PB_DUTY",
    7: "PB_ERROR",
    10: "PB_HIGH_VOLTAGE",
    11: "PB_LOW_VOLTAGE",
    12: "PB_TEMPERATURE",
}
ALERT_REASON_MAP = {
    0: "NONE",
    1: "LOW_VOLTAGE",
    2: "HIGH_VOLTAGE",
    3: "TEMP_MOSFET",
    4: "TEMP_MOTOR",
    5: "CURRENT",
    6: "DUTY",
    7: "SENSORS",
    8: "LOW_BATTERY",
    9: "IDLE",
    10: "ERROR",
}


def _version_tuple(version: str) -> tuple[int, int, int]:
    main = version.split("-", 1)[0]
    parts = main.split(".")
    numbers: list[int] = []
    for part in parts[:3]:
        try:
            numbers.append(int(part))
        except ValueError:
            numbers.append(0)
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)  # type: ignore[return-value]


def refloat_lights_control_supported(info: RefloatInfo | None) -> bool:
    """Return true only for the documented stable Refloat lights command.

    Source inspection found two Refloat command maps: official Refloat uses the
    documented stable `COMMAND_LIGHTS_CONTROL = 20` with a uint32 mask, while
    the older float-accessories fork used unstable command 202 with a different
    payload. Do not guess or send the unstable command from Home Assistant.
    """

    if info is None:
        return False
    if info.package_name != "Refloat":
        return False
    if info.command_version < 2:
        return False
    if not info.capabilities & REFLOAT_CAPABILITY_LEDS:
        return False
    return _version_tuple(info.package_version) >= REFLOAT_LIGHTS_CONTROL_MIN_VERSION


class VescProtocolError(RuntimeError):
    pass


class Buffer:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def require(self, size: int) -> None:
        if self.remaining < size:
            raise VescProtocolError(f"buffer underflow: need {size}, have {self.remaining}")

    def u8(self) -> int:
        self.require(1)
        value = self.data[self.offset]
        self.offset += 1
        return value

    def i16(self) -> int:
        self.require(2)
        value = int.from_bytes(self.data[self.offset:self.offset + 2], "big", signed=True)
        self.offset += 2
        return value

    def u16(self) -> int:
        self.require(2)
        value = int.from_bytes(self.data[self.offset:self.offset + 2], "big", signed=False)
        self.offset += 2
        return value

    def i32(self) -> int:
        self.require(4)
        value = int.from_bytes(self.data[self.offset:self.offset + 4], "big", signed=True)
        self.offset += 4
        return value

    def u32(self) -> int:
        self.require(4)
        value = int.from_bytes(self.data[self.offset:self.offset + 4], "big", signed=False)
        self.offset += 4
        return value

    def float16_scaled(self, scale: float) -> float:
        return self.i16() / scale

    def float32_scaled(self, scale: float) -> float:
        return self.i32() / scale

    def float32_auto(self) -> float:
        raw = self.u32()
        exponent = (raw >> 23) & 0xFF
        mantissa = raw & 0x7FFFFF
        negative = bool(raw & (1 << 31))
        significand = 0.0
        if exponent != 0 or mantissa != 0:
            significand = mantissa / (8388608.0 * 2.0) + 0.5
            exponent -= 126
        if negative:
            significand = -significand
        return math.ldexp(significand, exponent)

    def bytes(self, size: int) -> bytes:
        self.require(size)
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def remaining_bytes(self) -> bytes:
        value = self.data[self.offset:]
        self.offset = len(self.data)
        return value


class VescTcpClient:
    def __init__(self, config: VescConfig):
        self.config = config

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise EOFError("socket closed")
            data += chunk
        return data

    def _read_frame(self, sock: socket.socket) -> bytes:
        frame_type = self._recv_exact(sock, 1)[0]
        if frame_type == 2:
            length = self._recv_exact(sock, 1)[0]
        elif frame_type == 3:
            length = int.from_bytes(self._recv_exact(sock, 2), "big")
        else:
            raise VescProtocolError(f"unexpected frame type {frame_type}")
        payload = self._recv_exact(sock, length)
        received_crc = self._recv_exact(sock, 2)
        expected_crc = binascii.crc_hqx(payload, 0).to_bytes(2, "big")
        if received_crc != expected_crc:
            raise VescProtocolError(f"frame CRC mismatch: expected {expected_crc.hex()}, got {received_crc.hex()}")
        end = self._recv_exact(sock, 1)[0]
        if end != 3:
            raise VescProtocolError(f"unexpected frame end {end}")
        return payload

    @staticmethod
    def _encode_frame(payload: bytes) -> bytes:
        if len(payload) < 256:
            header = bytes([2, len(payload)])
        else:
            header = bytes([3]) + len(payload).to_bytes(2, "big")
        crc = binascii.crc_hqx(payload, 0).to_bytes(2, "big")
        return header + payload + crc + bytes([3])

    def query(self, payload: Iterable[int] | bytes, retries: int = 3) -> bytes:
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        frame = self._encode_frame(payload)
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            with socket.socket() as sock:
                sock.settimeout(self.config.timeout_seconds)
                try:
                    sock.connect((self.config.host, self.config.port))
                    sock.sendall(frame)
                    return self._read_frame(sock)
                except Exception as exc:  # noqa: BLE001 - network protocol wrapper
                    last_error = exc
                    LOG.debug("query attempt %s failed for payload %s: %s", attempt, payload.hex(), exc)
                    if attempt < retries:
                        time.sleep(0.2 * attempt)
        raise VescProtocolError(f"query failed after {retries} attempts: {last_error}")

    def send(self, payload: Iterable[int] | bytes, retries: int = 3) -> None:
        """Send a command frame without waiting for a response.

        Some BMS write commands are fire-and-forget in VESC firmware. This is
        intentionally separate from query() so command callers cannot
        accidentally block waiting for a response that will never arrive.
        """
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        frame = self._encode_frame(payload)
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            with socket.socket() as sock:
                sock.settimeout(self.config.timeout_seconds)
                try:
                    sock.connect((self.config.host, self.config.port))
                    sock.sendall(frame)
                    return
                except Exception as exc:  # noqa: BLE001 - network protocol wrapper
                    last_error = exc
                    LOG.debug("send attempt %s failed for payload %s: %s", attempt, payload.hex(), exc)
                    if attempt < retries:
                        time.sleep(0.2 * attempt)
        raise VescProtocolError(f"send failed after {retries} attempts: {last_error}")

    def forward_can(self, can_id: int, payload: Iterable[int] | bytes) -> bytes:
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        return self.query(bytes([COMM_FORWARD_CAN, can_id]) + payload)

    def send_forward_can(self, can_id: int, payload: Iterable[int] | bytes) -> None:
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        self.send(bytes([COMM_FORWARD_CAN, can_id]) + payload)

    def _retry_decode(self, label: str, fetch_payload, decode_payload, attempts: int = 3):  # noqa: ANN001, ANN202
        """Retry a read when the bridge returns a transient/stale packet.

        The Express/TCP bridge can occasionally reset or return a frame that is
        not the response to the just-sent command. Because this service is
        strictly read-only, the safest recovery is to discard the bad frame and
        retry the same read-only request a small number of times.
        """

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return decode_payload(fetch_payload())
            except Exception as exc:  # noqa: BLE001 - normalize read/decode retries
                last_error = exc
                LOG.debug("%s decode attempt %s failed: %s", label, attempt, exc)
                if attempt < attempts:
                    time.sleep(0.2 * attempt)
        raise VescProtocolError(f"{label} failed after {attempts} attempts: {last_error}")

    def get_fw_version(self) -> FirmwareInfo:
        return self._retry_decode(
            "COMM_FW_VERSION",
            lambda: self.query(bytes([COMM_FW_VERSION])),
            self.get_fw_version_from_payload,
        )

    def get_fw_version_from_payload(self, payload: bytes) -> FirmwareInfo:
        buffer = Buffer(payload)
        command = buffer.u8()
        if command != COMM_FW_VERSION:
            raise VescProtocolError(f"unexpected fw response command {command}")
        major = buffer.u8()
        minor = buffer.u8()

        string_bytes = bytearray()
        while True:
            byte = buffer.u8()
            if byte == 0:
                break
            string_bytes.append(byte)
        hardware_name = string_bytes.decode("utf-8", "replace")

        uuid = buffer.bytes(12).hex()
        pairing_done = bool(buffer.u8())
        test_version = buffer.u8()
        hardware_type = buffer.u8()
        custom_config_count = buffer.u8()
        phase_filters = bool(buffer.u8())
        buffer.u8()  # qml hw source flags
        buffer.u8()  # qml app source flags
        buffer.u8()  # nrf flags

        firmware_name = None
        if buffer.remaining >= 5:
            firmware_bytes = bytearray()
            while buffer.remaining:
                byte = buffer.u8()
                if byte == 0:
                    break
                firmware_bytes.append(byte)
            firmware_name = firmware_bytes.decode("utf-8", "replace")

        hw_crc = buffer.u32() if buffer.remaining >= 4 else None
        return FirmwareInfo(
            major=major,
            minor=minor,
            hardware_name=hardware_name,
            uuid=uuid,
            pairing_done=pairing_done,
            firmware_name=firmware_name,
            hardware_type=hardware_type,
            test_version=test_version,
            custom_config_count=custom_config_count,
            phase_filters=phase_filters,
            hw_crc=hw_crc,
        )

    def ping_can(self) -> list[int]:
        payload = self.query(bytes([COMM_PING_CAN]))
        if not payload or payload[0] != COMM_PING_CAN:
            raise VescProtocolError("invalid COMM_PING_CAN response")
        return list(payload[1:])

    def get_controller_values(self, can_id: int) -> ControllerValues:
        return self._retry_decode(
            "COMM_GET_VALUES",
            lambda: self.forward_can(can_id, bytes([COMM_GET_VALUES])),
            self.get_controller_values_from_payload,
        )

    def get_controller_values_from_payload(self, payload: bytes) -> ControllerValues:
        buffer = Buffer(payload)
        command = buffer.u8()
        if command != COMM_GET_VALUES:
            raise VescProtocolError(f"unexpected controller values response {command}")
        return ControllerValues(
            temp_fet_c=buffer.float16_scaled(1e1),
            temp_motor_c=buffer.float16_scaled(1e1),
            avg_motor_current_a=buffer.float32_scaled(1e2),
            avg_input_current_a=buffer.float32_scaled(1e2),
            avg_id_a=buffer.float32_scaled(1e2),
            avg_iq_a=buffer.float32_scaled(1e2),
            duty_cycle_ratio=buffer.float16_scaled(1e3),
            rpm=float(buffer.i32()),
            vin_v=buffer.float16_scaled(1e1),
            amp_hours=buffer.float32_scaled(1e4),
            amp_hours_charged=buffer.float32_scaled(1e4),
            watt_hours=buffer.float32_scaled(1e4),
            watt_hours_charged=buffer.float32_scaled(1e4),
            tachometer=buffer.i32(),
            tachometer_abs=buffer.i32(),
            fault_code=buffer.u8(),
            pid_pos=buffer.float32_scaled(1e6),
            controller_id=buffer.u8(),
            mos_temps_c=[buffer.float16_scaled(1e1) for _ in range(3)],
            vd=buffer.float32_scaled(1e3),
            vq=buffer.float32_scaled(1e3),
            status_raw=buffer.u8(),
        )

    def get_bms_values(self) -> BmsValues:
        return self._retry_decode(
            "COMM_BMS_GET_VALUES",
            lambda: self.query(bytes([COMM_BMS_GET_VALUES])),
            self.get_bms_values_from_payload,
        )

    def set_bms_charge_allowed(self, allowed: bool, can_id: int | None = None) -> None:
        payload = bytes([COMM_BMS_SET_CHARGE_ALLOWED, 1 if allowed else 0])
        if can_id is None:
            self.send(payload)
        else:
            self.send_forward_can(can_id, payload)

    def set_bms_balance_override(self, cell_index_0_based: int, override: int, can_id: int | None = None) -> None:
        if cell_index_0_based < 0:
            raise ValueError("cell index must be >= 0")
        if override not in {0, 1, 2}:
            raise ValueError("balance override must be 0, 1, or 2")
        payload = bytes([COMM_BMS_SET_BALANCE_OVERRIDE, cell_index_0_based, override])
        if can_id is None:
            self.send(payload)
        else:
            self.send_forward_can(can_id, payload)

    def force_bms_balance(self, enabled: bool, can_id: int | None = None) -> None:
        payload = bytes([COMM_BMS_FORCE_BALANCE, 1 if enabled else 0])
        if can_id is None:
            self.send(payload)
        else:
            self.send_forward_can(can_id, payload)

    def get_bms_values_from_payload(self, payload: bytes) -> BmsValues:
        buffer = Buffer(payload)
        command = buffer.u8()
        if command != COMM_BMS_GET_VALUES:
            raise VescProtocolError(f"unexpected BMS response {command}")

        pack_voltage = buffer.float32_scaled(1e6)
        charge_voltage = buffer.float32_scaled(1e6)
        current = buffer.float32_scaled(1e6)
        current_ic = buffer.float32_scaled(1e6)
        amp_hours = buffer.float32_scaled(1e3)
        watt_hours = buffer.float32_scaled(1e3)

        cell_num = buffer.u8()
        cells = [buffer.float16_scaled(1e3) for _ in range(cell_num)]
        balancing_state = [bool(buffer.u8()) for _ in range(cell_num)]

        temp_num = buffer.u8()
        temps = [buffer.float16_scaled(1e2) for _ in range(temp_num)]
        temp_ic = buffer.float16_scaled(1e2)
        temp_humidity = buffer.float16_scaled(1e2)
        humidity = buffer.float16_scaled(1e2)
        temp_max_cell = buffer.float16_scaled(1e2)
        soc = buffer.float16_scaled(1e3)
        soh = buffer.float16_scaled(1e3)
        can_id = buffer.u8()

        amp_hours_charged_total = buffer.float32_auto()
        watt_hours_charged_total = buffer.float32_auto()
        amp_hours_discharged_total = buffer.float32_auto()
        watt_hours_discharged_total = buffer.float32_auto()

        pressure_pa = buffer.float16_scaled(1e-1) if buffer.remaining >= 2 else None
        data_version = buffer.u8() if buffer.remaining >= 1 else None
        status = None
        if buffer.remaining:
            raw = buffer.remaining_bytes()
            status = raw.split(b"\x00", 1)[0].decode("utf-8", "replace") or None

        return BmsValues(
            pack_voltage_v=pack_voltage,
            charge_voltage_v=charge_voltage,
            current_a=current,
            current_ic_a=current_ic,
            amp_hours=amp_hours,
            watt_hours=watt_hours,
            cells_v=cells,
            balancing_state=balancing_state,
            temps_c=temps,
            temp_ic_c=temp_ic,
            temp_humidity_c=temp_humidity,
            humidity_pct=humidity,
            temp_max_cell_c=temp_max_cell,
            soc_ratio=soc,
            soh_ratio=soh,
            can_id=can_id,
            amp_hours_charged_total=amp_hours_charged_total,
            watt_hours_charged_total=watt_hours_charged_total,
            amp_hours_discharged_total=amp_hours_discharged_total,
            watt_hours_discharged_total=watt_hours_discharged_total,
            pressure_pa=pressure_pa,
            data_version=data_version,
            status=status,
        )

    def get_refloat_info(self, can_id: int) -> RefloatInfo:
        return self._retry_decode(
            "Refloat INFO",
            lambda: self.forward_can(can_id, bytes([COMM_CUSTOM_APP_DATA, REFLOAT_INTERFACE_ID, REFLOAT_INFO, 2, 0])),
            self.get_refloat_info_from_payload,
        )

    def get_refloat_info_from_payload(self, payload: bytes) -> RefloatInfo:
        buffer = Buffer(payload)
        command = buffer.u8()
        interface_id = buffer.u8()
        refloat_command = buffer.u8()
        if command != COMM_CUSTOM_APP_DATA or interface_id != REFLOAT_INTERFACE_ID or refloat_command != REFLOAT_INFO:
            raise VescProtocolError("invalid Refloat INFO response")

        command_version = buffer.u8()
        buffer.u8()  # echoed flags
        package_name = buffer.bytes(20).rstrip(b"\x00").decode("utf-8", "replace")
        major = buffer.u8()
        minor = buffer.u8()
        patch = buffer.u8()
        suffix = buffer.bytes(20).rstrip(b"\x00").decode("utf-8", "replace")
        version = f"{major}.{minor}.{patch}"
        if suffix:
            version += f"-{suffix}"
        git_hash = buffer.bytes(4).hex()
        tick_rate_hz = buffer.u32()
        capabilities = buffer.u32()
        extra_flags = buffer.u8() if buffer.remaining else 0
        return RefloatInfo(
            package_name=package_name,
            command_version=command_version,
            package_version=version,
            git_hash=git_hash,
            tick_rate_hz=tick_rate_hz,
            capabilities=capabilities,
            extra_flags=extra_flags,
        )

    def refloat_lights_control_supported(self, info: RefloatInfo | None) -> bool:
        return refloat_lights_control_supported(info)

    def get_refloat_lights(self, can_id: int, info: RefloatInfo | None) -> RefloatLights:
        if not self.refloat_lights_control_supported(info):
            raise VescProtocolError("Refloat LIGHTS_CONTROL command is not supported by this package profile")
        return self._retry_decode(
            "Refloat LIGHTS_CONTROL",
            lambda: self.forward_can(can_id, bytes([COMM_CUSTOM_APP_DATA, REFLOAT_INTERFACE_ID, REFLOAT_LIGHTS_CONTROL])),
            self.get_refloat_lights_from_payload,
        )

    def set_refloat_leds(self, leds_on: bool, can_id: int, info: RefloatInfo | None) -> RefloatLights:
        if not self.refloat_lights_control_supported(info):
            raise VescProtocolError("Refloat LIGHTS_CONTROL command is not supported by this package profile")
        # Official Refloat LIGHTS_CONTROL v1 uses a uint32 mask followed by the
        # flag values. Mask bit 0 updates only `leds_on`, preserving headlights.
        mask = 0x1
        flags = 0x1 if leds_on else 0x0
        payload = (
            bytes([COMM_CUSTOM_APP_DATA, REFLOAT_INTERFACE_ID, REFLOAT_LIGHTS_CONTROL])
            + mask.to_bytes(4, "big")
            + bytes([flags])
        )
        return self.get_refloat_lights_from_payload(self.forward_can(can_id, payload))

    def get_refloat_lights_from_payload(self, payload: bytes) -> RefloatLights:
        buffer = Buffer(payload)
        command = buffer.u8()
        interface_id = buffer.u8()
        refloat_command = buffer.u8()
        if command != COMM_CUSTOM_APP_DATA or interface_id != REFLOAT_INTERFACE_ID or refloat_command != REFLOAT_LIGHTS_CONTROL:
            raise VescProtocolError("invalid Refloat LIGHTS_CONTROL response")
        flags = buffer.u8()
        if buffer.remaining:
            LOG.debug("unused Refloat lights payload bytes: %s", buffer.remaining_bytes().hex())
        return RefloatLights(leds_on=bool(flags & 0x1), headlights_on=bool(flags & 0x2), raw_flags=flags)

    def get_refloat_ids(self, can_id: int) -> dict[str, list[str]]:
        return self._retry_decode(
            "Refloat REALTIME_DATA_IDS",
            lambda: self.forward_can(can_id, bytes([COMM_CUSTOM_APP_DATA, REFLOAT_INTERFACE_ID, REFLOAT_REALTIME_IDS])),
            self.get_refloat_ids_from_payload,
        )

    def get_refloat_ids_from_payload(self, payload: bytes) -> dict[str, list[str]]:
        buffer = Buffer(payload)
        command = buffer.u8()
        interface_id = buffer.u8()
        refloat_command = buffer.u8()
        if command != COMM_CUSTOM_APP_DATA or interface_id != REFLOAT_INTERFACE_ID or refloat_command != REFLOAT_REALTIME_IDS:
            raise VescProtocolError("invalid Refloat IDs response")
        realtime_count = buffer.u8()
        realtime_ids = []
        for _ in range(realtime_count):
            length = buffer.u8()
            realtime_ids.append(buffer.bytes(length).decode("utf-8", "replace"))
        runtime_count = buffer.u8()
        runtime_ids = []
        for _ in range(runtime_count):
            length = buffer.u8()
            runtime_ids.append(buffer.bytes(length).decode("utf-8", "replace"))
        return {"realtime": realtime_ids, "runtime": runtime_ids}

    @staticmethod
    def _decode_refloat_float16(raw: int) -> float:
        exponent = (raw & 0x7C00) >> 10
        mantissa = raw & 0x03FF
        if exponent == 0:
            value = (mantissa / 2**10) * 2**(-14)
        else:
            value = (1 + mantissa / 2**10) * 2 ** (exponent - 15)
        if raw & 0x8000:
            value = -value
        return value

    def get_refloat_realtime(self, can_id: int, ids: dict[str, list[str]]) -> RefloatRealtime:
        return self._retry_decode(
            "Refloat REALTIME_DATA",
            lambda: self.forward_can(can_id, bytes([COMM_CUSTOM_APP_DATA, REFLOAT_INTERFACE_ID, REFLOAT_REALTIME_DATA])),
            lambda payload: self.get_refloat_realtime_from_payload(payload, ids),
        )

    def get_refloat_realtime_from_payload(self, payload: bytes, ids: dict[str, list[str]]) -> RefloatRealtime:
        buffer = Buffer(payload)
        command = buffer.u8()
        interface_id = buffer.u8()
        refloat_command = buffer.u8()
        if command != COMM_CUSTOM_APP_DATA or interface_id != REFLOAT_INTERFACE_ID or refloat_command != REFLOAT_REALTIME_DATA:
            raise VescProtocolError("invalid Refloat realtime response")

        mask = buffer.u8()
        extra_flags = buffer.u8()
        time_ticks = buffer.u32()
        state_and_mode = buffer.u8()
        flags_and_footpad = buffer.u8()
        stop_and_sat = buffer.u8()
        alert_reason = buffer.u8()

        realtime_values: dict[str, float] = {}
        for value_id in ids.get("realtime", []):
            realtime_values[value_id] = self._decode_refloat_float16(buffer.u16())

        runtime_values: dict[str, float] = {}
        if mask & 0x1:
            for value_id in ids.get("runtime", []):
                runtime_values[value_id] = self._decode_refloat_float16(buffer.u16())

        charging_values: dict[str, float] = {}
        if mask & 0x2:
            charging_values = {
                "charging_current": self._decode_refloat_float16(buffer.u16()),
                "charging_voltage": self._decode_refloat_float16(buffer.u16()),
            }

        active_alert_mask_low = 0
        active_alert_mask_high = 0
        firmware_fault_code = 0
        if mask & 0x4:
            active_alert_mask_low = buffer.u32()
            active_alert_mask_high = buffer.u32()
            firmware_fault_code = buffer.u8()

        if buffer.remaining:
            LOG.debug("unused Refloat realtime payload bytes: %s", buffer.remaining_bytes().hex())

        return RefloatRealtime(
            mask=mask,
            extra_flags=extra_flags,
            time_ticks=time_ticks,
            package_state=PACKAGE_STATE_MAP.get(state_and_mode & 0x03, str(state_and_mode & 0x03)),
            package_mode=PACKAGE_MODE_MAP.get((state_and_mode >> 4) & 0x03, str((state_and_mode >> 4) & 0x03)),
            footpad_state=FOOTPAD_STATE_MAP.get((flags_and_footpad >> 6) & 0x03, str((flags_and_footpad >> 6) & 0x03)),
            charging=bool((flags_and_footpad >> 5) & 0x01),
            darkride=bool((flags_and_footpad >> 1) & 0x01),
            wheelslip=bool(flags_and_footpad & 0x01),
            stop_condition=STOP_CONDITION_MAP.get(stop_and_sat & 0x0F, str(stop_and_sat & 0x0F)),
            sat=SAT_MAP.get((stop_and_sat >> 4) & 0x0F, str((stop_and_sat >> 4) & 0x0F)),
            alert_reason=ALERT_REASON_MAP.get(alert_reason, str(alert_reason)),
            values=realtime_values,
            runtime_values=runtime_values,
            charging_values=charging_values,
            active_alert_mask_low=active_alert_mask_low,
            active_alert_mask_high=active_alert_mask_high,
            firmware_fault_code=firmware_fault_code,
        )
