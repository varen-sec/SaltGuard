import time
import sqlite3
from pathlib import Path
from app.storage import Storage


def pkt(ms, zone=0, source='NONE', on=False, z1=0.0, z2=0.0, state='IDLE'):
    return dict(ms=ms, zone=zone, source=source, pump_on=on, state=state,
                soil1_pct=20, soil2_pct=30, salinity_ppt=0.5,
                irrigation_zone1_estimated_total_l=z1,
                irrigation_zone2_estimated_total_l=z2)


def test_water_from_esp32_counter_and_pause_resume_no_double_count(tmp_path):
    db=Storage(str(tmp_path/'t.db'));t=time.time()-100
    db.ingest(pkt(1000),t)
    db.ingest(pkt(2000,1,'CANAL',True,0.2,state='CANAL_Z1'),t+1)
    db.ingest(pkt(4000,1,'CANAL',True,1.0,state='CANAL_Z1'),t+3)
    db.ingest(pkt(5000,z1=1.0,state='PAUSE'),t+4)
    db.ingest(pkt(12000,z1=1.0,state='REST'),t+11)
    db.ingest(pkt(14000,1,'CANAL',True,1.1,state='CANAL_Z1'),t+13)
    db.ingest(pkt(16000,1,'CANAL',True,1.6,state='CANAL_Z1'),t+15)
    db.ingest(pkt(18000,z1=1.8,state='REST'),t+17)
    records=list(reversed(db.activity_segments(1)))
    assert len(records)==2
    assert [x['water_estimated_l'] for x in records]==[1.0,0.8]
    summary=db.activity_report(1)
    assert summary['water_liters']==1.8
    assert summary['zone1_estimated_water_l']==1.8
    assert summary['water_verified_segments']==2
    db.close()


def test_water_separate_zones_and_missing_unverified(tmp_path):
    db=Storage(str(tmp_path/'t.db'));t=time.time()-100
    db.ingest(pkt(1000),t)
    db.ingest(pkt(2000,1,'CANAL',True,.2,state='CANAL_Z1'),t+1)
    db.ingest(pkt(4000,2,'TANK',True,1.0,.3,state='TANK_Z2'),t+3)
    db.ingest(pkt(6000,z1=1.0,z2=0.7),t+5)
    records=list(reversed(db.activity_segments(1)))
    assert len(records)==2
    assert records[0]['water_estimated_l']==1.0
    assert records[1]['water_estimated_l']==0.7
    assert db.activity_report(1)['water_liters']==1.7
    assert db.activity_report(1)['zone2_estimated_water_l']==0.7
    assert db.activity_report(1,2)['water_liters']==0.7
    db.close()


def test_mqtt_gap_and_restart_dont_invent_water(tmp_path):
    db=Storage(str(tmp_path/'t.db'));t=time.time()-100
    db.ingest(pkt(1000),t)
    db.ingest(pkt(2000,1,'CANAL',True,0.2,state='CANAL_Z1'),t+1)
    db.ingest(pkt(35000,1,'CANAL',True,2.0,state='CANAL_Z1'),t+3)
    rows=db.activity_segments(1)
    assert rows[0]['water_estimated_l'] is None
    assert rows[0]['water_quality']=='UNVERIFIED'
    db.ingest(pkt(100),t+4)
    assert db.activity_report(1)['water_liters'] is None
    db.close()


def test_volume_column_migration_and_csv(tmp_path,monkeypatch):
    import app.main as main
    db=Storage(str(tmp_path/'t.db'))
    cols=[r['name'] for r in db.conn.execute('PRAGMA table_info(irrigation_segments)')]
    assert 'water_estimated_l' in cols
    monkeypatch.setattr(main,'storage',db)
    out=main.activity_report(days=1,zone=0)
    assert len(out['water_daily'])>=1
    result=main.activity_csv(days=1,zone=0)
    assert 'estimated_water_l' in result.body.decode('utf-8-sig')
    html=(Path(main.BASE)/'static/activity.html').read_text()
    assert 'activity-water-chart' in html
    db.close()
