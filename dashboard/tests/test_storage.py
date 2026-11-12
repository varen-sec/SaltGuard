import time
from app.storage import Storage


def test_ingest_history_and_state_transitions(tmp_path):
    db = Storage(str(tmp_path / 'data.db'))
    now = time.time()
    p = {'device':'saltguard/demo/root', 'ms':100, 'state':'CANAL_Z1',
         'source':'CANAL','zone':1,'pump_on':True, 'canal_safe':True,
         'soil1_pct':20, 'soil2_pct':70, 'salinity_ppt':0.5, 'tank_l':50}
    db.ingest(p, now-2)
    db.ingest({**p, 'ms':200, 'state':'REST', 'pump_on':False, 'zone':0,
               'canal_safe':False, 'reason':'REST'}, now-1)
    latest=db.latest()
    assert latest['state']=='REST' and latest['received_at']>=now-2
    assert len(db.history(5))==2
    events=db.events()
    assert any('không an toàn' in e['title'] for e in events)
    assert any(e['title']=='Trạng thái: REST' for e in events)
    assert db.history(1, limit=1)[-1]['state']=='REST'
    db.close()


def test_empty_and_missing_values(tmp_path):
    db=Storage(str(tmp_path/'zero.db'))
    assert db.latest() is None
    assert db.history() == []
    db.ingest({'state':'FAULT','pump_on':False, 'soil1_pct':None})
    assert db.latest()['state']=='FAULT'
    assert db.events()[0]['severity']=='critical'
    db.close()
