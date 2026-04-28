# onewheel-ha-bridge

VESC TCP endpoint to Home Assistant bridge via MQTT discovery. Telemetry is read-only by default; optional BMS / Refloat LED controls are guarded and opt-in.

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
- `COMM_FORWARD_CAN + COMM_CUSTOM_APP_DATA` for Refloat `INFO`, `REALTIME_DATA_IDS`, `REALTIME_DATA`, and supported `LIGHTS_CONTROL` state queries only when the separate Refloat LED gate is enabled

It does **not** send duty/current/rpm/servo/config/update commands.

Optional BMS controls can be enabled explicitly with `[controls].enabled = true`. Those controls are limited to:
- `COMM_FORWARD_CAN + COMM_BMS_SET_CHARGE_ALLOWED` with payload `1` to allow charging
- `COMM_FORWARD_CAN + COMM_BMS_FORCE_BALANCE` with payload `1` to force balancing

The verified ENNOID command handler does not implement safe false/disable semantics for charging or balancing in the same path, so the bridge rejects `disable_charging` and `disable_balancing` rather than guessing. Optional Refloat LED on/off controls require a second opt-in, are version/capability gated, and use only the documented stable Refloat `LIGHTS_CONTROL = 20` command; the older unstable `202` command map is intentionally not sent. The bridge also rejects control requests unless telemetry says the board is connected and not running, and the command topic is ignored entirely while controls are disabled.

## what shows up in Home Assistant

The bridge auto-discovers a single device with entities including:
- State of Charge
- Pack Voltage / Pack Current / BMS SOH, totals, status, temps, humidity, and per-cell voltages
- Min Cell / Max Cell / Cell Delta / Cell 19
- Controller Voltage / Motor + input currents / ERPM / MOS temps / duty / controller counters
- Controller Temp / Motor Temp
- Speed (mph + km/h)
- Charging / Wheelslip / Darkride / Alerts Active / Ready / Running
- Package State / Package Mode / Stop Condition / Setpoint Adjustment / Alert Reason / Footpad State
- Refloat IMU/setpoint/current diagnostics, LED/headlight state, capabilities, and package identity
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
cd onewheel-ha-bridge
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
cd onewheel-ha-bridge
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

To additionally expose Refloat LED on/off buttons, explicitly enable the second gate:

```toml
[controls]
enabled = true
refloat_led_controls_enabled = true
require_safe_state = true
max_control_speed_mph = 0.5
command_cooldown_seconds = 1.0
```

Home Assistant buttons publish one of these payloads to `onewheel/custom_xr/command`:
- `allow_charging` — verified implemented by ENNOID
- `allow_balancing` — verified implemented by ENNOID as force-balance/all-time balancing
- `refloat_leds_on` — optional second opt-in; supported Refloat 1.2+ stable lights command only
- `refloat_leds_off` — optional second opt-in; supported Refloat 1.2+ stable lights command only
- `disable_charging` — rejected; ENNOID's verified command path does not safely disable charging
- `disable_balancing` — rejected; ENNOID's verified command path does not safely disable balancing

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
- `OWHB_CONTROLS_REFLOAT_LEDS`
- `OWHB_CONTROLS_COMMAND_TOPIC`
- `OWHB_CONTROLS_STATUS_TOPIC`
- `OWHB_CONTROLS_REQUIRE_SAFE_STATE`
- `OWHB_CONTROLS_MAX_SPEED_MPH`
- `OWHB_CONTROLS_COOLDOWN`

## Home Assistant notes

- discovery payloads are retained so HA can rediscover the device after restarts.
- state and raw JSON are retained too, so the dashboard can repopulate quickly.
- availability is driven by telemetry reachability: successful polls publish `online`; failed cycles publish `offline`.

## target assumptions

The defaults are intentionally generic. Copy `config.example.toml` to `config.toml` and set the values for your board:
- VESC TCP bridge host/port
- Thor/controller CAN ID
- BMS CAN ID
- MQTT broker host/credentials

`config.toml` is gitignored so local deployment details do not get committed.

## development

Run tests with:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## caveats

- Refloat runtime-only values are only populated while the package is actually `RUNNING`.
- Refloat LED state queries and buttons are enabled only when controls are enabled, `refloat_led_controls_enabled = true`, and Refloat package info reports a supported stable lights protocol.
- If the TCP bridge is flaky and resets connections, the client retries each query before marking the poll failed.
- The bridge currently treats Refloat `motor.speed` as km/h and also publishes mph.
