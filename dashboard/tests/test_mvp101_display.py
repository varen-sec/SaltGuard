"""Static regression checks for the Farmer UX/LCD/Wokwi-only MVP update.
Actual Wokwi compilation and pin-level simulation still require manual validation.
"""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[2]


def test_lcd_dark_when_master_off():
    source=(ROOT/'firmware_wokwi/sketch.ino').read_text()
    assert 'setLCDVisible(false);' in source
    assert 'lcd.noBacklight();' in source
    assert 'lcd.noDisplay();' in source
    assert 'lcd.init();lcd.clear();lcd.noDisplay();lcd.noBacklight();' in source
    assert 'if(!masterEnabled || !lcdVisible) return;' in source


def test_lcd_four_pages_without_vietnamese_accents():
    source=(ROOT/'firmware_wokwi/sketch.ino').read_text()
    assert 'page=(page+1)%4;' in source
    for label in ['DANG TUOI VUON %d','DANG NAP BON','AM DAT 1:', 'AM DAT 2:', 'DO MAN:', 'TAM DUNG TUOI']:
        assert label in source


def test_diagram_compatible_pins_and_zones():
    obj=json.loads((ROOT/'firmware_wokwi/diagram.json').read_text())
    ids=[part['id'] for part in obj['parts']]
    assert len(ids)==len(set(ids))
    assert len(obj['connections'])==58
    assert all(edge[0].split(':')[0] in ids and edge[1].split(':')[0] in ids for edge in obj['connections'])
    assert {'box_top','zone1_title','zone2_title','masterSwitch','pumpRelay','fillRelay'} <= set(ids)


def test_modal_and_home_offline_dedup():
    html=(ROOT/'dashboard/app/static/farmer.html').read_text()
    js=(ROOT/'dashboard/app/static/farmer.js').read_text()
    assert '<dialog id="action-dialog"' in html
    assert 'waitAck' in js and "await api('/api/snapshot')" in js
    assert 'if(!held&&!confirm(' not in js
    assert 'id="hero"' not in html
    assert 'Công tắc vận hành' not in html
    assert 'Mất kết nối với bộ điều khiển' in (ROOT/'dashboard/app/main.py').read_text()
