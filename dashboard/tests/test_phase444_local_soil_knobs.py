from pathlib import Path
import json

BASE = Path(__file__).resolve().parents[2]
FW = (BASE / "firmware_wokwi/sketch.ino").read_text()
D = json.loads((BASE / "firmware_wokwi/diagram.json").read_text())


def test_two_independent_soil_pots_connected_to_adc1():
    parts = {p["id"]:p for p in D["parts"]}
    connections={(c[0],c[1]) for c in D["connections"]}
    assert parts["soilZ1"]["type"] == "wokwi-potentiometer"
    assert parts["soilZ2"]["type"] == "wokwi-potentiometer"
    assert ("soilZ1:SIG","esp:D33") in connections
    assert ("soilZ2:SIG","esp:VN") in connections
    for k in ("soilZ1", "soilZ2"):
        assert (k+":VCC","esp:3V3") in connections
        assert (k+":GND","esp:GND.2") in connections

def test_existing_knobs_unchanged():
    connections={(c[0],c[1]) for c in D["connections"]}
    assert ("salt:SIG","esp:D34") in connections
    assert ("canal:SIG","esp:D35") in connections
    assert ("rain:SIG","esp:D32") in connections

def test_reassigned_nonanalog_inputs():
    connections={(c[0],c[1]) for c in D["connections"]}
    assert ("waterTemp:DQ","esp:D13") in connections
    assert ("fault:1.l","esp:RX0") in connections
    assert ("lcdPullup:1","esp:RX0") in connections
    assert "MANUAL_PIN=3" in FW
    assert "WATER_TEMP_PIN=13" in FW

def test_local_reads_and_no_auto_soil_growth():
    assert "analogRead(SOIL_Z1_PIN)" in FW
    assert "analogRead(SOIL_Z2_PIN)" in FW
    assert "if(testMode || twinMode) return;" in FW
    assert "soil[activeZone]=clampf(soil[activeZone]+2.15f" not in FW
    assert "soil[0]=clampf(soil[0]+0.24f*rain" not in FW

def test_wiring_does_not_duplicate_adc_sensors():
    pins={"esp:D32","esp:D33","esp:D34","esp:D35","esp:VN"}
    sources=[c[0] for c in D["connections"] if c[1] in pins and c[0].endswith(":SIG")]
    assert sorted(sources)==sorted(["salt:SIG","canal:SIG","rain:SIG","soilZ1:SIG","soilZ2:SIG"])
