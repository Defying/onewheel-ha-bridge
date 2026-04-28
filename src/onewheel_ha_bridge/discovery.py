from __future__ import annotations

from dataclasses import dataclass

from .config import ControlsConfig, HomeAssistantConfig
from .models import TelemetrySnapshot
from .protocol import refloat_lights_control_supported


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
    requires_refloat_lights: bool = False


BUTTON_DEFINITIONS: tuple[ButtonDefinition, ...] = (
    ButtonDefinition("allow_charging", "Allow Charging", "allow_charging", "mdi:battery-plus"),
    ButtonDefinition("allow_balancing", "Force Balancing", "allow_balancing", "mdi:battery-sync"),
    ButtonDefinition("refloat_leds_on_button", "Refloat LEDs On", "refloat_leds_on", "mdi:led-strip-variant", True),
    ButtonDefinition("refloat_leds_off_button", "Refloat LEDs Off", "refloat_leds_off", "mdi:led-strip-variant-off", True),
)


CELL_VOLTAGE_DEFINITIONS: tuple[EntityDefinition, ...] = tuple(
    EntityDefinition(
        "sensor",
        f"cell_{index}_v",
        f"Cell {index}",
        f"{{{{ value_json.cell_{index}_v }}}}",
        "V",
        "voltage",
        "measurement",
        suggested_display_precision=3,
    )
    for index in range(1, 33)
)

BMS_TEMP_DEFINITIONS: tuple[EntityDefinition, ...] = tuple(
    EntityDefinition(
        "sensor",
        f"bms_temp_{index}_c",
        f"BMS Temp {index}",
        f"{{{{ value_json.bms_temp_{index}_c }}}}",
        "°C",
        "temperature",
        "measurement",
        suggested_display_precision=1,
    )
    for index in range(1, 9)
)

CONTROLLER_MOS_TEMP_DEFINITIONS: tuple[EntityDefinition, ...] = tuple(
    EntityDefinition(
        "sensor",
        f"controller_mos_temp_{index}_c",
        f"Controller MOS Temp {index}",
        f"{{{{ value_json.controller_mos_temp_{index}_c }}}}",
        "°C",
        "temperature",
        "measurement",
        suggested_display_precision=1,
    )
    for index in range(1, 4)
)


ENTITY_DEFINITIONS: tuple[EntityDefinition, ...] = (
    EntityDefinition("sensor", "soc_percent", "State of Charge", "{{ value_json.soc_percent }}", "%", "battery", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "soh_percent", "State of Health", "{{ value_json.soh_percent }}", "%", None, "measurement", icon="mdi:battery-heart", suggested_display_precision=1),
    EntityDefinition("sensor", "pack_voltage_v", "Pack Voltage", "{{ value_json.pack_voltage_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "charge_voltage_v", "Charge Voltage", "{{ value_json.charge_voltage_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "pack_current_a", "Pack Current", "{{ value_json.pack_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "bms_current_ic_a", "BMS IC Current", "{{ value_json.bms_current_ic_a }}", "A", "current", "measurement", icon="mdi:current-dc", suggested_display_precision=3),
    EntityDefinition("sensor", "bms_amp_hours", "BMS Amp Hours", "{{ value_json.bms_amp_hours }}", "Ah", None, "total_increasing", icon="mdi:battery-clock", suggested_display_precision=3),
    EntityDefinition("sensor", "bms_watt_hours", "BMS Watt Hours", "{{ value_json.bms_watt_hours }}", "Wh", "energy", "total_increasing", suggested_display_precision=2),
    EntityDefinition("sensor", "bms_cell_count", "BMS Cell Count", "{{ value_json.bms_cell_count }}", icon="mdi:battery-unknown", entity_category="diagnostic"),
    EntityDefinition("sensor", "min_cell_v", "Min Cell", "{{ value_json.min_cell_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "min_cell_index", "Min Cell Index", "{{ value_json.min_cell_index }}", icon="mdi:format-list-numbered", entity_category="diagnostic"),
    EntityDefinition("sensor", "max_cell_v", "Max Cell", "{{ value_json.max_cell_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "max_cell_index", "Max Cell Index", "{{ value_json.max_cell_index }}", icon="mdi:format-list-numbered", entity_category="diagnostic"),
    EntityDefinition("sensor", "cell_delta_mv", "Cell Delta", "{{ value_json.cell_delta_mv }}", "mV", None, "measurement", icon="mdi:battery-sync", suggested_display_precision=1),
) + CELL_VOLTAGE_DEFINITIONS + (
    EntityDefinition("binary_sensor", "charging", "Charging", "{{ 'ON' if value_json.charging else 'OFF' }}", device_class="battery_charging", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "balancing_active", "Balancing Active", "{{ 'ON' if value_json.balancing_active else 'OFF' }}", icon="mdi:battery-sync", payload_on="ON", payload_off="OFF"),
    EntityDefinition("sensor", "balancing_cell_count", "Balancing Cell Count", "{{ value_json.balancing_cell_count }}", icon="mdi:battery-sync", state_class="measurement"),
    EntityDefinition("sensor", "bms_temp_count", "BMS Temp Count", "{{ value_json.bms_temp_count }}", icon="mdi:thermometer-lines", entity_category="diagnostic"),
) + BMS_TEMP_DEFINITIONS + (
    EntityDefinition("sensor", "bms_temp_ic_c", "BMS IC Temp", "{{ value_json.bms_temp_ic_c }}", "°C", "temperature", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "bms_temp_humidity_c", "BMS Humidity Sensor Temp", "{{ value_json.bms_temp_humidity_c }}", "°C", "temperature", "measurement", entity_category="diagnostic", suggested_display_precision=1),
    EntityDefinition("sensor", "bms_humidity_pct", "BMS Humidity", "{{ value_json.bms_humidity_pct }}", "%", "humidity", "measurement", entity_category="diagnostic", suggested_display_precision=1),
    EntityDefinition("sensor", "bms_temp_max_cell_c", "BMS Max Cell Temp", "{{ value_json.bms_temp_max_cell_c }}", "°C", "temperature", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "bms_can_id", "BMS CAN ID", "{{ value_json.bms_can_id }}", icon="mdi:identifier", entity_category="diagnostic"),
    EntityDefinition("sensor", "bms_amp_hours_charged_total", "BMS Charged Total", "{{ value_json.bms_amp_hours_charged_total }}", "Ah", None, "total_increasing", icon="mdi:battery-plus", suggested_display_precision=3),
    EntityDefinition("sensor", "bms_watt_hours_charged_total", "BMS Energy Charged Total", "{{ value_json.bms_watt_hours_charged_total }}", "Wh", "energy", "total_increasing", suggested_display_precision=2),
    EntityDefinition("sensor", "bms_amp_hours_discharged_total", "BMS Discharged Total", "{{ value_json.bms_amp_hours_discharged_total }}", "Ah", None, "total_increasing", icon="mdi:battery-minus", suggested_display_precision=3),
    EntityDefinition("sensor", "bms_watt_hours_discharged_total", "BMS Energy Discharged Total", "{{ value_json.bms_watt_hours_discharged_total }}", "Wh", "energy", "total_increasing", suggested_display_precision=2),
    EntityDefinition("sensor", "bms_pressure_pa", "BMS Pressure", "{{ value_json.bms_pressure_pa }}", "Pa", "pressure", "measurement", entity_category="diagnostic", suggested_display_precision=0),
    EntityDefinition("sensor", "bms_data_version", "BMS Data Version", "{{ value_json.bms_data_version }}", icon="mdi:counter", entity_category="diagnostic"),
    EntityDefinition("sensor", "bms_status", "BMS Status", "{{ value_json.bms_status }}", icon="mdi:message-text-outline", entity_category="diagnostic"),
    EntityDefinition("sensor", "controller_temp_c", "Controller Temp", "{{ value_json.controller_temp_c }}", "°C", "temperature", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "motor_temp_c", "Motor Temp", "{{ value_json.motor_temp_c }}", "°C", "temperature", "measurement", suggested_display_precision=1),
) + CONTROLLER_MOS_TEMP_DEFINITIONS + (
    EntityDefinition("sensor", "controller_voltage_v", "Controller Voltage", "{{ value_json.controller_voltage_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_avg_motor_current_a", "Controller Motor Current", "{{ value_json.controller_avg_motor_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_avg_input_current_a", "Controller Input Current", "{{ value_json.controller_avg_input_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_avg_id_a", "Controller Id Current", "{{ value_json.controller_avg_id_a }}", "A", "current", "measurement", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_avg_iq_a", "Controller Iq Current", "{{ value_json.controller_avg_iq_a }}", "A", "current", "measurement", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "speed_mph", "Speed", "{{ value_json.speed_mph }}", "mph", "speed", "measurement", suggested_display_precision=2),
    EntityDefinition("sensor", "speed_kph", "Speed (km/h)", "{{ value_json.speed_kph }}", "km/h", "speed", "measurement", suggested_display_precision=2),
    EntityDefinition("sensor", "motor_erpm", "Motor ERPM", "{{ value_json.motor_erpm }}", icon="mdi:speedometer", state_class="measurement", suggested_display_precision=0),
    EntityDefinition("sensor", "controller_rpm", "Controller RPM", "{{ value_json.controller_rpm }}", icon="mdi:rotate-3d-variant", state_class="measurement", suggested_display_precision=0),
    EntityDefinition("sensor", "duty_cycle_pct", "Duty Cycle", "{{ value_json.duty_cycle_pct }}", "%", None, "measurement", icon="mdi:sine-wave", suggested_display_precision=2),
    EntityDefinition("sensor", "controller_amp_hours", "Controller Amp Hours", "{{ value_json.controller_amp_hours }}", "Ah", None, "total_increasing", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_amp_hours_charged", "Controller Amp Hours Charged", "{{ value_json.controller_amp_hours_charged }}", "Ah", None, "total_increasing", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_watt_hours", "Controller Watt Hours", "{{ value_json.controller_watt_hours }}", "Wh", "energy", "total_increasing", entity_category="diagnostic", suggested_display_precision=2),
    EntityDefinition("sensor", "controller_watt_hours_charged", "Controller Watt Hours Charged", "{{ value_json.controller_watt_hours_charged }}", "Wh", "energy", "total_increasing", entity_category="diagnostic", suggested_display_precision=2),
    EntityDefinition("sensor", "controller_tachometer", "Controller Tachometer", "{{ value_json.controller_tachometer }}", icon="mdi:counter", entity_category="diagnostic"),
    EntityDefinition("sensor", "controller_tachometer_abs", "Controller Tachometer Abs", "{{ value_json.controller_tachometer_abs }}", icon="mdi:counter", entity_category="diagnostic"),
    EntityDefinition("sensor", "controller_pid_pos", "Controller PID Position", "{{ value_json.controller_pid_pos }}", icon="mdi:axis-arrow", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_id", "Controller ID", "{{ value_json.controller_id }}", icon="mdi:identifier", entity_category="diagnostic"),
    EntityDefinition("sensor", "controller_vd", "Controller Vd", "{{ value_json.controller_vd }}", "V", "voltage", "measurement", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_vq", "Controller Vq", "{{ value_json.controller_vq }}", "V", "voltage", "measurement", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "controller_status_raw", "Controller Status Raw", "{{ value_json.controller_status_raw }}", icon="mdi:counter", entity_category="diagnostic"),
    EntityDefinition("binary_sensor", "refloat_charging", "Refloat Charging Flag", "{{ 'ON' if value_json.refloat_charging else 'OFF' }}", icon="mdi:battery-clock", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "darkride", "Darkride", "{{ 'ON' if value_json.darkride else 'OFF' }}", icon="mdi:weather-night", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
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
    EntityDefinition("sensor", "footpad_adc1", "Footpad ADC 1", "{{ value_json.footpad_adc1 }}", icon="mdi:shoe-print", entity_category="diagnostic", suggested_display_precision=4),
    EntityDefinition("sensor", "footpad_adc2", "Footpad ADC 2", "{{ value_json.footpad_adc2 }}", icon="mdi:shoe-print", entity_category="diagnostic", suggested_display_precision=4),
    EntityDefinition("sensor", "remote_input", "Remote Input", "{{ value_json.remote_input }}", icon="mdi:remote", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "imu_pitch_deg", "IMU Pitch", "{{ value_json.imu_pitch_deg }}", "°", None, "measurement", icon="mdi:axis-z-rotate-clockwise", suggested_display_precision=2),
    EntityDefinition("sensor", "imu_balance_pitch_deg", "IMU Balance Pitch", "{{ value_json.imu_balance_pitch_deg }}", "°", None, "measurement", icon="mdi:axis-z-rotate-clockwise", suggested_display_precision=2),
    EntityDefinition("sensor", "imu_roll_deg", "IMU Roll", "{{ value_json.imu_roll_deg }}", "°", None, "measurement", icon="mdi:axis-x-rotate-clockwise", suggested_display_precision=2),
    EntityDefinition("sensor", "refloat_motor_current_a", "Refloat Motor Current", "{{ value_json.refloat_motor_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "refloat_motor_directional_current_a", "Refloat Directional Current", "{{ value_json.refloat_motor_directional_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "refloat_motor_filtered_current_a", "Refloat Filtered Current", "{{ value_json.refloat_motor_filtered_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "refloat_battery_voltage_v", "Refloat Battery Voltage", "{{ value_json.refloat_battery_voltage_v }}", "V", "voltage", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "refloat_battery_current_a", "Refloat Battery Current", "{{ value_json.refloat_battery_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "refloat_mosfet_temp_c", "Refloat MOSFET Temp", "{{ value_json.refloat_mosfet_temp_c }}", "°C", "temperature", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "refloat_motor_temp_c", "Refloat Motor Temp", "{{ value_json.refloat_motor_temp_c }}", "°C", "temperature", "measurement", suggested_display_precision=1),
    EntityDefinition("sensor", "setpoint_deg", "Setpoint", "{{ value_json.setpoint_deg }}", "°", None, "measurement", icon="mdi:angle-acute", suggested_display_precision=2),
    EntityDefinition("sensor", "atr_setpoint_deg", "ATR Setpoint", "{{ value_json.atr_setpoint_deg }}", "°", None, "measurement", icon="mdi:angle-acute", suggested_display_precision=2),
    EntityDefinition("sensor", "brake_tilt_setpoint_deg", "Brake Tilt Setpoint", "{{ value_json.brake_tilt_setpoint_deg }}", "°", None, "measurement", icon="mdi:angle-acute", suggested_display_precision=2),
    EntityDefinition("sensor", "torque_tilt_setpoint_deg", "Torque Tilt Setpoint", "{{ value_json.torque_tilt_setpoint_deg }}", "°", None, "measurement", icon="mdi:angle-acute", suggested_display_precision=2),
    EntityDefinition("sensor", "turn_tilt_setpoint_deg", "Turn Tilt Setpoint", "{{ value_json.turn_tilt_setpoint_deg }}", "°", None, "measurement", icon="mdi:angle-acute", suggested_display_precision=2),
    EntityDefinition("sensor", "remote_setpoint_deg", "Remote Setpoint", "{{ value_json.remote_setpoint_deg }}", "°", None, "measurement", icon="mdi:angle-acute", entity_category="diagnostic", suggested_display_precision=2),
    EntityDefinition("sensor", "balance_current_a", "Balance Current", "{{ value_json.balance_current_a }}", "A", "current", "measurement", suggested_display_precision=3),
    EntityDefinition("sensor", "atr_accel_diff", "ATR Accel Diff", "{{ value_json.atr_accel_diff }}", icon="mdi:axis-arrow", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "atr_speed_boost", "ATR Speed Boost", "{{ value_json.atr_speed_boost }}", icon="mdi:speedometer", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "booster_current_a", "Booster Current", "{{ value_json.booster_current_a }}", "A", "current", "measurement", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "refloat_charging_current_a", "Refloat Charging Current", "{{ value_json.refloat_charging_current_a }}", "A", "current", "measurement", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("sensor", "refloat_charging_voltage_v", "Refloat Charging Voltage", "{{ value_json.refloat_charging_voltage_v }}", "V", "voltage", "measurement", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("binary_sensor", "refloat_data_recording", "Refloat Data Recording", "{{ 'ON' if value_json.refloat_data_recording else 'OFF' }}", icon="mdi:record-rec", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "refloat_data_record_autostart", "Refloat Data Record Autostart", "{{ 'ON' if value_json.refloat_data_record_autostart else 'OFF' }}", icon="mdi:record-rec", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "refloat_data_record_autostop", "Refloat Data Record Autostop", "{{ 'ON' if value_json.refloat_data_record_autostop else 'OFF' }}", icon="mdi:record-rec", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("sensor", "active_alert_mask_low", "Active Alert Mask Low", "{{ value_json.active_alert_mask_low }}", icon="mdi:alert", entity_category="diagnostic"),
    EntityDefinition("sensor", "active_alert_mask_high", "Active Alert Mask High", "{{ value_json.active_alert_mask_high }}", icon="mdi:alert", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_mask", "Refloat Realtime Mask", "{{ value_json.refloat_mask }}", icon="mdi:counter", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_realtime_extra_flags", "Refloat Realtime Extra Flags", "{{ value_json.refloat_realtime_extra_flags }}", icon="mdi:flag", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_time_seconds", "Refloat Time", "{{ value_json.refloat_time_seconds }}", "s", "duration", "measurement", entity_category="diagnostic", suggested_display_precision=3),
    EntityDefinition("binary_sensor", "refloat_leds_on", "Refloat LEDs On", "{{ 'ON' if value_json.refloat_leds_on else 'OFF' }}", icon="mdi:led-strip-variant", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "refloat_headlights_on", "Refloat Headlights On", "{{ 'ON' if value_json.refloat_headlights_on else 'OFF' }}", icon="mdi:car-light-high", payload_on="ON", payload_off="OFF"),
    EntityDefinition("sensor", "refloat_lights_flags", "Refloat Lights Flags", "{{ value_json.refloat_lights_flags }}", icon="mdi:flag", entity_category="diagnostic"),
    EntityDefinition("binary_sensor", "connected", "Telemetry Connected", "{{ 'ON' if value_json.connected else 'OFF' }}", device_class="connectivity", payload_on="ON", payload_off="OFF"),
    EntityDefinition("sensor", "can_nodes_csv", "CAN Nodes", "{{ value_json.can_nodes_csv }}", icon="mdi:lan", entity_category="diagnostic"),
    EntityDefinition("sensor", "vesc_firmware_version", "VESC Firmware Version", "{{ value_json.vesc_firmware_version }}", icon="mdi:chip", entity_category="diagnostic"),
    EntityDefinition("sensor", "vesc_hardware_name", "VESC Hardware", "{{ value_json.vesc_hardware_name }}", icon="mdi:chip", entity_category="diagnostic"),
    EntityDefinition("sensor", "vesc_firmware_name", "VESC Firmware Name", "{{ value_json.vesc_firmware_name }}", icon="mdi:chip", entity_category="diagnostic"),
    EntityDefinition("sensor", "vesc_hardware_type", "VESC Hardware Type", "{{ value_json.vesc_hardware_type }}", icon="mdi:chip", entity_category="diagnostic"),
    EntityDefinition("sensor", "vesc_test_version", "VESC Test Version", "{{ value_json.vesc_test_version }}", icon="mdi:counter", entity_category="diagnostic"),
    EntityDefinition("sensor", "vesc_custom_config_count", "VESC Custom Config Count", "{{ value_json.vesc_custom_config_count }}", icon="mdi:counter", entity_category="diagnostic"),
    EntityDefinition("binary_sensor", "vesc_pairing_done", "VESC Pairing Done", "{{ 'ON' if value_json.vesc_pairing_done else 'OFF' }}", icon="mdi:bluetooth-connect", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "vesc_phase_filters", "VESC Phase Filters", "{{ 'ON' if value_json.vesc_phase_filters else 'OFF' }}", icon="mdi:filter", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("sensor", "vesc_hw_crc", "VESC HW CRC", "{{ value_json.vesc_hw_crc }}", icon="mdi:fingerprint", entity_category="diagnostic"),
    EntityDefinition("sensor", "firmware_fault_code", "Firmware Fault Code", "{{ value_json.firmware_fault_code }}", icon="mdi:chip", entity_category="diagnostic"),
    EntityDefinition("sensor", "controller_fault_code", "Controller Fault Code", "{{ value_json.controller_fault_code }}", icon="mdi:chip", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_package_name", "Refloat Package", "{{ value_json.refloat_package_name }}", icon="mdi:package-variant", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_package_version", "Refloat Version", "{{ value_json.refloat_package_version }}", icon="mdi:package-variant", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_git_hash", "Refloat Git Hash", "{{ value_json.refloat_git_hash }}", icon="mdi:source-commit", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_command_version", "Refloat Command Version", "{{ value_json.refloat_command_version }}", icon="mdi:counter", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_tick_rate_hz", "Refloat Tick Rate", "{{ value_json.refloat_tick_rate_hz }}", "Hz", "frequency", "measurement", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_capabilities", "Refloat Capabilities", "{{ value_json.refloat_capabilities }}", icon="mdi:puzzle", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_extra_flags", "Refloat Info Extra Flags", "{{ value_json.refloat_extra_flags }}", icon="mdi:flag", entity_category="diagnostic"),
    EntityDefinition("sensor", "refloat_time_ticks", "Refloat Time Ticks", "{{ value_json.refloat_time_ticks }}", icon="mdi:timer-outline", entity_category="diagnostic"),
    EntityDefinition("binary_sensor", "refloat_leds_capable", "Refloat LEDs Capable", "{{ 'ON' if value_json.refloat_leds_capable else 'OFF' }}", icon="mdi:led-strip-variant", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "refloat_external_leds_capable", "Refloat External LEDs Capable", "{{ 'ON' if value_json.refloat_external_leds_capable else 'OFF' }}", icon="mdi:led-strip", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
    EntityDefinition("binary_sensor", "refloat_data_recording_capable", "Refloat Data Recording Capable", "{{ 'ON' if value_json.refloat_data_recording_capable else 'OFF' }}", icon="mdi:record-rec", entity_category="diagnostic", payload_on="ON", payload_off="OFF"),
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


def _include_button(button: ButtonDefinition, controls_config: ControlsConfig, snapshot: TelemetrySnapshot | None) -> bool:
    if not button.requires_refloat_lights:
        return True
    return controls_config.refloat_led_controls_enabled and refloat_lights_control_supported(
        snapshot.refloat_info if snapshot else None
    )


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
            if not _include_button(button, controls_config, snapshot):
                continue
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
