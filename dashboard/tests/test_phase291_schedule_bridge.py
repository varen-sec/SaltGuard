"""Regression: allowed multi-window commands must pass both API and MQTT bridge."""
from unittest.mock import Mock
import pytest
from app.mqtt_service import MqttService

def test_bridge_accepts_multi_windows():
    bridge=MqttService(Mock(), 'broker', 1883, 'test/root')
    bridge.connected=True
    bridge.client=Mock()
    bridge.client.publish.return_value.rc=0
    commands=(
        'WIN:1,390,480;1,960,1080',
        'WIN:1,330,540;0,990,1110;1,720,780',
        'WIN:0,330,540',
        'WIN:1,330,540;1,990,1110;0,720,780;0,780,840',
    )
    for command in commands:
        result=bridge.command(command)
        assert result['sent'] is True
        bridge.client.publish.assert_called_with('test/root/cmd',payload=command,qos=0,retain=False)

def test_bridge_rejects_unrelated_commands():
    bridge=MqttService(Mock(), 'broker', 1883, 'test/root')
    for command in ('PUMP:ON', 'WIN:1,330,540;1,990,1110;1,720,780;1,780,840;1,900,920', 'WIN:abc'):
        with pytest.raises(ValueError):
            bridge.command(command)
