"""Configured ducted-air level; independent of combustion power."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import CONF_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN, PROFILE_JOLLYMEC


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    if coordinator.api.profile == PROFILE_JOLLYMEC:
        async_add_entities([DuctedFanLevel(coordinator, entry.data[CONF_NAME])])


class DuctedFanLevel(CoordinatorEntity, NumberEntity):
    """Level set on canalization 1; zero disables that outlet, not the stove."""

    _attr_has_entity_name = True
    _attr_translation_key = "ducted_fan_1"
    _attr_native_min_value = 0
    _attr_native_max_value = 6
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:fan"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator)
        self._stove_name = stove_name
        self._attr_unique_id = f"{stove_name}_ducted_fan_1_control"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._stove_name)}, "name": self._stove_name,
                "manufacturer": "4HEAT", "model": "Lite"}

    @property
    def native_value(self):
        value = (self.coordinator.data or {}).get("ducted_fan_1")
        return value if type(value) is int and 0 <= value <= 6 else None

    async def async_set_native_value(self, value: float) -> None:
        if isinstance(value, bool) or not 0 <= value <= 6 or not float(value).is_integer():
            raise HomeAssistantError("Ducted fan level must be an integer from 0 to 6")
        try:
            actual = await self.hass.async_add_executor_job(
                self.coordinator.api.set_ducted_fan, int(value)
            )
        except ValueError as exc:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(str(exc)) from exc
        self.coordinator.push_data({"ducted_fan_1": actual})
        await self.coordinator.async_request_refresh()
