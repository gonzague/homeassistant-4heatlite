"""Captured Jolly Mec replies, issue #2 examples and legacy regression checks."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

api_module = importlib.import_module("custom_components.4heatlite.api")
Api = api_module.FourHeatLiteApi
const = importlib.import_module("custom_components.4heatlite.const")
proxy = importlib.import_module("custom_components.4heatlite.proxy")
climate = importlib.import_module("custom_components.4heatlite.climate")
flow_module = importlib.import_module("custom_components.4heatlite.config_flow")
integration = importlib.import_module("custom_components.4heatlite")
from homeassistant.exceptions import HomeAssistantError

CAPTURE = json.loads((Path(__file__).parent / "fixtures/jollymec.json").read_text())


def jolly_api(monkeypatch):
    api = Api("test.invalid", const.PROFILE_JOLLYMEC)
    replies = {
        "0310": CAPTURE["before_ignition"],
        "0312ffff": CAPTURE["exhaust_temperature_register"],
        "030e0266": CAPTURE["ducted_fan_1"],
        "0312005a": CAPTURE["target_temperature"],
        "030e016c": CAPTURE["power"],
    }
    monkeypatch.setattr(api, "_send", lambda command: replies[json.loads(command)[2]])
    return api


def test_captured_jollymec_values(monkeypatch):
    api = jolly_api(monkeypatch)
    assert api.query_config() == {"target_temp": 18, "power": 3, "power_raw": 4}
    sensors = api.query_sensors()
    assert sensors["state"] == 0
    assert sensors["error"] == 0
    assert sensors["room_temp"] == 18
    assert sensors["exhaust_temp"] == 21  # Main block byte 4 is zero.
    assert sensors["ducted_fan_1"] == 4


def test_startup_unknown_temperature_is_not_a_real_measurement():
    data = Api._decode_0310(CAPTURE["sensors"][2], const.PROFILE_JOLLYMEC)
    assert data["room_temp"] is None
    assert "exhaust_temp" not in data


def test_captured_ignition():
    data = Api._decode_0310(CAPTURE["ignition"][2], const.PROFILE_JOLLYMEC)
    assert data["on_off"] == 1
    assert data["state"] == 1
    assert data["error"] == 0


def test_legacy_defaults_are_unchanged(monkeypatch):
    api = Api("test.invalid")
    assert api.profile == const.PROFILE_LASIAN
    data = bytearray(19)
    data[0], data[4], data[5] = 0x10, 90, 5
    data[10:12] = (215).to_bytes(2, "big")
    assert Api._decode_0310(data.hex())["room_temp"] == 21.5
    assert Api._decode_0310(data.hex())["exhaust_temp"] == 90
    replies = [
        ["2WC", "1", "12005a00d2006401900000000100000000"],
        ["2WC", "1", "0e016c00040001000700000001016c0007"],
    ]
    monkeypatch.setattr(api, "_send", Mock(side_effect=replies))
    assert api.query_config() == {"target_temp": 21.0, "power": 1}
    assert Api.build_temp_command(21) == ["2WC", "1", "0512005a00d2006401900001000100"]
    assert Api.build_power_command(3) == ["2WC", "1", "050e016c00030001000700"]


def test_cache_reply_selects_requested_register(monkeypatch):
    api = Api("test.invalid", const.PROFILE_JOLLYMEC)
    # The count field can still say 1 even with multiple cached registers.
    cache = ["2WC", "1", CAPTURE["before_ignition"][2],
             CAPTURE["power"][2], CAPTURE["target_temperature"][2]]
    monkeypatch.setattr(api, "_send", lambda _: cache)
    assert api.query_config() == {"target_temp": 18, "power": 3, "power_raw": 4}


@pytest.mark.parametrize("response", [
    ["ERR", "1", "5"], [], None, ["2WC", "1", "12005azzzz"],
    ["2WC", "1", "12005a"], ["2WC", "1", CAPTURE["power"][2]],
    ["OTHER", "1", CAPTURE["target_temperature"][2]],
    ["2WC", "1", None],
    ["2WC", "1", "12005a 0012000a00280000000100000000"],
])
def test_missing_or_invalid_register_does_not_create_a_value(monkeypatch, response):
    api = Api("test.invalid", const.PROFILE_JOLLYMEC)
    monkeypatch.setattr(api, "_send", lambda _: response)
    assert api._query(const.QUERY_CONFIG["target_temp"], 34) is None


def test_query_accepts_2wr_and_uppercase(monkeypatch):
    api = Api("test.invalid")
    payload = CAPTURE["target_temperature"][2].upper()
    monkeypatch.setattr(api, "_send", lambda _: ["2WR", "1", payload])
    assert api._query(const.QUERY_CONFIG["target_temp"], 34) == payload


def test_tcp_reads_complete_json_across_chunks(monkeypatch):
    sock = Mock()
    response = ["2WC", "1", *([CAPTURE["power"][2]] * 50)]
    payload = json.dumps(response).encode()
    assert len(payload) > const.SOCKET_BUFFER
    sock.recv.side_effect = [payload[:9], payload[9:1030], payload[1030:]]
    monkeypatch.setattr(api_module.socket, "socket", lambda *args: sock)
    assert Api("test.invalid")._send('["2WC","1","030e016c"]') == response
    sock.sendall.assert_called_once()
    sock.close.assert_called_once()


def test_tcp_truncated_reply_is_rejected(monkeypatch):
    sock = Mock()
    sock.recv.side_effect = [b'["2WC",', b'']
    monkeypatch.setattr(api_module.socket, "socket", lambda *args: sock)
    assert Api("test.invalid").query_sensors() is None
    sock.close.assert_called_once()


def test_issue_2_write_examples_are_encoded_without_network():
    assert Api.build_temp_command(21, const.PROFILE_JOLLYMEC) == ["2WC", "1", "0512005a0015000a00280000"]
    assert Api.build_power_command(3, const.PROFILE_JOLLYMEC) == ["2WC", "1", "050e016c0004000100070000"]
    assert Api.build_power_command(0, const.PROFILE_JOLLYMEC)[2] == "050e016c0001000100070000"
    assert Api.build_on_command() == ["2WC", "1", "05040000"]


@pytest.mark.parametrize("value", [9, 41, 18.5, float("nan"), float("inf")])
def test_jollymec_rejects_invalid_target(value):
    with pytest.raises(ValueError):
        Api.build_temp_command(value, const.PROFILE_JOLLYMEC)


@pytest.mark.parametrize("value", [-1, 6, 7, 3.5])
def test_jollymec_rejects_unknown_power(value):
    with pytest.raises(ValueError):
        Api.build_power_command(value, const.PROFILE_JOLLYMEC)


def test_ccg_schedule_keeps_day_groups_and_uninterpreted_flags():
    result = Api.parse_ccg_response(CAPTURE["schedule"])
    assert result["format"] == "CCG"
    assert result["read_only"] is True
    assert result["mode_raw"] == 3
    assert result["days"][5] == {"day": "sat", "slots": [
        {"start": "08:00", "end": "09:00", "flag_raw": 0},
        {"start": "12:00", "end": "12:30", "flag_raw": 0},
        {"start": "00:00", "end": "00:00", "flag_raw": 0},
    ]}
    assert result["days"][6]["slots"] == result["days"][5]["slots"]


@pytest.mark.parametrize("index,value", [(1, "70"), (3, "2"), (4, "24:00"), (5, "1:00"), (6, "unknown")])
def test_invalid_ccg_is_rejected(index, value):
    response = CAPTURE["schedule"].copy()
    response[index] = value
    assert Api.parse_ccg_response(response) is None


def test_schedule_query_dispatch_and_legacy_parser(monkeypatch):
    api = Api("test.invalid", const.PROFILE_JOLLYMEC)
    monkeypatch.setattr(api, "_send", lambda _: CAPTURE["schedule"])
    assert api.query_schedule()["format"] == "CCG"
    assert Api.parse_ccg_response(CAPTURE["schedule"][:-1]) is None
    h24 = ["H24", "9", "#13", "0", "180", "220", "240", "0", "0", "60", "220"]
    assert Api.parse_h24_response(h24)["comfort"] == 22
    assert Api.parse_ccg_response(h24) is None


def test_h24_never_sent_or_queued_for_jollymec(monkeypatch):
    api = Api("test.invalid", const.PROFILE_JOLLYMEC)
    send = Mock()
    monkeypatch.setattr(api, "_send", send)
    with pytest.raises(ValueError):
        api.send_command(["H24", "0"])
    send.assert_not_called()
    entry = {"coordinator": SimpleNamespace(api=api)}
    monkeypatch.setattr(proxy, "_lookup_device", lambda *args, **kw: (entry, "test"))
    assert proxy.enqueue_command({}, "test", ["H24", "0"]) is False


def test_proxy_uses_same_jollymec_units():
    data = proxy.StoveStoreView._parse_values([
        CAPTURE["before_ignition"][2], CAPTURE["target_temperature"][2],
        CAPTURE["power"][2], CAPTURE["exhaust_temperature_register"][2],
        CAPTURE["ducted_fan_1"][2], "12xyz",
    ], const.PROFILE_JOLLYMEC)
    assert {k: data[k] for k in ["room_temp", "target_temp", "power", "exhaust_temp", "ducted_fan_1"]} == {
        "room_temp": 18, "target_temp": 18, "power": 3, "exhaust_temp": 21, "ducted_fan_1": 4,
    }


def test_proxy_rejects_spaced_and_odd_hex_words():
    assert proxy.StoveStoreView._parse_values([
        "12005a 0012000a00280000000100000000", "12005a001",
    ], const.PROFILE_JOLLYMEC) == {}


def test_error_reply_is_not_success(monkeypatch):
    api = Api("test.invalid")
    monkeypatch.setattr(api, "_send", lambda _: ["ERR", "1", "5"])
    assert api.send_command(Api.build_on_command()) is None


@pytest.mark.asyncio
async def test_climate_uses_profile_encoding(monkeypatch):
    api = Api("test.invalid", const.PROFILE_JOLLYMEC)
    coordinator = SimpleNamespace(api=api, data={"power": 0})
    entity = climate.StoveClimate(coordinator, "Test stove")
    assert entity.target_temperature_step == 1
    assert entity.preset_mode == "Silent"
    assert entity.preset_modes == ["Silent", "Power 1", "Power 2", "Power 3", "Power 4", "Power 5"]
    send = AsyncMock()
    monkeypatch.setattr(entity, "_send_command", send)
    await entity.async_set_temperature(temperature=21)
    assert send.call_args.args[0] == ["2WC", "1", "0512005a0015000a00280000"]
    await entity.async_set_preset_mode("Power 3")
    assert send.call_args.args[0] == ["2WC", "1", "050e016c0004000100070000"]
    with pytest.raises(HomeAssistantError):
        await entity.async_set_preset_mode("Power 7")


@pytest.mark.asyncio
async def test_profile_options_do_not_write_a_schedule(monkeypatch):
    flow = flow_module.FourHeatLiteOptionsFlow()
    entry = SimpleNamespace(options={const.CONF_STOVE_PROFILE: const.PROFILE_LASIAN}, data={"host": "test.invalid"})
    monkeypatch.setattr(type(flow), "config_entry", property(lambda _: entry))
    monkeypatch.setattr(flow, "async_create_entry", lambda **kwargs: kwargs)
    deliver = AsyncMock()
    monkeypatch.setattr(flow, "_deliver_command", deliver)
    result = await flow.async_step_init({const.CONF_STOVE_PROFILE: const.PROFILE_JOLLYMEC})
    assert result["data"][const.CONF_STOVE_PROFILE] == const.PROFILE_JOLLYMEC
    deliver.assert_not_called()


@pytest.mark.asyncio
async def test_service_blocks_jollymec_schedule_writes():
    callbacks = {}
    api = Api("test.invalid", const.PROFILE_JOLLYMEC)
    coordinator = SimpleNamespace(api=api)
    hass = SimpleNamespace(
        data={const.DOMAIN: {"entry": {const.DATA_COORDINATOR: coordinator}}},
        services=SimpleNamespace(async_register=lambda domain, name, callback, **kw: callbacks.update({name: callback})),
    )
    integration._register_services(hass)
    with pytest.raises(HomeAssistantError, match="read-only"):
        await callbacks[const.SERVICE_SET_SCHEDULE](SimpleNamespace(data={"config_entry_id": "entry", "schedule": {}}))


@pytest.mark.asyncio
async def test_partial_reads_preserve_last_valid_fields_but_clear_invalid_values():
    module = importlib.import_module("custom_components.4heatlite.coordinator")

    async def executor(method):
        return method()

    coordinator = SimpleNamespace(
        hass=SimpleNamespace(async_add_executor_job=executor),
        api=SimpleNamespace(
            query_sensors=lambda: {"state": 2, "room_temp": None},
            query_config=lambda: {"target_temp": 18},
        ),
        data={"state": 0, "room_temp": 17, "exhaust_temp": 21, "power": 3},
    )
    data = await module.FourHeatLiteCoordinator._async_update_data(coordinator)
    assert data == {"state": 2, "room_temp": None, "exhaust_temp": 21, "power": 3, "target_temp": 18}


@pytest.mark.asyncio
async def test_jollymec_options_hide_schedule_editor(monkeypatch):
    flow = flow_module.FourHeatLiteOptionsFlow()
    entry = SimpleNamespace(options={const.CONF_STOVE_PROFILE: const.PROFILE_JOLLYMEC}, data={"host": "test.invalid"})
    monkeypatch.setattr(type(flow), "config_entry", property(lambda _: entry))
    monkeypatch.setattr(flow, "async_show_form", lambda **kwargs: kwargs)
    result = await flow.async_step_init()
    keys = {str(key) for key in result["data_schema"].schema}
    assert "schedules" not in keys
    assert "stove_profile" in keys


@pytest.mark.asyncio
async def test_profile_is_saved_during_initial_setup(monkeypatch):
    flow = flow_module.FourHeatLiteConfigFlow()
    async def executor(method):
        return method()
    flow.hass = SimpleNamespace(async_add_executor_job=executor)
    monkeypatch.setattr(flow, "_async_current_entries", lambda: [])
    monkeypatch.setattr(flow, "_async_resolve_host", AsyncMock(return_value="test.invalid"))
    monkeypatch.setattr(flow, "_async_fetch_device_key", AsyncMock(return_value="test-key"))
    monkeypatch.setattr(flow, "async_create_entry", lambda **kwargs: kwargs)
    observed = []
    def test_connection(api):
        observed.append(api.profile)
        return True
    monkeypatch.setattr(Api, "test_connection", test_connection)
    result = await flow.async_step_device({
        "device_id": "test-device", "host": "test.invalid", "name": "Test",
        const.CONF_STOVE_PROFILE: const.PROFILE_JOLLYMEC,
    })
    assert observed == [const.PROFILE_JOLLYMEC]
    assert result["options"][const.CONF_STOVE_PROFILE] == const.PROFILE_JOLLYMEC


@pytest.mark.parametrize('raw, expected', [(0, 'None'), (32, 'Lack of depression'), (2, 'Unknown (raw 2)')])
def test_jollymec_alarm_codes_are_profile_specific(raw, expected):
    module = importlib.import_module('custom_components.4heatlite.sensor')
    coordinator = SimpleNamespace(api=Api('test.invalid', const.PROFILE_JOLLYMEC), data={'error': raw})
    entity = module.StoveErrorSensor(coordinator, 'Test')
    assert entity.native_value == expected
    assert entity.extra_state_attributes == {'error_code': raw, 'error_code_raw': raw}


def test_legacy_alarm_code_keeps_its_existing_meaning():
    module = importlib.import_module('custom_components.4heatlite.sensor')
    coordinator = SimpleNamespace(api=Api('test.invalid'), data={'error': 2})
    entity = module.StoveErrorSensor(coordinator, 'Test')
    assert entity.native_value == 'Safety PressureSwitch HV2'
    assert entity.extra_state_attributes == {'error_code': 2}


def test_observed_shutdown_block_is_not_off():
    data = Api._decode_0310('10200100000902061425001122000000018400', const.PROFILE_JOLLYMEC)
    assert data['state'] == 9
    assert data['error'] == 32
    assert data['on_off'] == 1


def test_confirmed_off_uses_state_despite_retained_raw_alarm_and_flag():
    data = Api._decode_0310('10200100000000061434001122000000018400', const.PROFILE_JOLLYMEC)
    coordinator = SimpleNamespace(api=Api('test.invalid', const.PROFILE_JOLLYMEC), data=data)
    entity = climate.StoveClimate(coordinator, 'Test')
    assert data['error'] == 32 and data['on_off'] == 1
    assert entity.hvac_mode == climate.HVACMode.OFF
    assert entity.hvac_action == climate.HVACAction.OFF
