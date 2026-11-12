"""MVP 1.1.1 regression: farmer home, settings and removal of redundant trends."""
from pathlib import Path
S=Path(__file__).resolve().parents[1]/'app'/'static'

def test_home_dynamic_water_source_and_color_levels():
    html=(S/'farmer.html').read_text()
    js=(S/'farmer.js').read_text()
    css=(S/'farmer.css').read_text()
    assert 'NGUỒN NƯỚC ĐANG SỬ DỤNG' in html
    assert 'salinity-fill' in html and 'reserve-fill' in html
    assert 'renderLiquid(d,online)' in js
    assert 'salt>=1.0' in js and 'salt>=0.7' in js
    assert 'live.canal_safe===false' in js
    assert 'reserve-card[data-level="safe"]' in css
    assert 'Chưa rõ nguồn đang dùng' in js

def test_journal_activities_only():
    html=(S/'farmer.html').read_text()
    assert 'id="journal-list"' in html
    assert 'Biến động môi trường' not in html
    assert 'trend-soil' not in html

def test_settings_as_subscreens_and_single_toggle():
    html=(S/'farmer.html').read_text()
    js=(S/'farmer.js').read_text()
    for key in ('profile','device','password','terms','logout'):
        assert 'data-settings-view="'+key+'"' in html
        assert 'settings-panel-'+key in html
    assert 'id="notification-pref"' in html
    assert 'function openSettingsView' in js
    assert 'localStorage' in js
    assert 'Chưa hỗ trợ' in html
    assert '/advanced-login?next=/expert' in html
    assert 'id="zone-names-form"' not in html

def test_expert_keeps_zone_renaming():
    html=(S/'expert.html').read_text(); js=(S/'expert.js').read_text()
    assert 'id="expert-zone-names"' in html
    assert "/api/farm/zones/names" in js
    assert 'crop-config-form' in html
