"""Sensor platform for 4HEAT Lite."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN, ERROR_NAMES, JOLLYMEC_ERROR_NAMES, STATE_NAMES, PROFILE_JOLLYMEC
from .coordinator import FourHeatLiteCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FourHeatLiteCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    name = entry.data[CONF_NAME]

    entities = [
        StoveStateSensor(coordinator, name),
        StoveErrorSensor(coordinator, name),
        ExhaustTemperatureSensor(coordinator, name),
        RoomTemperatureSensor(coordinator, name),
        TargetTemperatureSensor(coordinator, name),
        PowerLevelSensor(coordinator, name),
    ]

    for defn in REGISTER_SENSOR_DEFS:
        if defn["key"] == "ducted_fan_1" and coordinator.api.profile == PROFILE_JOLLYMEC:
            defn = {**defn, "enabled_default": True, "zero_means_absent": False}
        entities.append(RegisterSensor(coordinator, name, defn))

    async_add_entities(entities)


class FourHeatLiteEntity(CoordinatorEntity):
    """Base entity for 4HEAT Lite."""

    def __init__(self, coordinator: FourHeatLiteCoordinator, stove_name: str) -> None:
        super().__init__(coordinator)
        self._stove_name = stove_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._stove_name)},
            "name": self._stove_name,
            "manufacturer": "4HEAT",
            "model": "Lite",
        }


class StoveStateSensor(FourHeatLiteEntity, SensorEntity):
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} State"
        self._attr_unique_id = f"{stove_name}_state"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        state = self.coordinator.data["state"]
        if self.coordinator.api.profile == PROFILE_JOLLYMEC and state == 7:
            return "Final cleaning"
        return STATE_NAMES.get(state, f"Unknown ({state})")

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return None
        return {"state_code": self.coordinator.data["state"]}


class StoveErrorSensor(FourHeatLiteEntity, SensorEntity):
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        label = "Reported Alarm" if coordinator.api.profile == PROFILE_JOLLYMEC else "Error"
        self._attr_name = f"{stove_name} {label}"
        self._attr_unique_id = f"{stove_name}_error"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        error = self.coordinator.data["error"]
        if self.coordinator.api.profile == PROFILE_JOLLYMEC:
            return JOLLYMEC_ERROR_NAMES.get(error, f"Unknown (raw {error})")
        return ERROR_NAMES.get(error, f"Unknown ({error})")

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return None
        error = self.coordinator.data["error"]
        attributes = {"error_code": error}
        if self.coordinator.api.profile == PROFILE_JOLLYMEC:
            attributes["error_code_raw"] = error
        return attributes


class ExhaustTemperatureSensor(FourHeatLiteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Exhaust Temperature"
        self._attr_unique_id = f"{stove_name}_exhaust_temp"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("exhaust_temp")


class RoomTemperatureSensor(FourHeatLiteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Room Temperature"
        self._attr_unique_id = f"{stove_name}_room_temp"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["room_temp"]


class TargetTemperatureSensor(FourHeatLiteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:thermometer-check"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Target Temperature"
        self._attr_unique_id = f"{stove_name}_target_temp"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("target_temp")


class PowerLevelSensor(FourHeatLiteEntity, SensorEntity):
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Power Level"
        self._attr_unique_id = f"{stove_name}_power_level"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("power")


REGISTER_SENSOR_DEFS = [
    {
        "key": "remote_room_temp",
        "name": "Remote Room Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
        "precision": 1,
        "zero_means_absent": True,
    },
    {
        "key": "remote_room_temp_2",
        "name": "Remote Room Temperature 2",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
        "precision": 1,
        "zero_means_absent": True,
    },
    {
        "key": "airflow",
        "name": "Airflow",
        "icon": "mdi:fan",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "heating_fan_power",
        "name": "Heating Fan Power",
        "icon": "mdi:fan",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "ducted_fan_1",
        "name": "Ducted Fan 1",
        "icon": "mdi:fan",
        "state_class": SensorStateClass.MEASUREMENT,
        "enabled_default": False,
        "zero_means_absent": True,
    },
    {
        "key": "ducted_fan_2",
        "name": "Ducted Fan 2",
        "icon": "mdi:fan",
        "state_class": SensorStateClass.MEASUREMENT,
        "enabled_default": False,
        "zero_means_absent": True,
    },
    {
        "key": "cleaning_counter",
        "name": "Cleaning Counter",
        "icon": "mdi:broom",
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    {
        "key": "service_counter",
        "name": "Service Counter",
        "icon": "mdi:wrench",
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "enabled_default": False,
    },
]


class RegisterSensor(FourHeatLiteEntity, SensorEntity):
    """Generic sensor driven by a register definition."""

    def __init__(self, coordinator, stove_name, definition):
        super().__init__(coordinator, stove_name)
        self._data_key = definition["key"]
        self._zero_means_absent = definition.get("zero_means_absent", False)
        self._attr_name = f"{stove_name} {definition['name']}"
        self._attr_unique_id = f"{stove_name}_{definition['key']}"
        if definition.get("device_class"):
            self._attr_device_class = definition["device_class"]
        if definition.get("unit"):
            self._attr_native_unit_of_measurement = definition["unit"]
        if definition.get("state_class"):
            self._attr_state_class = definition["state_class"]
        if definition.get("precision") is not None:
            self._attr_suggested_display_precision = definition["precision"]
        if definition.get("icon"):
            self._attr_icon = definition["icon"]
        if definition.get("entity_category"):
            self._attr_entity_category = definition["entity_category"]
        if not definition.get("enabled_default", True):
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._data_key)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self._zero_means_absent:
            val = self.coordinator.data.get(self._data_key) if self.coordinator.data else None
            if val is not None and val == 0:
                return False
        return True
