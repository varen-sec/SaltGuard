"""Phase 4.6.2: serial D must not strand an already-running Backend CUSTOM."""
import time
from app.storage import Storage
from app.twin import TwinService

class Bridge:
    connected = True
    def __init__(self):
        self.commands = []
        self.frames = []
    def command(self, cmd):
        self.commands.append(cmd)
    def publish_twin(self, frame):
        self.frames.append(frame)

DATA = dict(soil1_pct=20.,soil2_pct=80.,salinity_ppt=0.5,
            canal_pct=80.,rain_pct=0.,tank_l=1500.)
def sample(mode,rx=1,**changes):
    d=dict(DATA,mode=mode, twin_rx_count=rx, state='IDLE',
           master_enabled=True,clock_valid=True,irrigation_window=False)
    d.update(changes)
    return d

def test_rearms_twin_after_serial_d_without_backend_disable(tmp_path):
    clock = [time.time()]
    db=Storage(str(tmp_path/'case.db')); br=Bridge()
    db.ingest(sample('DYNAMIC', rx=4),ts=clock[0]-1)
    svc=TwinService(br,db,clock=lambda:clock[0]); svc.running=True
    result=svc.apply_custom_inputs(DATA)
    assert br.commands.index('TWIN:ON') < br.commands.index('DEMO:CUSTOM:START')
    assert result['delivery_status']=='PUBLISHED_AWAITING_ESP32'
    assert br.frames and br.frames[-1].startswith('SGT2,')
    assert 'ZONE:1:ONCE' not in br.commands
    clock[0]+=.3
    db.ingest(sample('DYNAMIC',rx=5),ts=clock[0]);svc.step()
    assert 'ZONE:1:ONCE' not in br.commands
    clock[0]+=.3
    db.ingest(sample('TWIN',rx=6),ts=clock[0]);svc.step()
    assert svc._custom_frame_confirmed(db.latest(),clock[0])
    db.close()

def test_does_not_rearm_when_controller_already_twin(tmp_path):
    clock=[time.time()]
    db=Storage(str(tmp_path/'case.db'));br=Bridge()
    db.ingest(sample('TWIN',rx=3),ts=clock[0]-1)
    svc=TwinService(br,db,clock=lambda:clock[0]);svc.running=True
    svc.apply_custom_inputs(DATA)
    assert 'TWIN:ON' not in br.commands
    assert 'DEMO:CUSTOM:START' in br.commands
    db.close()

def test_rejects_preset_without_sending_twin_on(tmp_path):
    clock=[time.time()]
    db=Storage(str(tmp_path/'case.db'));br=Bridge()
    db.ingest(sample('PRESET'),ts=clock[0]-1)
    svc=TwinService(br,db,clock=lambda:clock[0]);svc.running=True
    try:svc.apply_custom_inputs(DATA)
    except ValueError:pass
    else:raise AssertionError('Expected PRESET rejection')
    assert not br.commands
    db.close()
