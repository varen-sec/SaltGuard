"""MVP 1.0.3: one-time irrigation exception is a bounded, safety-gated command."""
from pathlib import Path
from app.mqtt_service import ALLOWED_COMMANDS
ROOT=Path(__file__).parents[2]

def test_one_time_command_is_allowlisted_without_generic_pump_on():
    assert {"ZONE:1:ONCE", "ZONE:2:ONCE"} <= ALLOWED_COMMANDS
    for unsupported in ('MASTER:ON','PUMP:ON','WATER:Z1:300','ZONE:1:FOREVER'):
        assert unsupported not in ALLOWED_COMMANDS

def test_firmware_guardrails_and_separate_zone_permissions():
    s=(ROOT/'firmware_wokwi/sketch.ino').read_text()
    assert 'const unsigned long EXTRA_WATER_MS=120000UL' in s
    assert 'else if(cmd=="ZONE:1:ONCE" || cmd=="ZONE:2:ONCE")' in s
    assert 'if(!masterEnabled) {accepted=false;result="MASTER_OFF";}' in s
    assert 'else if(zoneHold[zi])' in s
    assert 'else if(paused || injectedFault)' in s
    assert 'else if(!canalOK() && !tankOK())' in s
    assert 'extraWaterGranted[zi]=true;' in s
    assert 'selectAuthorizedZone():selectZone()' in s
    assert 'now-extraWaterStartedAt[zi]>=EXTRA_WATER_MS' in s
    assert 'if(newHold) clearOneTime(zi)' in s
    assert 'ONE_TIME_QUEUED' in s
    assert 'EXCEPTION_ACTIVE' not in s
    assert 'extraWaterGranted[0]' in s and 'extraWaterGranted[1]' in s

def test_farmer_ui_accessible_nav_and_one_time_action():
    s=(ROOT/'dashboard/app/static/farmer.html').read_text()
    js=(ROOT/'dashboard/app/static/farmer.js').read_text()
    assert s.count('class="navitem')==5
    assert 'data-page="settings"' in s
    assert 'class="app-header"' not in s
    assert 'id="home-activity"' in s
    assert 'allow-once-alert' in js
    assert "ONCE" in js and "askOneTime" in js
