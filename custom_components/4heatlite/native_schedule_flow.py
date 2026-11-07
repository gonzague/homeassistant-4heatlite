"""Options forms for the stove's autonomous native chronothermostat."""

from copy import deepcopy

import voluptuous as vol
from homeassistant.helpers.selector import BooleanSelector, SelectSelector, TimeSelector

from .const import DATA_COORDINATOR, DAY_NAMES, DOMAIN, PROFILE_JOLLYMEC
from .native_schedule import NativeScheduleError, validate_native_schedule

GROUPS = {day: [i] for i, day in enumerate(DAY_NAMES)} | {
    "weekdays": list(range(5)), "weekend": [5, 6], "all": list(range(7)),
}


class NativeScheduleFlowMixin:
    """Read fresh on entry, stage edits, review, then save with a readback."""

    def _native_api(self):
        coordinator = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id, {}
        ).get(DATA_COORDINATOR)
        if coordinator and coordinator.api.profile == PROFILE_JOLLYMEC:
            return coordinator.api
        return None

    async def async_step_native(self, user_input=None):
        if user_input is None:
            api = self._native_api()
            if api is None:
                return self.async_abort(reason="native_read_failed")
            baseline = await self.hass.async_add_executor_job(api.query_schedule)
            if baseline is None:
                return self.async_abort(reason="native_read_failed")
            if validate_native_schedule(baseline):
                return self.async_abort(reason="native_unsupported")
            self._native_baseline = baseline
            self._native_draft = deepcopy(baseline)
        else:
            mode = int(user_input["mode"])
            self._native_draft["mode_raw"] = mode
            if mode == 0:
                return await self.async_step_native_review()
            if mode == 1:
                return await self.async_step_native_day()
            self._native_group = "all" if mode == 2 else "weekdays"
            return await self.async_step_native_slots()
        return self.async_show_form(
            step_id="native",
            data_schema=vol.Schema({
                vol.Required("mode", default=str(baseline["mode_raw"])): SelectSelector({
                    "options": ["1", "2", "3", "0"], "translation_key": "native_mode",
                    "mode": "dropdown",
                }),
            }),
        )

    async def async_step_native_day(self, user_input=None):
        """Daily mode alone lets the user choose a single weekday."""
        if user_input is not None:
            self._native_group = user_input["day"]
            return await self.async_step_native_slots()
        return self.async_show_form(
            step_id="native_day",
            data_schema=vol.Schema({
                vol.Required("day", default="mon"): SelectSelector({
                    "options": list(DAY_NAMES), "translation_key": "native_days",
                    "mode": "dropdown",
                }),
            }),
            description_placeholders={"schedule": self._native_summary(self._native_draft)},
        )

    async def async_step_native_slots(self, user_input=None):
        errors = {}
        indices = GROUPS[self._native_group]
        slots = self._native_draft["days"][indices[0]]["slots"]
        if user_input is not None:
            slots = []
            for i in range(1, 4):
                start, end = user_input[f"start_{i}"], user_input[f"end_{i}"]
                # HA time selectors can return seconds; never round them silently.
                for value in (start, end):
                    if len(value) > 5 and value[5:] != ":00":
                        errors["base"] = "invalid_time"
                slots.append({"start": start[:5], "end": end[:5],
                              "flag_raw": int(user_input[f"enabled_{i}"])})
            draft = deepcopy(self._native_draft)
            for index in indices:
                draft["days"][index]["slots"] = deepcopy(slots)
            if error := validate_native_schedule(draft):
                errors["base"] = error
            if not errors:
                self._native_draft = draft
                if draft["mode_raw"] == 3 and self._native_group == "weekdays":
                    self._native_group = "weekend"
                    return await self.async_step_native_slots()
                if draft["mode_raw"] == 1 and user_input.get("next_action") == "another_day":
                    return await self.async_step_native_day()
                return await self.async_step_native_review()
        schema = {}
        for i, slot in enumerate(slots, 1):
            schema[vol.Required(f"enabled_{i}", default=bool(slot["flag_raw"]))] = BooleanSelector()
            schema[vol.Required(f"start_{i}", default=slot["start"])] = TimeSelector()
            schema[vol.Required(f"end_{i}", default=slot["end"])] = TimeSelector()
        if self._native_draft["mode_raw"] == 1:
            schema[vol.Required("next_action", default="review")] = SelectSelector({
                "options": ["review", "another_day"], "translation_key": "native_next",
            })
        french = self._native_french()
        if self._native_draft["mode_raw"] == 3 and self._native_group == "weekdays":
            next_step = "Ensuite : les créneaux du samedi et du dimanche." if french else "Next: Saturday and Sunday time slots."
        else:
            next_step = "Ensuite : récapitulatif avant enregistrement." if french else "Next: review before saving."
        return self.async_show_form(
            step_id="native_slots", data_schema=vol.Schema(schema), errors=errors,
            description_placeholders={
                "days": ", ".join(self._native_day_labels()[i] for i in indices),
                "next_step": next_step,
            },
        )

    async def async_step_native_review(self, user_input=None):
        if user_input is not None:
            api = self._native_api()
            if api is None:
                return self.async_abort(reason="native_read_failed")
            try:
                actual = await self.hass.async_add_executor_job(
                    api.write_native_schedule, self._native_draft, self._native_baseline
                )
            except NativeScheduleError as exc:
                # End the flow on uncertainty/conflict; a fresh flow reads reality.
                return self.async_abort(reason=str(exc))
            self._update_proxy_schedule(actual)
            return self.async_abort(reason="native_saved")
        return self.async_show_form(
            step_id="native_review", data_schema=vol.Schema({}),
            description_placeholders={
                "before": self._native_summary(self._native_baseline),
                "after": self._native_summary(self._native_draft),
            },
        )

    def _native_french(self):
        return getattr(getattr(self.hass, "config", None), "language", "en").startswith("fr")

    def _native_day_labels(self):
        if self._native_french():
            return ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def _native_summary(self, schedule):
        modes = (["Désactivé", "Journalier", "Hebdomadaire", "Semaine / week-end"]
                 if self._native_french() else ["Disabled", "Daily", "Weekly", "Weekday / weekend"])
        mode = modes[schedule["mode_raw"]]
        lines = [f"**{mode}**"]
        for label, day in zip(self._native_day_labels(), schedule["days"], strict=True):
            slots = [f"{'☑' if s['flag_raw'] else '☐'} {s['start']}–{s['end']}" for s in day["slots"]]
            lines.append(f"- **{label}** : " + " · ".join(slots))
        return lines[0] + "\n\n" + "\n".join(lines[1:])
