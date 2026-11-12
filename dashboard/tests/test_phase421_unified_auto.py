"""Phase 4.2.1: one irrigation switch; timer is never independent of manual mode."""
from pathlib import Path
import tempfile
import time

import pytest
from fastapi import HTTPException
from app import main
from app.storage import Storage

class Bridge:
    connected=True
    last_ack=None
    def __init__(self): self.commands=[]
    def command(self, cmd):
        self.commands.append(cmd)
        return {'sent':True,'command':cmd}

@pytest.fixture
def context(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        st=Storage(str(Path(folder)/'test.db'))
        dev=Bridge()
        live={'zone1_hold':False,'zone2_hold':False,'received_at':time.time()}
        monkeypatch.setattr(main,'storage',st)
        monkeypatch.setattr(main,'bridge',dev)
        monkeypatch.setattr(main,'snapshot',lambda:{'device_online':True,'broker_connected':dev.connected,'latest':live})
        monkeypatch.setattr(st,'latest',lambda:live)
        yield st,dev,live
        st.close()

def payload(action,minutes=None):
    return main.AutoIrrigationPayload(action=action,minutes=minutes)

def test_timer_start_then_switch_to_indefinite(context):
    st,dev,live=context
    r=main.set_zone_automatic(1,payload('hold_timed',60))
    assert r['status']=='PENDING_HOLD'
    assert dev.commands==['ZONE:1:HOLD']
    assert len(st.timed_holds())==1
    live['zone1_hold']=True
    main.set_zone_automatic(1,payload('hold_manual'))
    assert st.timed_holds()==[]
    assert dev.commands==['ZONE:1:HOLD']  # no duplicate HOLD

def test_held_manual_to_timed_and_change_duration(context):
    st,dev,live=context
    live['zone1_hold']=True
    first=main.set_zone_automatic(1,payload('hold_timed',15))
    assert first['confirmed'] is True
    second=main.set_zone_automatic(1,payload('hold_timed',120))
    assert second['until_ts']>first['until_ts']
    assert len(st.timed_holds())==1
    assert st.timed_holds()[0]['status']=='ACTIVE'
    assert dev.commands==[]

def test_resume_cancels_timer(context):
    st,dev,live=context
    live['zone2_hold']=True
    main.set_zone_automatic(2,payload('hold_timed',60))
    r=main.set_zone_automatic(2,payload('resume'))
    assert r['status']=='PENDING_RESUME'
    assert st.timed_holds()==[]
    assert dev.commands==['ZONE:2:RESUME']

def test_offline_cannot_claim_activation(context):
    st,dev,live=context
    dev.connected=False
    with pytest.raises(HTTPException) as ex:
        main.set_zone_automatic(1,payload('hold_timed',60))
    assert ex.value.status_code==503
    assert st.timed_holds()==[]
    assert dev.commands==[]

def test_due_timer_waits_for_connection(context):
    st,dev,live=context
    live['zone1_hold']=True
    main.set_zone_automatic(1,payload('hold_timed',15))
    st.conn.execute('UPDATE timed_zone_holds SET until_ts=? WHERE zone=1',(time.time()-1,))
    st.conn.commit()
    dev.connected=False
    main.reconcile_timed_holds()
    assert dev.commands==[]
    dev.connected=True
    main.reconcile_timed_holds()
    assert dev.commands==['ZONE:1:RESUME']
    assert st.timed_holds()[0]['status']=='PENDING_RESUME'

def test_invalid_period_rejected(context):
    st,dev,live=context
    with pytest.raises(HTTPException) as ex:
        main.set_zone_automatic(1,payload('hold_timed',3))
    assert ex.value.status_code==400
    assert st.timed_holds()==[]
