"""Phase 3.8.1: diagnostic contract without changing GPIO or irrigation logic."""
from pathlib import Path
from app.mqtt_service import ALLOWED_COMMANDS
from app.twin import TwinService
from app.storage import Storage

ROOT=Path(__file__).resolve().parents[2]
FIRMWARE=(ROOT/'firmware_wokwi/sketch.ino').read_text(encoding='utf-8')

class Bridge:
    connected=True
    def __init__(self):self.commands=[];self.frames=[]
    def command(self,cmd):self.commands.append(cmd)
    def publish_twin(self,payload):self.frames.append(payload)

def test_custom_markers_allowlisted():
    for name in ('START','UPDATE','END'):
        assert 'DEMO:CUSTOM:'+name in ALLOWED_COMMANDS
        assert 'DEMO:CUSTOM:'+name in FIRMWARE

def test_custom_reapply_sends_markers_and_input(tmp_path):
    storage=Storage(str(tmp_path/'t.db'));bridge=Bridge()
    storage.ingest({'device':'test','mode':'TWIN','state':'IDLE','master_enabled':True})
    svc=TwinService(bridge,storage)
    vals=dict(soil1_pct=20,soil2_pct=25,salinity_ppt=.5,canal_pct=80,rain_pct=0,tank_l=1500)
    svc.apply_custom_inputs(vals)
    assert 'DEMO:CUSTOM:START' in bridge.commands
    assert bridge.frames
    svc.apply_custom_inputs({**vals,'salinity_ppt':1.5})
    assert 'DEMO:CUSTOM:UPDATE' in bridge.commands
    svc.disable()
    assert 'DEMO:CUSTOM:END' in bridge.commands
    storage.close()

def test_manual_preserves_gpio_and_exposes_diagnostics():
    assert 'MANUAL_PIN=39' in FIRMWARE
    assert 'PANEL MANUAL GPIO39' in FIRMWARE
    assert 'requestManualIrrigation(now);' in FIRMWARE
    assert 'advanceLCDPage' not in FIRMWARE
