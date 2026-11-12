import json
import time
from types import SimpleNamespace
import pytest
from app.twin import FarmWorld,TwinService
from app.storage import Storage
from app.mqtt_service import MqttService

class FakeBridge:
    connected=True
    def __init__(self):self.commands=[];self.frames=[]
    def command(self,cmd):self.commands.append(cmd)
    def publish_twin(self,frame):self.frames.append(frame)

def test_world_response_to_esp32_and_pump_offline():
    w=FarmWorld()
    prior=w.soil1_pct
    w.advance(3,{'mode':'TWIN','pump_on':True,'source':'CANAL','zone':1},True)
    assert w.irrigating and w.estimated_flow_l_min==6.0
    assert w.soil1_pct>prior and w.soil2_pct<49
    assert w.tank_l>=75
    vol=w.estimated_total_l
    w.advance(3,{'mode':'TWIN','pump_on':True,'source':'TANK','zone':2},True)
    assert w.tank_l<75.01 and w.estimated_total_l>vol
    w.advance(3,{'mode':'TWIN','pump_on':True,'source':'TANK','zone':2},False)
    assert w.estimated_flow_l_min==0 and not w.irrigating
    assert len(w.wire_input().split(','))==8

def test_salinisation_then_rain_recovers():
    w=FarmWorld(scenario='SALINITY')
    for _ in range(20):w.advance(3,None,False)
    assert w.salinity_ppt>1.0
    w.scenario='RAIN'
    for _ in range(25):w.advance(3,None,False)
    assert w.salinity_ppt<0.7 and w.rain_pct>50

def test_twin_api_control_storage(tmp_path):
    db=Storage(str(tmp_path/'twin.db'))
    bridge=FakeBridge();t=TwinService(bridge,db)
    with pytest.raises(ConnectionError):t.enable()
    db.ingest({'device':'test','state':'CANAL_Z1','mode':'DYNAMIC','pump_on':True,'zone':1})
    result=t.enable('SALINITY')
    assert result['running'] and bridge.commands==['TWIN:ON']
    assert bridge.frames[0].startswith('SGT2,')
    assert len(db.twin_history())==1
    assert t.set_scenario('RAIN')['scenario']=='RAIN'
    result=t.disable()
    assert not result['running'] and bridge.commands[-1]=='TWIN:OFF'
    db.close()

def test_reject_preset_mode_and_unknown_scenario(tmp_path):
    db=Storage(str(tmp_path/'twin.db'));br=FakeBridge();t=TwinService(br,db)
    db.ingest({'device':'test','state':'CANAL_Z1','mode':'PRESET'})
    with pytest.raises(ValueError):t.enable()
    with pytest.raises(ValueError):t.set_scenario('UNKNOWN')
    db.close()

def test_twin_mqtt_never_retained(tmp_path):
    db=Storage(str(tmp_path/'mqtt.db'))
    m=MqttService(db,'host',1883,'sg/demo')
    calls=[]
    m.client=SimpleNamespace(publish=lambda topic,payload,qos,retain:(calls.append((topic,payload,qos,retain)) or SimpleNamespace(rc=0)))
    m.connected=True
    assert m.publish_twin('SGT2,0.5,80,0,24,49,75,0.3')
    assert calls[0][0]=='sg/demo/twin/input' and calls[0][2:]==(0,False)
    with pytest.raises(ValueError):m.publish_twin('ON')
    db.close()
