"""MVP 1.1.3 regression: queue both dry zones without defeating pump safety."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
FW=(ROOT/'firmware_wokwi/sketch.ino').read_text()
JS=(ROOT/'dashboard/app/static/farmer.js').read_text()

def test_per_zone_permission_instead_of_global_single_slot():
    assert 'bool extraWaterGranted[2]' in FW
    assert 'bool extraWaterStarted[2]' in FW
    assert 'EXCEPTION_ACTIVE' not in FW
    assert 'extraWaterGranted[zi]=true' in FW
    assert 'ONE_TIME_QUEUED' in FW

def test_fair_rotation_and_rest_remain():
    assert 'if(z1 && z2) return 1-lastServedZone;' in FW
    assert 'now-restStart<REST_MS' in FW
    assert 'now-sessionStart>=SESSION_MS' in FW
    assert 'digitalWrite(VALVE1_PIN,(state==CANAL_Z1||state==TANK_Z1)?HIGH:LOW)' in FW
    assert 'digitalWrite(VALVE2_PIN,(state==CANAL_Z2||state==TANK_Z2)?HIGH:LOW)' in FW

def test_independent_deadlines_begin_at_first_irrigation():
    assert 'extraWaterStartedAt[activeZone]=now;' in FW
    assert 'now-extraWaterStartedAt[zi]>=EXTRA_WATER_MS' in FW
    assert 'now-extraWaterQueuedAt[zi]>=EXTRA_QUEUE_MS' in FW

def test_safety_priorities_do_not_change():
    for token in ('MASTER_OFF','TWIN_INPUT_STALE','NO_SAFE_SOURCE','if(newHold) clearOneTime(zi)','clearAllOneTime();'):
        assert token in FW
    assert 'if(!masterEnabled) {accepted=false;result="MASTER_OFF";}' in FW
    assert 'else if(zoneHold[zi]) {accepted=false;result="ZONE_HELD";}' in FW

def test_farmer_app_shows_independent_actions_and_queued_state():
    assert 'extra_water_allowed_z1' in FW and 'extra_water_allowed_z2' in FW
    assert 'Cả hai khu vực đang cần nước' in JS
    assert 'Chờ đến lượt tưới' in JS
    assert 'val<=35' in JS
    assert "hasOneTime(live,i)" in JS
    assert "['ONE_TIME_QUEUED','ALREADY_QUEUED']" in JS
