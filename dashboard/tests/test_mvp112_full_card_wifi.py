from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / 'app' / 'static'
HTML = (STATIC / 'farmer.html').read_text(encoding='utf-8')
CSS = (STATIC / 'farmer.css').read_text(encoding='utf-8')
JS = (STATIC / 'farmer.js').read_text(encoding='utf-8')


def test_removed_technical_note_and_kept_expert_pin_access():
    assert 'Cấu hình nông học và phòng mô phỏng chỉ mở sau khi nhập PIN' not in HTML
    assert 'href="/advanced-login?next=/expert"' in HTML


def test_full_card_levels_no_nested_bottle():
    assert 'class="liquid-glass"' not in HTML
    assert 'class="liquid-fill" id="salinity-fill"' in HTML
    assert 'class="liquid-fill" id="reserve-fill"' in HTML
    assert '.liquid-card .liquid-fill' in CSS
    assert 'width:100%;height:0' in CSS


def test_live_level_values_and_color_thresholds():
    assert '(salt/1.0)*100' in JS
    assert "salt>=1.0?'danger':salt>=0.7?'warning':'safe'" in JS
    assert "tank<=20?'danger':tank<=30?'warning':'safe'" in JS
    assert "const tankValid=online" in JS
    assert "card.dataset.level=state;fill.style.height=pct+'%'" in JS


def test_wifi_icon_colored_by_esp32_connectivity():
    assert '-webkit-mask-image:url(' in CSS
    assert '.mobile-topbar .connection-pill.bad' in CSS
    assert '#d74842' in CSS and '#16804b' in CSS
    assert "'Trạng thái kết nối ESP32: '" in JS
    assert "'ESP32 ngoại tuyến'" in JS
