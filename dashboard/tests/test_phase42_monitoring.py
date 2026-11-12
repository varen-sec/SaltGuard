import tempfile,time
from pathlib import Path
from app.storage import Storage
from app.data_quality import evaluate,advice_for

def sample(**kw):
    base=dict(soil1_pct=35,soil2_pct=40,salinity_ppt=0.5,tank_l=1500,tank_sensor_valid=True)
    base.update(kw)
    return base

def test_quality_fresh_and_invalid_and_stale():
    assert evaluate(sample(),2,True)['status']=='FRESH'
    assert evaluate(sample(soil1_pct=150),1,True)['status']=='INVALID'
    assert evaluate(sample(),20,True)['status']=='STALE'
    assert evaluate(sample(),1,False)['status']=='STALE'
    assert evaluate(None,None,False)['status']=='NO_DATA'
    assert evaluate(sample(),12,True)['status']=='DELAYED'

def test_advice_is_actionable():
    assert 'Kiểm tra' in advice_for('FAULT')
    assert 'Kiểm tra' in advice_for('SOIL_DRY')

def test_timed_hold_lifecycle_persistence():
    with tempfile.TemporaryDirectory() as d:
        path=str(Path(d)/'hold.db'); st=Storage(path)
        end=time.time()+3600
        st.timed_hold_set(1,end,'request-one')
        assert st.timed_holds()[0]['status']=='PENDING_HOLD'
        st.timed_hold_update(1,'request-one','ACTIVE')
        assert st.timed_holds()[0]['status']=='ACTIVE'
        st.timed_hold_update(1,'wrong-request','PENDING_RESUME')
        assert st.timed_holds()[0]['status']=='ACTIVE'
        st.close()
        st=Storage(path)
        assert st.timed_holds()[0]['until_ts']==end
        st.timed_hold_delete(1)
        assert st.timed_holds()==[]
        st.close()
