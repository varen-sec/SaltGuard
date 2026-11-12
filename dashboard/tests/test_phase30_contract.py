"""Phase 3.0: regression contracts. These do not replace a Wokwi end-to-end test."""
from pathlib import Path
import json
from unittest.mock import Mock
from app.mqtt_service import MqttService

ROOT=Path(__file__).resolve().parents[2]
FW=(ROOT/'firmware_wokwi'/'sketch.ino').read_text(encoding='utf-8')
DIAGRAM=json.loads((ROOT/'firmware_wokwi'/'diagram.json').read_text(encoding='utf-8'))


def test_tank_pins_and_connections():
    assert 'TANK_TRIG_PIN=26, TANK_ECHO_PIN=27' in FW
    edges={tuple(e[:2]) for e in DIAGRAM['connections']}
    assert ('tankSensor:TRIG','esp:D26') in edges
    assert ('tankSensor:ECHO','esp:D27') in edges


def test_five_valves_reported_from_firmware():
    assert 'const uint8_t V1=' in FW
    for v in range(1,6):
        assert f'"valve_v{v}"' in FW or f'\\"valve_v{v}\\"' in FW


def test_schedule_command_bridge_and_safety_rejection():
    svc=MqttService(Mock(),'host',1883,'saltguard/test')
    svc.connected=True
    svc.client=Mock()
    svc.client.publish.return_value.rc=0
    good=('WIN:1,330,540;0,990,1110','WIN:0,330,540;0,990,1110;0,720,780;0,780,840')
    for payload in good:
        assert svc.command(payload)['sent'] is True
    for bad in ('PUMP:ON','EMERGENCY:RESET','WIN:1,330,540;1,990,1110;1,720,780;1,780,840;1,900,920'):
        try:svc.command(bad)
        except ValueError: pass
        else: raise AssertionError(f'Unsafe/unexpected command allowed: {bad}')


def test_emergency_recovery_and_local_input_present():
    for token in ('emergencyLatched','handleButtons','TANK_TRIG_PIN','TWIN:ON','TWIN:OFF'):
        assert token in FW
