# 4HEAT Lite Stove - Home Assistant Integration

> **WARNING: This integration is a Work in Progress and currently in Beta.**
> Use at your own risk. This software is provided "as is", without warranty of any kind. We are not responsible for bricked stoves, thermonuclear war, your house burning down, or you getting fired because the pellet stove kept you so warm you overslept. Please do some research if you have any concerns about features included in this integration before using it! YOU are choosing to use this, and if you point the finger at us for messing up your setup, we will laugh at you.

Home Assistant custom integration for pellet stoves equipped with a **4HEAT Lite** WiFi module. Communicates locally over TCP using the 2WC protocol — no cloud dependency. All features (sensors, controls, schedule) work via direct TCP connection to the module.

<a href="https://www.buymeacoffee.com/pafernanr" target="_blank"><img height="41px" width="167px" src="https://cdn.buymeacoffee.com/buttons/default-blue.png" alt="Buy Me A Coffee"></a> [![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)

## Compatibility

This integration works with the **4HEAT Lite** WiFi module (Tiemme). It does NOT work with the older 4HEAT module that uses the SEL/SEC protocol — for that, see [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat).

How to tell which module you have — connect to port 80 and send a test command:

```bash
# 4HEAT Lite: send a JSON 2WC sensor query
echo -n '["2WC","1","0310"]' | nc -w 3 <MODULE_IP> 80

# Lite response: JSON array with register data
# ["2WR","1","031000000012005a00e6..."]

# Original 4HEAT: send a SEL status query
echo -n 'SEL' | nc -w 3 <MODULE_IP> 80

# Original response: plain text with SEC prefix
# SEC ...
```

- **4HEAT Lite** (this integration): responds with `["2WR","1","..."]` JSON
- **Original 4HEAT**: responds with `SEC` plain text

Tested with a Lasian Eriste air pellet stove. Should work with any stove using a 4HEAT Lite module (Tiemme electronics).

An opt-in **Jolly Mec** profile supports whole-degree temperatures, its combustion
power mapping, direct exhaust/ducted-fan readings and read-only CCG schedules.
Select the profile during setup or in integration options. Existing entries keep
the Lasian behavior. See [Jolly Mec compatibility and validation](docs/JOLLYMEC.md)
for tested behavior and limitations; see also [issue #2](https://github.com/pafernanr/homeassistant-4heatlite/issues/2).

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pafernanr&repository=homeassistant-4heatlite&category=integration)

Or manually add the custom repository:

1. Open HACS in Home Assistant
2. Click the three-dot menu (top right) and select **Custom repositories**
3. Paste `https://github.com/pafernanr/homeassistant-4heatlite` and select **Integration** as category
4. Click **Add**
5. Find "4HEAT Lite Stove" in HACS and click **Download**
6. Restart Home Assistant

HACS will notify you in Home Assistant when a new version is available.

### Manual

1. Download the [latest release](https://github.com/pafernanr/homeassistant-4heatlite/releases/latest)
2. Copy the `custom_components/4heatlite/` directory to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

With manual installation you will not receive update notifications.

## Configuration

1. Go to Settings > Devices & Services > Add Integration
2. Search for "4HEAT Lite Stove"
3. Choose **Direct local connection (no cloud account)** for local TCP control, or **Cloud-assisted setup** if you need proxy modes. The latter asks for your 4HEAT account to retrieve a device key.
4. Select a discovered module or enter its IP address/hostname manually, choose a name and the stove profile. The Device ID is optional for direct local setup; keeping a discovered ID helps track IP changes.
5. Direct local setup uses **Direct** mode. Cloud-assisted setup also offers Cloud Keepalive and Local Only — see [Proxy Modes](docs/PROXY_MODES.md).
6. The integration will verify connectivity before completing setup

Direct local setup does not contact the cloud from Home Assistant. It does not
change the module's own connection to the manufacturer's cloud or the mobile app.

### Device ID

The Device ID is printed on the module's label. You can also find it in the 4HEAT mobile app (device info section).

### Options

After setup, go to the integration's options to change:
- **Proxy Mode**: Direct; entries configured through the cloud also offer Cloud Keepalive and Local Only (see [Proxy Modes](docs/PROXY_MODES.md))
- **Heating Schedules**: YAML editor with multiple named schedules. Set `active: true` on one to send it to the stove. See the [schedule example](#schedule-management) below.

To enable debug logging, use HA's built-in toggle: go to the integration page, click the three-dot menu, and select "Enable debug logging".

### Multiple Stoves

To add multiple stoves, run the "Add Integration" flow once per stove — each gets its own config entry with its own module IP. In Local Only mode, each module needs its own firewall DNAT rule (`src_ip` = that module's IP). See [Proxy Modes](docs/PROXY_MODES.md#multiple-modules).

## Known Limitations

- **Air stoves only** (for now): tested with an air stove. Hydro (water) stoves may expose additional registers (boiler pressure, water temperature) that are not yet mapped.

## Features and Modes

All features work via direct TCP connection to the module. Commands (ON/OFF, temperature, power, schedule) are sent instantly over TCP and take effect immediately. Schedules are delivered via dual path: TCP direct (immediate) + proxy command queue (backup, delivered on next module poll ~60s).

| Feature | Direct (default) | Cloud Keepalive | Local Only |
|---------|-----------------|-----------------|------------|
| [Core sensors](#sensors) (state, temperatures, power, errors) | Yes | Yes | Yes |
| [Additional sensors](#sensors) (airflow, fans, remote temps, counters) | No | Yes | Yes |
| [Write commands](#write-commands) (ON/OFF, target temperature, power level) | Yes | Yes | Yes |
| [Schedule management](#schedule-management) (weekly heating program) | Yes (TCP + queue) | Yes (TCP + queue) | Yes (TCP + queue) |
| 4HEAT mobile app (same WiFi) | Yes | Yes | Yes |
| 4HEAT mobile app (remote/cloud) | Yes | Yes | No |
| Requires DNS/DNAT | No | Yes | Yes |

### Direct Mode (default)

The module communicates with both HA (via TCP direct) and the 4HEAT cloud (via its own WiFi connection). No router configuration needed. The 4HEAT mobile app works normally alongside HA.

### Cloud Keepalive Mode

Module traffic is intercepted and handled locally by HA (requires [DNS override and firewall DNAT rule](docs/PROXY_MODES.md#network-setup-openwrt)). Only `/register` and `/store` keepalives are mirrored to Azure via HTTPS, so the mobile app sees the device as online. Commands are controlled exclusively by HA. Best of both worlds: local command control + mobile app compatibility.

### Local Only Mode

Module traffic is intercepted and handled locally by HA (requires [DNS override and firewall DNAT rule](docs/PROXY_MODES.md#network-setup-openwrt)). Nothing is sent to Azure — the device appears offline in the cloud. The mobile app will show "No device found".

In this mode:
- No data reaches the 4HEAT cloud (privacy)
- The 4HEAT mobile app will **not** work remotely
- HA receives real-time sensor push via the proxy's `/store` endpoint (in addition to TCP polling)

### Sensors

Core sensors (TCP polling, all modes):

- **State**: operating state (OFF, Ignition, Run, Modulation, Extinguishing, etc.)
- **Error**: active error description (None, Failed Ignition, Exhaust over Temperature, etc.)
- **Exhaust temperature**: exhaust gas temperature in °C
- **Room temperature**: room temperature in °C (0.1° precision)
- **Target temperature**: configured target room temperature in °C
- **Power level**: current power level (1-7)
- **Running**: binary sensor, ON when stove is in any active state
- **Error Active**: binary sensor, ON when an error code is present

Additional sensors (proxy store push, cloud_keepalive/local_only modes):

- **Remote Room Temperature** / **Remote Room Temperature 2**: remote temperature probes (°C, shows unavailable when no probe connected)
- **Airflow**: combustion airflow (raw value)
- **Heating Fan Power**: heating fan speed level
- **Ducted Fan 1** / **Ducted Fan 2**: ducted fan speed levels (disabled by default)
- **Cleaning Counter** / **Service Counter**: maintenance counters (diagnostic)

See [Sensors & Entities](docs/SENSORS.md) for the full register map and 2WC protocol details.

### Write Commands

Sent via [TCP direct](#tcp-direct) — instant response, no polling delay.

- **ON / OFF**: start or stop the stove
- **Target temperature**: set room target (10-40°C, 0.1°C step)
- **Power level**: set power (1-7)

All write commands are available via the [climate entity](docs/SENSORS.md#climate-entity) (HVAC modes, temperature slider, power presets).

### Schedule Management

View and edit the stove's weekly heating schedule (H24 program) directly from HA. Schedules are delivered via [dual delivery](#command-delivery-methods) — TCP direct (immediate) + command queue (backup).

- **Options Flow**: YAML editor pre-populated with the current schedule
- **Services**: `4heatlite.get_schedule` and `4heatlite.set_schedule` for automations

See [Scheduling](docs/SCHEDULING.md) for the H24/CCG protocol details.

Schedule YAML example (paste into the Heating Schedules editor):

```yaml
- name: autumn
  active: true
  comfort: 23.0
  comfort2: 24.0
  eco: 18.0
  slots:
    - band: comfort
      days: [mon, tue, wed, thu, fri]
      start: "07:30"
      end: "09:30"
    - band: comfort
      days: [mon, tue, wed, thu, fri]
      start: "19:00"
      end: "22:00"
    - band: eco
      days: [sat, sun]
      start: "08:00"
      end: "23:00"
- name: winter
  active: false
  comfort: 23.0
  comfort2: 25.0
  eco: 19.0
  slots:
    - band: comfort2
      days: [mon, tue, wed, thu, fri, sat, sun]
      start: "07:00"
      end: "23:00"
```

Only one schedule can have `active: true`. The active schedule is sent to the stove on save. Set all to `active: false` to disable the schedule.

### Command Delivery Methods

The module accepts commands via two methods. The integration uses both for schedule delivery (TCP primary, queue backup). Simple write commands (ON/OFF, temperature, power) use TCP only.

#### TCP Direct

Raw JSON array sent to the module on port 80. No HTTP framing — just a plain TCP socket. The module parses the JSON, executes the command, and responds on the same connection. **JSON must be compact** (no spaces) — the module rejects spaced JSON with `["ERR","1","1"]`.

```bash
# Read sensors
echo -n '["2WC","1","0310"]' | nc -w 3 <MODULE_IP> 80

# Turn ON
echo -n '["2WC","1","0504000000"]' | nc -w 3 <MODULE_IP> 80

# Turn OFF
echo -n '["2WC","1","0505000000"]' | nc -w 3 <MODULE_IP> 80

# Set target temperature to 23.0°C (0x00E6 = 230)
echo -n '["2WC","1","0512005a00e6006401900001000100"]' | nc -w 3 <MODULE_IP> 80

# Read current schedule
echo -n '["CCG","0"]' | nc -w 3 <MODULE_IP> 80

# Write a schedule (compact JSON, no spaces)
echo -n '["H24","119","#13","1","180","230","240","0","0","450","230","570","0",...,"9930","0"]' | nc -w 3 <MODULE_IP> 80
# Response: ["H24","1","OK"]
```

#### Command Queue (Proxy Endpoint)

In Local Only mode, the module polls `GET /api/devices/commands?id=<device_id>&removefromserver=true` every ~60 seconds. The proxy returns queued commands in compact JSON. This is the same protocol the 4HEAT cloud uses.

```bash
# Check the queue (without draining it)
curl -s 'http://<HA_IP>:8123/api/devices/commands?id=<DEVICE_ID>'

# Check the queue (drain it, as the module does)
curl -s 'http://<HA_IP>:8123/api/devices/commands?id=<DEVICE_ID>&removefromserver=true'

# Response when commands are queued:
# [{"id":"24018919","comando":["H24","119","#13","1","180","230","240",...]}]

# Response when empty:
# []
```

The queue is populated by the integration when delivering schedules. Commands are cleared only when the module polls with `removefromserver=true`.

See [Proxy Modes](docs/PROXY_MODES.md) for architecture and [Proxy Endpoints](docs/PROXY_ENDPOINTS.md) for the endpoint reference.

## Documentation

- [Sensors & Entities](docs/SENSORS.md) — entity list, register map, 2WC protocol, state/error codes
- [Proxy Modes](docs/PROXY_MODES.md) — architecture, direct/cloud_keepalive/local_only modes, network setup, stunnel
- [Proxy Endpoints](docs/PROXY_ENDPOINTS.md) — endpoint reference, request/response formats, values decoding
- [Scheduling](docs/SCHEDULING.md) — H24/CCG schedule protocols, timeAlign clock sync, schedule read/write

## Related Projects

- [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat) — HA integration for the older 4HEAT module (SEL/SEC protocol)
- [4heat-esphome](https://github.com/leoshusar/4heat-esphome) — ESPHome component for direct ESP32-to-stove serial connection (Tiemme protocol)

## License

GPL-3.0 — see [LICENSE](LICENSE).
