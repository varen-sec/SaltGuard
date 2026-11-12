"""Phase 3.8.2: the physical MANUAL button authorizes exactly one safe session."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
SKETCH = (ROOT / 'firmware_wokwi' / 'sketch.ino').read_text(encoding='utf-8')
DIAGRAM = json.loads((ROOT / 'firmware_wokwi' / 'diagram.json').read_text(encoding='utf-8'))

def test_manual_is_gpio39_and_button_is_labelled():
    assert 'MANUAL_PIN=39' in SKETCH
    parts = {p['id']:p for p in DIAGRAM['parts']}
    assert parts['fault']['attrs']['label'] == 'MANUAL'
    assert ['fault:1.l','esp:VN','orange',[]] in DIAGRAM['connections']
    assert ['lcdPullup:1','esp:VN','green',[]] in DIAGRAM['connections']

def test_manual_respects_safety_and_schedule():
    body = SKETCH.split('void requestManualIrrigation(unsigned long now) {',1)[1].split('void handleButtons(',1)[0]
    for guard in ['!masterEnabled','emergencyLatched','paused','injectedFault',
                  'TWIN_INPUT_TIMEOUT_MS','clockValid(now)','irrigationWindow(now)',
                  'watering(state)','!canalOK() && !tankOK()', 'zoneHold[zi]','demand[zi]']:
        assert guard in body, guard
    assert 'control(now);' in body
    assert 'digitalWrite(RELAY_PIN' not in body
    assert 'writeValves(' not in body

def test_manual_grant_expires_after_one_zone_session():
    assert 'manualSessionOneShot[2]' in SKETCH
    assert 'if(manualSessionOneShot[activeZone])' in SKETCH
    assert 'clearOneTime(activeZone);' in SKETCH
    assert 'manualSessionOneShot[zi]=false;' in SKETCH

def test_no_changes_to_servo_adapters():
    assert 'sg-servo-adapter' in json.dumps(DIAGRAM['parts'])
    assert any(p.get('id')=='v1Led' or p.get('id')=='v1led' for p in DIAGRAM['parts'])
