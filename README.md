# onewheel-ha-bridge

VESC TCP endpoint to Home Assistant bridge via MQTT discovery. Telemetry is read-only by default; optional BMS controls are guarded and opt-in.

this project polls a custom Onewheel's VESC/Refloat/BMS telemetry and publishes:
- retained Home Assistant MQTT discovery payloads
- a flattened state topic for HA entities
- a nested raw JSON topic for debugging

## design

**read-only by default.**
The bridge uses these proven-safe reads:
- `COMM_FW_VERSION`
- `COMM_PING_CAN`
- `COMM_FORWARD_CAN + COMM_GET_VALUES` for Thor controller telemetry
- `COMM_BMS_GET_VALUES` for ENNOID BMS telemetry
- `COMM_FORWARD_CAN + COMM_CUSTOM_APP_DATA` for Refloat `INFO`, `REALTIME_DATA_IDS`, and `REALTIME_DATA`

It does **not** send duty/current/rpm/servo/config/update commands.

Optional BMS controls can be enabled explicitly with `[controls].enabled = true`. Those controls are limited to:
- `COMM_BMS_SET_CHARGE_ALLOWED` with payload `1` or `0`
- `COMM_BMS_SET_BALANCE_OVERRIDE` for every discovered cell, with override `0` (allow automatic balancing) or `1` (disable balancing)

The bridge rejects control requests unless telemetry says the board is connected and not running, and the command topic is ignored entirely while controls are disabled.

## what shows up in Home Assistant

The bridge auto-discovers a single device with entities including:
- State of Charge
- Pack Voltage / Pack Current
- Min Cell / Max Cell / Cell Delta / Cell 19
- Controller Temp / Motor Temp
- Speed (mph + km/h)
- Duty Cycle
- Charging / Wheelslip / Alerts Active / Ready / Running
- Package State / Package Mode / Stop Condition / Setpoint Adjustment / Alert Reason / Footpad State
- CAN Nodes / Firmware Fault Code / Controller Fault Code

## topics

Using the default config:
- state topic: `onewheel/custom_xr/state`
- raw topic: `onewheel/custom_xr/raw`
- availability topic: `onewheel/custom_xr/availability`
- guarded control command topic: `onewheel/custom_xr/command` (only subscribed when enabled)
- guarded control status topic: `onewheel/custom_xr/command_status` (only published when enabled)

## requirements

- Python 3.11+
- an MQTT broker reachable by both this bridge and Home Assistant
- Home Assistant MQTT integration enabled

The simplest broker for Home Assistant is the official Mosquitto add-on.

## setup

```bash
cd /Volumes/Carve/Projects/onewheel-ha-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml
```

Edit `config.toml`:
- `vesc.host` / `vesc.port`
- MQTT host / port / credentials
- Home Assistant naming/topics if desired

## test a single read-only poll

```bash
source .venv/bin/activate
onewheel-ha-bridge --config config.toml --once --raw
```

That prints one nested telemetry snapshot and exits.

## run the bridge

```bash
source .venv/bin/activate
onewheel-ha-bridge --config config.toml
```

Once it connects and publishes discovery, Home Assistant should auto-create the device.

## optional launchd service (macOS)

A sample plist lives at:

`examples/launchd/com.carve.onewheel-ha-bridge.plist`

Copy it to `~/Library/LaunchAgents/`, adjust paths if needed, then load it with `launchctl`.

## optional Docker / Orange Pi deployment

A small Docker setup lives at:

`examples/docker-compose.yml`

Because the bridge talks directly to a LAN TCP endpoint and an MQTT broker, the example uses `network_mode: host`.

```bash
cd /Volumes/Carve/Projects/onewheel-ha-bridge
cp config.example.toml config.toml
# edit config.toml first
cd examples
docker compose up -d --build
```

If this runs on the Orange Pi next to Mosquitto, set `mqtt.host` to the reachable broker host/IP/container DNS name used by that stack.

## guarded controls

Controls are off by default. To expose Home Assistant MQTT buttons for charging/balancing controls:

```toml
[controls]
enabled = true
require_safe_state = true
max_control_speed_mph = 0.5
command_cooldown_seconds = 1.0
```

Home Assistant buttons publish one of these payloads to `onewheel/custom_xr/command`:
- `allow_charging`
- `disable_charging`
- `allow_balancing`
- `disable_balancing`

The command handler runs on the bridge loop, not directly in the MQTT callback, so writes do not overlap normal telemetry polling. A retained `Command Status` sensor reports queued/ok/rejected outcomes.

## environment variable overrides

You can override common settings without editing the file:
- `OWHB_CONFIG`
- `OWHB_VESC_HOST`
- `OWHB_VESC_PORT`
- `OWHB_THOR_CAN_ID`
- `OWHB_BMS_CAN_ID`
- `OWHB_POLL_INTERVAL`
- `OWHB_MQTT_HOST`
- `OWHB_MQTT_PORT`
- `OWHB_MQTT_USERNAME`
- `OWHB_MQTT_PASSWORD`
- `OWHB_HA_BASE_TOPIC`
- `OWHB_DEVICE_NAME`
- `OWHB_DEVICE_ID`
- `OWHB_CONTROLS_ENABLED`
- `OWHB_CONTROLS_COMMAND_TOPIC`
- `OWHB_CONTROLS_STATUS_TOPIC`
- `OWHB_CONTROLS_REQUIRE_SAFE_STATE`
- `OWHB_CONTROLS_MAX_SPEED_MPH`
- `OWHB_CONTROLS_COOLDOWN`

## Home Assistant notes

- discovery payloads are retained so HA can rediscover the device after restarts.
- state and raw JSON are retained too, so the dashboard can repopulate quickly.
- availability is driven by telemetry reachability: successful polls publish `online`; failed cycles publish `offline`.

## live target assumptions baked into defaults

Defaults match the currently observed setup:
- VESC TCP bridge: `10.0.0.191:65102`
- Thor controller CAN ID: `3`
- ENNOID BMS CAN ID: `4`

If those move, update the config.

## development

Run tests with:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## caveats

- Refloat runtime-only values are only populated while the package is actually `RUNNING`.
- If the TCP bridge is flaky and resets connections, the client retries each query before marking the poll failed.
- The bridge currently treats Refloat `motor.speed` as km/h and also publishes mph.
