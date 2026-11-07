"""Binary sensor platform for 4HEAT Lite."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN, PROFILE_JOLLYMEC
from .coordinator import FourHeatLiteCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FourHeatLiteCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    name = entry.data[CONF_NAME]
    async_add_entities([
        StoveRunningSensor(coordinator, name),
        StoveErrorActiveSensor(coordinator, name),
    ])


class StoveRunningSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator)
        self._stove_name = stove_name
        self._attr_name = f"{stove_name} Running"
        self._attr_unique_id = f"{stove_name}_running"

    @property
    def is_on(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["state"] != 0

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._stove_name)},
            "name": self._stove_name,
            "manufacturer": "4HEAT",
            "model": "Lite",
        }


class StoveErrorActiveSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator)
        self._stove_name = stove_name
        self._attr_name = f"{stove_name} Error Active"
        self._attr_unique_id = f"{stove_name}_error_active"

    @property
    def is_on(self):
        if self.coordinator.data is None:
            return None
        if self.coordinator.api.profile == PROFILE_JOLLYMEC:
            state = self.coordinator.data.get("state")
            if state == 9:
                return True
            if state == 0:
                return False
            # A nonzero alarm byte can survive acknowledgement and OFF.
            # Its active/retained meaning in other states is not established.
            if self.coordinator.data["error"] != 0:
                return None
        return self.coordinator.data["error"] != 0

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._stove_name)},
            "name": self._stove_name,
            "manufacturer": "4HEAT",
            "model": "Lite",
        }
