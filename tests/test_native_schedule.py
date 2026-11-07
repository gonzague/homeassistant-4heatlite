"""Native scheduling: no blind retry, no stale edits, no H24 side effects."""
import importlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

Api = importlib.import_module('custom_components.4heatlite.api').FourHeatLiteApi
native = importlib.import_module('custom_components.4heatlite.native_schedule')
flows = importlib.import_module('custom_components.4heatlite.config_flow')


@pytest.fixture
def schedule():
    return {'mode_raw': 3, 'days': [
        {'day': day, 'slots': [
            {'start': '08:00', 'end': '09:00', 'flag_raw': int(day in ('sat', 'sun'))},
            {'start': '12:00', 'end': '13:00', 'flag_raw': 0},
            {'start': '00:00', 'end': '00:00', 'flag_raw': 0},
        ]} for day in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
    ]}


def test_ccs_round_trip_and_count(schedule):
    command = native.build_native_schedule(schedule)
    assert len(command) == 73 and command[:4] == ['CCS', '71', '3', '1']
    assert command[53:57] == ['6', '08:00', '09:00', '1']
    for header in ('CCS', 'CCG'):
        command[0] = header
        parsed = Api.parse_ccg_response(command)
        assert parsed['days'] == schedule['days']
        assert parsed['read_only'] is False


@pytest.mark.parametrize('mutation,error', [
    (lambda s: s.update(mode_raw=4), 'native_invalid'),
    (lambda s: s.update(mode_raw=True), 'native_invalid'),
    (lambda s: s['days'].pop(), 'native_invalid'),
    (lambda s: s['days'][0].update(day='sat'), 'native_invalid'),
    (lambda s: s['days'][0]['slots'][0].update(flag_raw=2), 'native_invalid'),
    (lambda s: s['days'][0]['slots'][0].update(start='24:00'), 'invalid_time'),
    (lambda s: s['days'][0]['slots'][0].update(start='8:00'), 'invalid_time'),
    (lambda s: s['days'][0]['slots'][0].update(start='23:00',end='02:00',flag_raw=1), 'invalid_time'),
    (lambda s: s['days'][5]['slots'][1].update(start='08:30',flag_raw=1), 'overlapping_slots'),
])
def test_invalid_program_never_encoded(schedule, mutation, error):
    mutation(schedule)
    with pytest.raises(native.NativeScheduleError, match=error):
        native.build_native_schedule(schedule)


def test_unknown_codes_remain_readable_but_uneditable(schedule):
    raw = native.build_native_schedule(schedule)
    raw[2], raw[6] = '9', '2'
    parsed = Api.parse_ccg_response(raw)
    assert parsed['mode_raw'] == 9
    assert parsed['days'][0]['slots'][0]['flag_raw'] == 2
    assert parsed['read_only'] is True


def test_noop_reads_but_never_writes(schedule, monkeypatch):
    api = Api('test.invalid','jollymec')
    monkeypatch.setattr(api,'query_schedule',Mock(return_value=schedule))
    send = Mock()
    monkeypatch.setattr(api,'_send',send)
    assert api.write_native_schedule(schedule,deepcopy(schedule)) == schedule
    send.assert_not_called()


def test_concurrent_change_blocks_write(schedule, monkeypatch):
    api = Api('test.invalid','jollymec')
    current = deepcopy(schedule); current['days'][6]['slots'][0]['start'] = '07:00'
    monkeypatch.setattr(api,'query_schedule',Mock(return_value=current))
    send = Mock(); monkeypatch.setattr(api,'_send',send)
    with pytest.raises(native.NativeScheduleError,match='native_conflict'):
        api.write_native_schedule(schedule,schedule)
    send.assert_not_called()


@pytest.mark.parametrize('reply', [['CCS','1','OK'], None, TimeoutError(), ['unexpected']])
def test_single_write_requires_matching_readback(schedule, monkeypatch, reply):
    api = Api('test.invalid','jollymec')
    draft = deepcopy(schedule); draft['days'][5]['slots'][0]['start']='07:30'
    monkeypatch.setattr(api,'query_schedule',Mock(side_effect=[schedule,draft]))
    send=Mock(side_effect=reply) if isinstance(reply,Exception) else Mock(return_value=reply)
    monkeypatch.setattr(api,'_send',send)
    assert api.write_native_schedule(draft,schedule) == draft
    send.assert_called_once_with(json.dumps(native.build_native_schedule(draft),separators=(',',':')))
    assert draft['days'][6] == schedule['days'][6]


@pytest.mark.parametrize('reply,readback,error', [
    (['CCS','1','OK'], None, 'native_unverified'),
    (['CCS','1','OK'], 'unchanged', 'native_unverified'),
    (['ERR','1','1'], None, 'native_rejected'),
])
def test_failed_or_unverified_write_never_retried(schedule, monkeypatch, reply, readback, error):
    api=Api('test.invalid','jollymec')
    draft=deepcopy(schedule); draft['mode_raw']=0
    monkeypatch.setattr(api,'query_schedule',Mock(side_effect=[schedule,schedule if readback else None]))
    send=Mock(return_value=reply); monkeypatch.setattr(api,'_send',send)
    with pytest.raises(native.NativeScheduleError,match=error):
        api.write_native_schedule(draft,schedule)
    send.assert_called_once()


def test_legacy_profile_cannot_write_ccs(schedule):
    with pytest.raises(native.NativeScheduleError,match='native_unsupported'):
        Api('test.invalid').write_native_schedule(schedule,schedule)


@pytest.fixture
def flow(schedule,monkeypatch):
    flow=flows.FourHeatLiteOptionsFlow()
    api=Api('test.invalid','jollymec')
    monkeypatch.setattr(api,'query_schedule',Mock(return_value=schedule))
    monkeypatch.setattr(api,'write_native_schedule',Mock(side_effect=lambda draft,expected:draft))
    entry=SimpleNamespace(entry_id='entry',options={'stove_profile':'jollymec'},data={})
    monkeypatch.setattr(type(flow),'config_entry',property(lambda _:entry))
    async def executor(fn,*args): return fn(*args)
    flow.hass=SimpleNamespace(data={'4heatlite':{'entry':{'coordinator':SimpleNamespace(api=api)}}},async_add_executor_job=executor)
    for name in ('async_show_form','async_show_menu','async_abort'):
        monkeypatch.setattr(flow,name,lambda **kw:kw)
    return flow,api


@pytest.mark.asyncio
async def test_native_flow_stages_group_preserves_other_days_and_confirms(flow,schedule):
    editor,api=flow
    assert (await editor.async_step_init())['menu_options']==['native','settings']
    await editor.async_step_native()
    weekday_form=await editor.async_step_native({'mode':'3'})
    form=await editor.async_step_native_slots(weekday_form['data_schema']({}))
    data=form['data_schema']({})
    data.update(start_1='07:30:00',end_1='09:00:00')
    review=await editor.async_step_native_slots(data)
    assert review['step_id']=='native_review'
    assert editor._native_draft['days'][:5]==schedule['days'][:5]
    assert editor._native_draft['days'][5]['slots'][0]['start']=='07:30'
    assert editor._native_draft['days'][6]['slots'][0]['start']=='07:30'
    api.write_native_schedule.assert_not_called()
    assert await editor.async_step_native_review({})=={'reason':'native_saved'}
    api.write_native_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_mode_only_preserves_every_slot(flow,schedule):
    editor,api=flow
    await editor.async_step_native()
    assert (await editor.async_step_native({'mode':'0'}))['step_id']=='native_review'
    assert editor._native_draft['days']==schedule['days']
    assert editor._native_draft['mode_raw']==0
    api.write_native_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_seconds_and_invalid_intervals_stay_in_form(flow):
    editor,api=flow
    await editor.async_step_native()
    await editor.async_step_native({'mode':'1'})
    form=await editor.async_step_native_day({'day':'sat'})
    data=form['data_schema']({}); data['start_1']='08:00:30'
    assert (await editor.async_step_native_slots(data))['errors']=={'base':'invalid_time'}
    api.write_native_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_conflict_ends_flow_without_retry(flow):
    editor,api=flow
    await editor.async_step_native()
    await editor.async_step_native({'mode':'0'})
    api.write_native_schedule.side_effect=native.NativeScheduleError('native_conflict')
    assert await editor.async_step_native_review({})=={'reason':'native_conflict'}
    api.write_native_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_weekly_mode_edits_one_program_for_all_days(flow):
    editor,api=flow
    first=await editor.async_step_native()
    assert set(str(k) for k in first['data_schema'].schema)=={'mode'}
    form=await editor.async_step_native({'mode':'2'})
    assert form['step_id']=='native_slots'
    data=form['data_schema']({})
    data.update(enabled_1=True,start_1='06:30:00',end_1='08:30:00')
    assert (await editor.async_step_native_slots(data))['step_id']=='native_review'
    assert all(day['slots']==editor._native_draft['days'][0]['slots'] for day in editor._native_draft['days'])
    assert editor._native_draft['days'][6]['slots'][0]=={'start':'06:30','end':'08:30','flag_raw':1}
    api.write_native_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_weekend_mode_has_two_independent_groups_before_review(flow):
    editor,api=flow
    await editor.async_step_native()
    weekdays=await editor.async_step_native({'mode':'3'})
    values=weekdays['data_schema']({}); values.update(enabled_1=True,start_1='06:00:00')
    weekend=await editor.async_step_native_slots(values)
    assert weekend['step_id']=='native_slots'
    assert 'Saturday' in weekend['description_placeholders']['days']
    values=weekend['data_schema']({}); values.update(start_1='10:00:00',end_1='11:00:00')
    assert (await editor.async_step_native_slots(values))['step_id']=='native_review'
    assert [d['slots'][0]['start'] for d in editor._native_draft['days']]==['06:00']*5+['10:00']*2
    api.write_native_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_daily_can_edit_several_days_before_saving(flow,schedule):
    editor,api=flow
    await editor.async_step_native()
    choice=await editor.async_step_native({'mode':'1'})
    assert choice['step_id']=='native_day'
    assert choice['data_schema'].schema[next(iter(choice['data_schema'].schema))].config['options']==['mon','tue','wed','thu','fri','sat','sun']
    form=await editor.async_step_native_day({'day':'tue'})
    values=form['data_schema']({}); values.update(start_1='06:30:00',next_action='another_day')
    assert (await editor.async_step_native_slots(values))['step_id']=='native_day'
    form=await editor.async_step_native_day({'day':'thu'})
    values=form['data_schema']({}); values.update(start_1='07:30:00')
    assert (await editor.async_step_native_slots(values))['step_id']=='native_review'
    assert editor._native_draft['days'][1]['slots'][0]['start']=='06:30'
    assert editor._native_draft['days'][3]['slots'][0]['start']=='07:30'
    for i in (0,2,4,5,6): assert editor._native_draft['days'][i]==schedule['days'][i]
    api.write_native_schedule.assert_not_called()
