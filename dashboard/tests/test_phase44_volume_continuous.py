from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
FW=(ROOT/'firmware_wokwi/sketch.ino').read_text()
BE=(ROOT/'dashboard/app/mqtt_service.py').read_text()
FARMER=(ROOT/'dashboard/app/static/farmer.html').read_text()
EXPERT=(ROOT/'dashboard/app/static/expert.html').read_text()
def test_duration_is_volume_over_flow():
 assert 'sessionTargetL[zi]*60000.0' in FW and 'flowLpm[zi]' in FW
 assert 'MAX_IRRIGATION_SESSION_MS=1800000UL' in FW
 assert 'now-sessionStart>=sessionBudgetMs' in FW
 assert 'const unsigned long RELEASE_MS=5000UL, SESSION_MS=' not in FW

def test_pause_remainder_dynamic():
 assert 'pausedSessionRemainingMs=sessionBudgetMs-used;' in FW
 assert 'unsigned long alreadyUsed=sessionBudgetMs-remaining;' in FW
 assert 'void accrueEstimatedWater' in FW

def test_expert_config_persistent():
 assert 'WATER_CONFIG_BUSY' in FW and 'WATER_CONFIG_SAVED' in FW
 assert 'irrigationPrefs.putUShort("flow1"' in FW
 assert 'WATER:(?:[0-9]{1,4},){3}[0-9]{1,4}' in BE

def test_telemetry_and_ui():
 for t in ('irrigation_session_estimated_l','irrigation_session_remaining_l','irrigation_session_used_ms','irrigation_target_z1_l'):
  assert t in FW
 assert 'sg-water-used' in FARMER and 'water-config-form' in EXPERT

def test_no_burst_or_soak():
 assert 'SOAK' not in FW and 'BURST' not in FW

def test_paused_telemetry_remaining_does_not_require_active_meter():
 assert 'pausedSessionPending&&pausedSessionZone>=0' in FW

def test_meter_does_not_count_pause_fault_and_is_bounded():
 assert 'if(waterMeterZone<0 || !watering(state)) return;' in FW
 assert 'virtualFault==VF_NO_FLOW' in FW
 assert 'unsigned long overflow=cumulative>sessionBudgetMs' in FW
