import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
S = (ROOT/'firmware_wokwi/sketch.ino').read_text()
D = json.loads((ROOT/'firmware_wokwi/diagram.json').read_text())
B = json.loads((ROOT/'firmware_wokwi/diagram_USER_LAYOUT_BASELINE_20261106.json').read_text())
def test_dht_and_ds_pin_config():
    assert 'DHT_PIN=5, WATER_TEMP_PIN=13' in S
    links = {(x[0],x[1]) for x in D['connections']}
    assert ('dht:SDA','esp:D5') in links
    assert ('waterTemp:DQ','esp:D13') in links
    assert ('waterPullup:1','waterTemp:DQ') in links

def test_ready_led_q5_not_gpio5():
    links = {(x[0],x[1]) for x in D['connections']}
    assert ('sr:Q5','panel_ready_r:1') in links
    assert ('esp:D5','panel_ready_r:1') not in links
    assert 'mask | (readyLedState?SR_READY_LED:0)' in S
    assert 'writeValves(valveMask); // refresh Q5' in S

def test_user_layout_preserved():
    assert D['parts']==B['parts']
    assert len(D['connections'])==len(B['connections'])==112
    modified={(a[0],a[1]) for a in D['connections']} ^ {(a[0],a[1]) for a in B['connections']}
    assert modified=={('dht:SDA','esp:D13'),('waterTemp:DQ','esp:D0'),('dht:SDA','esp:D5'),('waterTemp:DQ','esp:D13'),('esp:D5','panel_ready_r:1'),('sr:Q5','panel_ready_r:1')}

def test_environment_diagnostics():
    assert 'DHT22 READ FAILED' in S and 'DHT22 RECOVERED' in S
    assert 'DHT22 INIT pin=%d' in S
    assert 'airTempC=NAN; airRH=NAN;' in S
