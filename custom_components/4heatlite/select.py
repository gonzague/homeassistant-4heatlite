"""Configured ducted-air level; independent of combustion power."""

from homeassistant.components.select import SelectEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.const import CONF_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN, PROFILE_JOLLYMEC


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    if coordinator.api.profile == PROFILE_JOLLYMEC:
        entity = DuctedFanLevel(coordinator, entry.data[CONF_NAME])
        # Replace the numeric control from earlier development versions.
        registry = er.async_get(hass)
        old_id = registry.async_get_entity_id("number", DOMAIN, entity.unique_id)
        old = registry.async_get(old_id) if old_id else None
        if old is not None and old.config_entry_id == entry.entry_id:
            if old.name:
                entity._attr_name = old.name
            registry.async_remove(old_id)
        async_add_entities([entity])


class DuctedFanLevel(CoordinatorEntity, SelectEntity):
    """Level set on canalization 1; zero disables that outlet, not the stove."""

    _attr_has_entity_name = True
    _attr_translation_key = "ducted_fan_1"
    _attr_options = ["off", "1", "2", "3", "4", "5", "6"]
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
    def current_option(self):
        value = (self.coordinator.data or {}).get("ducted_fan_1")
        if type(value) is not int or not 0 <= value <= 6:
            return None
        return "off" if value == 0 else str(value)

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise HomeAssistantError("Unsupported ducted fan option")
        value = 0 if option == "off" else int(option)
        try:
            actual = await self.hass.async_add_executor_job(
                self.coordinator.api.set_ducted_fan, int(value)
            )
        except ValueError as exc:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(str(exc)) from exc
        self.coordinator.push_data({"ducted_fan_1": actual})
        await self.coordinator.async_request_refresh()
