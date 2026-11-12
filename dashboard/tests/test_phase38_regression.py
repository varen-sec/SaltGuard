"""Phase 3.8: UI contracts and TC07's LOCAL -> TWIN -> stale handshake."""
from pathlib import Path
import json
from app.twin import TwinService
from app.storage import Storage

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / 'dashboard' / 'app' / 'static'

class FakeBridge:
    connected = True
    def __init__(self): self.commands=[];self.frames=[]
    def command(self,cmd): self.commands.append(cmd)
    def publish_twin(self,payload): self.frames.append(payload)


def test_tc07_from_local_arms_after_fresh_twin_telemetry(tmp_path):
    storage=Storage(str(tmp_path/'test.db'));bridge=FakeBridge()
    storage.ingest({'device':'test','mode':'DYNAMIC','state':'IDLE','master_enabled':True})
    svc=TwinService(bridge,storage)
    result=svc.test_stale_input()
    assert result['stale_arm_pending'] and not result['twin_publish_paused']
    assert 'TWIN:ON' in bridge.commands
    # A newly arrived ESP32 TWIN frame is required before stopping publishing.
    svc._stale_requested_at=0
    storage.ingest({'device':'test','mode':'TWIN','state':'REST','master_enabled':True})
    svc.step()
    assert not svc.snapshot()['stale_arm_pending']
    assert svc.snapshot()['twin_publish_paused']
    assert 'DEMO:TC07:START' in bridge.commands
    assert svc._mute_until > svc.clock() + 50
    svc.resume_test_input()
    assert not svc.snapshot()['twin_publish_paused']
    storage.close()


def test_tc07_recovery_and_single_trigger_in_ui():
    js=(STATIC/'lab.js').read_text(encoding='utf-8')
    html=(STATIC/'lab.html').read_text(encoding='utf-8')
    assert 'id="lab-stale"' not in html
    assert 'id="lab-resume"' in html
    assert 'id===\'STALE\'' in js
    assert "api('/api/twin/lab/test-stale'" in js
    assert 'd.twin_publish_paused||d.stale_arm_pending' in js
    assert 'const t=snap.latest||{}' in js


def test_home_has_no_duplicate_fixed_panels_and_valves_unchanged():
    html=(STATIC/'farmer.html').read_text(encoding='utf-8')
    js=(STATIC/'farmer.js').read_text(encoding='utf-8')
    assert 'id="home-activity"' not in html
    assert 'id="home-water-primary"' not in html
    assert 'id="home-priority"' in html
    assert 'function renderHomePriority(' in js
    assert 'nextWaterTime()' not in js
    diagram=json.loads((ROOT/'firmware_wokwi'/'diagram.json').read_text(encoding='utf-8'))
    assert sum(p['type']=='wokwi-servo' for p in diagram['parts']) == 5


def test_firmware_feedback_and_safe_rest():
    fw=(ROOT/'firmware_wokwi'/'sketch.ino').read_text(encoding='utf-8')
    assert 'REST_MS=2000UL' in fw
    assert 'MASTER_RECHECK_MS=1500UL' in fw
    assert 'twin_rx_count' in fw
    assert '++twinRxCount' in fw
    assert 'if(emergencyLatched)' in fw
    assert 'if(wanted==AL_NONE || buzzerAcknowledged) return;' in fw
