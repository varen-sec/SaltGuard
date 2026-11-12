"""v2.5 model/API regression. Does NOT replace hardware/Wokwi tests."""
import pytest
from fastapi.testclient import TestClient
from app.twin import FarmWorld
from app.storage import Storage
from app.main import soil_alerts


def test_refill_only_when_controller_reports_fill_and_not_irrigation():
    w=FarmWorld(tank_l=75,tank_salt_ppt=0.3)
    w.advance(5,{'mode':'TWIN','tank_fill_on':False,'pump_on':False,'state':'IDLE'},True)
    assert w.tank_l==75 and w.fill_total_l==0
    w.advance(5,{'mode':'TWIN','tank_fill_on':True,'pump_on':False,'state':'REFILL_TANK'},True)
    assert w.tank_l==81.25 and w.fill_total_l==6.25 and w.filling
    before=w.tank_l
    w.advance(5,{'mode':'TWIN','tank_fill_on':True,'pump_on':True,'source':'CANAL','zone':1},True)
    assert w.tank_l==before and not w.filling and w.irrigating
    w.advance(5,{'mode':'TWIN','tank_fill_on':True,'pump_on':False},False)
    assert not w.filling and w.tank_l==before


def test_tank_salinity_mass_balance_and_rain_no_magic_fill():
    w=FarmWorld(tank_l=50,tank_salt_ppt=0.2,salinity_ppt=0.5)
    w.advance(3,{'mode':'TWIN','tank_fill_on':True,'pump_on':False},True)
    assert 50 < w.tank_l < 60
    assert .2 < w.tank_salt_ppt < .5
    after=w.tank_l
    w.scenario='RAIN'
    for _ in range(8):w.advance(3,{'mode':'TWIN','tank_fill_on':False,'pump_on':False},True)
    assert w.tank_l==after  # no rainwater magically accumulating inside tank


def test_rain_moistens_soil_without_irrigation():
    w=FarmWorld(scenario='RAIN')
    start=w.soil1_pct
    for _ in range(10):w.advance(3,None,False)
    assert w.soil1_pct > start


def test_soil_threshold_only_alerts_with_config():
    w=FarmWorld()
    config={'zones':[{'name':'Vườn trước','soil_ec_max':None,'soil_ph_min':None,'soil_ph_max':None,'soil_na_max':None},
                     {'name':'Vườn sau','soil_ec_max':None,'soil_ph_min':None,'soil_ph_max':None,'soil_na_max':None}]}
    assert soil_alerts(config,w.__dict__)==[]
    config['zones'][0]['soil_ec_max']=.8
    config['zones'][1]['soil_na_max']=55
    alerts=soil_alerts(config,w.__dict__)
    assert len(alerts)==2
    assert all(a['kind']=='SOIL_MONITOR' and a['level']=='warning' for a in alerts)
    assert all('đề xuất' not in a['detail'].lower() for a in alerts)


def test_persist_crop_settings(tmp_path):
    db=Storage(str(tmp_path/'x.db'))
    cfg=db.get_farm_config()
    assert cfg['zones'][0]['soil_ec_max'] is None
    cfg['zones'][0]['name']='Vườn trước'
    cfg['zones'][0]['crop']='Xoài'
    cfg['zones'][0]['soil_ec_max']=1.4
    db.save_farm_config(cfg)
    assert db.get_farm_config()['zones'][0]['crop']=='Xoài'
    db.close()
    db2=Storage(str(tmp_path/'x.db'))
    assert db2.get_farm_config()['zones'][0]['soil_ec_max']==1.4
    db2.close()


def test_farm_api_offline_safe_and_config(tmp_path,monkeypatch):
    monkeypatch.setenv('SALTGUARD_DB',str(tmp_path/'api.db'))
    import importlib
    from app import mqtt_service
    monkeypatch.setattr(mqtt_service.MqttService,'start',lambda self:None)
    monkeypatch.setattr(mqtt_service.MqttService,'stop',lambda self:None)
    import app.main as m
    importlib.reload(m)
    with TestClient(m.app) as client:
        assert client.post('/api/advanced/login',json={'pin':'1111'}).status_code==200
        assert 'Vườn của tôi' in client.get('/').text
        assert 'Kịch bản môi trường' in client.get('/lab').text
        assert 'Thông số theo dõi cây và đất' in client.get('/expert').text
        assert client.get('/static/farmer.js').status_code==200
        s=client.get('/api/farm').json()
        assert not s['device_online'] and s['live'] is None
        assert s['alerts'][0]['kind']=='OFFLINE'
        bad=client.post('/api/farm/config',json={'zones':[{'name':'A','crop':'X'}, {'name':'B','crop':'Y'}]})
        assert bad.status_code==200
        invalid=client.post('/api/farm/config',json={'zones':[
            {'name':'A','crop':'X','soil_ph_min':8,'soil_ph_max':5}, {'name':'B','crop':'Y'}]})
        assert invalid.status_code==400
        assert client.post('/api/command',json={'command':'FILL:REQUEST'}).status_code==503
        m.storage.ingest({'device':m.ROOT,'state':'REFILL_TANK','pump_on':False,'tank_fill_on':True,
                          'tank_l':76,'tank_quality_safe':None,'tank_quality_policy':'MONITOR_ONLY','canal_safe':True,
                          'mode':'DYNAMIC','fill_auto':True,'master_enabled':True})
        s=client.get('/api/farm').json()
        assert s['device_online'] and s['headline']=='Đang bổ sung nước dự trữ'
        assert s['live']['tank_fill_on']
        assert s['alerts']==[]
        # A stale previous value must not be treated as a live valve/pump state.
        m.storage.ingest({'device':m.ROOT,'state':'CANAL_Z1','pump_on':True,'zone':1},ts=1)
        # latest row is stale despite previously fresh state
        s=client.get('/api/farm').json()
        assert s['live'] is None and s['alerts'][0]['kind']=='OFFLINE'


def test_technical_lab_fixtures(tmp_path):
    from app.twin import TwinService
    class Bridge:
        connected=True
        def __init__(self):self.sent=[]
        def publish_twin(self,msg):self.sent.append(msg)
        def command(self,cmd):pass
    db=Storage(str(tmp_path/'fixtures.db'))
    br=Bridge();t=TwinService(br,db)
    db.ingest({'device':'demo','state':'IDLE','mode':'TWIN','pump_on':False})
    t.running=True
    a=t.prepare_fill_test()
    assert a['world']['soil1_pct']==75 and a['world']['tank_l']==25
    assert br.sent[-1].startswith('SGT2,')
    b=t.prepare_irrigation_priority_test()
    assert b['world']['soil1_pct']==20
    assert br.sent[-1].startswith('SGT2,')
    db.close()


def test_lab_fixture_requires_live_twin(tmp_path):
    from app.twin import TwinService
    class Bridge:
        connected=False
    db=Storage(str(tmp_path/'fixtures.db'))
    t=TwinService(Bridge(),db)
    with pytest.raises(ConnectionError):t.prepare_fill_test()
    db.close()
