"""Phase 4.0: simulated agronomic profiles, two-zone thresholds, ESP32 authoritative sync."""
from pathlib import Path
import json
import time
import pytest
from fastapi import HTTPException
from app.storage import Storage
from app import main

ROOT=Path(__file__).resolve().parents[2]
SKETCH=(ROOT/'firmware_wokwi/sketch.ino').read_text(encoding='utf-8')
DIAGRAM=json.loads((ROOT/'firmware_wokwi/diagram.json').read_text(encoding='utf-8'))

class Bridge:
    def __init__(self,connected=True):
        self.connected=connected
        self.commands=[]
    def command(self,cmd):
        if not self.connected:raise ConnectionError('offline')
        self.commands.append(cmd)
        return {'sent':True,'command':cmd}

class Twin:
    def snapshot(self):return {'running':False}

@pytest.fixture
def ctx(tmp_path,monkeypatch):
    db=Storage(str(tmp_path/'saltguard.db'))
    bridge=Bridge()
    monkeypatch.setattr(main,'storage',db)
    monkeypatch.setattr(main,'bridge',bridge)
    monkeypatch.setattr(main,'twin',Twin())
    monkeypatch.setattr(main,'soil_sync_pending_since',0.0)
    yield db,bridge
    db.close()

def body(start=(25,45),stop=(55,75)):
    zs=[]
    for i in range(2):
        z={'name':f'Z{i+1}','crop':'Thử nghiệm','soil_type':'Đất thịt',
           'growth_stage':'Sinh trưởng','soil_start_pct':start[i],
           'soil_stop_pct':stop[i]}
        zs.append(z)
    return main.FarmConfigPayload(zones=zs)

def test_default_migrates_to_35_60(ctx):
    db,_=ctx
    assert [(z['soil_start_pct'],z['soil_stop_pct']) for z in db.get_farm_config()['zones']]==[(35,60),(35,60)]

def test_command_sent_before_save_and_telemetry_authoritative(ctx):
    db,bridge=ctx
    result=main.farm_config_save(body())
    assert bridge.commands==['SOIL:25,55,45,75']
    assert result['sync_status']=='PENDING_ESP32_TELEMETRY'
    assert not main.farm_config_sync()['synced']
    # Wokwi device explicitly returns the thresholds in a fresh frame.
    db.ingest({'state':'IDLE','soil_start_z1':25,'soil_stop_z1':55,
               'soil_start_z2':45,'soil_stop_z2':75},ts=time.time()+0.01)
    assert main.farm_config_sync()['status']=='SYNCED'
    assert main.farm_config_sync()['synced']

def test_mismatch_not_falsely_reported_synced(ctx):
    db,_=ctx
    main.farm_config_save(body())
    db.ingest({'state':'IDLE','soil_start_z1':35,'soil_stop_z1':60,
               'soil_start_z2':35,'soil_stop_z2':60},ts=time.time()+0.01)
    assert main.farm_config_sync()['status']=='MISMATCH'

def test_offline_does_not_replace_saved_settings(ctx):
    db,bridge=ctx
    bridge.connected=False
    with pytest.raises(HTTPException) as exc:
        main.farm_config_save(body())
    assert exc.value.status_code==503
    assert db.get_farm_config()['zones'][0]['soil_start_pct']==35

def test_invalid_thresholds_rejected_before_mqtt(ctx):
    db,bridge=ctx
    with pytest.raises(HTTPException) as exc:
        main.farm_config_save(body(start=(55,45),stop=(58,75)))
    assert exc.value.status_code==400
    assert bridge.commands==[]
    assert db.get_farm_config()['zones'][0]['soil_start_pct']==35

def test_reusable_profiles_persist_across_db_reopen(tmp_path):
    path=str(tmp_path/'profiles.db')
    p={'crop':'Lúa','soil_type':'Đất thịt','growth_stage':'Sinh trưởng',
       'soil_start_pct':27,'soil_stop_pct':57}
    db=Storage(path);db.save_crop_profile(p);db.close()
    db=Storage(path)
    assert len(db.list_crop_profiles())==1
    assert db.list_crop_profiles()[0]['soil_start_pct']==27
    db.close()

def test_firmware_atomic_validation_and_preferences():
    assert 'SOIL:start1,stop1,start2,stop2' in SKETCH
    assert 'INVALID_SOIL_THRESHOLDS' in SKETCH
    for name in ['soilS1','soilT1','soilS2','soilT2']:
        assert f'putUChar("{name}"' in SKETCH
        assert f'getUChar("{name}"' in SKETCH
    assert 'if(soil[i]<=soilStartPct[i])' in SKETCH
    assert 'else if(soil[i]>=soilStopPct[i])' in SKETCH
    assert 'soil_config_revision' in SKETCH
    assert 'SOIL_THRESHOLDS_SAVED' in SKETCH

def test_no_gpio_or_wiring_changes():
    assert len(DIAGRAM['connections'])==106
    assert ['pause:1.l','esp:TX2','orange',[]] in DIAGRAM['connections']
    assert ['fault:1.l','esp:VN','orange',[]] in DIAGRAM['connections']
    assert 'ACK_RECOVERY_HOLD_MS=2000UL' in SKETCH
