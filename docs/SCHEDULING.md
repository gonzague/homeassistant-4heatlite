# Module Scheduling (Cron)

Jolly Mec profiles expose the native CCG/CCS on/off program through an options
editor with time pickers, enabled flags and a review step. Native writes are
TCP-only with fresh comparison and readback verification; they are never queued.
The H24 temperature-band editor below applies only to the default Lasian profile.
See [Jolly Mec profile](JOLLYMEC.md#native-ccg--ccs-schedules).

The 4HEAT Lite WiFi module has a built-in scheduler that turns the stove on and off at configured times. The schedule is stored on the module itself, not in HA. The mobile app writes the schedule directly over TCP, and the module executes it locally based on its internal clock.

## How it works

1. The **mobile app** sends schedule commands via **raw TCP** directly to the module on port 80. The app does NOT use the cloud commands queue for schedules.
2. The **module** stores the schedule internally and executes it using its internal clock.
3. The module periodically uploads its current schedule to the cloud via `POST /api/devices/cron`. The cloud stores it but never pushes it back — `GET /api/devices/commands` always returns `[]` for schedule data.
4. The module synchronizes its clock via `GET /api/Devices/timeAlign`.

## Clock synchronization (timeAlign)

The module calls `GET /api/Devices/timeAlign?deviceKey=<key>` after each commands poll. The response:

```json
{
  "gmtOffset": 7200,
  "timestamp": 1792576277
}
```

**Important:** `timestamp` is **not** a standard Unix epoch. It is `epoch_UTC + gmtOffset` — the cloud returns the timestamp already shifted to local time. The module uses this value directly as its local clock. If the timestamp is a raw UTC epoch, the module clock will be behind by `gmtOffset` seconds.

The proxy computes `gmtOffset` dynamically from the HA server's system timezone, so it adjusts automatically for DST transitions (e.g., CEST 7200 → CET 3600).

## Schedule protocols

The module supports two mutually exclusive schedule protocols. Only one can be active at a time — writing one replaces the other. Both are read via the same query (`["CCG","0"]`); the response format indicates which is active.

### H24 protocol (24-hour heating program)

Used by the "Heating" page in the mobile app. Defines temperature bands (ECO, COMFORT, COMFORT2) with minute-precision transitions across the entire week.

```
["H24","<count>","#<register>","<program_index>","<ECO>","<COMFORT>","<COMFORT2>", <minute>,<temp>, <minute>,<temp>, ...]
```

| Field | Description |
|-------|-------------|
| `count` | Total elements after `H24` and `count`: `(pairs × 2) + 5`. The 5 = `#register`, `program_index`, `ECO`, `COMFORT`, `COMFORT2` |
| `#<register>` | Register reference (e.g., `#13`). The `#` prefix indicates new format |
| `program_index` | Schedule slot (0, 1, or 2). The app stores 3 schedules locally and sends the active slot's index here |
| `ECO` | ECO temperature value (raw, divided by 10 for °C) |
| `COMFORT` | COMFORT temperature value |
| `COMFORT2` | COMFORT2 temperature value |
| pairs | `(minute_in_week, temperature)` — transitions through the week |

**Minutes are counted from Monday 00:00.** Each day has 1440 minutes:

| Day | Minute range |
|-----|-------------|
| Monday | 0–1439 |
| Tuesday | 1440–2879 |
| Wednesday | 2880–4319 |
| Thursday | 4320–5759 |
| Friday | 5760–7199 |
| Saturday | 7200–8639 |
| Sunday | 8640–10079 |

Temperature values in the pairs match one of the defined bands (ECO, COMFORT, COMFORT2) or `0` for OFF. The module switches to the specified temperature at each minute mark.

#### Example

A schedule with 57 event pairs (4 daily comfort slots × 7 days, plus day-start OFF transitions):

```
["H24","119","#13","1","180","230","240",
  "0","0",       <- Monday 00:00, OFF
  "450","230",   <- Monday 07:30, COMFORT (23.0°C)
  "570","0",     <- Monday 09:30, OFF
  ...
  "1890","230",  <- Tuesday 07:30, COMFORT
  ...
]
```

count = 57 pairs × 2 + 5 = **119**. This defines 4 daily slots (07:30–09:30, 11:30–13:30, 15:30–17:30, 19:30–21:30) at COMFORT temperature, repeated every day.

**Important:** When queried back via `["CCG","0"]`, the stove returns `count=62` (pair count, not element count). The send and read formats use different count semantics.

#### Protocol constraints

- **JSON must be compact** — no spaces. Use `separators=(",",":")`. The stove returns `["ERR","1","1"]` on spaced JSON via TCP.
- **program_index is 0, 1, or 2** — identifies which of the app's 3 schedule slots this belongs to. The stove accepts all three values (and higher). The stove stores one schedule at a time; program_index is metadata the app uses to track which local slot is active.
- **Minimum 2 transition pairs** — a command with only 1 pair returns `["ERR","1","1"]`.
- **count must be `pairs*2 + 5`** — an incorrect count causes the stove to truncate the schedule. With count=62 (wrong) for 57 pairs, the stove only stored ~33 events.
- **Minutes have 2-minute granularity** — the stove rounds odd minutes up (e.g., 19:31 → 19:32).

### CCS protocol (chronothermostat)

Used by the "Crono" page in the mobile app. Defines 3 time slots per day with enable/disable flags.

```
["CCS","<count>","<period>","<day>","<start1>","<end1>","<check1>","<start2>","<end2>","<check2>","<start3>","<end3>","<check3>", ...]
```

| Field | Description |
|-------|-------------|
| `count` | Total element count (period + 7 days × 10 fields) |
| `period` | Timer mode: `0`=disabled, `1`=per-day, `2`=weekly, `3`=weekday/weekend |
| `day` | Day number (1–7) |
| `startN/endN` | Time range in `HH:MM` format |
| `checkN` | Slot enabled: `0`=off, `1`=on |

When `period=0`, the schedule is stored but inactive — the module ignores all time slots. The mobile app uses this to "disable" without erasing slot data.

Read via `["CCG","0"]` — response starts with `"CCS"` or `"CCG"` (same format).

## Reading the schedule

Send a TCP query to the module on port 80:

```
["CCG","0"]
```

The module responds with its current schedule. The response protocol (`H24` or `CCS`/`CCG`) indicates which schedule type is active.

## Writing the schedule

The integration uses **dual delivery**: TCP direct + proxy command queue.

**TCP (primary):** Send the raw JSON array directly to the module on port 80. This is how the mobile app does it. Takes effect immediately. The stove responds `["H24","1","OK"]` on success or `["ERR","1","1"]` on failure.

```
["H24","119","#13","1","180","230","240","0","0","450","230",...]
```

**Command queue (backup):** The same command is also enqueued in the proxy's in-memory queue. On the module's next `GET /api/devices/commands` poll (~60s), it receives the command wrapped in the queue format:

```json
[{"id":"<device_id>","comando":["H24","119","#13","1","180","230","240","0","0","450","230",...]}]
```

The queue response must use compact JSON (`separators=(",",":")`) to fit within the ESP32's HTTP receive buffer.

## Disabling the schedule

The mobile app disables the schedule by sending a CCS command with `period=0`, which overwrites whatever schedule is active (including H24) with a disabled CCS. The app caches the schedule locally and re-sends it to re-enable.

**For the Lasian H24 editor,** Instead of switching to CCS, disabling sends an H24 command with two OFF transitions (minimum required). The ECO/COMFORT/COMFORT2 temperatures from the current schedule are preserved in the command:

```
["H24","9","#13","0","<ECO>","<COMFORT>","<COMFORT2>","0","0","0","0"]
```

count = 2 pairs × 2 + 5 = **9**.

The schedule data is cached in the HA config entry options. Setting `active: true` on a schedule in the options YAML editor sends it to the stove; setting all schedules to `active: false` sends the disable command.

## Proxy behavior

| Mode | `POST /api/devices/cron` | `timeAlign` |
|------|--------------------------|-------------|
| `direct` | Forward to Azure, then acknowledge | Forward to Azure; fall back to local if cloud fails |
| `cloud_keepalive` | Acknowledge only (not mirrored) | Return local fallback with dynamic timezone offset |
| `local_only` | Acknowledge only (not mirrored) | Return local fallback with dynamic timezone offset |

The proxy parses H24 data from `POST /api/devices/cron` and caches it in `device_entry["last_schedule"]`. This cache is used by the options flow and `get_schedule` service. The schedule can also be read directly from the module via TCP (`["CCG","0"]`).
