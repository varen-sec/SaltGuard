"""Static regression checks for the Phase 3.6 Wokwi-only enhancement."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = (ROOT / "firmware_wokwi" / "sketch.ino").read_text(encoding="utf-8")
D = json.loads((ROOT / "firmware_wokwi" / "diagram.json").read_text(encoding="utf-8"))

def test_five_servo_outputs_and_adapters():
    parts = D["parts"]
    assert sum(p["type"] == "wokwi-servo" for p in parts) == 5
    assert sum(p["type"] == "chip-sg-servo-adapter" for p in parts) == 5
    assert all(any(p["id"] == f"v{i}Servo" for p in parts) for i in range(1, 6))

def test_six_distinct_buzzer_categories_and_priority():
    for name in ["AL_EMERGENCY", "AL_FAULT", "AL_STALE", "AL_NO_WATER", "AL_REFILL", "AL_SALINITY"]:
        assert name in FW
    logic = FW.split("AlarmKind classifyAlarm()", 1)[1].split("struct AlarmNote", 1)[0]
    assert logic.index("if(emergencyLatched)") < logic.index("if(injectedFault") < logic.index("if(state==HOLD_NO_WATER)")
    assert "if(refillFault)" in logic

def test_buzzer_nonblocking_and_ack_mutes():
    scheduler = FW.split("void alarm(unsigned long now)", 1)[1].split("// === GIAI DOAN 2", 1)[0]
    assert "delay(" not in scheduler
    assert "tone(BUZZER_PIN,note.hz,note.ms)" in scheduler
    assert "noTone(BUZZER_PIN); // Immediate silence" in FW
    assert "buzzerAcknowledged=true" in FW

def test_existing_valve_pins_and_relay_pins():
    for line in ["const int SR_DATA_PIN=18, SR_CLOCK_PIN=19, SR_LATCH_PIN=23;",
                 "const uint8_t V1=1<<0,V2=1<<1,V3=1<<2,V4=1<<3,V5=1<<4;",
                 "const int RELAY_PIN=16, FILL_RELAY_PIN=4, DHT_PIN=13, WATER_TEMP_PIN=33;"]:
        assert line in FW
