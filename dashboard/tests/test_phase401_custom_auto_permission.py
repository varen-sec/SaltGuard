"""Phase 4.0.1: CUSTOM out-of-hours permissions require new matching ESP32 input."""
import time
from app.storage import Storage
from app.twin import TwinService

class Bridge:
    connected=True
    def __init__(self):self.commands=[];self.frames=[]
    def command(self,cmd):self.commands.append(cmd)
    def publish_twin(self,data):self.frames.append(data)

CUSTOM=dict(soil1_pct=35.,soil2_pct=35.,salinity_ppt=.5,canal_pct=80.,rain_pct=0.,tank_l=1500.)

def sample(rx=1, **updates):
    d=dict(mode='TWIN', state='IDLE', master_enabled=True,
           clock_valid=True, irrigation_window=False,
           zone1_hold=False,zone2_hold=False, paused=False,fault=False,
           twin_rx_count=rx, **CUSTOM)
    d.update(updates)
    return d

def test_custom_only_grants_after_new_matching_esp_telemetry(tmp_path):
    clock=[time.time()]
    db=Storage(str(tmp_path/'db.sqlite')); bridge=Bridge()
    db.ingest(sample(rx=5),ts=clock[0]-1)
    svc=TwinService(bridge,db,clock=lambda:clock[0]); svc.running=True
    svc.apply_custom_inputs(CUSTOM)
    assert 'ZONE:1:ONCE' not in bridge.commands
    assert svc.snapshot()['demo_permission_pending']==[1,2]
    clock[0]+=0.2
    db.ingest(sample(rx=5),ts=clock[0])
    svc.step()
    assert 'ZONE:1:ONCE' not in bridge.commands
    clock[0]+=0.2
    db.ingest(sample(rx=6,soil1_pct=20),ts=clock[0])
    svc.step()
    assert 'ZONE:1:ONCE' not in bridge.commands  # stale previous CUSTOM values
    clock[0]+=0.2
    db.ingest(sample(rx=7),ts=clock[0])
    svc.step()
    assert bridge.commands.count('ZONE:1:ONCE')==1
    assert bridge.commands.count('ZONE:2:ONCE')==0
    clock[0]+=3.2
    db.ingest(sample(rx=8),ts=clock[0])
    svc.step()
    assert bridge.commands.count('ZONE:2:ONCE')==1
    assert svc.snapshot()['demo_permission_pending']==[]
    svc.disable()
    assert 'ZONE:1:CANCEL_ONCE' in bridge.commands
    assert 'ZONE:2:CANCEL_ONCE' in bridge.commands
    db.close()

def test_custom_update_cancels_previous_and_does_not_reuse_telemetry(tmp_path):
    clock=[time.time()]
    db=Storage(str(tmp_path/'db.sqlite'));bridge=Bridge()
    db.ingest(sample(rx=1),ts=clock[0]-1)
    svc=TwinService(bridge,db,clock=lambda:clock[0]);svc.running=True
    svc.apply_custom_inputs(CUSTOM)
    clock[0]+=0.2
    db.ingest(sample(rx=2),ts=clock[0]);svc.step()
    assert 'ZONE:1:ONCE' in bridge.commands
    updated=dict(CUSTOM,soil1_pct=20.,soil2_pct=80.)
    svc.apply_custom_inputs(updated)
    assert 'ZONE:1:CANCEL_ONCE' in bridge.commands
    count=bridge.commands.count('ZONE:1:ONCE')
    clock[0]+=0.2
    db.ingest(sample(rx=3),ts=clock[0]);svc.step()
    assert bridge.commands.count('ZONE:1:ONCE')==count  # old values rejected
    clock[0]+=0.2
    db.ingest(sample(rx=4,soil1_pct=20.,soil2_pct=80.),ts=clock[0]);svc.step()
    assert bridge.commands.count('ZONE:1:ONCE')==count+1
    db.close()

def test_local_mode_pause_and_in_window_are_never_granted(tmp_path):
    clock=[time.time()]
    db=Storage(str(tmp_path/'db.sqlite'));bridge=Bridge()
    db.ingest(sample(rx=1,mode='DYNAMIC'),ts=clock[0]-1)
    svc=TwinService(bridge,db,clock=lambda:clock[0]);svc.running=True
    svc.apply_custom_inputs(CUSTOM)
    clock[0]+=0.2
    db.ingest(sample(rx=2,mode='DYNAMIC'),ts=clock[0]);svc.step()
    assert 'ZONE:1:ONCE' not in bridge.commands
    clock[0]+=0.2
    db.ingest(sample(rx=3,paused=True),ts=clock[0]);svc.step()
    assert 'ZONE:1:ONCE' not in bridge.commands
    clock[0]+=0.2
    db.ingest(sample(rx=4,irrigation_window=True),ts=clock[0]);svc.step()
    assert 'ZONE:1:ONCE' not in bridge.commands
    db.close()
