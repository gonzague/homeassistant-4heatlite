"""Native CCS chronothermostat validation and encoding (separate from H24)."""

import re

from .const import DAY_NAMES


class NativeScheduleError(Exception):
    """A schedule was rejected, changed concurrently, or not verified."""


def validate_native_schedule(schedule: dict) -> str | None:
    """Accept only the verified seven-day, three-slot CCS dialect."""
    if not isinstance(schedule, dict):
        return "native_invalid"
    mode = schedule.get("mode_raw")
    if type(mode) is not int or mode not in range(4):
        return "native_invalid"
    days = schedule.get("days")
    if not isinstance(days, list) or len(days) != 7:
        return "native_invalid"
    for day, name in zip(days, DAY_NAMES, strict=True):
        if not isinstance(day, dict) or day.get("day") != name:
            return "native_invalid"
        slots = day.get("slots")
        if not isinstance(slots, list) or len(slots) != 3:
            return "native_invalid"
        active = []
        for slot in slots:
            if not isinstance(slot, dict):
                return "native_invalid"
            flag = slot.get("flag_raw")
            if type(flag) is not int or flag not in (0, 1):
                return "native_invalid"
            start, end = slot.get("start"), slot.get("end")
            if any(not isinstance(t, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", t) for t in (start, end)):
                return "invalid_time"
            if flag:
                # Overnight semantics have not been verified for this dialect.
                if start >= end:
                    return "invalid_time"
                active.append((start, end))
        active.sort()
        if any(left[1] > right[0] for left, right in zip(active, active[1:])):
            return "overlapping_slots"
    return None


def build_native_schedule(schedule: dict) -> list[str]:
    """Encode a complete program; never infer or change unedited values."""
    if error := validate_native_schedule(schedule):
        raise NativeScheduleError(error)
    command = ["CCS", "71", str(schedule["mode_raw"])]
    for index, day in enumerate(schedule["days"], 1):
        command.append(str(index))
        for slot in day["slots"]:
            command.extend((slot["start"], slot["end"], str(slot["flag_raw"])))
    return command
