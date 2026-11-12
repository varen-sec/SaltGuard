from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[2]
FW=(ROOT/'firmware_wokwi/sketch.ino').read_text(encoding='utf-8')
DIAGRAM=json.loads((ROOT/'firmware_wokwi/diagram.json').read_text(encoding='utf-8'))
BASE=json.loads((ROOT/'firmware_wokwi/diagram_USER_LAYOUT_BASELINE_20261106.json').read_text(encoding='utf-8'))

def test_water_temperature_pin_and_pullup():
    c={(x[0],x[1]) for x in DIAGRAM['connections']}
    assert ('waterTemp:DQ','esp:D13') in c
    assert ('dht:SDA','esp:D5') in c
    assert ('waterPullup:1','waterTemp:DQ') in c
    assert ('waterPullup:2','esp:3V3') in c
    assert 'DHT_PIN=5, WATER_TEMP_PIN=13' in FW

def test_preserve_user_layout_and_cables_except_two_signals():
    assert DIAGRAM['parts']==BASE['parts']
    old={(x[0],x[1]) for x in BASE['connections']}
    new={(x[0],x[1]) for x in DIAGRAM['connections']}
    assert old-new=={('waterTemp:DQ','esp:D0'),('dht:SDA','esp:D13'),('esp:D5','panel_ready_r:1')}
    assert new-old=={('waterTemp:DQ','esp:D13'),('dht:SDA','esp:D5'),('sr:Q5','panel_ready_r:1')}

def test_explicit_failure_and_recovery_instead_of_fabrication():
    assert 'DS18B20 INIT pin=' in FW
    assert 'DS18B20 READ FAILED pin=' in FW
    assert 'DS18B20 RECOVERED pin=' in FW
    assert 'waterTempC=waterReadingOK?value:NAN;' in FW
    assert 'jFloat(waterTempC,1)' in FW
