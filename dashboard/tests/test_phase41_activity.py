import time
from pathlib import Path
from app.storage import Storage

def sample(ms,state='CANAL_Z1',zone=1,source='CANAL',on=True,soil=20):
    return {'device':'test','ms':ms,'state':state,'zone':zone,'source':source,'pump_on':on,
            'soil1_pct':soil,'soil2_pct':70,'salinity_ppt':0.5,'tank_l':1500}

def test_session_completed_and_report(tmp_path):
    st=Storage(str(tmp_path/'db.sqlite'))
    now=time.time()
    st.ingest(sample(1000),now-15)
    st.ingest(sample(5400,soil=30),now-10)
    st.ingest(sample(7100,'REST',0,'NONE',False,soil=35),now-8)
    r=st.activity_report(1)
    assert r['segments']==1 and r['verified_segments']==1 and r['pump_sim_seconds']==6.1
    assert r['water_liters'] is None
    entry=st.activity_segments(1)[0]
    assert entry['zone']==1 and entry['source']=='CANAL' and entry['end_soil_pct']==35
    st.close()

def test_zone_change_source_change_and_reboot(tmp_path):
    st=Storage(str(tmp_path/'db.sqlite'))
    now=time.time()
    st.ingest(sample(1000),now-15)
    st.ingest(sample(2500,'TANK_Z1',1,'TANK'),now-14)
    st.ingest(sample(4000,'TANK_Z2',2,'TANK'),now-13)
    st.ingest(sample(5,'REST',0,'NONE',False),now-12)
    a=st.activity_segments(1)
    assert len(a)==3
    assert sum(x['status']=='COMPLETED' for x in a)==2
    assert sum(x['status']=='UNVERIFIED' for x in a)==1
    assert st.activity_report(1,2)['unverified_segments']==1
    st.close()

def test_gap_unverified(tmp_path):
    st=Storage(str(tmp_path/'db.sqlite'))
    now=time.time();st.ingest(sample(1000),now-15);st.ingest(sample(35000),now-5)
    r=st.activity_segments(1)[0]
    assert r['status']=='UNVERIFIED' and r['duration_sim_seconds'] is None
    st.close()

def test_restart_orphan_has_no_made_up_duration(tmp_path):
    path=str(tmp_path/'db.sqlite')
    st=Storage(path);st.ingest(sample(1000));st.close()
    st=Storage(path)
    assert st.activity_segments(1)[0]['status']=='UNVERIFIED'
    assert st.activity_segments(1)[0]['end_reason']=='BACKEND_RESTART'
    assert st.activity_report(1)['pump_sim_seconds']==0
    st.close()

def test_existing_old_db_migrates(tmp_path):
    import sqlite3
    path=str(tmp_path/'db.sqlite')
    conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE active_irrigation(id INTEGER PRIMARY KEY, zone INTEGER, source TEXT, started_ms INTEGER,started_at REAL)')
    conn.commit();conn.close()
    st=Storage(path)
    st.ingest(sample(1000)); st.ingest(sample(2000,'REST',0,'NONE',False))
    assert st.activity_report(1)['verified_segments']==1
    st.close()

def test_export_response_and_activity_markup(tmp_path, monkeypatch):
    import app.main as main
    mock=Storage(str(tmp_path/'activity.db'))
    monkeypatch.setattr(main,'storage',mock)
    response=main.activity_csv(days=1,zone=0)
    assert 'filename="saltguard_nhat_ky_' in response.headers['content-disposition']
    assert 'segment_id' in response.body.decode('utf-8-sig')
    html=(Path(main.BASE)/'static/activity.html').read_text()
    assert 'activity-export' in html and 'volume' not in html.lower()
    mock.close()
