"""Source-level guards for new session checkpoint contract (no hardware emulator)."""
from pathlib import Path

S = (Path(__file__).parents[2] / 'firmware_wokwi' / 'sketch.ino').read_text()


def test_pause_saves_remaining_runtime_not_fresh_full_session():
    assert 'pausedSessionRemainingMs=sessionBudgetMs-used' in S
    assert 'pausedSessionZone=activeZone' in S
    assert 'PAUSE SESSION SAVED:' in S


def test_pause_does_not_revoke_demo_grant():
    assert 'if(paused) { activeZone=-1; enter(PAUSE,"USER_PAUSE",now); return; }' in S
    assert 'if(paused) { clearAllOneTime()' not in S


def test_resume_rechecks_and_honors_rest():
    assert 'enter(REST,"RESUME_RECHECK",now)' in S
    assert 'if(state==REST && now-restStart<REST_MS) return;' in S
    assert '(!windowOpen && !authorizedOutsideWindow(zi))' in S
    assert 'if(zi<0 || zi>=configuredZones || !demand[zi]' in S


def test_resume_charges_only_pump_running_time():
    assert 'unsigned long alreadyUsed=sessionBudgetMs-remaining;' in S
    assert 'sessionStart=now-alreadyUsed;' in S
    assert 'PAUSE SESSION RESUMED:' in S
    assert 'activeZone=resuming?pausedSessionZone:' in S


def test_all_dangerous_stops_cancel_checkpoint():
    assert 'void clearAllOneTime() { clearOneTime(0); clearOneTime(1); discardPausedSession(); }' in S
    assert 'if(!masterEnabled) { discardPausedSession();' in S
    assert 'if(newHold) clearOneTime(zi);' in S
    assert 'if(pausedSessionPending && pausedSessionZone==zi) discardPausedSession();' in S


def test_telemetry_is_observable():
    assert 'paused_session_remaining_ms' in S
    assert 'paused_session_pending' in S
