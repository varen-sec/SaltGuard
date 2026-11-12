from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def test_firmware_handles_stale_millis_and_caps_volume():
 s=(ROOT/'firmware_wokwi/sketch.ino').read_text()
 assert 'if((int32_t)(now-waterMeterAt)<=0) return;' in s
 assert 'float remaining=max(0.0f,sessionTargetL[zi]-sessionEstimatedL);' in s
 assert 'float litres=min(remaining,flowLpm[zi]*(float)elapsed/60000.0f);' in s

def test_farmer_page_has_no_removed_ui():
 h=(ROOT/'dashboard/app/static/farmer.html').read_text()
 j=(ROOT/'dashboard/app/static/farmer.js').read_text()
 assert 'id="home-recent"' not in h
 assert 'id="sg-water-note"' not in h
 assert 'function renderHomeRecent' not in j
 assert "$('sg-water-note')" not in j
 assert 'validSession' in j
