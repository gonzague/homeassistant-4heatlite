"""DataUpdateCoordinator for 4HEAT Lite."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FourHeatLiteApi
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, PROXY_POLL_INTERVAL, PROFILE_LASIAN

_LOGGER = logging.getLogger(__name__)


class FourHeatLiteCoordinator(DataUpdateCoordinator):
    """Fetch sensor data from the 4HEAT Lite module."""

    def __init__(self, hass: HomeAssistant, host: str, profile: str = PROFILE_LASIAN) -> None:
        self.api = FourHeatLiteApi(host, profile)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    def set_proxy_mode(self, enabled: bool) -> None:
        """Switch to longer poll interval when proxy provides real-time data."""
        if enabled:
            self.update_interval = timedelta(seconds=PROXY_POLL_INTERVAL)

    def push_data(self, data: dict) -> None:
        """Inject sensor data from proxy store endpoint."""
        if self.data:
            merged = dict(self.data)
            merged.update(data)
        else:
            merged = data
        self.async_set_updated_data(merged)

    async def _async_update_data(self) -> dict:
        data = await self.hass.async_add_executor_job(self.api.query_sensors)
        if data is None:
            raise UpdateFailed("Failed to query 4HEAT Lite module")
        config = await self.hass.async_add_executor_job(self.api.query_config)
        if config:
            data.update(config)
        # A cache response can omit an individual register. Retain its last
        # valid sample; explicit None still clears an invalid/sentinel value.
        return {**(self.data or {}), **data}
