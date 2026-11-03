# Proxy Endpoints

The proxy registers HTTP endpoints on HA's web server (port 8123) using the `HomeAssistantView` pattern. All endpoints use `requires_auth = False` because the module has no authentication capabilities.

## Endpoint Reference

### Module-facing (proxy-intercepted)

| Endpoint | Method | When | Proxy Mode | Azure Mirror |
|----------|--------|------|------------|-------------|
| [`/api/devices/register`](#post-apidevicesregister) | POST | Module boot | keepalive + local_only | keepalive only |
| [`/api/devices/commands`](#get-apidevicescommands) | GET | Every ~60s | keepalive + local_only | No |
| [`/api/Devices/timeAlign`](#get-apidevicestimealign) | GET | After each commands poll | keepalive + local_only | No |
| [`/api/devices/store`](#post-apidevicesstore) | POST | On value change + ~15min keepalive | keepalive + local_only | keepalive only |
| [`/api/devices/cron`](#post-apidevicescron) | POST | Periodically | keepalive + local_only | No |

### App-facing (cloud API)

| Endpoint | Method | Purpose | Implemented |
|----------|--------|---------|-------------|
| [`POST /Token`](#post-token) | POST | OAuth token | config_flow only |
| [`GET /api/devices/summary`](#get-apidevicessummary) | GET | Status/temp/online for all devices | No |
| [`GET /api/Devices/SummaryClosed`](#get-apidevicessummaryclosed) | GET | Summary variant (logged-in) | No |
| [`GET /api/devices/Details`](#get-apidevicesdetails) | GET | Device info + firmware version | config_flow only |
| [`GET /api/Devices/DetailsCustomer`](#get-apidevicesdetailscustomer) | GET | Access check / device discovery | No |
| [`GET /api/devices/RealTime`](#get-apidevicesrealtime) | GET | Live data (remote fallback) | No |
| [`GET /api/Devices/Customer`](#get-apidevicescustomer) | GET | Manufacturer/support contact info | No |
| [`GET /api/Devices/NotificationErrors/{id}`](#get-apidevicesnotificationerrorsid) | GET | Error history | No |
| [`GET /api/Devices/History`](#get-apideviceshistory) | GET | Time-series sensor data for charts | No |
| [`GET /api/Devices/FileMap`](#get-apidevicesfilemap) | GET | Full device config download | No |
| [`GET /api/DeviceTypes/LastVersion`](#get-apidevicetypeslastversion) | GET | Filemap update check | No |
| [`GET /api/firmwares/{type}/lastVersion`](#get-apifirmwarestypelastversion) | GET | Firmware binary download | No |
| [`GET /api/Devices/DeviceLiteType`](#get-apidevicesdevicelitetype) | GET | Device type check (BLE setup) | No |
| [`POST /api/devices/command`](#post-apidevicescommand) | POST | Send commands (on/off, temp, power) | No |
| [`POST /api/devices/RemoteSupportFlag`](#post-apidevicesremotesupportflag) | POST | Remote support toggle | No |
| [`GET /api/devices/cron`](#get-apidevicescron) | GET | Read schedule (remote fallback) | No |

### Debug

| Endpoint | Method | Purpose | Implemented |
|----------|--------|---------|-------------|
| [`GET /api/devices/diag`](#get-apidevicesdiag) | GET | Cloud connectivity test | Yes |

---

### POST `/api/devices/register`

Module sends this once on boot before starting the polling cycle.

**Request:**

```json
{
  "Id": "<DEVICE_ID>",
  "DeviceName": "",
  "Pin": "<PIN>",
  "ProductCode": "<PRODUCT_CODE>",
  "ProductVersion": "000000000001",
  "ProductCommunication": "2ways",
  "FirmwareVersion": 2,
  "FirmwareRevision": 11,
  "FilemapVersion": 34,
  "IpAddress": "<MODULE_IP>",
  "DeviceType": "Lite",
  "Coordinates": {"Latitude": "0.00", "Longitude": "0.00"},
  "NodeList": [
    {"Firmware": "4.3.0", "Type": "MSTR", "Address": "48", "Desc": "..."},
    {"Firmware": "0.3.0", "Type": "KEYB", "Address": "26", "Desc": "..."},
    {"Firmware": "0.3.0", "Type": "COMI", "Address": "50", "Desc": "..."},
    {"Firmware": "0.1.4", "Type": "COMI", "Address": "48", "Desc": "4Heat Firmware"}
  ],
  "SSID": "<WIFI_SSID>",
  "RSSI": "-60"
}
```

**Response:**

```json
{"Key": "<DEVICE_KEY>"}
```

`cloud_keepalive`: forwards to Azure via HTTPS mirror, receives and persists DeviceKey. `local_only`: returns stored DeviceKey from config entry.

---

### GET `/api/devices/commands`

Module polls every ~60s for pending commands.

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | query | Device ID |
| `removefromserver` | query | `true` — dequeue after delivery |

**Response** (with pending command):

```json
[{"id": "<DEVICE_ID>", "comando": ["2WC", "1", "0512005a00b4006401900001000100"]}]
```

**Response** (no pending commands):

```json
[]
```

`cloud_keepalive` / `local_only`: drains local queue only. Commands are controlled exclusively by HA.

---

### GET `/api/Devices/timeAlign`

Module calls this after every commands poll to sync its internal clock.

| Parameter | Type | Description |
|-----------|------|-------------|
| `deviceKey` | query | DeviceKey UUID |

**Response:**

```json
{"gmtOffset": 7200, "timestamp": 1787022616}
```

`cloud_keepalive` / `local_only`: returns local system time with configured GMT offset (not mirrored).

> **Critical**: If this endpoint returns 404, the module stops its polling cycle and never sends `/store`.

---

### POST `/api/devices/store`

Module sends sensor data on value changes (within seconds) and periodically as a keepalive (~15 minutes).

**Request:**

```json
{
  "DeviceKey": "<DEVICE_KEY>",
  "TimeStamp": "2026-08-18T02:15:00",
  "GmtOffset": 7200,
  "Values": [
    "1000010017000002021600f322000000010801",
    "12005a00b4006401900001000100000000",
    "0e016c00070001000700000001016c0007"
  ]
}
```

**Response:**

```json
{"DeviceId": "<DEVICE_ID>", "Assistant": ""}
```

Proxy parses `Values` to extract sensor data (see [Values Decoding](#values-decoding) below), pushes to coordinator for immediate entity updates. `cloud_keepalive`: also mirrors full body to Azure via HTTPS.

---

### POST `/api/devices/cron`

Module sends schedule/timer data periodically.

**Response:**

```json
{"DeviceId": "<DEVICE_ID>", "Assistant": ""}
```

`cloud_keepalive` / `local_only`: acknowledges only (cron is not mirrored).

---

## App-Facing Endpoints (not yet proxied)

These endpoints are called by the mobile app against `https://wifi4heat.azurewebsites.net`. They are documented here for completeness and future implementation.

### POST `/Token`

OAuth token endpoint. Used by config_flow during setup, not by proxy at runtime.

- **Full URI:** `https://wifi4heat.azurewebsites.net/Token`
- **Auth:** None
- **Headers:** `Content-Type: application/x-www-form-urlencoded`
- **Request body (form-encoded):**
  - `grant_type`: `password`
  - `username`: user email (lowercased)
  - `password`: user password
- **Response (JSON):**
  - `access_token`: Bearer token (14-day expiry)
- **Status:** Used in `config_flow.py` only — not available at runtime

---

### GET `/api/devices/summary`

Main polling endpoint — returns current status for all devices.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/devices/summary?ids[0]=<id1>&ids[1]=<id2>...`
- **Auth:** None or `Bearer @token`
- **Headers:** `Content-Type: application/json`
- **Query params:** `ids[]` — array of device ID strings
- **Response (JSON array):**
  - `[].Id`: device ID
  - `[].LastMessageReceived`: JSON string with sensor `Values[]`
  - `[].IsOnline`: boolean
  - `[].FirmwareVersion`, `[].FirmwareRevision`: strings
  - `[].FilemapHash`, `[].LastFilemapHash`: strings
  - `[].NewFirmwareAvailable`: boolean
- **Status:** Not implemented — referenced only in `ProxyDiagView` connectivity test

---

### GET `/api/Devices/SummaryClosed`

Logged-in variant of summary. Possibly restricts to user's associated devices.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/Devices/SummaryClosed?ids[0]=<id1>&ids[1]=<id2>...`
- **Auth:** None
- **Query params:** Same as `/api/devices/summary`
- **Response:** Same as `/api/devices/summary`
- **Status:** Not implemented

---

### GET `/api/devices/Details`

Device info including firmware version.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/devices/Details?id=<device_id>`
- **Auth:** `Bearer @token`
- **Query params:** `id` — device ID string
- **Response (JSON):**
  - `FirmwareVersion`, `FirmwareRevision`: strings
- **Status:** Used in `config_flow.py` during setup — not available at runtime

---

### GET `/api/Devices/DetailsCustomer`

Access check and device discovery — determines if user has access to a device.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/Devices/DetailsCustomer?id=<device_id>`
- **Auth:** `Bearer @token`
- **Query params:** `id` — device ID string
- **Response (JSON):**
  - `FullUserGroups[]`: array of user group IDs
  - `Name`: device/customer name
- **Status:** Not implemented

---

### GET `/api/devices/RealTime`

Live device data — fallback when LAN TCP connection unavailable.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/devices/RealTime?id=<device_id>`
- **Auth:** `Bearer @token`
- **Query params:** `id` — device ID string
- **Response (JSON):** Current device data (same parsing as Summary)
- **Status:** Not implemented

---

### GET `/api/Devices/Customer`

Manufacturer/installer contact details for a device.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/Devices/Customer?deviceId=<device_id>`
- **Auth:** None
- **Query params:** `deviceId` — device ID string
- **Response (JSON):**
  - `Id`: numeric customer ID
  - `Name`: customer/brand name
  - `PhoneNumber`: support phone number
  - `WebSiteUrl`: website URL
  - `DefaultLanguage`: language code
  - `Email`: support email
- **Status:** Not implemented

---

### GET `/api/Devices/NotificationErrors/{id}`

Error history for a device.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/Devices/NotificationErrors/<device_id>?max=50`
- **Auth:** None
- **Path params:** device ID
- **Query params:** `max` — maximum errors to return (default 50)
- **Response (JSON):** Array of error/notification objects
- **Status:** Not implemented

---

### GET `/api/Devices/History`

Time-series sensor data for charting.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/Devices/History?DeviceId=<id>&From=<date>&To=<date>&Period=<period>&Tags[0].Name=<tag>&Tags[0].Aggregation=<agg>`
- **Auth:** `Bearer @token`
- **Query params:**
  - `DeviceId`: device ID string
  - `From`: date `yyyy-MM-dd`
  - `To`: date `yyyy-MM-dd` (optional)
  - `Period`: `"default"` or other
  - `Tags[]`: array with `.Name` and `.Aggregation` (`"last"`, `"default"`)
- **Response (JSON):** Time-series data
- **Status:** Not implemented

---

### GET `/api/Devices/FileMap`

Full device configuration — ON/OFF commands, sensor definitions, power levels, thermostat settings.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/Devices/FileMap?pin=<pin>&id=<device_id>`
- **Auth:** None (requires pin + device ID)
- **Query params:**
  - `pin`: device PIN (6-digit string)
  - `id`: device ID string
- **Response (JSON):** Complete device config including `comandi_on_off`, `gest_potenze[]`, `gest_termostati[]`, `comandi_log[]`
- **Status:** Not implemented

---

### GET `/api/DeviceTypes/LastVersion`

Check if a newer filemap version exists.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/DeviceTypes/LastVersion?id=<codifica>|<codice_prod>|<versione_prod>`
- **Auth:** None
- **Query params:** `id` — pipe-delimited string: `<device_type_code>|<product_code>|<product_version>`
- **Response (JSON):**
  - `JsonMap`: JSON string containing latest filemap
- **Status:** Not implemented

---

### GET `/api/firmwares/{type}/lastVersion`

Download firmware binary.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/firmwares/{type}/lastVersion?deviceKey=<device_key>`
- **`{type}` values:** `Micro`, `Wifi`, `MicroLight`, `LiteV2`
- **Auth:** None (requires DeviceKey)
- **Query params:** `deviceKey` — device UUID
- **Response:** Raw firmware binary (ESP-IDF application image, ~1.2MB)
- **Status:** Not implemented

---

### GET `/api/Devices/DeviceLiteType`

Determine device type during BLE setup.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/Devices/DeviceLiteType?deviceId=<device_id>`
- **Auth:** `Bearer @token`
- **Query params:** `deviceId` — device ID string
- **Response (JSON):**
  - `Key`: device type string (e.g. `"Lite"`)
- **Status:** Not implemented

---

### POST `/api/devices/command`

Send commands to a device (on/off, temperature, power, schedule). Commands are queued server-side and delivered to the module via `GET /api/devices/commands`.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/devices/command`
- **Auth:** `Bearer @token`
- **Headers:** `Content-Type: application/json`
- **Request body (JSON):**
  - `id`: device ID string
  - `comando`: command array (e.g. `["2WC", "1", "05040000"]`)
- **Response:** HTTP 200
- **Status:** Not implemented — proxy queues commands locally via `StoveCommandsView` instead

---

### POST `/api/devices/RemoteSupportFlag`

Toggle remote support access for a device.

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/devices/RemoteSupportFlag`
- **Auth:** `Bearer @token`
- **Headers:** `Content-Type: application/json`
- **Request body (JSON):**
  - `DeviceId`: device ID string
  - `Flag`: `"enabled"` or `"disabled"`
- **Response:** HTTP 200
- **Status:** Not implemented

---

### GET `/api/devices/cron`

Read current schedule/timer data from cloud (fallback when local TCP fails).

- **Full URI:** `https://wifi4heat.azurewebsites.net/api/devices/cron?deviceId=<device_id>`
- **Auth:** `Bearer @token`
- **Headers:** `Content-Type: application/json`
- **Query params:** `deviceId` — device ID string
- **Response (JSON):**
  - `Command`: array — current schedule/timer command (same format as `comando` in `/api/devices/command`)
- **Status:** Not implemented

---

### GET `/api/devices/diag`

Debug endpoint — tests cloud connectivity and shows proxy state. Not a 4HEAT cloud endpoint; implemented locally by the proxy.

- **Query params:** None
- **Response (JSON):** Device count, host map, cloud session status, last forward results
- **Status:** Implemented in `proxy.py` (`ProxyDiagView`)

---

## DeviceKey Origin

The DeviceKey is **generated server-side by Azure** during the module's first `POST /api/devices/register` call. It is not pre-flashed on the device. After first registration, the key persists across reboots and does not change on subsequent registrations. There is no local protocol (TCP 2WC, UDP CF4, or BLE) that exposes the DeviceKey.

---

## Values Decoding

The `Values` array in `/store` contains hex-encoded register data. Each string is identified by its prefix:

| Prefix | Register | Parsed Fields | Decoding |
|--------|----------|---------------|----------|
| `10` (38 chars) | 0310 — main sensors | state, error, exhaust_temp, room_temp, on_off | See [register map](SENSORS.md#register-map-0310-response) |
| `12005a` | Target temp | target_temp | bytes 3-4, big-endian, /10 = °C |
| `0e016c` | Power level | power | bytes 5-6, big-endian |

## Device Lookup

The proxy identifies which stove a request belongs to using two methods:

1. **Device ID** — from query parameters (`id=`) or request body (`Id`). Used by `/register` and `/commands`.
2. **Source IP** — the module's IP address. Used by `/store` and `/cron` which don't include a device ID.

A host-to-device mapping is maintained in memory and updated on every request.

## Auto-Detection

If the integration is configured without a Device ID (empty field), the proxy places the config entry in a "pending" state. When the first request arrives from the module, the device ID is auto-detected from the request and the entry is promoted to active.
