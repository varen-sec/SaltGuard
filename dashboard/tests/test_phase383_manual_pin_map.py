"""Verify ESP32 DevKit V1 GPIO39 is wired to actual board pin VN."""
import json
from pathlib import Path
D = json.loads((Path(__file__).resolve().parents[2]/"firmware_wokwi/diagram.json").read_text(encoding="utf8"))

def test_manual_uses_esp32_vn_pad():
    conn = D["connections"]
    assert ["fault:1.l", "esp:VN", "orange", []] in conn
    assert ["lcdPullup:1", "esp:VN", "green", []] in conn
    assert ["lcdPullup:2", "esp:3V3", "red", []] in conn
    assert ["fault:2.r", "esp:GND.2", "black", []] in conn
    assert not any("esp:D39" in c[:2] for c in conn)
