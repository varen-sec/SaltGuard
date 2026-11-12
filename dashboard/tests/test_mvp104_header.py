from pathlib import Path

S = Path(__file__).resolve().parents[1] / "app" / "static"


def test_farmer_compact_sticky_header():
    html = (S / "farmer.html").read_text()
    css = (S / "farmer.css").read_text()
    assert html.count('class="mobile-topbar"') == 1
    assert html.count('id="page-title"') == 1
    assert html.count('id="online-pill"') == 1
    assert 'class="device-line"' not in html
    assert 'position:sticky;top:0' in css
    assert 'max-width:752px' in css


def test_technical_matches_farmer_header():
    html = (S / "expert.html").read_text()
    js = (S / "expert.js").read_text()
    assert html.count('class="mobile-topbar"') == 1
    assert html.count('class="mobile-topbar-title"') == 1
    assert html.count('id="expert-online"') == 1
    assert 'class="device-line"' not in html
    assert "$('expert-online')" in js


def test_connection_is_device_status_and_assets_bumped():
    farmer = (S / "farmer.html").read_text()
    technical = (S / "expert.html").read_text()
    js = (S / "farmer.js").read_text()
    for html in (farmer, technical):
        assert 'Trạng thái kết nối ESP32' in html
        assert 'farmer.css?v=mvp11' in html
    assert 'farmer.js?v=mvp11' in farmer
    assert 'expert.js?v=mvp11' in technical
    assert 'Trạng thái kết nối ESP32:' in js
