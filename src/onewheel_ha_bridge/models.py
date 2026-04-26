from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


ENNOID_CHARGING_CURRENT_THRESHOLD_A = 0.5


@dataclass(slots=True)
class FirmwareInfo:
    major: int
    minor: int
    hardware_name: str
    uuid: str
    pairing_done: bool
    firmware_name: str | None = None
    hardware_type: int | None = None
    test_version: int | None = None
    custom_config_count: int | None = None
    phase_filters: bool | None = None
    hw_crc: int | None = None

    @property
    def version(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(slots=True)
class ControllerValues:
    temp_fet_c: float
    temp_motor_c: float
    avg_motor_current_a: float
    avg_input_current_a: float
    avg_id_a: float
    avg_iq_a: float
    duty_cycle_ratio: float
    rpm: float
    vin_v: float
    amp_hours: float
    amp_hours_charged: float
    watt_hours: float
    watt_hours_charged: float
    tachometer: int
    tachometer_abs: int
    fault_code: int
    pid_pos: float
    controller_id: int
    mos_temps_c: list[float]
    vd: float
    vq: float
    status_raw: int


@dataclass(slots=True)
class BmsValues:
    pack_voltage_v: float
    charge_voltage_v: float
    current_a: float
    current_ic_a: float
    amp_hours: float
    watt_hours: float
    cells_v: list[float]
    balancing_state: list[bool]
    temps_c: list[float]
    temp_ic_c: float
    temp_humidity_c: float
    humidity_pct: float
    temp_max_cell_c: float
    soc_ratio: float
    soh_ratio: float
    can_id: int
    amp_hours_charged_total: float
    watt_hours_charged_total: float
    amp_hours_discharged_total: float
    watt_hours_discharged_total: float
    pressure_pa: float | None = None
    data_version: int | None = None
    status: str | None = None

    @property
    def min_cell_v(self) -> float | None:
        return min(self.cells_v) if self.cells_v else None

    @property
    def max_cell_v(self) -> float | None:
        return max(self.cells_v) if self.cells_v else None

    @property
    def min_cell_index(self) -> int | None:
        return self.cells_v.index(self.min_cell_v) + 1 if self.cells_v else None

    @property
    def max_cell_index(self) -> int | None:
        return self.cells_v.index(self.max_cell_v) + 1 if self.cells_v else None

    @property
    def cell_delta_v(self) -> float | None:
        if not self.cells_v:
            return None
        return self.max_cell_v - self.min_cell_v

    @property
    def charging(self) -> bool:
        # ENNOID's COMM_BMS_GET_VALUES does not expose a charging flag or
        # chargeAllowed state. In this firmware positive pack current means
        # current is flowing into the pack; the firmware's own charger-enabled
        # threshold defaults to 0.5 A.
        return self.current_a > ENNOID_CHARGING_CURRENT_THRESHOLD_A

    @property
    def balancing_active(self) -> bool:
        return any(self.balancing_state)

    @property
    def balancing_cell_count(self) -> int:
        return sum(1 for active in self.balancing_state if active)

    def cell_voltage(self, index_1_based: int) -> float | None:
        if index_1_based < 1 or index_1_based > len(self.cells_v):
            return None
        return self.cells_v[index_1_based - 1]


@dataclass(slots=True)
class RefloatInfo:
    package_name: str
    command_version: int
    package_version: str
    git_hash: str
    tick_rate_hz: int
    capabilities: int
    extra_flags: int


@dataclass(slots=True)
class RefloatRealtime:
    mask: int
    extra_flags: int
    time_ticks: int
    package_state: str
    package_mode: str
    footpad_state: str
    charging: bool
    darkride: bool
    wheelslip: bool
    stop_condition: str
    sat: str
    alert_reason: str
    values: dict[str, float]
    runtime_values: dict[str, float]
    charging_values: dict[str, float]
    active_alert_mask_low: int
    active_alert_mask_high: int
    firmware_fault_code: int

    @property
    def alerts_active(self) -> bool:
        return bool(self.active_alert_mask_low or self.active_alert_mask_high or self.firmware_fault_code)


@dataclass(slots=True)
class TelemetrySnapshot:
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    firmware: FirmwareInfo | None = None
    can_nodes: list[int] = field(default_factory=list)
    controller: ControllerValues | None = None
    bms: BmsValues | None = None
    refloat_info: RefloatInfo | None = None
    refloat_realtime: RefloatRealtime | None = None
    refloat_ids: dict[str, list[str]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def connected(self) -> bool:
        return any((self.controller, self.bms, self.refloat_realtime))

    def to_raw_dict(self) -> dict:
        payload = {
            "timestamp": self.collected_at.isoformat(),
            "connected": self.connected,
            "can_nodes": self.can_nodes,
            "errors": self.errors,
            "refloat_ids": self.refloat_ids,
        }
        if self.firmware:
            payload["firmware"] = asdict(self.firmware)
            payload["firmware"]["version"] = self.firmware.version
        if self.controller:
            payload["controller"] = asdict(self.controller)
        if self.bms:
            payload["bms"] = asdict(self.bms)
            payload["bms"]["min_cell_v"] = self.bms.min_cell_v
            payload["bms"]["min_cell_index"] = self.bms.min_cell_index
            payload["bms"]["max_cell_v"] = self.bms.max_cell_v
            payload["bms"]["max_cell_index"] = self.bms.max_cell_index
            payload["bms"]["cell_delta_v"] = self.bms.cell_delta_v
            payload["bms"]["charging"] = self.bms.charging
            payload["bms"]["balancing_active"] = self.bms.balancing_active
            payload["bms"]["balancing_cell_count"] = self.bms.balancing_cell_count
        if self.refloat_info:
            payload["refloat_info"] = asdict(self.refloat_info)
        if self.refloat_realtime:
            payload["refloat"] = asdict(self.refloat_realtime)
            payload["refloat"]["alerts_active"] = self.refloat_realtime.alerts_active
        return payload

    def to_state_dict(self) -> dict:
        state = {
            "timestamp": self.collected_at.isoformat(),
            "connected": self.connected,
            "can_nodes_csv": ",".join(str(node) for node in self.can_nodes),
        }
        if self.bms:
            state.update(
                {
                    "pack_voltage_v": self.bms.pack_voltage_v,
                    "pack_current_a": self.bms.current_a,
                    "soc_ratio": self.bms.soc_ratio,
                    "soc_percent": round(self.bms.soc_ratio * 100.0, 1),
                    "min_cell_v": self.bms.min_cell_v,
                    "min_cell_index": self.bms.min_cell_index,
                    "max_cell_v": self.bms.max_cell_v,
                    "max_cell_index": self.bms.max_cell_index,
                    "cell_delta_v": self.bms.cell_delta_v,
                    "cell_delta_mv": round((self.bms.cell_delta_v or 0.0) * 1000.0, 1),
                    "cell_19_v": self.bms.cell_voltage(19),
                    "charging": self.bms.charging,
                    "balancing_active": self.bms.balancing_active,
                    "balancing_cell_count": self.bms.balancing_cell_count,
                }
            )
        if self.controller:
            speed_kph = None
            speed_mph = None
            if self.refloat_realtime:
                speed_kph = self.refloat_realtime.values.get("motor.speed")
                speed_mph = speed_kph * 0.621371 if speed_kph is not None else None
            state.update(
                {
                    "controller_temp_c": self.controller.temp_fet_c,
                    "motor_temp_c": self.controller.temp_motor_c,
                    "controller_voltage_v": self.controller.vin_v,
                    "duty_cycle_ratio": self.controller.duty_cycle_ratio,
                    "duty_cycle_pct": round(self.controller.duty_cycle_ratio * 100.0, 2),
                    "speed_kph": speed_kph,
                    "speed_mph": round(speed_mph, 3) if speed_mph is not None else None,
                    "controller_fault_code": self.controller.fault_code,
                }
            )
        if self.refloat_realtime:
            state.update(
                {
                    "refloat_charging": self.refloat_realtime.charging,
                    "wheelslip": self.refloat_realtime.wheelslip,
                    "alerts_active": self.refloat_realtime.alerts_active,
                    "ready": self.refloat_realtime.package_state in {"READY", "RUNNING"},
                    "running": self.refloat_realtime.package_state == "RUNNING",
                    "package_state": self.refloat_realtime.package_state,
                    "package_mode": self.refloat_realtime.package_mode,
                    "stop_condition": self.refloat_realtime.stop_condition,
                    "sat": self.refloat_realtime.sat,
                    "alert_reason": self.refloat_realtime.alert_reason,
                    "footpad_state": self.refloat_realtime.footpad_state,
                    "firmware_fault_code": self.refloat_realtime.firmware_fault_code,
                }
            )
            if "balance_current" in self.refloat_realtime.runtime_values:
                state["balance_current_a"] = self.refloat_realtime.runtime_values["balance_current"]
        return state
