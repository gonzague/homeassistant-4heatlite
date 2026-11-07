"""TCP client for 4HEAT Lite module (2WC protocol)."""

import json
import logging
import socket
import time

from .const import (
    BAND_NAMES,
    DAY_NAMES,
    DAY_OFFSETS,
    MINUTES_PER_DAY,
    QUERY_CONFIG,
    QUERY_SCHEDULE,
    QUERY_SENSORS,
    REGISTER_TEMP,
    SOCKET_BUFFER,
    SOCKET_TIMEOUT,
    TCP_PORT,
    TEMP_MAX_RAW,
    TEMP_MIN_RAW,
    TEMP_SCALE,
    TEMP_WRITE_SUFFIX,
    WRITE_FUNCTION,
    JOLLYMEC_READS,
    PROFILE_JOLLYMEC,
    PROFILE_LASIAN,
    STOVE_PROFILES,
)

_LOGGER = logging.getLogger(__name__)


class FourHeatLiteApi:
    """Communicate with a 4HEAT Lite module over TCP:80."""

    def __init__(self, host: str, profile: str = PROFILE_LASIAN) -> None:
        if profile not in STOVE_PROFILES:
            raise ValueError("Unknown stove profile")
        self._host = host
        self.profile = profile

    @property
    def supports_schedule_write(self) -> bool:
        """Jolly Mec's CCG program is not an H24 temperature schedule."""
        return self.profile != PROFILE_JOLLYMEC

    def _send(self, command: str) -> list:
        """Send a JSON command and return the parsed response."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(SOCKET_TIMEOUT)
        try:
            s.connect((self._host, TCP_PORT))
            s.sendall(command.encode())
            raw = bytearray()
            deadline = time.monotonic() + SOCKET_TIMEOUT
            while len(raw) < 65536:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Incomplete module response")
                s.settimeout(remaining)
                chunk = s.recv(SOCKET_BUFFER)
                if not chunk:
                    raise ValueError("Connection closed before complete JSON")
                raw.extend(chunk)
                try:
                    return json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            raise ValueError("Module response exceeds size limit")
        finally:
            s.close()

    def send_command(self, cmd: list) -> list | None:
        """Send a command via TCP and return the parsed response."""
        if cmd and cmd[0] == "H24" and not self.supports_schedule_write:
            raise ValueError("H24 schedule writes are not supported by this profile")
        try:
            response = self._send(json.dumps(cmd, separators=(",", ":")))
            if not isinstance(response, list) or not response or response[0] == "ERR":
                return None
            return response
        except (OSError, ValueError, json.JSONDecodeError):
            _LOGGER.warning("TCP command failed: %s", cmd)
            return None

    def _query(self, command: str, min_hex_len: int = 4) -> str | None:
        """Send a 2WC query and return hex payload, or None on failure."""
        try:
            response = self._send(command)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _LOGGER.debug("Query failed: %s", exc)
            return None

        if not isinstance(response, list) or len(response) < 3:
            return None
        if response[0] == "ERR":
            _LOGGER.warning("Module returned error: %s", response)
            return None

        if response[0] not in ("2WC", "2WR"):
            return None
        # Some firmware returns the entire cache, irrespective of response[1].
        prefix = json.loads(command)[2][2:].lower()
        for hexdata in response[2:]:
            if not isinstance(hexdata, str) or not hexdata.lower().startswith(prefix):
                continue
            if len(hexdata) < min_hex_len or len(hexdata) % 2:
                continue
            if any(char not in "0123456789abcdefABCDEF" for char in hexdata):
                continue
            try:
                bytes.fromhex(hexdata)
            except ValueError:
                continue
            return hexdata
        return None

    def query_sensors(self) -> dict | None:
        """Query main sensor block (0310) and decode into a dict."""
        hexdata = self._query(QUERY_SENSORS, min_hex_len=38)
        if hexdata is None:
            return None
        result = self._decode_0310(hexdata, self.profile)
        if self.profile == PROFILE_JOLLYMEC:
            for key, register in JOLLYMEC_READS.items():
                value = self._query(f'["2WC","1","03{register}"]', min_hex_len=10)
                if value:
                    result[key] = int(value[6:10], 16)
        return result

    def query_config(self) -> dict | None:
        """Query target temp (12/005a) and power (0e/016c)."""
        result = {}
        hexdata = self._query(QUERY_CONFIG["target_temp"], min_hex_len=34)
        if hexdata:
            vals = [int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)]
            scale = 1 if self.profile == PROFILE_JOLLYMEC else 10
            result["target_temp"] = ((vals[3] << 8) | vals[4]) / scale

        hexdata = self._query(QUERY_CONFIG["power"], min_hex_len=34)
        if hexdata:
            vals = [int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)]
            if self.profile == PROFILE_JOLLYMEC:
                raw = (vals[3] << 8) | vals[4]
                result["power_raw"] = raw
                result["power"] = raw - 1 if 1 <= raw <= 6 else None
            else:
                result["power"] = (vals[5] << 8) | vals[6]

        return result if result else None

    def test_connection(self) -> bool:
        """Test if the module responds to a 2WC query."""
        result = self.query_sensors()
        return result is not None

    @staticmethod
    def _decode_0310(hexdata: str, profile: str = PROFILE_LASIAN) -> dict:
        """Decode the 0310 sensor response (19 bytes / 38 hex chars).

        Confirmed register map (Lasian Eriste air stove):
          Byte  0: header (0x10)
          Byte  1: error code (0=none)
          Byte  2: on/off flag (0=off, 1=on)
          Byte  4: exhaust temperature (°C, 1 byte)
          Byte  5: operating state (0=OFF, 5=Run, 6=Modulation, etc.)
          Bytes 10-11: room temperature (big-endian, 0.1°C)
        """
        vals = [int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)]
        room_raw = (vals[10] << 8) | vals[11]

        result = {
            "state": vals[5],
            "error": vals[1],
            "on_off": vals[2],
            "exhaust_temp": vals[4],
            "room_temp": room_raw / 10.0,
            "raw": vals,
        }
        if profile == PROFILE_JOLLYMEC:
            # No signed/sentinel encoding has been established. In particular,
            # 0xfff6 was observed at startup; never publish it as 65526 °C.
            result["room_temp"] = room_raw if room_raw < 0x8000 else None
            # Byte 4 is not the flue temperature on this profile.
            del result["exhaust_temp"]
        return result

    @staticmethod
    def build_temp_command(temp_c: float, profile: str = PROFILE_LASIAN) -> list:
        """Build write command for target temperature register (12/005a)."""
        if profile == PROFILE_JOLLYMEC:
            if not 10 <= temp_c <= 40 or not float(temp_c).is_integer():
                raise ValueError("Jolly Mec target must be a whole degree from 10 to 40")
            return ["2WC", "1", f"0512005a{int(temp_c):04x}000a00280000"]
        raw = int(round(temp_c * 10))
        raw = max(TEMP_MIN_RAW, min(TEMP_MAX_RAW, raw))
        temp_hex = f"{raw:04x}"
        min_hex = f"{TEMP_MIN_RAW:04x}"
        max_hex = f"{TEMP_MAX_RAW:04x}"
        data = f"{WRITE_FUNCTION}{REGISTER_TEMP}{temp_hex}{min_hex}{max_hex}{TEMP_WRITE_SUFFIX}"
        return ["2WC", "1", data]

    @staticmethod
    def build_power_command(level: int, profile: str = PROFILE_LASIAN) -> list:
        """Build write command for combustion power level (register 0e/016c, range 1-7)."""
        if profile == PROFILE_JOLLYMEC:
            if not isinstance(level, int) or not 0 <= level <= 5:
                raise ValueError("Jolly Mec power must be Silent (0) or 1–5")
            return ["2WC", "1", f"050e016c{level + 1:04x}000100070000"]
        level = max(1, min(7, level))
        level_hex = f"{level:04x}"
        data = f"050e016c{level_hex}0001000700"
        return ["2WC", "1", data]

    @staticmethod
    def build_on_command() -> list:
        """Build ON command (accensione from FileMap)."""
        return ["2WC", "1", "05040000"]

    @staticmethod
    def build_off_command() -> list:
        """Build OFF command (spegnimento from FileMap)."""
        return ["2WC", "1", "05050000"]

    @staticmethod
    def build_disable_schedule_command(
        schedule: dict | None = None, program_index: int = 0
    ) -> list:
        """Build H24 command with no active slots (two OFF transitions)."""
        if schedule:
            eco = int(round(schedule.get("eco", 18) * TEMP_SCALE))
            comfort = int(round(schedule.get("comfort", 22) * TEMP_SCALE))
            comfort2 = int(round(schedule.get("comfort2", 24) * TEMP_SCALE))
        else:
            eco, comfort, comfort2 = 180, 220, 240
        return [
            "H24", "9", "#13", str(program_index),
            str(eco), str(comfort), str(comfort2),
            "0", "0", "0", "0",
        ]

    def query_schedule(self) -> dict | None:
        """Query the module's weekly schedule via CCG/H24 protocol."""
        try:
            response = self._send(QUERY_SCHEDULE)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _LOGGER.debug("Schedule query failed: %s", exc)
            return None
        if self.profile == PROFILE_JOLLYMEC:
            return self.parse_ccg_response(response)
        return self.parse_h24_response(response)

    @staticmethod
    def parse_ccg_response(response: list) -> dict | None:
        """Read seven groups of three start/end/flag slots without guessing flags.

        CCG is deliberately distinct from editable H24 schedules. Its mode and
        per-slot flags are preserved as raw codes until their meaning is verified.
        """
        if not isinstance(response, list) or len(response) != 73 or response[0] != "CCG":
            return None
        try:
            if int(response[1]) != len(response) - 2:
                return None
            mode = int(response[2])
            days = []
            for index, day in enumerate(DAY_NAMES):
                offset = 3 + index * 10
                if int(response[offset]) != index + 1:
                    return None
                slots = []
                for slot in range(3):
                    pos = offset + 1 + slot * 3
                    start, end = response[pos:pos + 2]
                    for value in (start, end):
                        if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
                            return None
                        h, m = value.split(":")
                        if not h.isdigit() or not m.isdigit() or not (0 <= int(h) < 24 and 0 <= int(m) < 60):
                            return None
                    slots.append({"start": start, "end": end, "flag_raw": int(response[pos + 2])})
                days.append({"day": day, "slots": slots})
            return {"format": "CCG", "mode_raw": mode, "days": days, "read_only": True}
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_h24_response(response: list) -> dict | None:
        """Parse an H24 schedule response into a user-facing dict."""
        if not isinstance(response, list) or len(response) < 8:
            return None
        if str(response[0]) != "H24":
            return None

        offset = 1 if str(response[2]).startswith("#") else 0
        try:
            program_index = int(response[2 + offset])
            eco_raw = int(response[3 + offset])
            comfort_raw = int(response[4 + offset])
            comfort2_raw = int(response[5 + offset])
        except (ValueError, IndexError):
            return None

        band_map = {}
        if eco_raw:
            band_map[eco_raw] = "eco"
        if comfort_raw:
            band_map[comfort_raw] = "comfort"
        if comfort2_raw:
            band_map[comfort2_raw] = "comfort2"

        transitions = []
        start_idx = 6 + offset
        for i in range(start_idx, len(response) - 1, 2):
            try:
                minute = int(response[i])
                temp = int(response[i + 1])
            except (ValueError, IndexError):
                break
            transitions.append((minute, temp))

        slots_raw = []
        current_band = None
        slot_start = None
        for minute, temp in transitions:
            band = band_map.get(temp)
            if band and current_band is None:
                current_band = band
                slot_start = minute
            elif (band is None or band != current_band) and current_band is not None:
                slots_raw.append((slot_start, minute, current_band))
                if band:
                    current_band = band
                    slot_start = minute
                else:
                    current_band = None
                    slot_start = None
        if current_band is not None and slot_start is not None:
            slots_raw.append((slot_start, MINUTES_PER_DAY * 7, current_band))

        def _minute_to_day_time(m):
            day_idx = m // MINUTES_PER_DAY
            day_m = m % MINUTES_PER_DAY
            day = DAY_NAMES[day_idx] if day_idx < 7 else DAY_NAMES[6]
            return day, f"{day_m // 60:02d}:{day_m % 60:02d}"

        day_slots = {}
        for start_m, end_m, band in slots_raw:
            day, start_t = _minute_to_day_time(start_m)
            _, end_t = _minute_to_day_time(end_m)
            key = (start_t, end_t, band)
            day_slots.setdefault(key, []).append(day)

        slots = []
        for (start_t, end_t, band), days in day_slots.items():
            ordered = [d for d in DAY_NAMES if d in days]
            slots.append({
                "days": ordered,
                "start": start_t,
                "end": end_t,
                "band": band,
            })
        slots.sort(key=lambda s: (
            DAY_OFFSETS.get(s["days"][0], 0) if s["days"] else 0,
            s["start"],
        ))

        return {
            "program_index": program_index,
            "eco": eco_raw / TEMP_SCALE,
            "comfort": comfort_raw / TEMP_SCALE,
            "comfort2": comfort2_raw / TEMP_SCALE,
            "slots": slots,
        }

    @staticmethod
    def build_schedule_command(schedule: dict, program_index: int = 0) -> list:
        """Encode a user-facing schedule dict into an H24 command array."""
        eco_raw = int(round(schedule["eco"] * TEMP_SCALE))
        comfort_raw = int(round(schedule["comfort"] * TEMP_SCALE))
        comfort2_raw = int(round(schedule["comfort2"] * TEMP_SCALE))

        band_to_temp = {
            "off": 0,
            "eco": eco_raw,
            "comfort": comfort_raw,
            "comfort2": comfort2_raw,
        }

        events = []
        for slot in schedule.get("slots", []):
            band = slot["band"]
            temp = band_to_temp.get(band, 0)
            start_parts = slot["start"].split(":")
            end_parts = slot["end"].split(":")
            start_offset = int(start_parts[0]) * 60 + int(start_parts[1])
            end_offset = int(end_parts[0]) * 60 + int(end_parts[1])

            for day in slot["days"]:
                base = DAY_OFFSETS[day]
                events.append((base + start_offset, temp))
                events.append((base + end_offset, 0))

        for day in DAY_NAMES:
            base = DAY_OFFSETS[day]
            events.append((base, 0))

        events.sort(key=lambda e: (e[0], -e[1]))

        deduped = []
        prev_temp = None
        seen_minutes = set()
        for minute, temp in events:
            if minute in seen_minutes:
                continue
            seen_minutes.add(minute)
            if temp != prev_temp:
                deduped.append((minute, temp))
                prev_temp = temp

        data = []
        for minute, temp in deduped:
            data.extend([str(minute), str(temp)])

        count = len(deduped) * 2 + 5
        return [
            "H24", str(count), "#13", str(program_index),
            str(eco_raw), str(comfort_raw), str(comfort2_raw),
            *data,
        ]

    @staticmethod
    def validate_schedule(data) -> str | None:
        """Validate a schedule dict. Returns error string or None."""
        if not isinstance(data, dict):
            return "invalid_schedule"

        for key in ("eco", "comfort", "comfort2"):
            val = data.get(key)
            if val is None:
                return "invalid_schedule"
            try:
                val = float(val)
            except (TypeError, ValueError):
                return "invalid_temperature"
            if not 10.0 <= val <= 40.0:
                return "invalid_temperature"

        slots = data.get("slots")
        if not isinstance(slots, list):
            return "invalid_schedule"

        day_intervals: dict[str, list[tuple[int, int]]] = {}
        for slot in slots:
            if not isinstance(slot, dict):
                return "invalid_schedule"

            days = slot.get("days")
            if not isinstance(days, list) or not days:
                return "invalid_day"
            for d in days:
                if d not in DAY_NAMES:
                    return "invalid_day"

            for field in ("start", "end"):
                val = slot.get(field, "")
                if not isinstance(val, str):
                    return "invalid_time"
                parts = val.split(":")
                if len(parts) != 2:
                    return "invalid_time"
                try:
                    h, m = int(parts[0]), int(parts[1])
                except ValueError:
                    return "invalid_time"
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    return "invalid_time"

            start_m = int(slot["start"].split(":")[0]) * 60 + int(slot["start"].split(":")[1])
            end_m = int(slot["end"].split(":")[0]) * 60 + int(slot["end"].split(":")[1])
            if start_m >= end_m:
                return "invalid_time"

            band = slot.get("band", "")
            if band not in BAND_NAMES or band == "off":
                return "invalid_schedule"

            for d in days:
                day_intervals.setdefault(d, []).append((start_m, end_m))

        for d, intervals in day_intervals.items():
            intervals.sort()
            for i in range(len(intervals) - 1):
                if intervals[i][1] > intervals[i + 1][0]:
                    return "overlapping_slots"

        return None
