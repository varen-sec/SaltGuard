"""MVP 1.1 keeps the farmer app usable without pretending to add real hardware."""
import time
from pathlib import Path
from fastapi.testclient import TestClient
from app.storage import Storage

STATIC=Path(__file__).resolve().parents[1]/'app'/'static'

def test_trends_sample_real_telemetry_and_preference_persists(tmp_path):
    db=Storage(str(tmp_path/'trend.db'))
    now=time.time()
    for i in range(180):
        db.ingest({'device':'test','state':'IDLE','source':'NONE','zone':0,'pump_on':False,
                   'salinity_ppt':0.3+i/1000,'soil1_pct':33+i/90,
                   'soil2_pct':49+i/100,'tank_l':75},ts=now-7200+i*40)
    trends=db.trends(1,50)
    assert 2<=len(trends)<=50
    assert trends[0]['salinity_ppt']<trends[-1]['salinity_ppt']
    assert db.set_app_preferences('Vườn Sầu Riêng')['farm_name']=='Vườn Sầu Riêng'
    db.close()
    old=Storage(str(tmp_path/'trend.db'))
    assert old.get_app_preferences()['farm_name']=='Vườn Sầu Riêng'
    old.close()

def test_farmer_five_tabs_source_status_and_history_ui():
    ui=(STATIC/'farmer.html').read_text()
    js=(STATIC/'farmer.js').read_text()
    assert ui.count('data-page=')==5
    assert 'water-primary-title' in ui
    assert 'trend-salinity' not in ui and 'trend-soil' not in ui
    assert 'salinity-fill' in ui and 'reserve-fill' in ui
    assert 'profile-demo-form' in ui
    assert 'farmer.css?v=mvp11' in ui
    assert 'Đã khóa nguồn kênh' in js
    assert 'FILL:AUTO:ON' in js
    assert 'remote master' not in ui.lower()
    assert 'QR' not in ui

def test_backend_preferences_and_trends_no_pin(tmp_path,monkeypatch):
    monkeypatch.setenv('SALTGUARD_DB',str(tmp_path/'api.db'))
    from app import mqtt_service
    monkeypatch.setattr(mqtt_service.MqttService,'start',lambda self:None)
    monkeypatch.setattr(mqtt_service.MqttService,'stop',lambda self:None)
    import app.main as m
    from importlib import reload
    reload(m)
    with TestClient(m.app) as c:
        assert c.get('/api/farm/preferences').json()['farm_name']=='Vườn của tôi'
        assert c.patch('/api/farm/preferences',json={'farm_name':'Vườn Bưởi'}).status_code==200
        assert c.get('/api/farm/preferences').json()['farm_name']=='Vườn Bưởi'
        assert c.patch('/api/farm/preferences',json={'farm_name':''}).status_code==400
        assert c.get('/api/farm/trends?days=7').status_code==200
        assert c.get('/api/farm/trends?days=10').status_code==400
        assert c.post('/api/twin/start',json={'scenario':'NORMAL'}).status_code==403
        assert c.get('/api/farm').json()['app_preferences']['farm_name']=='Vườn Bưởi'

def test_irrigation_session_uses_device_millis_not_guessed_wall_time(tmp_path):
    db=Storage(str(tmp_path/'sessions.db'))
    common={'device':'demo','source':'CANAL','soil1_pct':25,'soil2_pct':55,'salinity_ppt':0.5,'tank_l':60}
    db.ingest({**common,'state':'CANAL_Z1','zone':1,'ms':1000,'pump_on':True})
    db.ingest({**common,'state':'CANAL_Z1','zone':1,'ms':6000,'pump_on':True})
    db.ingest({**common,'state':'REST','zone':0,'ms':11000,'pump_on':False})
    events=[e for e in db.events() if e['kind']=='irrigation_session']
    assert len(events)==1
    assert '10 giây mô phỏng' in events[0]['detail']
    db.ingest({**common,'state':'CANAL_Z1','zone':1,'ms':15000,'pump_on':True})
    db.ingest({**common,'state':'IDLE','zone':0,'ms':200,'pump_on':False}) # reboot
    assert len([e for e in db.events() if e['kind']=='irrigation_session'])==1
    db.close()
