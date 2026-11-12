"""MVP contract checks: removed legacy automation, local-only master, per-zone holds."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.storage import Storage
from app.mqtt_service import MqttService

ROOT=Path(__file__).resolve().parents[2]


def test_decommission_legacy_schedules(tmp_path):
    store=Storage(str(tmp_path/'legacy.db'))
    store.add_schedule(1,'2026-11-01','07:00',1,30)
    cfg=store.get_farm_config()
    cfg['zones'][0]['irrigation_mode']='SCHEDULE'
    store.save_farm_config(cfg)
    store.retire_schedules()
    assert all(not row['enabled'] for row in store.schedules())
    assert store.get_farm_config()['zones'][0]['irrigation_mode']=='MOISTURE'
    store.close()


def test_command_api_refuses_remote_start_and_scheduled_watering(tmp_path):
    store=Storage(str(tmp_path/'new.db'))
    bridge=MqttService(store,'localhost',1883,'saltguard/demo/testing')
    items=[]
    bridge.connected=True
    bridge.client=SimpleNamespace(publish=lambda topic,payload,qos,retain:items.append((topic,payload,qos,retain)) or SimpleNamespace(rc=0))
    for cmd in ('PAUSE','RESUME','WATER:Z1:300','MODE:Z1:SCHEDULE','MASTER:ON','MASTER:OFF','CLOCK:1780000000'):
        with pytest.raises(ValueError):bridge.command(cmd)
    assert bridge.command('ZONE:1:HOLD')['sent']
    assert bridge.command('ZONE:2:RESUME')['sent']
    assert all(x[3] is False for x in items)
    assert len(items)==2
    store.close()


def test_clock_sync_from_telemetry_is_internal_and_rate_limited(tmp_path,monkeypatch):
    store=Storage(str(tmp_path/'clock.db'))
    bridge=MqttService(store,'localhost',1883,'saltguard/demo/testing')
    pubs=[]
    bridge.connected=True
    bridge.client=SimpleNamespace(publish=lambda topic,payload,qos,retain:pubs.append((topic,payload)) or SimpleNamespace(rc=0))
    data={'device':bridge.root,'state':'IDLE','master_enabled':False,'clock_valid':False}
    msg=SimpleNamespace(topic=bridge.root+'/telemetry',payload=json.dumps(data).encode())
    bridge._on_message(None,None,msg)
    bridge._on_message(None,None,msg)
    assert len(pubs)==1
    assert pubs[0][1].startswith('CLOCK:')
    ack={'command':pubs[0][1],'accepted':True,'message':'CLOCK_SYNCED'}
    bridge._on_message(None,None,SimpleNamespace(topic=bridge.root+'/ack',payload=json.dumps(ack).encode()))
    assert bridge.last_ack is None
    store.close()


def test_farmer_ui_has_five_pages_and_no_remote_master(tmp_path,monkeypatch):
    monkeypatch.setenv('SALTGUARD_DB',str(tmp_path/'api.db'))
    monkeypatch.setattr(MqttService,'start',lambda self:None)
    monkeypatch.setattr(MqttService,'stop',lambda self:None)
    import app.main as m
    importlib.reload(m)
    with TestClient(m.app) as client:
        assert client.post('/api/advanced/login',json={'pin':'1111'}).status_code==200
        page=client.get('/').text
        assert 'data-page="schedules"' not in page
        assert page.count('class="navitem')==5
        assert 'irrigation-switch' not in page
        assert 'data-page="zones"' in page
        assert client.post('/api/command',json={'command':'RESUME'}).status_code==400
        assert client.post('/api/command',json={'command':'WATER:Z1:300'}).status_code==400
        assert client.get('/api/schedules').status_code==404
        m.storage.ingest({'device':m.ROOT,'state':'IDLE','master_enabled':False,'pump_on':False,'mode':'TWIN','zones':2,'zone1_hold':True,'zone2_hold':False,'soil1_pct':15,'soil2_pct':48})
        snap=client.get('/api/farm').json()
        assert 'chờ bật công tắc' in snap['headline'].lower()
        assert any(a['kind']=='SOIL_DRY' for a in snap['alerts'])


def test_wokwi_physical_switch_and_durable_zone_hold():
    fw=(ROOT/'firmware_wokwi/sketch.ino').read_text()
    diagram=json.loads((ROOT/'firmware_wokwi/diagram.json').read_text())
    assert 'MASTER_SWITCH_PIN=36' in fw
    assert 'masterEnabled=false' in fw
    assert 'if(!masterEnabled)' in fw
    assert 'updateMaster(now);' in fw
    assert 'irrigationPrefs.putBool(zi==0?"hold1":"hold2"' in fw
    assert 'if(zoneHold[i])' in fw
    assert 'WATER:Z' not in fw and 'MODE:Z1:SCHEDULE' not in fw
    switch=next(p for p in diagram['parts'] if p['id']=='masterSwitch')
    assert switch['attrs']['value']==''
    edges={tuple(x[:2]) for x in diagram['connections']}
    assert ('masterSwitch:2','esp:VP') in edges
    assert ('masterSwitch:1','esp:GND.1') in edges
    assert ('masterSwitch:3','esp:3V3') in edges
