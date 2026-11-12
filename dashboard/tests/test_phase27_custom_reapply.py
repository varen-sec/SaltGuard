"""Regression: CUSTOM runs in background without indexing TEST_PRESETS['CUSTOM']."""
from pathlib import Path
import ast


def test_custom_scenario_excluded_from_preset_verification():
    source = (Path(__file__).resolve().parents[1] / "app" / "twin.py").read_text()
    ast.parse(source)
    assert "if getattr(self,'preset_result',None)=='RUNNING' and fresh and self.last_preset in TEST_PRESETS:" in source
    assert "self.last_preset in TEST_PRESETS:" in source
    assert "self.last_preset=='CUSTOM' and self._custom_frame_confirmed(actual,now)" in source


def test_custom_endpoint_preserved():
    main = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    assert "@app.post('/api/twin/lab/custom')" in main
