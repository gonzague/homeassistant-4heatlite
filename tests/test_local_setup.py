"""Local setup must never authenticate or retrieve a cloud device key."""
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol

flow_module = importlib.import_module('custom_components.4heatlite.config_flow')
const = importlib.import_module('custom_components.4heatlite.const')


@pytest.fixture
def flow(monkeypatch):
    instance = flow_module.FourHeatLiteConfigFlow()
    async def executor(method, *args):
        return method(*args)
    instance.hass = SimpleNamespace(async_add_executor_job=executor)
    monkeypatch.setattr(instance, '_async_current_entries', lambda: [])
    monkeypatch.setattr(instance, '_async_resolve_host', AsyncMock(return_value='test.invalid'))
    monkeypatch.setattr(instance, '_async_authenticate', AsyncMock(side_effect=AssertionError('No cloud login')))
    monkeypatch.setattr(instance, '_async_fetch_device_key', AsyncMock(side_effect=AssertionError('No cloud key')))
    monkeypatch.setattr(instance, 'async_show_form', lambda **kwargs: kwargs)
    monkeypatch.setattr(instance, 'async_create_entry', lambda **kwargs: kwargs)
    monkeypatch.setattr(flow_module.FourHeatLiteApi, 'test_connection', lambda self: True)
    monkeypatch.setattr(flow_module, 'discover_modules', lambda: [])
    return instance


@pytest.mark.asyncio
async def test_entry_menu_preserves_cloud_path(flow, monkeypatch):
    monkeypatch.setattr(flow, 'async_show_menu', lambda **kwargs: kwargs)
    assert (await flow.async_step_user())['menu_options'] == ['local', 'cloud']
    assert (await flow.async_step_cloud())['step_id'] == 'cloud'


@pytest.mark.asyncio
async def test_local_setup_without_id_never_calls_cloud(flow):
    form = await flow.async_step_local()
    fields = {str(key) for key in form['data_schema'].schema}
    assert 'proxy_mode' not in fields
    assert 'module_address' not in fields
    values = form['data_schema']({'name': 'Test', 'host': 'test.invalid', 'stove_profile': 'jollymec'})
    result = await flow.async_step_device(values)
    assert result['data']['device_id'] == ''
    assert result['data']['device_key'] == ''
    assert result['options']['proxy_mode'] == const.PROXY_MODE_DIRECT
    assert result['options']['stove_profile'] == const.PROFILE_JOLLYMEC
    flow._async_authenticate.assert_not_awaited()
    flow._async_fetch_device_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_discovery_preserves_device_identity(flow, monkeypatch):
    monkeypatch.setattr(flow_module, 'discover_modules', lambda: [{'device_id': 'test-device', 'ip': 'test.invalid'}])
    assert (await flow.async_step_local())['step_id'] == 'discovery'
    form = await flow.async_step_discovery({'selected_device': 'test-device|test.invalid'})
    values = form['data_schema']({'name': 'Test'})
    result = await flow.async_step_device(values)
    assert result['data']['device_id'] == 'test-device'
    assert result['data']['host'] == 'test.invalid'


@pytest.mark.asyncio
async def test_local_connection_failure_stays_in_form(flow, monkeypatch):
    await flow.async_step_local()
    monkeypatch.setattr(flow_module.FourHeatLiteApi, 'test_connection', lambda self: False)
    result = await flow.async_step_device({'name': 'Test', 'host': 'test.invalid'})
    assert result['errors'] == {'host': 'cannot_connect'}
    flow._async_fetch_device_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_ids_do_not_collide_but_hosts_do(flow, monkeypatch):
    await flow.async_step_local()
    monkeypatch.setattr(flow, '_async_current_entries', lambda: [SimpleNamespace(data={'device_id': '', 'host': 'other.invalid'})])
    assert 'data' in await flow.async_step_device({'name': 'Test', 'host': 'test.invalid'})
    result = await flow.async_step_device({'name': 'Test', 'host': 'other.invalid'})
    assert result['errors'] == {'host': 'already_configured'}


@pytest.mark.asyncio
async def test_local_mode_cannot_be_changed_to_proxy_during_setup(flow):
    await flow.async_step_local()
    result = await flow.async_step_device({'name': 'Test', 'host': 'test.invalid', 'proxy_mode': const.PROXY_MODE_KEEPALIVE})
    assert result['options']['proxy_mode'] == const.PROXY_MODE_DIRECT


@pytest.mark.asyncio
async def test_local_options_exclude_and_reject_proxy_modes(monkeypatch):
    flow = flow_module.FourHeatLiteOptionsFlow()
    entry = SimpleNamespace(options={'stove_profile': const.PROFILE_JOLLYMEC}, data={'host': 'test.invalid', 'device_key': ''})
    monkeypatch.setattr(type(flow), 'config_entry', property(lambda _: entry))
    monkeypatch.setattr(flow, 'async_show_form', lambda **kwargs: kwargs)
    monkeypatch.setattr(flow, 'async_abort', lambda **kwargs: kwargs)
    form = await flow.async_step_init()
    with pytest.raises(vol.Invalid):
        form['data_schema']({'proxy_mode': const.PROXY_MODE_KEEPALIVE})
    assert await flow.async_step_init({'proxy_mode': const.PROXY_MODE_KEEPALIVE}) == {'reason': 'cloud_setup_required'}
