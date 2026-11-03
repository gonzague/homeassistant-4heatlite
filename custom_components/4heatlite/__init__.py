"""The 4HEAT Lite integration."""

import logging
import socket

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import FourHeatLiteApi
from .const import (
    CONF_ACTIVE_SCHEDULE,
    CONF_CACHED_SCHEDULE,
    CONF_CACHED_SCHEDULES,
    CONF_DEVICE_ID,
    CONF_MODULE_ADDRESS,
    CONF_PROXY_MODE,
    CONF_SCHEDULE_ENABLED,
    DATA_COORDINATOR,
    DOMAIN,
    NUM_SCHEDULE_SLOTS,
    PROXY_MODE_DIRECT,
    PROXY_MODE_KEEPALIVE,
    PROXY_MODE_LOCAL,
    SERVICE_GET_SCHEDULE,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import FourHeatLiteCoordinator
from .discovery import discover_module_by_id
from .proxy import (
    ProxyDiagView,
    StoveCommandsView,
    StoveCronView,
    StoveRegisterView,
    StoveStoreView,
    StoveTimeAlignView,
    enqueue_command,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CLIMATE]
DATA_PLATFORMS = "platforms"
PROXY_STATE = "proxy_state"


async def _async_resolve_host(hass: HomeAssistant, host: str) -> str:
    """Resolve a hostname to its IPv4 address. Returns the original host on failure."""
    try:
        result = await hass.async_add_executor_job(
            socket.getaddrinfo, host, None, socket.AF_INET, socket.SOCK_STREAM
        )
        if result:
            return result[0][4][0]
    except OSError:
        pass
    return host


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up 4HEAT Lite from a config entry."""
    proxy_mode = entry.options.get(CONF_PROXY_MODE, PROXY_MODE_DIRECT)
    device_id = entry.data.get(CONF_DEVICE_ID, "")
    stored_host = entry.data[CONF_HOST]

    if device_id:
        fresh_ip = await hass.async_add_executor_job(
            discover_module_by_id, device_id
        )
        if fresh_ip:
            host = fresh_ip
            if fresh_ip != stored_host:
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_HOST: fresh_ip}
                )
                _LOGGER.info(
                    "Device %s IP changed: %s -> %s", device_id, stored_host, fresh_ip
                )
        else:
            host = await _async_resolve_host(hass, stored_host)
    else:
        host = await _async_resolve_host(hass, stored_host)

    coordinator = FourHeatLiteCoordinator(hass, host)

    hass.data.setdefault(DOMAIN, {})

    coordinator.set_proxy_mode(proxy_mode in (PROXY_MODE_LOCAL, PROXY_MODE_KEEPALIVE))


    proxy_state = hass.data[DOMAIN].get(PROXY_STATE)
    if proxy_state is None:
        proxy_state = {"devices": {}, "hosts": {}, "pending": {}, "hass": hass}
        hass.data[DOMAIN][PROXY_STATE] = proxy_state

    module_address = entry.options.get(CONF_MODULE_ADDRESS, "") or host

    device_entry = {
        "coordinator": coordinator,
        "proxy_mode": proxy_mode,
        "host": host,
        "module_address": module_address,
        "entry_id": entry.entry_id,
        "device_key": entry.data.get("device_key", ""),
    }

    if device_id:
        proxy_state["devices"][device_id] = device_entry
        proxy_state["hosts"][host] = device_id
    else:
        proxy_state["pending"][entry.entry_id] = device_entry

    if not proxy_state.get("_views_registered"):
        hass.http.register_view(StoveRegisterView(proxy_state))
        hass.http.register_view(StoveCommandsView(proxy_state))
        hass.http.register_view(StoveStoreView(proxy_state))
        hass.http.register_view(StoveCronView(proxy_state))
        hass.http.register_view(StoveTimeAlignView(proxy_state))
        hass.http.register_view(ProxyDiagView(proxy_state))
        proxy_state["_views_registered"] = True

    if not hass.data[DOMAIN].get("_services_registered"):
        _register_services(hass)
        hass.data[DOMAIN]["_services_registered"] = True

    entry_data = {
        DATA_COORDINATOR: coordinator,
    }

    entry_data[DATA_PLATFORMS] = list(PLATFORMS)

    hass.data[DOMAIN][entry.entry_id] = entry_data

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


def _resolve_entry(hass: HomeAssistant, config_entry_id: str | None = None):
    """Find entry data and device entry for a service call."""
    domain_data = hass.data.get(DOMAIN, {})
    proxy_state = domain_data.get(PROXY_STATE, {})

    if config_entry_id:
        entry_data = domain_data.get(config_entry_id)
        if not entry_data:
            raise HomeAssistantError(f"Config entry {config_entry_id} not found")
    else:
        entries = {
            k: v for k, v in domain_data.items()
            if k not in (PROXY_STATE, "_services_registered") and isinstance(v, dict)
        }
        if len(entries) == 1:
            config_entry_id, entry_data = next(iter(entries.items()))
        elif not entries:
            raise HomeAssistantError("No 4HEAT Lite stoves configured")
        else:
            raise HomeAssistantError(
                "Multiple stoves configured — specify config_entry_id"
            )

    device_entry = None
    for dev in proxy_state.get("devices", {}).values():
        if dev.get("entry_id") == config_entry_id:
            device_entry = dev
            break

    return entry_data, device_entry


def _register_services(hass: HomeAssistant) -> None:
    """Register get_schedule and set_schedule services."""

    async def async_get_schedule(call: ServiceCall):
        entry_data, device_entry = _resolve_entry(
            hass, call.data.get("config_entry_id")
        )

        schedule = None
        if device_entry:
            schedule = device_entry.get("last_schedule")

        if schedule is None:
            coordinator = entry_data.get(DATA_COORDINATOR)
            if coordinator:
                schedule = await hass.async_add_executor_job(
                    coordinator.api.query_schedule
                )

        if schedule is None:
            raise HomeAssistantError("Failed to read schedule from module")

        return schedule

    async def async_set_schedule(call: ServiceCall):
        entry_data, device_entry = _resolve_entry(
            hass, call.data.get("config_entry_id")
        )

        schedule = call.data["schedule"]
        error = FourHeatLiteApi.validate_schedule(schedule)
        if error:
            raise HomeAssistantError(f"Invalid schedule: {error}")

        program_index = call.data.get("program_index", 0)
        cmd = FourHeatLiteApi.build_schedule_command(schedule, program_index)
        coordinator = entry_data.get(DATA_COORDINATOR)

        tcp_ok = False
        if coordinator:
            result = await hass.async_add_executor_job(
                coordinator.api.send_command, cmd
            )
            if result and len(result) >= 3 and str(result[2]) == "OK":
                tcp_ok = True

        proxy_state = hass.data[DOMAIN].get(PROXY_STATE, {})
        device_id = None
        for did, dev in proxy_state.get("devices", {}).items():
            if dev is device_entry:
                device_id = did
                break

        if device_id:
            enqueue_command(proxy_state, device_id, cmd)

        if not tcp_ok and not device_id:
            raise HomeAssistantError(
                "Failed to deliver schedule: no TCP and no proxy queue"
            )

        if device_entry:
            device_entry["last_schedule"] = schedule

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        async_get_schedule,
        schema=vol.Schema({
            vol.Optional("config_entry_id"): cv.string,
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        async_set_schedule,
        schema=vol.Schema({
            vol.Optional("config_entry_id"): cv.string,
            vol.Required("schedule"): dict,
            vol.Optional("program_index", default=0): vol.All(
                int, vol.Range(min=0, max=NUM_SCHEDULE_SLOTS - 1)
            ),
        }),
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to current version."""
    if entry.version == 1:
        options = dict(entry.options)
        old_mode = options.get(CONF_PROXY_MODE, PROXY_MODE_LOCAL)
        if old_mode == "cloud_sync":
            options[CONF_PROXY_MODE] = PROXY_MODE_DIRECT
        data = dict(entry.data)
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=2
        )
        _LOGGER.info("Migrated config entry %s to version 2", entry.entry_id)

    if entry.version == 2:
        options = dict(entry.options)
        old_enabled = options.pop(CONF_SCHEDULE_ENABLED, True)
        old_schedule = options.pop(CONF_CACHED_SCHEDULE, None)
        options[CONF_ACTIVE_SCHEDULE] = 0 if old_enabled else None
        options[CONF_CACHED_SCHEDULES] = [
            old_schedule, None, None
        ]
        hass.config_entries.async_update_entry(
            entry, options=options, version=3
        )
        _LOGGER.info("Migrated config entry %s to version 3", entry.entry_id)

    if entry.version == 3:
        options = dict(entry.options)
        old_schedules = options.get(CONF_CACHED_SCHEDULES, [None] * 3)
        old_active = options.get(CONF_ACTIVE_SCHEDULE)
        new_schedules = []
        for i, sched in enumerate(old_schedules):
            if sched is None:
                sched = {"eco": 18, "comfort": 21, "comfort2": 23, "slots": []}
            sched = dict(sched)
            sched["name"] = f"Schedule {i + 1}"
            sched["active"] = old_active == i
            new_schedules.append(sched)
        options[CONF_CACHED_SCHEDULES] = new_schedules
        options[CONF_ACTIVE_SCHEDULE] = old_active
        hass.config_entries.async_update_entry(
            entry, options=options, version=4
        )
        _LOGGER.info("Migrated config entry %s to version 4", entry.entry_id)

    if entry.version == 4:
        data = dict(entry.data)
        host = data.get(CONF_HOST, "")
        resolved = await _async_resolve_host(hass, host)
        data[CONF_HOST] = resolved
        hass.config_entries.async_update_entry(
            entry, data=data, version=5
        )
        _LOGGER.info("Migrated config entry %s to version 5", entry.entry_id)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})

    platforms = entry_data.get(DATA_PLATFORMS, PLATFORMS)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    if unload_ok:
        proxy_state = hass.data[DOMAIN].get(PROXY_STATE)
        if proxy_state:
            proxy_state["pending"].pop(entry.entry_id, None)

            remove_ids = [
                did
                for did, d in proxy_state["devices"].items()
                if d.get("entry_id") == entry.entry_id
            ]
            for did in remove_ids:
                proxy_state["devices"].pop(did, None)

            remove_hosts = [
                h for h, did in proxy_state["hosts"].items() if did in remove_ids
            ]
            for h in remove_hosts:
                proxy_state["hosts"].pop(h, None)

        hass.data[DOMAIN].pop(entry.entry_id, None)

        remaining = [
            k for k in hass.data[DOMAIN]
            if k not in (PROXY_STATE, "_services_registered")
        ]
        if not remaining and hass.data[DOMAIN].get("_services_registered"):
            hass.services.async_remove(DOMAIN, SERVICE_GET_SCHEDULE)
            hass.services.async_remove(DOMAIN, SERVICE_SET_SCHEDULE)
            hass.data[DOMAIN].pop("_services_registered", None)

    return unload_ok
