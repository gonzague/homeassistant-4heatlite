"""Cloud API proxy for 4HEAT Lite module.

Responds to module cloud endpoints locally. Required for local_only and
cloud_keepalive modes (DNS/firewall intercepts module traffic). In direct
mode, these endpoints exist but receive no traffic since the module talks
to Azure directly.

Proxy modes:
  direct          — endpoints idle, module talks to Azure
  local_only      — full local interception, no Azure forwarding
  cloud_keepalive — local interception + mirror /register and /store to Azure
"""

import json
import logging
import time
from datetime import datetime, timezone

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .api import FourHeatLiteApi
from .const import (
    AZURE_HTTPS_BASE,
    PROXY_MODE_DIRECT,
    PROXY_MODE_KEEPALIVE,
    STORE_REGISTERS,
    PROFILE_JOLLYMEC,
    PROFILE_LASIAN,
)

_LOGGER = logging.getLogger(__name__)


async def _mirror_to_azure(method: str, path: str, body: dict | None = None,
                           params: dict | None = None) -> dict | None:
    """Fire-and-forget HTTP request to Azure HTTPS endpoint.

    Returns the parsed JSON response on success, None on failure.
    Uses the HTTPS endpoint which is not affected by DNS overrides.
    """
    url = f"{AZURE_HTTPS_BASE}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            if method == "POST":
                async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp_text = await resp.text()
                    if resp.status == 200:
                        _LOGGER.debug(
                            "Azure mirror POST %s → %d: %s", path, resp.status, resp_text[:200]
                        )
                        try:
                            return json.loads(resp_text)
                        except (ValueError, TypeError):
                            return {}
                    else:
                        _LOGGER.warning(
                            "Azure mirror POST %s failed: HTTP %d: %s", path, resp.status, resp_text[:200]
                        )
            elif method == "GET":
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp_text = await resp.text()
                    if resp.status == 200:
                        _LOGGER.debug(
                            "Azure mirror GET %s → %d: %s", path, resp.status, resp_text[:200]
                        )
                        try:
                            return json.loads(resp_text)
                        except (ValueError, TypeError):
                            return {}
                    else:
                        _LOGGER.warning(
                            "Azure mirror GET %s failed: HTTP %d: %s", path, resp.status, resp_text[:200]
                        )
    except Exception:
        _LOGGER.warning("Azure mirror %s %s failed", method, path, exc_info=True)
    return None


def _should_mirror(state) -> bool:
    """Check if any device is in cloud_keepalive mode."""
    for entry in state.get("devices", {}).values():
        if entry.get("proxy_mode") == PROXY_MODE_KEEPALIVE:
            return True
    return False


def _device_should_mirror(entry) -> bool:
    """Check if a specific device entry uses cloud_keepalive mode."""
    return entry.get("proxy_mode") == PROXY_MODE_KEEPALIVE if entry else False


def enqueue_command(state, device_id: str, command: list) -> bool:
    """Add a command to the device's polling queue."""
    entry, did = _lookup_device(state, device_id=device_id)
    if entry and command and command[0] == "H24":
        coordinator = entry.get("coordinator")
        if coordinator and not coordinator.api.supports_schedule_write:
            return False
    if not entry:
        _LOGGER.warning("Cannot enqueue command: device %s not found", device_id)
        return False
    queue = entry.setdefault("command_queue", [])
    queue.append(command)
    _LOGGER.info("Enqueued command for device %s: %.60s...", did, str(command))
    return True


def _lookup_device(state, device_id=None, remote_ip=None):
    """Find device entry by device_id or remote IP."""
    devices = state.get("devices", {})
    if device_id and device_id in devices:
        return devices[device_id], device_id

    if remote_ip:
        hosts = state.get("hosts", {})
        did = hosts.get(remote_ip)
        if did and did in devices:
            return devices[did], did

    return None, None


def _promote_pending(state, device_id, remote_ip):
    """Move a pending entry to devices when device_id is auto-detected."""
    pending = state.get("pending", {})
    devices = state.setdefault("devices", {})

    matched_eid = None
    for eid, pentry in pending.items():
        module_addr = pentry.get("module_address") or pentry.get("host")
        if module_addr == remote_ip:
            matched_eid = eid
            break

    if matched_eid:
        entry = pending.pop(matched_eid)
        entry["entry_id"] = matched_eid
        devices[device_id] = entry
        _LOGGER.info(
            "Auto-detected device ID %s from %s (entry %s)",
            device_id,
            remote_ip,
            matched_eid,
        )
        return entry

    return None


def _validate_module(state, remote_ip):
    """Validate that a request comes from a configured non-direct-mode module.

    Checks request.remote against the configured module_address (falling back
    to host) for each device entry. Only accepts requests whose source IP
    matches the user-configured address.

    Returns (entry, device_id) for active devices, (pending_entry, None) for
    pending entries, or (None, None) if the caller is not recognised or the
    entry uses direct mode.
    """
    if not remote_ip:
        return None, None

    devices = state.get("devices", {})
    for did, entry in devices.items():
        if entry.get("proxy_mode") == PROXY_MODE_DIRECT:
            continue
        module_addr = entry.get("module_address") or entry.get("host")
        if module_addr == remote_ip:
            return entry, did

    pending = state.get("pending", {})
    for _eid, pentry in pending.items():
        if pentry.get("proxy_mode") == PROXY_MODE_DIRECT:
            continue
        module_addr = pentry.get("module_address") or pentry.get("host")
        if module_addr == remote_ip:
            return pentry, None

    return None, None


class StoveRegisterView(HomeAssistantView):
    """POST /api/devices/register — module registers on boot before polling."""

    url = "/api/devices/register"
    name = "api:devices:register"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def post(self, request):
        remote_ip = request.remote

        try:
            body = await request.json()
        except Exception:
            _LOGGER.warning("Register: invalid JSON from %s", remote_ip)
            return self.json({"Key": ""})

        device_id = body.get("Id", "")
        _LOGGER.info(
            "Register from %s: id=%s fw=%s.%s product=%s rssi=%s",
            remote_ip,
            device_id,
            body.get("FirmwareVersion", "?"),
            body.get("FirmwareRevision", "?"),
            body.get("ProductCode", "?"),
            body.get("RSSI", "?"),
        )
        _LOGGER.debug("Register body: %s", json.dumps(body, separators=(",", ":")))

        entry, validated_did = _validate_module(self._state, remote_ip)

        if not entry:
            _LOGGER.debug("Register: rejected request from %s", remote_ip)
            return self.json({"Key": ""})

        if validated_did is None and device_id and remote_ip:
            promoted = _promote_pending(self._state, device_id, remote_ip)
            if promoted:
                entry = promoted
                validated_did = device_id

        if validated_did and device_id and device_id != validated_did:
            _LOGGER.warning(
                "Register: device_id mismatch from %s: expected %s, got %s",
                remote_ip, validated_did, device_id,
            )

        device_key = entry.get("device_key", "")
        if not device_key:
            _LOGGER.warning(
                "No DeviceKey for device %s — reconfigure the integration",
                validated_did or device_id,
            )

        if _device_should_mirror(entry):
            _LOGGER.info("Register: mirroring to Azure for device %s", validated_did or device_id)
            hass = self._state.get("hass")
            if hass:
                hass.async_create_task(
                    _mirror_to_azure("POST", "/api/devices/register", body=body)
                )

        return self.json({"Key": device_key})


class StoveCommandsView(HomeAssistantView):
    """GET /api/devices/commands — module polls for pending write commands."""

    url = "/api/devices/commands"
    name = "api:devices:commands"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def get(self, request):
        remote_ip = request.remote

        entry, device_id = _validate_module(self._state, remote_ip)
        if not entry:
            _LOGGER.debug("Commands: rejected request from %s", remote_ip)
            return self.json([])

        queue = entry.get("command_queue", [])
        if queue:
            commands = [
                {"id": device_id, "comando": cmd} for cmd in queue
            ]
            remove = request.query.get("removefromserver", "").lower()
            if remove == "true":
                entry["command_queue"] = []
            _LOGGER.info(
                "Commands: delivering %d command(s) to %s (remove=%s)",
                len(commands),
                device_id,
                remove,
            )
            _LOGGER.debug("Commands payload: %s", json.dumps(commands, separators=(",", ":")))
            return web.Response(
                body=json.dumps(commands, separators=(",", ":")),
                content_type="application/json",
            )

        _LOGGER.debug("Commands: no pending commands for %s", device_id)
        return self.json([])


class StoveStoreView(HomeAssistantView):
    """POST /api/devices/store — module uploads sensor data."""

    url = "/api/devices/store"
    name = "api:devices:store"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def post(self, request):
        remote_ip = request.remote

        entry, device_id = _validate_module(self._state, remote_ip)
        if not entry:
            _LOGGER.debug("Store: rejected request from %s", remote_ip)
            return self.json({"DeviceId": "", "Assistant": ""})

        device_id = device_id or ""
        ok_response = {"DeviceId": device_id, "Assistant": ""}

        try:
            body = await request.json()
        except Exception:
            _LOGGER.warning("Store: invalid JSON from %s", remote_ip)
            return self.json(ok_response)

        _LOGGER.debug(
            "Store from %s (device %s): %s",
            remote_ip,
            device_id,
            json.dumps(body, separators=(",", ":")),
        )

        values = body.get("Values", [])
        if values and entry:
            coordinator = entry.get("coordinator")
            if coordinator:
                data = self._parse_values(values, coordinator.api.profile)
                if data:
                    _LOGGER.info(
                        "Store: parsed from %s (device %s): %s",
                        remote_ip,
                        device_id,
                        {k: v for k, v in data.items() if k != "raw"},
                    )
                    coordinator.push_data(data)

        if _device_should_mirror(entry):
            _LOGGER.info("Store: mirroring to Azure for device %s", device_id)
            hass = self._state.get("hass")
            if hass:
                hass.async_create_task(
                    _mirror_to_azure("POST", "/api/devices/store", body=body)
                )

        return self.json(ok_response)

    @staticmethod
    def _parse_values(values, profile=PROFILE_LASIAN):
        result = {}
        for hexdata in values:
            if not isinstance(hexdata, str) or len(hexdata) < 4:
                continue
            if len(hexdata) % 2 or any(char not in "0123456789abcdefABCDEF" for char in hexdata):
                continue
            try:
                bytes.fromhex(hexdata)
            except ValueError:
                continue
            hexdata = hexdata.lower()
            if hexdata.startswith("10") and len(hexdata) >= 38:
                result.update(FourHeatLiteApi._decode_0310(hexdata, profile))
                continue
            matched = False
            for prefix, meta in STORE_REGISTERS.items():
                if not hexdata.startswith(prefix):
                    continue
                matched = True
                vals = [int(hexdata[i:i+2], 16) for i in range(0, len(hexdata), 2)]
                group = meta["group"]
                if profile == PROFILE_JOLLYMEC:
                    # Only publish fields whose Jolly Mec register map is known.
                    if len(vals) < 5:
                        break
                    raw = (vals[3] << 8) | vals[4]
                    if prefix == "12fff7":
                        result["room_temp"] = raw if raw < 0x8000 else None
                    elif prefix == "12ffff":
                        result["exhaust_temp"] = raw
                    elif prefix == "12005a":
                        result["target_temp"] = raw
                    elif prefix == "0e016c":
                        result["power_raw"] = raw
                        result["power"] = raw - 1 if 1 <= raw <= 6 else None
                    elif prefix == "0e0266":
                        result["ducted_fan_1"] = raw
                    elif prefix == "0c81":
                        result["module_info"] = hexdata
                    break
                if group == "12" and len(vals) >= 5:
                    raw = (vals[3] << 8) | vals[4]
                    result[meta["key"]] = raw * meta.get("scale", 1)
                elif group == "0e" and len(vals) >= 7:
                    result[meta["key"]] = (vals[5] << 8) | vals[6]
                elif group == "0c":
                    result[meta["key"]] = hexdata
                break
            if not matched:
                _LOGGER.debug(
                    "Store: unrecognized value prefix: %.10s... (%d chars)",
                    hexdata,
                    len(hexdata),
                )
        return result


class StoveCronView(HomeAssistantView):
    """POST /api/devices/cron — module uploads schedule data."""

    url = "/api/devices/cron"
    name = "api:devices:cron"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def post(self, request):
        remote_ip = request.remote

        entry, device_id = _validate_module(self._state, remote_ip)
        if not entry:
            _LOGGER.debug("Cron: rejected request from %s", remote_ip)
            return self.json({"DeviceId": "", "Assistant": ""})

        device_id = device_id or ""
        ok_response = {"DeviceId": device_id, "Assistant": ""}

        try:
            body = await request.json()
        except Exception:
            _LOGGER.warning("Cron: invalid JSON from %s", remote_ip)
            return self.json(ok_response)

        _LOGGER.debug("Cron from %s (device %s): %s", remote_ip, device_id,
                       json.dumps(body, separators=(",", ":")) if isinstance(body, dict) else str(body))

        command = body.get("Command") if isinstance(body, dict) else body
        if isinstance(command, list) and command and entry:
            coordinator = entry.get("coordinator")
            jollymec = coordinator and coordinator.api.profile == PROFILE_JOLLYMEC
            parsed = (
                FourHeatLiteApi.parse_ccg_response(command) if jollymec
                else FourHeatLiteApi.parse_h24_response(command)
            )
            if parsed and entry:
                entry["last_schedule"] = parsed
                _LOGGER.info("Cron: schedule stored for device %s", device_id)

        return self.json(ok_response)


class StoveTimeAlignView(HomeAssistantView):
    """GET /api/Devices/timeAlign — module syncs its clock."""

    url = "/api/Devices/timeAlign"
    name = "api:devices:timealign"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def get(self, request):
        remote_ip = request.remote

        validated, _ = _validate_module(self._state, remote_ip)
        if not validated:
            _LOGGER.debug("TimeAlign: rejected request from %s", remote_ip)
            return web.Response(status=404)

        now = datetime.now(timezone.utc)
        gmt_offset = int(now.astimezone().utcoffset().total_seconds())
        timestamp = int(time.time()) + gmt_offset
        _LOGGER.debug(
            "TimeAlign: gmtOffset=%d timestamp=%d", gmt_offset, timestamp,
        )
        return self.json({
            "gmtOffset": gmt_offset,
            "timestamp": timestamp,
        })


class ProxyDiagView(HomeAssistantView):
    """GET /api/devices/diag — diagnostic endpoint."""

    url = "/api/devices/diag"
    name = "api:devices:diag"
    requires_auth = True

    def __init__(self, state):
        self._state = state

    async def get(self, request):
        try:
            devices = self._state.get("devices", {})
            hosts = self._state.get("hosts", {})
            pending = self._state.get("pending", {})

            result = {
                "device_count": len(devices),
                "host_count": len(hosts),
                "pending_count": len(pending),
                "device_ids": list(devices.keys()),
                "host_map": {k: v for k, v in hosts.items()},
            }

            for did, entry in devices.items():
                result[f"dev_{did}"] = {
                    "proxy_mode": entry.get("proxy_mode", "unknown"),
                    "cloud_mirror": _device_should_mirror(entry),
                }

            return self.json(result)
        except Exception as exc:
            return self.json({"error": f"{type(exc).__name__}: {exc}"})
