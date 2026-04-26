from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class VescConfig:
    host: str = "10.0.0.191"
    port: int = 65102
    thor_can_id: int = 3
    bms_can_id: int = 4
    timeout_seconds: float = 3.0
    poll_interval_seconds: float = 2.0
    static_refresh_every_polls: int = 30


@dataclass(slots=True)
class MqttConfig:
    host: str = "homeassistant.local"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str = "onewheel-ha-bridge"
    keepalive_seconds: int = 30


@dataclass(slots=True)
class HomeAssistantConfig:
    discovery_prefix: str = "homeassistant"
    base_topic: str = "onewheel/custom_xr"
    device_name: str = "Custom Onewheel"
    device_id: str = "custom_onewheel"
    manufacturer: str = "Custom / VESC"
    model: str = "Thor400v2 + ENNOID XLITE 32 V4"
    controller_name: str = "Thor400v2"
    bms_name: str = "ENNOID-XLITE-32-V4"


@dataclass(slots=True)
class ControlsConfig:
    # Battery control writes are disabled unless explicitly enabled. When
    # enabled, Home Assistant MQTT button entities can request only the guarded
    # BMS actions implemented in bridge.py.
    enabled: bool = False
    command_topic: str | None = None
    status_topic: str | None = None
    require_safe_state: bool = True
    max_control_speed_mph: float = 0.5
    command_cooldown_seconds: float = 1.0


@dataclass(slots=True)
class BridgeConfig:
    vesc: VescConfig
    mqtt: MqttConfig
    home_assistant: HomeAssistantConfig
    controls: ControlsConfig


_ENV_MAP: dict[tuple[str, str], tuple[str, object]] = {
    ("vesc", "host"): ("OWHB_VESC_HOST", str),
    ("vesc", "port"): ("OWHB_VESC_PORT", int),
    ("vesc", "thor_can_id"): ("OWHB_THOR_CAN_ID", int),
    ("vesc", "bms_can_id"): ("OWHB_BMS_CAN_ID", int),
    ("vesc", "timeout_seconds"): ("OWHB_VESC_TIMEOUT", float),
    ("vesc", "poll_interval_seconds"): ("OWHB_POLL_INTERVAL", float),
    ("vesc", "static_refresh_every_polls"): ("OWHB_STATIC_REFRESH_POLLS", int),
    ("mqtt", "host"): ("OWHB_MQTT_HOST", str),
    ("mqtt", "port"): ("OWHB_MQTT_PORT", int),
    ("mqtt", "username"): ("OWHB_MQTT_USERNAME", str),
    ("mqtt", "password"): ("OWHB_MQTT_PASSWORD", str),
    ("mqtt", "client_id"): ("OWHB_MQTT_CLIENT_ID", str),
    ("mqtt", "keepalive_seconds"): ("OWHB_MQTT_KEEPALIVE", int),
    ("home_assistant", "discovery_prefix"): ("OWHB_HA_DISCOVERY_PREFIX", str),
    ("home_assistant", "base_topic"): ("OWHB_HA_BASE_TOPIC", str),
    ("home_assistant", "device_name"): ("OWHB_DEVICE_NAME", str),
    ("home_assistant", "device_id"): ("OWHB_DEVICE_ID", str),
    ("home_assistant", "manufacturer"): ("OWHB_DEVICE_MANUFACTURER", str),
    ("home_assistant", "model"): ("OWHB_DEVICE_MODEL", str),
    ("home_assistant", "controller_name"): ("OWHB_CONTROLLER_NAME", str),
    ("home_assistant", "bms_name"): ("OWHB_BMS_NAME", str),
    ("controls", "enabled"): ("OWHB_CONTROLS_ENABLED", _bool),
    ("controls", "command_topic"): ("OWHB_CONTROLS_COMMAND_TOPIC", str),
    ("controls", "status_topic"): ("OWHB_CONTROLS_STATUS_TOPIC", str),
    ("controls", "require_safe_state"): ("OWHB_CONTROLS_REQUIRE_SAFE_STATE", _bool),
    ("controls", "max_control_speed_mph"): ("OWHB_CONTROLS_MAX_SPEED_MPH", float),
    ("controls", "command_cooldown_seconds"): ("OWHB_CONTROLS_COOLDOWN", float),
}


def _deep_merge(base: dict, incoming: dict) -> dict:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_file(path: Path | None) -> dict:
    if not path:
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _apply_env(data: dict) -> dict:
    for (section, key), (env_name, caster) in _ENV_MAP.items():
        raw = os.getenv(env_name)
        if raw is None:
            continue
        data.setdefault(section, {})[key] = caster(raw)
    return data


def load_config(path: str | Path | None = None) -> BridgeConfig:
    config_path = Path(path) if path else None
    env_path = os.getenv("OWHB_CONFIG")
    if env_path:
        config_path = Path(env_path)

    data: dict = {}
    if config_path:
        data = _deep_merge(data, _load_file(config_path))
    data = _apply_env(data)

    vesc = VescConfig(**data.get("vesc", {}))
    mqtt = MqttConfig(**data.get("mqtt", {}))
    home_assistant = HomeAssistantConfig(**data.get("home_assistant", {}))
    controls = ControlsConfig(**data.get("controls", {}))
    return BridgeConfig(vesc=vesc, mqtt=mqtt, home_assistant=home_assistant, controls=controls)
