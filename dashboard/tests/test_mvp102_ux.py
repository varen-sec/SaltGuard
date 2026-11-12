"""New 1.0.2 usability regression checks."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_farmer_clean_home_and_reserve_open():
    html=(ROOT/'app/static/farmer.html').read_text()
    assert 'id="hero"' not in html
    assert 'class="primary-control"' not in html
    assert '<section class="settings-details reserve-panel">' in html
    assert '<details class="settings-details"><summary>Nước dự trữ' not in html
    assert 'id="page-settings"' in html
    assert 'id="profile-demo-form"' in html
    assert 'Thông tin người dùng' in html
def test_offline_refers_to_iot():
    source=(ROOT/'app/main.py').read_text()
    assert 'Mất kết nối với bộ điều khiển' in source
def test_technical_has_mobile_nav_and_advanced_fallback():
    html=(ROOT/'app/static/expert.html').read_text() + (ROOT/'app/static/lab.html').read_text()
    source=(ROOT/'app/main.py').read_text()
    assert 'class="bottom-nav workspace-nav"' in html
    assert 'crop-config-form' in html
    assert '/technical/advanced' in html
    assert "@app.get('/technical/advanced')" in source
def test_journal_is_specific():
    js=(ROOT/'app/static/farmer.js').read_text()
    assert 'Đã gửi yêu cầu '+"'"+'+meaning' in js or 'Đã gửi yêu cầu ${' in js or 'Đã gửi yêu cầu '+"'"+'+meaning' in js
    assert 'Đã nhận phản hồi' not in js
