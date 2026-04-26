from __future__ import annotations

from dataclasses import dataclass

from .config import ControlsConfig, HomeAssistantConfig
from .models import TelemetrySnapshot


@dataclass(frozen=True, slots=True)
class EntityDefinition:
    component: str
    key: str
    name: str
    value_template: str
    unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    entity_category: str | None = None
    payload_on: str | None = None
    payload_off: str | None = None
    suggested_display_precision: int | None = None


@dataclass(frozen=True, slots=True)
class ButtonDefinition:
    key: str
    name: str
    action: str
    icon: str


BUTTON_DEFINITIONS: tuple[ButtonDefinition, ...] = (
    ButtonDefinition("allow_charging", "Allow Charging", "allow_charging", "mdi:battery-plus"),
    ButtonDefinition("allow_balancing", "Force Balancing", "allow_balancing", "mdi:battery-sync"),
)


ENTITY_DEFINITIONS: tuple[EntityDefinition, ...] = (
    EntityDefinition("sensor", "soc_percent", "State of Charge", "{{ value_json.soc_percent }}", "%", "battery", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "pack_voltage_v", "Pack Voltage", "{{ value_json.pack_voltage_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "pack_current_a", "Pack Current", "{{ value_json.pack_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "min_cell_v", "Min Cell", "{{ value_json.min_cell_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "max_cell_v", "Max Cell", "{{ value_json.max_cell_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "cell_delta_mv", "Cell Delta", "{{ value_json.cell_delta_mv }}", "mV", None, "measurement", icon="mdi:battery-sync", suggested_display_precision=1),
    EntityDefinition("sensor", "cell_19_v", "Cell 19", "{{ value_json.cell_19_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_temp_c", "Controller Temp", "{{ value_json.controller_temp_c }}", "°C", "temperature", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "motor_temp_c", "Motor Temp", "{{ value_json.motor_temp_c }}", "°C", "temperature", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "speed_mph", "Speed", "{{ value_json.speed_mph }}", "mph", "speed", "measurement", suggested_display_precision=2),
    EntityDefinition("sensor", "speed_kph", "Speed (km/h)", "{{ value_json.speed_kph }}", "km/h", "speed", "measurement", suggested_display_precision=2),
    EntityDefinition("sensor", "duty_cycle_pct", "Duty Cycle", "{{ value_json.duty_cycle_pct }}", "%", None, "measurement", icon="mdi:sine-wave", suggested_display_precision=2),
    EntityDefinition("binary_sensor", "charging", "Charging", "{{ 'ON' if value_json.charging else 'OFF' }}", device_class="battery_charging", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "balancing_active", "Balancing Active", "{{ 'ON' if value_json.balancing_active else 'OFF' }}", icon="mdi:battery-sync", payload_on="ON", payload_off="OFF"),
    EntityDefinition("sensor", "balancing_cell_count", "Balancing Cell Count", "{{ value_json.balancing_cell_count }}", icon="mdi:battery-sync", state_class="measurement"),
    EntityDefinition("binary_sensor", "refloat_charging", "Refloat Charging Flag", "{{ 'ON' if value_json.refloat_charging else 'OFF' }}", icon="mdi:battery-clock", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "wheelslip", "Wheelslip", "{{ 'ON' if value_json.wheelslip else 'OFF' }}", icon="mdi:car-traction-control", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "alerts_active", "Alerts Active", "{{ 'ON' if value_json.alerts_active else 'OFF' }}", device_class="problem", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "ready", "Ready", "{{ 'ON' if value_json.ready else 'OFF' }}", payload_on="ON", payload_off="OFF", icon="mdi:check-circle-outline"),
    EntityDefinition("binary_sensor", "running", "Running", "{{ 'ON' if value_json.running else 'OFF' }}", payload_on="ON", payload_off="OFF", icon="mdi:motion-play-outline"),
    EntityDefinition("sensor", "package_state", "Package State", "{{ value_json.package_state }}", icon="mdi:state-machine"),
    EntityDefinition("sensor", "package_mode", "Package Mode", "{{ value_json.package_mode }}", icon="mdi:cog-play-outline"),
    EntityDefinition("sensor", "stop_condition", "Stop Condition", "{{ value_json.stop_condition }}", icon="mdi:hand-back-right-off"),
    EntityDefinition("sensor", "sat", "Setpoint Adjustment", "{{ value_json.sat }}", icon="mdi:arrow-up-down-bold-outline"),
    EntityDefinition("sensor", "alert_reason", "Alert Reason", "{{ value_json.alert_reason }}", icon="mdi:alert-circle-outline"),
    EntityDefinition("sensor", "footpad_state", "Footpad State", "{{ value_json.footpad_state }}", icon="mdi:shoe-print"),
    EntityDefinition("sensor", "can_nodes_csv", "CAN Nodes", "{{ value_json.can_nodes_csv }}", icon="mdi:lan", entity_category="diagnostic"),
    EntityDefinition("sensor", "firmware_fault_code", "Firmware Fault Code", "{{ value_json.firmware_fault_code }}", icon="mdi:chip", entity_category="diagnostic"),
    EntityDefinition("sensor", "controller_fault_code", "Controller Fault Code", "{{ value_json.controller_fault_code }}", icon="mdi:chip", entity_category="diagnostic"),
)


def state_topic(config: HomeAssistantConfig) -> str:
    return f"{config.base_topic}/state"


def raw_topic(config: HomeAssistantConfig) -> str:
    return f"{config.base_topic}/raw"


def availability_topic(config: HomeAssistantConfig) -> str:
    return f"{config.base_topic}/availability"


def command_topic(ha_config: HomeAssistantConfig, controls_config: ControlsConfig | None = None) -> str:
    if controls_config and controls_config.command_topic:
        return controls_config.command_topic
    return f"{ha_config.base_topic}/command"


def command_status_topic(ha_config: HomeAssistantConfig, controls_config: ControlsConfig | None = None) -> str:
    if controls_config and controls_config.status_topic:
        return controls_config.status_topic
    return f"{ha_config.base_topic}/command_status"


def discovery_topic(config: HomeAssistantConfig, entity: EntityDefinition) -> str:
    object_id = f"{config.device_id}_{entity.key}"
    return f"{config.discovery_prefix}/{entity.component}/{config.device_id}/{object_id}/config"


def build_device(config: HomeAssistantConfig, snapshot: TelemetrySnapshot | None = None) -> dict:
    device: dict[str, object] = {
        "identifiers": [config.device_id],
        "name": config.device_name,
        "manufacturer": config.manufacturer,
        "model": config.model,
    }
    if snapshot and snapshot.refloat_info:
        version = snapshot.refloat_info.package_version
        if snapshot.firmware:
            version = f"Refloat {version} / VESC {snapshot.firmware.version}"
        device["sw_version"] = version
    elif snapshot and snapshot.firmware:
        device["sw_version"] = f"VESC {snapshot.firmware.version}"
    return device


def build_discovery_payloads(
    config: HomeAssistantConfig,
    snapshot: TelemetrySnapshot | None = None,
    controls_config: ControlsConfig | None = None,
) -> list[tuple[str, dict]]:
    state = state_topic(config)
    availability = availability_topic(config)
    device = build_device(config, snapshot)
    payloads: list[tuple[str, dict]] = []
    for entity in ENTITY_DEFINITIONS:
        unique_id = f"{config.device_id}_{entity.key}"
        payload: dict[str, object] = {
            "name": entity.name,
            "unique_id": unique_id,
            "state_topic": state,
            "availability_topic": availability,
            "payload_available": "online",
            "payload_not_available": "offline",
            "value_template": entity.value_template,
            "device": device,
            "object_id": unique_id,
        }
        if entity.unit_of_measurement:
            payload["unit_of_measurement"] = entity.unit_of_measurement
        if entity.device_class:
            payload["device_class"] = entity.device_class
        if entity.state_class:
            payload["state_class"] = entity.state_class
        if entity.icon:
            payload["icon"] = entity.icon
        if entity.entity_category:
            payload["entity_category"] = entity.entity_category
        if entity.payload_on is not None:
            payload["payload_on"] = entity.payload_on
        if entity.payload_off is not None:
            payload["payload_off"] = entity.payload_off
        if entity.suggested_display_precision is not None:
            payload["suggested_display_precision"] = entity.suggested_display_precision
        payloads.append((discovery_topic(config, entity), payload))

    if controls_config and controls_config.enabled:
        status_entity = EntityDefinition(
            "sensor",
            "command_status",
            "Command Status",
            "{{ value_json.status }}: {{ value_json.message }}",
            icon="mdi:shield-check",
            entity_category="diagnostic",
        )
        payloads.append(
            (
                discovery_topic(config, status_entity),
                {
                    "name": status_entity.name,
                    "unique_id": f"{config.device_id}_{status_entity.key}",
                    "state_topic": command_status_topic(config, controls_config),
                    "availability_topic": availability,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "value_template": status_entity.value_template,
                    "json_attributes_topic": command_status_topic(config, controls_config),
                    "device": device,
                    "object_id": f"{config.device_id}_{status_entity.key}",
                    "icon": status_entity.icon,
                    "entity_category": status_entity.entity_category,
                },
            )
        )
        for button in BUTTON_DEFINITIONS:
            unique_id = f"{config.device_id}_{button.key}"
            payloads.append(
                (
                    f"{config.discovery_prefix}/button/{config.device_id}/{unique_id}/config",
                    {
                        "name": button.name,
                        "unique_id": unique_id,
                        "command_topic": command_topic(config, controls_config),
                        "payload_press": button.action,
                        "availability_topic": availability,
                        "payload_available": "online",
                        "payload_not_available": "offline",
                        "device": device,
                        "object_id": unique_id,
                        "icon": button.icon,
                    },
                )
            )
    return payloads
