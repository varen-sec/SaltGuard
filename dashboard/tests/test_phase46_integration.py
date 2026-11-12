"""Phase 4.6 integration contracts: offline, repeatable and non-destructive.
Run: cd dashboard && python -m pytest -q tests/test_phase46_integration.py
These tests do NOT replace Wokwi hardware/MQTT end-to-end acceptance.
"""
import json
import math
import time
from pathlib import Path

import pytest
from app.storage import Storage

ROOT = Path(__file__).resolve().parents[2]

def packet(ms, zone=0, source='NONE', pump=False, z1=0.0, z2=0.0, **kw):
    data = {
        'device': 'saltguard/demo/phase46-test', 'ms': ms, 'zone': zone,
        'source': source, 'pump_on': pump,
        'state': f'{source}_Z{zone}' if pump else 'IDLE', 'reason': 'SOIL_OK',
        'soil1_pct': 20., 'soil2_pct': 20., 'salinity_ppt': .5,
        'irrigation_zone1_estimated_total_l': z1,
        'irrigation_zone2_estimated_total_l': z2,
    }
    data.update(kw)
    return data

@pytest.fixture
def store(tmp_path):
    s=Storage(str(tmp_path/'phase46.sqlite'))
    yield s
    s.close()

def feed(store, entries):
    ts=time.time()-200
    for offset, frame in entries:
        store.ingest(frame,ts+offset)

def test_01_two_zones_sum_and_filter(store):
    feed(store, [(0,packet(1000)),(1,packet(2000,1,'CANAL',True,.1)),
      (5,packet(6000,1,'CANAL',True,.8)),
      (6,packet(7000,2,'TANK',True,1.,.1)),
      (10,packet(11000,2,'TANK',True,1.,1.1)),
      (11,packet(12000,z1=1.,z2=1.5))])
    r=store.activity_report(1)
    assert r['water_liters']==2.5
    assert r['zone1_estimated_water_l']==1.0
    assert r['zone2_estimated_water_l']==1.5
    assert store.activity_report(1,1)['water_liters']==1.0
    assert store.activity_report(1,2)['water_liters']==1.5
    assert {x['source'] for x in store.activity_segments(1)} == {'CANAL','TANK'}

def test_02_pause_resume_no_double_count(store):
    feed(store, [(0,packet(1000)),(1,packet(2000,1,'CANAL',True,.1)),
      (3,packet(4000,1,'CANAL',True,.7)),
      (4,packet(5000,z1=.9,reason='USER_PAUSE')),
      (5,packet(6000,z1=.9,reason='PAUSE')),
      (6,packet(7000,1,'CANAL',True,1.0)),
      (8,packet(9000,z1=1.7))])
    s=store.activity_report(1)
    assert s['water_liters']==1.7
    assert s['water_verified_segments']==2

def test_03_reordered_telemetry_not_restart(store):
    feed(store,[(0,packet(1000)),(1,packet(2000,1,'CANAL',True,.1)),
      (3,packet(4000,1,'CANAL',True,.5)),
      (4,packet(3500,1,'CANAL',True,.4)),
      (5,packet(6000,z1=1.))])
    rows=store.activity_segments(1)
    assert len(rows)==1
    assert rows[0]['water_quality']=='ESTIMATED'
    assert rows[0]['end_reason']!='ESP32_RESTART'

def test_04_real_restart_no_fabricated_water(store):
    feed(store,[(0,packet(30000)),(1,packet(32000,1,'CANAL',True,.3)),
      (2,packet(35000,1,'CANAL',True,1.)),(3,packet(1000,z1=0))])
    row=store.activity_segments(1)[0]
    assert row['end_reason']=='ESP32_RESTART'
    assert row['water_quality']=='UNVERIFIED'
    assert row['water_estimated_l'] is None

def test_05_gap_no_fabricated_water(store):
    feed(store,[(0,packet(1000)),(1,packet(2000,1,'CANAL',True,.1)),
      (2,packet(24000,1,'CANAL',True,3.))])
    row=store.activity_segments(1)[0]
    assert row['end_reason']=='TELEMETRY_GAP'
    assert row['water_quality']=='UNVERIFIED'

def test_06_partial_not_in_verified_total(store):
    feed(store,[(0,packet(2000,1,'CANAL',True,.4)),
      (1,packet(4000,1,'CANAL',True,.9)),
      (2,packet(6000,z1=1.2))])
    row=store.activity_segments(1)[0]
    assert row['water_quality']=='PARTIAL'
    assert row['water_estimated_l']>0
    assert store.activity_report(1)['water_liters'] is None

def test_07_invalid_counter_not_verified(store):
    feed(store,[(0,packet(1000)),(1,packet(2000,1,'CANAL',True,.2)),
      (2,packet(3000,1,'CANAL',True,float('nan'))),
      (3,packet(4000,z1=1.2))])
    row=store.activity_segments(1)[0]
    assert row['water_quality']=='UNVERIFIED'
    assert row['water_estimated_l'] is None

def test_08_pinmap_matches_user_wokwi_layout():
    diagram=json.loads((ROOT/'firmware_wokwi/diagram.json').read_text(encoding='utf-8'))
    links={(a,b) for a,b,*_ in diagram['connections']}
    expected={('dht:SDA','esp:D26'),('waterTemp:DQ','esp:D13'),
       ('tankSensor:TRIG','esp:D5'),('tankSensor:ECHO','esp:D27'),
       ('soilZ1:SIG','esp:D33'),('soilZ2:SIG','esp:VN')}
    assert expected<=links
    baseline=json.loads((ROOT/'firmware_wokwi/diagram_USER_LAYOUT_BASELINE_20261106.json').read_text(encoding='utf-8'))
    byid=lambda x:{p['id']:(p.get('top'),p.get('left')) for p in x['parts']}
    base=byid(baseline); current=byid(diagram)
    assert all(current.get(name)==pos for name,pos in base.items())

def test_09_phase453_chart_contract():
    js=(ROOT/'dashboard/app/static/activity.js').read_text(encoding='utf-8')
    css=(ROOT/'dashboard/app/static/activity.css').read_text(encoding='utf-8')
    html=(ROOT/'dashboard/app/static/activity.html').read_text(encoding='utf-8')
    assert 'activity-water-chart' in html
    assert '#2FBF71'.lower() in (js+css).lower()
    assert '#4A90E2'.lower() in (js+css).lower()

def test_10_storage_persists_without_erasing_history(tmp_path):
    p=tmp_path/'persist.sqlite'; s=Storage(str(p))
    feed(s,[(0,packet(1000)),(1,packet(2000,1,'CANAL',True,.1)),
        (2,packet(3000,z1=.4))]); s.close()
    reopened=Storage(str(p))
    try:
        assert reopened.activity_report(1)['water_liters']==.4
        assert len(reopened.activity_segments(1))==1
    finally: reopened.close()
