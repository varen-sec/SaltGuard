import importlib

from fastapi.testclient import TestClient


def test_http_dashboard_and_command_validation(tmp_path,monkeypatch):
    monkeypatch.setenv('SALTGUARD_DB',str(tmp_path/'test.db'))
    from app import mqtt_service
    monkeypatch.setattr(mqtt_service.MqttService,'start',lambda self:None)
    monkeypatch.setattr(mqtt_service.MqttService,'stop',lambda self:None)
    import app.main as webapp
    importlib.reload(webapp)
    with TestClient(webapp.app) as client:
        assert client.post('/api/advanced/login',json={'pin':'1111'}).status_code==200
        page=client.get('/')
        assert page.status_code==200 and 'SaltGuard' in page.text
        assert client.get('/static/dashboard.js').status_code==200
        snap=client.get('/api/snapshot').json()
        assert snap['latest'] is None and not snap['device_online']
        assert client.get('/api/history').json()['data']==[]
        bad=client.post('/api/command',json={'command':'PUMP_ON'})
        assert bad.status_code==400
        unavailable=client.post('/api/command',json={'command':'STATUS'})
        assert unavailable.status_code==503
        webapp.storage.ingest({'device':webapp.ROOT,'state':'CANAL_Z1','pump_on':True,'zone':1,'salinity_ppt':0.5})
        live=client.get('/api/snapshot').json()
        assert live['device_online'] and live['latest']['pump_on']
        assert len(client.get('/api/history').json()['data'])==1
        assert client.get('/api/events').json()['events']
