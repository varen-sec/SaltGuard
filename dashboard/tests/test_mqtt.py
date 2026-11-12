import json
from types import SimpleNamespace

import pytest
from app.mqtt_service import MqttService
from app.storage import Storage


def test_ingestion_and_ack(tmp_path):
    db=Storage(str(tmp_path/'test.db'))
    mqtt=MqttService(db,'broker.example',1883,'saltguard/demo/test')
    payload={'device':mqtt.root,'ms':1200,'state':'CANAL_Z1','source':'CANAL',
             'soil1_pct':24,'pump_on':True,'canal_safe':True}
    mqtt._on_message(None,None,SimpleNamespace(
        topic=mqtt.root+'/telemetry',payload=json.dumps(payload).encode()))
    assert db.latest()['state']=='CANAL_Z1'
    mqtt._on_message(None,None,SimpleNamespace(
        topic=mqtt.root+'/ack',payload=json.dumps({'command':'ZONE:1:HOLD','accepted':True,'message':'OK'}).encode()))
    assert mqtt.last_ack['command']=='ZONE:1:HOLD'
    assert any('ZONE:1:HOLD' in e['title'] for e in db.events())
    mqtt._on_message(None,None,SimpleNamespace(
        topic=mqtt.root+'/telemetry',payload=b'{"device":"other","state":"FAULT"}'))
    assert db.latest()['state']=='CANAL_Z1'
    db.close()


def test_only_allowlisted_commands_and_nonretained_publish(tmp_path):
    db=Storage(str(tmp_path/'mqtt.db'))
    bridge=MqttService(db,'broker.example',1883,'saltguard/demo/test')
    pub=[]
    bridge.client=SimpleNamespace(publish=lambda topic,payload,qos,retain:(pub.append((topic,payload,qos,retain)) or SimpleNamespace(rc=0)))
    bridge.connected=True
    result=bridge.command('ZONE:1:HOLD')
    assert result['sent']
    assert pub==[(bridge.root+'/cmd','ZONE:1:HOLD',0,False)]
    with pytest.raises(ValueError): bridge.command('PUMP_ON')
    db.close()
