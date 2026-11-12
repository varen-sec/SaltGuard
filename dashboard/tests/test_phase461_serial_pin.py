"""Phase 4.6.1 diagram/firmware regression contracts."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SKETCH=(ROOT/'firmware_wokwi/sketch.ino').read_text()
DIAGRAM=json.loads((ROOT/'firmware_wokwi/diagram.json').read_text())
EDGES={(a,b) for a,b,*_ in DIAGRAM['connections']}

def test_uart_rx0_has_no_connections():
    assert not [e for e in EDGES if 'esp:RX0' in e]
    assert 'MANUAL_PIN=15' in SKETCH

def test_manual_switch_and_pullup_on_gpio15():
    assert ('fault:1.l','esp:D15') in EDGES
    assert ('lcdPullup:1','esp:D15') in EDGES
    assert ('lcdPullup:2','esp:3V3') in EDGES
    assert ('fault:2.r','esp:GND.2') in EDGES

def test_notice_shift_register_and_ready_unchanged():
    assert ('sr:Q6','panel_notice_r:1') in EDGES
    assert ('sr:Q5','panel_ready_r:1') in EDGES
    assert 'SR_NOTICE_LED=1<<6' in SKETCH
    assert 'SR_READY_LED=1<<5' in SKETCH
    assert 'noticeLedState?SR_NOTICE_LED:0' in SKETCH
    assert 'LED_NOTICE_PIN' not in SKETCH

def test_serial_commands_and_setup_retained():
    for snippet in ["c=='D'", "c=='I'", "c=='S'", "c=='?'",'Serial.available()>0', 'pinMode(MANUAL_PIN,INPUT_PULLUP)', 'PANEL DIAG MANUAL GPIO%d']:
        assert snippet in SKETCH

def test_sensitive_sensor_and_valve_pins_preserved():
    for snippet in ['DHT_PIN=26','WATER_TEMP_PIN=13','TANK_TRIG_PIN=5','TANK_ECHO_PIN=27','SOIL_Z1_PIN=33','SOIL_Z2_PIN=39']:
        assert snippet in SKETCH
    for i in range(5): assert (f'sr:Q{i}',f'v{i+1}ServoAdapter:IN') in EDGES
