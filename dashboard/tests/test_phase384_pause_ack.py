from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]
FW=(ROOT/'firmware_wokwi/sketch.ino').read_text(encoding='utf8')
D=json.loads((ROOT/'firmware_wokwi/diagram.json').read_text(encoding='utf8'))

def test_pause_real_board_pin_and_diagnostics():
    assert ['pause:1.l','esp:TX2','orange',[]] in D['connections']
    assert ['pause:2.r','esp:GND.2','black',[]] in D['connections']
    assert not any('esp:D17' in str(c) for c in D['connections'])
    assert 'PAUSE_PIN=17' in FW
    assert 'pinMode(PAUSE_PIN,INPUT_PULLUP)' in FW
    assert 'PANEL PAUSE GPIO17 %s' in FW
    assert 'PANEL PAUSE=%s' in FW

def test_ack_two_seconds_and_emergency_rearm():
    assert 'ACK_RECOVERY_HOLD_MS=2000UL' in FW
    assert 'now-ackDownAt>=ACK_RECOVERY_HOLD_MS' in FW
    assert 'masterArmed=false;' in FW
    assert 'emergencyLatched=false;' in FW
    assert 'GIU ACK 2s MO' in FW
    assert 'PANEL ALARM ACK SHORT' in FW

def test_manual_wiring_is_preserved():
    assert ['fault:1.l','esp:VN','orange',[]] in D['connections']
    assert ['lcdPullup:1','esp:VN','green',[]] in D['connections']
    assert 'requestManualIrrigation(now)' in FW
