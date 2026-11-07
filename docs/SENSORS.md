# Sensors & Entities

The layouts and scales below describe the default Lasian profile. For Jolly Mec
whole-degree temperatures, combustion power offsets, dedicated exhaust readings
and direct ducted-fan polling, see [Jolly Mec profile](JOLLYMEC.md).

## Sensor Entities

| Entity | Description | Source |
|--------|-------------|--------|
| State | Stove operating state (OFF, Check Up, Ignition, Stabilization, Run, Modulation, Extinguishing, etc.) | TCP poll (0310 byte 5) |
| Error | Active error description (None, Failed Ignition, Exhaust over Temperature, etc.) | TCP poll (0310 byte 1) |
| Exhaust Temperature | Exhaust gas temperature in °C | TCP poll (0310 byte 4) |
| Room Temperature | Room temperature in °C (0.1° precision) | TCP poll (0310 bytes 10-11) |
| Target Temperature | Configured target room temperature in °C | TCP poll (12/005a register) |
| Power Level | Current power level setting (1-7) | TCP poll (0e/016c register) |

## Binary Sensor Entities

| Entity | Description |
|--------|-------------|
| Running | ON when stove is in any active state (ignition, run, modulation, stabilization) |
| Error Active | ON when an error code is present |

## Climate Entity

A climate entity is always created for display (current/target temperature, stove state). Write commands (temperature, ON/OFF, power) require the [cloud API proxy](PROXY_MODES.md) — without it, changes are logged but not sent.

When the proxy is enabled:
- **HVAC modes**: OFF / HEAT (sends ON/OFF command to the module)
- **Target temperature**: 10-40°C, 0.1°C step
- **Preset modes**: Power 1-7
- **HVAC action**: OFF, Preheating (ignition), Heating (run/modulation), Idle (extinguishing/standby)

All write commands are queued and delivered to the stove via the proxy within ~60 seconds (module polling interval).

## Register Sensors (from store push)

Additional sensors parsed from the module's `POST /api/devices/store` Values array. These update every ~3 minutes when the proxy is active (cloud_keepalive or local_only mode). In direct mode, these sensors are not populated.

| Entity | Data key | Register | Source (filemap) | Notes |
|--------|----------|----------|-----------------|-------|
| Remote Room Temperature | `remote_room_temp` | 12/ffe0 | Temp ambiente remota | Shows unavailable when 0 (no probe) |
| Remote Room Temperature 2 | `remote_room_temp_2` | 12/ffe8 | Temp ambiente remota 2 | Shows unavailable when 0 (no probe) |
| Airflow | `airflow` | 12/ffed | Flusso aria | Raw value (unit TBD) |
| Heating Fan Power | `heating_fan_power` | 0e/023f | Potencia calefacción | |
| Ducted Fan 1 | `ducted_fan_1` | 0e/0266 | Potencia canalizada 1 | Disabled by default |
| Ducted Fan 2 | `ducted_fan_2` | 0e/027e | Potencia canalizada 2 | Disabled by default |
| Cleaning Counter | `cleaning_counter` | 12/ffde | CLEANING 4WEB | Diagnostic |
| Service Counter | `service_counter` | 12/ffdf | SERVICE 4WEB | Diagnostic, disabled by default |

Registers 12/ffff (exhaust temp) and 12/fff7 (room temp) are also parsed but not exposed as entities — they duplicate data already available from the 0310 sensor block via TCP polling.

### Full store register map

| Prefix | Register | Group | Decode | Key |
|--------|----------|-------|--------|-----|
| `10` | 0310 main block | compound | `_decode_0310()` — 19 bytes | state, error, on_off, exhaust_temp, room_temp |
| `12ffff` | Exhaust temp | 12 | bytes 3-4, ×1 | exhaust_temp_store (duplicate) |
| `12fff7` | Room temp | 12 | bytes 3-4, ×0.1 | room_temp_store (duplicate) |
| `12ffe0` | Remote room temp | 12 | bytes 3-4, ×0.1 | remote_room_temp |
| `12ffe8` | Remote room temp 2 | 12 | bytes 3-4, ×0.1 | remote_room_temp_2 |
| `12ffed` | Airflow | 12 | bytes 3-4, ×1 | airflow |
| `12ffde` | Cleaning counter | 12 | bytes 3-4, ×1 | cleaning_counter |
| `12ffdf` | Service counter | 12 | bytes 3-4, ×1 | service_counter |
| `12005a` | Target temp | 12 | bytes 3-4, ×0.1 | target_temp |
| `120058` | Unknown | 12 | bytes 3-4, ×1 | reg_120058 |
| `120059` | Unknown | 12 | bytes 3-4, ×1 | reg_120059 |
| `0e016c` | Combustion power | 0e | bytes 5-6 | power |
| `0e023f` | Heating fan power | 0e | bytes 5-6 | heating_fan_power |
| `0e0266` | Ducted fan 1 | 0e | bytes 5-6 | ducted_fan_1 |
| `0e027e` | Ducted fan 2 | 0e | bytes 5-6 | ducted_fan_2 |
| `0e0231` | Unknown | 0e | bytes 5-6 | reg_0e0231 |
| `0c81` | Module info | 0c | raw hex | module_info |

## How Sensors Are Updated

The integration uses two data sources:

1. **TCP polling** (primary): Direct queries to the module over TCP:80 using the 2WC protocol. Polls every 30 seconds in local mode, every 120 seconds when the proxy is active.

2. **Proxy push** (real-time): When the proxy is active, the module pushes sensor data via `POST /api/devices/store` every time values change (typically within seconds of a change) and periodically as a keepalive. This data is injected directly into the coordinator, updating all entities immediately without waiting for the next TCP poll.

## 2WC Protocol

The 4HEAT Lite module exposes a TCP server on port 80. The integration sends JSON-encoded 2WC commands to read sensor registers from the stove's Tiemme controller board via the module's RS485 bus.

```
Query:    ["2WC","1","0310"]
Response: ["2WC","1","<38 hex chars>"]
```

The 19-byte response contains the stove state, error code, exhaust temperature, room temperature, and other registers.

### Register Map (0310 response)

| Byte(s) | Field | Unit | Notes |
|---------|-------|------|-------|
| 0 | Header | - | Always 0x10 |
| 1 | Error | enum | See `ERROR_NAMES` in const.py |
| 2 | On/Off | flag | 0=off, 1=on (stays 1 during cooldown) |
| 3 | Unknown | - | |
| 4 | Exhaust temp | °C | 1-byte unsigned |
| 5 | State | enum | See `STATE_NAMES` in const.py |
| 6-9 | Unknown | - | |
| 10-11 | Room temp | 0.1°C | 2-byte big-endian |
| 12-18 | Unknown | - | |

### State Values

| Code | State |
|------|-------|
| 0 | OFF |
| 1 | Check Up |
| 2-4 | Ignition |
| 5 | Run |
| 6 | Modulation |
| 7 | Extinguishing |
| 8 | Safety |
| 9 | Block |
| 10 | Recover Ignition |
| 11 | Standby |
| 13 | Run M |
| 30-34 | Ignition |

### Error Codes

| Code | Error |
|------|-------|
| 0 | None |
| 1 | Safety Thermostat HV1 |
| 2 | Safety PressureSwitch HV2 |
| 3 | Exhaust Temp lowering |
| 4 | Water over Temperature |
| 5 | Exhaust over Temperature |
| 7 | Encoder: No Signal |
| 8 | Encoder: Fan regulation failed |
| 9 | Low boiler pressure |
| 10 | High boiler pressure |
| 11 | Clock reset (power loss) |
| 12-14 | Failed/Ignition error |
| 15 | Lack of Voltage |
| 16-17 | Ignition error |
| 18 | Lack of Voltage |
| 44 | Door error |

### Write Command Format

Write commands use function code `05` followed by the register address and data:

```
["2WC","1","05<register><data>"]
```

Example — set target temperature to 28.8°C:
```
["2WC","1","0512005a0120006401900001000100"]
```

- `05` — write function
- `12005a` — register group 12, address 005a (target temperature)
- `0120` — 28.8°C (0x120 = 288, in 0.1°C units)
- `0064` — min 10.0°C
- `0190` — max 40.0°C
- `0001000100` — trailing register data
