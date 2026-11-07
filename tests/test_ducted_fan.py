"""Ducted fan level is independent of stove power and has verified readback."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock,AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

Api=importlib.import_module('custom_components.4heatlite.api').FourHeatLiteApi
Select=importlib.import_module('custom_components.4heatlite.select').DuctedFanLevel


def test_write_matches_verified_upstream_example():
    assert Api.build_ducted_fan_command(4,'jollymec')==['2WC','1','050e02660004000000070000']
    assert Api.build_ducted_fan_command(1,'jollymec')[2]=='050e02660001000000070000'


@pytest.mark.parametrize('level',[-1,7,1.5,True,'1'])
def test_invalid_values_rejected_before_transport(level):
    with pytest.raises(ValueError): Api.build_ducted_fan_command(level,'jollymec')


def test_legacy_profile_not_exposed():
    with pytest.raises(ValueError): Api.build_ducted_fan_command(4,'lasian')


def test_read_matches_register_in_cache(monkeypatch):
    api=Api('test.invalid','jollymec')
    monkeypatch.setattr(api,'_send',Mock(return_value=['2WC','1','0e016c0004000100070000','0e02660001000000070000']))
    assert api.query_ducted_fan()==1


@pytest.mark.parametrize('reply',[['2WC','1','0e02660001000000070000'],TimeoutError()])
def test_write_once_readback_confirmed(monkeypatch,reply):
    api=Api('test.invalid','jollymec')
    send=Mock(side_effect=reply) if isinstance(reply,Exception) else Mock(return_value=reply)
    monkeypatch.setattr(api,'_send',send)
    monkeypatch.setattr(api,'query_ducted_fan',Mock(return_value=1))
    assert api.set_ducted_fan(1)==1
    send.assert_called_once_with(json.dumps(Api.build_ducted_fan_command(1,'jollymec'),separators=(',',':')))


def test_mismatched_readback_fails_without_retry(monkeypatch):
    api=Api('test.invalid','jollymec')
    send=Mock(return_value=['2WC','1','0e02660001000000070000'])
    monkeypatch.setattr(api,'_send',send)
    monkeypatch.setattr(api,'query_ducted_fan',Mock(return_value=4))
    with pytest.raises(ValueError,match='could not be verified'): api.set_ducted_fan(1)
    send.assert_called_once()


@pytest.mark.asyncio
async def test_select_only_sets_fan_and_preserves_combustion():
    async def executor(fn,*args): return fn(*args)
    coordinator=SimpleNamespace(data={'ducted_fan_1':1,'power':3},api=SimpleNamespace(set_ducted_fan=Mock(return_value=4)),
        async_request_refresh=AsyncMock(),push_data=Mock(),last_update_success=True)
    entity=Select(coordinator,'Test')
    entity.hass=SimpleNamespace(async_add_executor_job=executor)
    assert entity.current_option=="1"
    assert entity.options==["off","1","2","3","4","5","6"]
    await entity.async_select_option("4")
    coordinator.api.set_ducted_fan.assert_called_once_with(4)
    coordinator.push_data.assert_called_once_with({'ducted_fan_1':4})
    assert coordinator.data['power']==3
    with pytest.raises(HomeAssistantError): await entity.async_select_option("7")
    coordinator.api.set_ducted_fan.assert_called_once()


@pytest.mark.asyncio
async def test_select_off_and_unknown_values():
    async def executor(fn,*args): return fn(*args)
    coordinator=SimpleNamespace(data={'ducted_fan_1':0},api=SimpleNamespace(set_ducted_fan=Mock(return_value=0)),async_request_refresh=AsyncMock(),push_data=Mock())
    entity=Select(coordinator,'Test'); entity.hass=SimpleNamespace(async_add_executor_job=executor)
    assert entity.current_option=='off'
    await entity.async_select_option('off')
    coordinator.api.set_ducted_fan.assert_called_once_with(0)
    coordinator.data['ducted_fan_1']=7
    assert entity.current_option is None


@pytest.mark.asyncio
@pytest.mark.parametrize('owner',['entry','other_entry'])
async def test_numeric_control_migration_is_scoped_to_this_entry(monkeypatch,owner):
    module=importlib.import_module('custom_components.4heatlite.select')
    registry=SimpleNamespace(async_get_entity_id=Mock(return_value='number.old'),async_get=Mock(return_value=SimpleNamespace(config_entry_id=owner,name=None)),async_remove=Mock())
    monkeypatch.setattr(module.er,'async_get',lambda hass:registry)
    api=SimpleNamespace(profile='jollymec')
    hass=SimpleNamespace(data={'4heatlite':{'entry':{'coordinator':SimpleNamespace(api=api)}}})
    add=Mock()
    await module.async_setup_entry(hass,SimpleNamespace(entry_id='entry',data={'name':'Test'}),add)
    if owner=='entry': registry.async_remove.assert_called_once_with('number.old')
    else: registry.async_remove.assert_not_called()
    add.assert_called_once()
