"""Phase 4.5.1 regression: stale telemetry and conservatively observed water."""
import time
from app.storage import Storage


def frame(ms, zone=0, source='NONE', pump=False, z1=0.0, z2=0.0, reason='REST'):
    return dict(device='saltguard/demo/a', ms=ms, zone=zone, source=source,
                pump_on=pump, state='CANAL_Z1' if pump and zone==1 else 'IDLE',
                reason=reason,soil1_pct=20.,soil2_pct=20.,
                irrigation_zone1_estimated_total_l=z1,
                irrigation_zone2_estimated_total_l=z2)


def test_delayed_sample_does_not_falsely_close_active_segment(tmp_path):
    s=Storage(str(tmp_path/'log.db')); t=time.time()-100
    for dt,p in [(0,frame(1000)),(2,frame(3000,1,'CANAL',True,.3)),
                 (4,frame(5000,1,'CANAL',True,.7)),
                 (5,frame(4500,1,'CANAL',True,.6)),
                 (6,frame(7000,1,'CANAL',True,1.1)),(7,frame(8000,z1=1.2))]:
        s.ingest(p,t+dt)
    rows=s.activity_segments(1)
    assert len(rows)==1
    assert rows[0]['end_reason']!='ESP32_RESTART'
    assert rows[0]['water_quality']=='ESTIMATED'
    assert rows[0]['water_estimated_l']==1.2
    assert s.latest()['ms']==8000
    s.close()


def test_first_seen_while_pumping_records_lower_bound_only(tmp_path):
    s=Storage(str(tmp_path/'log.db')); t=time.time()-100
    s.ingest(frame(2500,1,'CANAL',True,.4),t)
    s.ingest(frame(4500,1,'CANAL',True,.8),t+2)
    s.ingest(frame(6500,z1=1.2),t+4)
    rec=s.activity_segments(1)[0]
    assert rec['water_quality']=='PARTIAL'
    assert rec['water_estimated_l']==.8
    summary=s.activity_report(1)
    assert summary['water_liters'] is None
    assert summary['water_partial_segments']==1
    assert summary['water_partial_l']==.8
    s.close()


def test_true_reboot_counter_rollback_is_unverified(tmp_path):
    s=Storage(str(tmp_path/'log.db'));t=time.time()-100
    s.ingest(frame(30000),t)
    s.ingest(frame(32000,1,'CANAL',True,1.0),t+1)
    s.ingest(frame(35000,1,'CANAL',True,1.5),t+2)
    s.ingest(frame(1000,1,'CANAL',True,0.0),t+3)
    rows=s.activity_segments(1)
    assert len(rows)==1 and rows[0]['end_reason']=='ESP32_RESTART'
    assert rows[0]['water_estimated_l'] is None
    s.close()


def test_pause_resume_verified_without_double_count(tmp_path):
    s=Storage(str(tmp_path/'log.db'));t=time.time()-100
    for dt,p in [(0,frame(1000)),(1,frame(2000,1,'CANAL',True,.2)),
                 (3,frame(4000,1,'CANAL',True,.8)),(4,frame(5000,z1=1.0)),
                 (5,frame(6000,z1=1.0)),(6,frame(7000,1,'CANAL',True,1.1)),
                 (8,frame(9000,1,'CANAL',True,1.5)),(9,frame(10000,z1=1.9))]:
        s.ingest(p,t+dt)
    assert [r['water_estimated_l'] for r in reversed(s.activity_segments(1))]==[1.,.9]
    assert s.activity_report(1)['water_liters']==1.9
    s.close()
