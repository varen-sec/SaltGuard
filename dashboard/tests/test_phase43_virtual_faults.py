from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INO = (ROOT / 'firmware_wokwi' / 'sketch.ino').read_text(encoding='utf-8')
BACKEND = (ROOT / 'dashboard' / 'app' / 'mqtt_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'dashboard' / 'app' / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'dashboard' / 'app' / 'static' / 'expert.html').read_text(encoding='utf-8')


def test_virtual_faults_are_not_real_sensors():
    assert 'explicitly VIRTUAL feedback' in INO
    assert 'diag_virtual_flow_lpm' in INO
    assert 'diag_virtual_valve_ok' in INO
    assert 'diag_fault_latched' in INO


def test_fault_codes_and_controller_outputs_off():
    for code in ['DIAG_NO_FLOW', 'DIAG_VALVE_STUCK', 'DIAG_SOIL_INVALID']:
        assert code in INO
    assert 'virtualFaultLatched) return;' in INO  # output guard and/or probe guard
    assert 'tickVirtualFault(now);' in INO
    assert 'VIRTUAL_FAULT_DETECT_MS=1500UL' in INO
    assert 'clearAllOneTime();activeZone=-1;' in INO


def test_expert_auth_and_simulation_gate():
    for cmd in ['TEST:FLOW:ZERO', 'TEST:VALVE:STUCK', 'TEST:SENSOR:BAD', 'TEST:CLEAR']:
        assert cmd in BACKEND
        assert cmd in INO
        assert cmd in HTML
    assert 'if(!testMode && !twinMode)' in INO
    assert 'DIAG_SIMULATION_ONLY' in INO
    assert 'if not farmer_command and not access.authenticated(request)' in MAIN


def test_reset_does_not_clear_emergency():
    assert 'if(state==FAULT && !emergencyLatched && !injectedFault)' in INO
    assert 'resetVirtualFault();' in INO
    assert 'enter(REST,"DIAG_CLEARED_RECHECK",now)' in INO


def test_existing_wiring_unchanged():
    import json
    current = json.loads((ROOT / 'firmware_wokwi' / 'diagram.json').read_text())
    assert len(current['connections']) == 112  # Phase 4.4.4 added two soil potentiometers
    assert any(c[1] == 'esp:TX2' for c in current['connections'])
    assert any(c[1] == 'esp:VN' for c in current['connections'])
