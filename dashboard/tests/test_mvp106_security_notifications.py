"""MVP 1.0.6 PIN gate and SQLite notification regression."""
from fastapi.testclient import TestClient
from app.storage import Storage


def test_notification_episodes_persist_and_separate(tmp_path):
    db=Storage(str(tmp_path/'alerts.db'))
    first={'kind':'CANAL','level':'warning','title':'Kênh không dùng được','detail':'Độ mặn vượt ngưỡng'}
    second={'kind':'SOIL_DRY','zone':1,'level':'warning','title':'Vườn 1 rất khô','detail':'Cần nước'}
    db.sync_notifications([first,second])
    db.sync_notifications([first,second])
    assert db.notification_count()==2
    assert all(x['active'] for x in db.notifications())
    db.sync_notifications([second])
    assert len([x for x in db.notifications() if x['active']])==1
    assert len([x for x in db.notifications() if not x['active']])==1
    db.sync_notifications([first,second])  # the same issue reoccurs as a fresh episode
    assert db.notification_count()==3
    db.close()
    reopened=Storage(str(tmp_path/'alerts.db'))
    assert reopened.notification_count()==3
    assert len(reopened.notifications(limit=2,offset=1))==2
    reopened.close()


def test_pin_restricts_specialist_pages_and_api(tmp_path,monkeypatch):
    monkeypatch.setenv('SALTGUARD_DB',str(tmp_path/'pin.db'))
    from app import mqtt_service
    monkeypatch.setattr(mqtt_service.MqttService,'start',lambda self:None)
    monkeypatch.setattr(mqtt_service.MqttService,'stop',lambda self:None)
    import app.main as m
    from importlib import reload
    reload(m)
    with TestClient(m.app) as c:
        assert c.get('/').status_code==200
        assert c.get('/expert',follow_redirects=False).status_code==303
        assert c.get('/lab',follow_redirects=False).status_code==303
        assert c.post('/api/twin/start',json={'scenario':'NORMAL'}).status_code==403
        assert c.post('/api/command',json={'command':'ZONES:1'}).status_code==403
        assert c.post('/api/farm/config',json={'zones':[{'name':'1','crop':'A'},{'name':'2','crop':'B'}]}).status_code==403
        assert c.post('/api/advanced/login',json={'pin':'2222'}).status_code==401
        assert c.post('/api/advanced/login',json={'pin':'1111'}).status_code==200
        assert c.get('/expert').status_code==200
        assert c.get('/lab').status_code==200
        assert c.get('/technical/advanced').status_code==200
        assert c.post('/api/farm/config',json={'zones':[{'name':'1','crop':'A'},{'name':'2','crop':'B'}]}).status_code==200
        assert c.post('/api/advanced/logout').status_code==200
        assert c.get('/expert',follow_redirects=False).status_code==303
        assert c.post('/api/twin/start',json={'scenario':'NORMAL'}).status_code==403


def test_farmer_notifications_show_multiple_saved_items(tmp_path,monkeypatch):
    monkeypatch.setenv('SALTGUARD_DB',str(tmp_path/'ui.db'))
    from app import mqtt_service
    monkeypatch.setattr(mqtt_service.MqttService,'start',lambda self:None)
    monkeypatch.setattr(mqtt_service.MqttService,'stop',lambda self:None)
    import app.main as m
    from importlib import reload
    reload(m)
    with TestClient(m.app) as c:
        assert c.get('/api/farm').status_code==200
        assert c.get('/api/notifications').json()['total']==1 # offline
        m.storage.ingest({'device':m.ROOT,'state':'IDLE','canal_safe':False,'soil1_pct':5,
                          'master_enabled':False,'mode':'DYNAMIC','zone1_hold':False})
        summary=c.get('/api/farm').json()
        assert len(summary['alerts'])>=2
        items=c.get('/api/notifications').json()['items']
        assert len(items)>=3 # offline archived + multiple active warnings
        assert any(not item['active'] for item in items)
        assert any(item['active'] for item in items)
        assert 'Thông báo trước đây' in c.get('/').text
        assert 'Chế độ chuyên gia' in c.get('/').text
