"""2.5.1: farmer warning lifecycle and technical fixture; no real Wokwi required."""
import time
import pytest
from fastapi.testclient import TestClient
from app.alerts import soil_alerts
from app.storage import Storage
from app.twin import TwinService


def config():
    return {'zones':[
        {'name':'Vườn trước','crop':'Xoài','soil_ec_max':1.5,
         'soil_ph_min':6.0,'soil_ph_max':7.0,'soil_na_max':80.0},
        {'name':'Vườn sau','crop':'Bưởi','soil_ec_max':1.5,
         'soil_ph_min':6.0,'soil_ph_max':7.0,'soil_na_max':80.0}]}


class Bridge:
    connected=True
    def __init__(self):self.messages=[];self.commands=[]
    def publish_twin(self,payload):self.messages.append(payload)
    def command(self,payload):self.commands.append(payload)


def test_soil_test_only_influences_monitoring_fields(tmp_path):
    db=Storage(str(tmp_path/'t.db'))
    db.save_farm_config(config())
    br=Bridge();t=TwinService(br,db)
    db.ingest({'device':'demo','state':'IDLE','mode':'TWIN','pump_on':False})
    t.running=True
    before=t.snapshot()['world'].copy()
    assert soil_alerts(config(),before)==[]
    result=t.prepare_soil_alert_test(config())
    after=result['world']
    assert result['soil_test_active']
    for field in ('salinity_ppt','canal_pct','rain_pct','soil1_pct','soil2_pct','tank_l','tank_salt_ppt'):
        assert before[field] == after[field],field
    assert len(soil_alerts(config(),after))>=4
    assert all('SGT2,' in p for p in br.messages)
    assert not br.commands  # does not send PAUSE/RESUME or force irrigation
    assert len([e for e in db.events() if e['kind']=='soil_warning']) >= 4
    t.step(initial=True)
    assert len([e for e in db.events() if e['kind']=='soil_warning']) == len(soil_alerts(config(),after))
    restored=t.restore_soil_alert_test()
    for field in ('soil_ec_z1_ds_m','soil_ph_z1','soil_na_z1_mg_kg','soil_ec_z2_ds_m','soil_ph_z2','soil_na_z2_mg_kg'):
        assert restored['world'][field] == before[field]
    assert not restored['soil_test_active']
    assert soil_alerts(config(),restored['world']) == []
    assert len([e for e in db.events() if e['kind']=='soil_clear']) == len(soil_alerts(config(),after))
    db.close()


def test_soil_alert_fixture_refuses_missing_thresholds(tmp_path):
    db=Storage(str(tmp_path/'empty.db'))
    br=Bridge();t=TwinService(br,db)
    t.running=True
    with pytest.raises(ValueError,match='cấu hình'):
        t.prepare_soil_alert_test(db.get_farm_config())
    assert not br.messages
    db.close()


def test_public_ui_and_rest_api_offline_soil_twin(monkeypatch,tmp_path):
    monkeypatch.setenv('SALTGUARD_DB',str(tmp_path/'api.db'))
    from app import mqtt_service
    monkeypatch.setattr(mqtt_service.MqttService,'start',lambda self:None)
    monkeypatch.setattr(mqtt_service.MqttService,'stop',lambda self:None)
    import app.main as m
    import importlib
    importlib.reload(m)
    with TestClient(m.app) as client:
        assert client.post('/api/advanced/login',json={'pin':'1111'}).status_code==200
        assert client.get('/static/engineer_config.js').status_code==200
        assert 'lab-soil-warning' in client.get('/lab').text
        assert 'soil-detail' in client.get('/static/farmer.js').text
        assert client.post('/api/twin/lab/soil-warning').status_code==400
        assert client.post('/api/farm/config',json=config()).status_code==200
        # Python model runs for soil monitoring even if Wokwi's PUBLIC gateway fails.
        m.twin.running=True
        m.twin.bridge.connected=False
        m.twin.step(initial=True)
        before=client.get('/api/farm').json()
        assert before['device_online'] is False
        assert before['twin_world'] is not None
        assert not any(a['kind']=='SOIL_MONITOR' for a in before['alerts'])
        response=client.post('/api/twin/lab/soil-warning')
        assert response.status_code==200,response.text
        farm=client.get('/api/farm').json()
        assert any(a['kind']=='SOIL_MONITOR' for a in farm['alerts'])
        assert farm['device_online'] is False
        assert any(e['kind']=='soil_warning' for e in farm['events'])
        assert client.post('/api/twin/lab/soil-restore').status_code==200
        farm=client.get('/api/farm').json()
        assert not any(a['kind']=='SOIL_MONITOR' for a in farm['alerts'])
        assert any(e['kind']=='soil_clear' for e in farm['events'])
