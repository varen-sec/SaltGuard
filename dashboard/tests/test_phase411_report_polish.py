"""Report navigation, truthful graph interpolation and robust CSV exports."""
import csv, io, time
from pathlib import Path
from app.storage import Storage
from app import main

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/'app'/'static'

def test_activity_independent_navigation():
    for name in ('expert.html','lab.html','activity.html'):
        text=(UI/name).read_text(encoding='utf-8')
        assert 'href="/activity"' in text
        assert 'href="/expert"' in text
        assert 'href="/lab"' in text
        assert '<nav class="bottom-nav workspace-nav"' in text
    expert=(UI/'expert.html').read_text(encoding='utf-8')
    assert '<h2>Lịch sử & báo cáo</h2>' not in expert
    report=(UI/'activity.html').read_text(encoding='utf-8')
    assert 'PHASE 4.1' not in report
    assert 'mô phỏng' not in report.lower()
    assert '<h2>Nhật ký tưới</h2>' in report
    assert 'Thời gian tưới' in report

def test_chart_is_smooth_without_fake_values():
    js=(UI/'activity.js').read_text(encoding='utf-8')
    assert '<polyline' not in js
    assert 'smoothPath(points)' in js
    assert ' C ' in js
    assert 'gapThreshold' in js
    assert 'x[field]!==null' in js

def test_csv_has_iso_timestamp_and_empty_unverified_duration(tmp_path,monkeypatch):
    st=Storage(str(tmp_path/'db.sqlite'))
    monkeypatch.setattr(main,'storage',st)
    now=time.time()
    def ingest(ms,state='CANAL_Z1',zone=1,src='CANAL',pump=True):
        st.ingest({'device':'test','ms':ms,'state':state,'zone':zone,'source':src,'pump_on':pump,'soil1_pct':20,'soil2_pct':70,'salinity_ppt':0.5,'tank_l':1500},now-10+(ms/1000))
    ingest(1000);ingest(2200,'REST',0,'NONE',False)
    ingest(4000);st.close()  # interrupted session must not invent duration
    st=Storage(str(tmp_path/'db.sqlite'));monkeypatch.setattr(main,'storage',st)
    response=main.activity_csv(days=1,zone=0)
    content=response.body.decode('utf-8-sig')
    assert '\r\n' in content
    table=list(csv.DictReader(io.StringIO(content)))
    assert len(table)==2
    assert list(table[0])==['segment_id','started_at_iso8601','ended_at_iso8601','zone','water_source','duration_seconds','status','end_reason','soil_start_pct','soil_end_pct']
    assert all('+07:00' in row['started_at_iso8601'] for row in table)
    bad=next(row for row in table if row['status']=='UNVERIFIED')
    assert bad['duration_seconds']==''
    ok=next(row for row in table if row['status']=='COMPLETED')
    assert float(ok['duration_seconds'])==1.2
    st.close()
