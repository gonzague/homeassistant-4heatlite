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
                "review": self._native_review_summary(),
            },
        )

    def _native_french(self):
        return getattr(getattr(self.hass, "config", None), "language", "en").startswith("fr")

    def _native_day_labels(self):
        if self._native_french():
            return ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def _native_mode_label(self, mode):
        modes = (["Désactivé", "Journalier", "Hebdomadaire", "Fin de semaine"]
                 if self._native_french() else ["Disabled", "Daily", "Weekly", "Weekday / weekend"])
        return modes[mode]

    def _native_grouped_lines(self, values):
        """Combine consecutive days with identical display text, never data."""
        labels = self._native_day_labels()
        lines = []
        first = 0
        while first < len(values):
            last = first
            while last + 1 < len(values) and values[last + 1] == values[first]:
                last += 1
            if values[first]:
                label = labels[first] if first == last else f"{labels[first]}–{labels[last]}"
                if first == 0 and last == 6:
                    label = "Tous les jours" if self._native_french() else "Every day"
                lines.append(f"- **{label}** : {values[first]}")
            first = last + 1
        return lines

    def _native_summary(self, schedule):
        mode = self._native_mode_label(schedule["mode_raw"])
        if schedule["mode_raw"] == 0:
            note = ("Aucun déclenchement automatique. Les horaires restent mémorisés."
                    if self._native_french() else "No automatic starts. Stored times are retained.")
            return f"**{mode}**\n\n{note}"
        empty = "Aucun créneau actif" if self._native_french() else "No enabled slots"
        values = []
        for day in schedule["days"]:
            slots = [f"{s['start']}–{s['end']}" for s in day["slots"] if s["flag_raw"]]
            values.append(" · ".join(slots) or empty)
        return f"**{mode}**\n\n" + "\n".join(self._native_grouped_lines(values))

    def _native_review_summary(self):
        """Show one compact program and explicit edits, including inactive slots."""
        before, after = self._native_baseline, self._native_draft
        french = self._native_french()
        changes = []
        if before["mode_raw"] != after["mode_raw"]:
            changes.append(f"- Mode : {self._native_mode_label(before['mode_raw'])} → {self._native_mode_label(after['mode_raw'])}")

        def describe(slot):
            status = (("activé" if slot["flag_raw"] else "désactivé") if french
                      else ("enabled" if slot["flag_raw"] else "disabled"))
            return f"{slot['start']}–{slot['end']} ({status})"

        day_changes = []
        for old_day, new_day in zip(before["days"], after["days"], strict=True):
            edits = []
            for i, (old, new) in enumerate(zip(old_day["slots"], new_day["slots"], strict=True), 1):
                if old != new:
                    label = "créneau" if french else "slot"
                    edits.append(f"{label} {i} : {describe(old)} → {describe(new)}")
            day_changes.append(" ; ".join(edits))
        changes.extend(self._native_grouped_lines(day_changes))
        if not changes:
            heading = "Aucune modification" if french else "No changes"
            return f"**{heading}**\n\n" + self._native_summary(after)
        heading = "Programme à enregistrer" if french else "Program to save"
        change_heading = "Modifications" if french else "Changes"
        return f"**{heading}**\n\n{self._native_summary(after)}\n\n**{change_heading}**\n\n" + "\n".join(changes)
