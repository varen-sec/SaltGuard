from app.twin import TEST_PRESETS, FarmWorld, TwinService
import pytest

class Bridge:
    connected=True
    def __init__(self): self.frames=[]
    def publish_twin(self, frame): self.frames.append(frame)

class Storage:
    def latest(self): return {'mode':'TWIN', 'received_at':100.,'pump_on':False}
    def event(self,*args): pass
    def record_twin(self,*args): pass
    def get_farm_config(self): return {'zones': [{},{}]}
    def sync_soil_alerts(self,*args): pass

def make_service():
    bridge=Bridge()
    svc=TwinService(bridge,Storage(),clock=lambda:100.)
    svc.running=True
    return svc,bridge

@pytest.mark.parametrize('preset',TEST_PRESETS)
def test_real_twin_frames(preset):
    svc,bridge=make_service()
    result=svc.apply_test_preset(preset)
    assert result['last_preset']==preset
    assert bridge.frames[-1].startswith('SGT2,')
    assert svc.world.scenario=='NORMAL'
    for k,v in TEST_PRESETS[preset].items(): assert getattr(svc.world,k)==v

def test_unknown_preset_not_accepted():
    svc,_=make_service()
    with pytest.raises(ValueError):svc.apply_test_preset('BAD')

def test_offline_blocks_preset():
    svc,bridge=make_service()
    bridge.connected=False
    with pytest.raises(ConnectionError):svc.apply_test_preset('BOTH_DRY')

def test_stale_stops_frames_and_can_resume():
    svc,bridge=make_service()
    svc.test_stale_input()
    assert svc.snapshot()['twin_publish_paused']
    svc.step(initial=True)
    assert not bridge.frames
    svc.resume_test_input()
    assert bridge.frames and bridge.frames[-1].startswith('SGT2,')
