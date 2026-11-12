from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MAIN=(ROOT/'dashboard/app/main.py').read_text()
BRIDGE=(ROOT/'dashboard/app/mqtt_service.py').read_text()
SKETCH=(ROOT/'firmware_wokwi/sketch.ino').read_text()
EXPERT=(ROOT/'dashboard/app/static/expert.html').read_text()
FARMER=(ROOT/'dashboard/app/static/farmer.html').read_text()
JS=(ROOT/'dashboard/app/static/irrigation-volume-expert.js').read_text()

def test_water_admitted_at_both_backend_layers():
    pattern="re.fullmatch(r'WATER:(?:[0-9]{1,4},){3}[0-9]{1,4}',cmd)"
    assert pattern in MAIN
    assert "re.fullmatch(r'WATER:(?:[0-9]{1,4},){3}[0-9]{1,4}',cmd)" in BRIDGE
    assert 'cmd.startsWith("WATER:")' in SKETCH

def test_water_requires_specialist_authentication():
    block=MAIN.split("@app.post('/api/command')",1)[1].split("@app.",1)[0]
    assert "cmd.startswith(('HOURS:','WIN:'))" in block
    assert "if not farmer_command and not access.authenticated(request)" in block
    assert "cmd.startswith(('HOURS:','WIN:','WATER:'))" not in block

def test_new_water_form_clean_of_extra_explanation():
    assert 'id="water-config-form"' in EXPERT
    assert 'Lưu lượng giả định và giới hạn nước' not in EXPERT
    assert 'giới hạn an toàn 30 phút' not in JS
    assert 'Thời gian dự kiến:' not in JS
    assert 'không đo trực tiếp' not in FARMER
