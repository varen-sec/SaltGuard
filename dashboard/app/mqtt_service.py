"""MQTT ingestion: Wokwi ESP32 (2.2) -> public broker -> SQLite.
PUBLIC DEMO ONLY. Commands are strictly allowlisted, never pump/valve force-ON.
"""
from __future__ import annotations

import json
import re
import logging
import uuid
import time
from .storage import Storage
from .water_config_registry import WaterConfigRegistry

log = logging.getLogger('saltguard.mqtt')
ALLOWED_COMMANDS = {'TEST:FLOW:ZERO', 'TEST:VALVE:STUCK', 'TEST:SENSOR:BAD', 'TEST:CLEAR', 'DEMO:CUSTOM:START', 'DEMO:CUSTOM:UPDATE', 'DEMO:CUSTOM:END', 'EMERGENCY:STOP', 'DEMO:TC01:START', 'DEMO:TC01:END', 'DEMO:TC02:START', 'DEMO:TC02:END', 'DEMO:TC03:START', 'DEMO:TC03:END', 'DEMO:TC04:START', 'DEMO:TC04:END', 'DEMO:TC05:START', 'DEMO:TC05:END', 'DEMO:TC06:START', 'DEMO:TC06:END', 'DEMO:TC07:START', 'DEMO:TC07:END', 'STATUS', 'ZONES:1', 'ZONES:2', 'TWIN:ON', 'TWIN:OFF', 'FILL:REQUEST', 'FILL:CANCEL', 'FILL:AUTO:ON', 'FILL:AUTO:OFF', 'ZONE:1:HOLD', 'ZONE:1:RESUME', 'ZONE:2:HOLD', 'ZONE:2:RESUME', 'ZONE:1:ONCE', 'ZONE:2:ONCE', 'ZONE:1:CANCEL_ONCE', 'ZONE:2:CANCEL_ONCE'}

class MqttService:
    def __init__(self, storage: Storage, host: str, port: int, root: str):
        self.storage = storage
        self.water_config = WaterConfigRegistry(storage)
        self.host, self.port, self.root = host, port, root
        self.connected = False
        self.started = False
        self.last_ack = None
        self.last_status = None
        self.error = None
        self.client = None
        self._last_clock_sent = 0.0
        self._topics = {key: f'{root}/{key}' for key in ('telemetry', 'status', 'cmd', 'ack', 'twin/input')}

    def start(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.error = 'Thiếu gói paho-mqtt: pip install -r requirements.txt'
            log.error(self.error)
            return
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id='saltguard-dashboard-' + uuid.uuid4().hex[:12],
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=True,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        try:
            self.client.connect_async(self.host, self.port, keepalive=30)
            self.client.loop_start()
            self.started = True
        except Exception as e:
            self.error = f'Khởi động MQTT thất bại: {e}'
            log.exception('MQTT start failed')

    def stop(self):
        if self.client:
            self.client.disconnect()
            if self.started:
                self.client.loop_stop()
        self.connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if not self.connected:
            self.error = f'MQTT refused: {reason_code}'
            log.warning(self.error)
            return
        self.error = None
        for k in ('telemetry', 'status', 'ack'):
            client.subscribe(self._topics[k], qos=0)
        log.info('MQTT connected and subscribed to SaltGuard topics')

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        log.info('MQTT disconnected: %s', reason_code)

    def _on_message(self, client, userdata, message):
        try:
            if len(message.payload) > 8192:
                return
            if message.topic == self._topics['telemetry']:
                data = json.loads(message.payload.decode('utf-8'))
                if not isinstance(data, dict) or not isinstance(data.get('state'), str):
                    return
                # Ignore unexpected third-party devices sharing the public topic.
                if data.get('device') != self.root:
                    return
                self.storage.ingest(data)
                self.water_config.on_telemetry(data)
                # The firmware owns all pump permission. MQTT only provides a wall-clock
                # reference. Do not translate time sync into an ON / RESUME command.
                if (self.connected and self.client and
                    (self._last_clock_sent==0 or time.monotonic()-self._last_clock_sent>=55)):
                    self._last_clock_sent=time.monotonic()
                    self.client.publish(self._topics['cmd'],
                                        payload='CLOCK:'+str(int(time.time())),
                                        qos=0,retain=False)
            elif message.topic == self._topics['status']:
                self.last_status = message.payload.decode('utf-8', errors='replace')[:100]
            elif message.topic == self._topics['ack']:
                ack = json.loads(message.payload.decode('utf-8'))
                if not isinstance(ack, dict) or 'command' not in ack:
                    return
                if str(ack.get('command','')).startswith('CLOCK:'):
                    return  # internal clock sync, not a farmer operation
                self.last_ack = ack
                self.water_config.on_ack(ack)
                outcome = 'Chấp nhận' if ack.get('accepted') else 'Từ chối'
                self.storage.event('ack', 'info' if ack.get('accepted') else 'warning',
                   f"{outcome}: {str(ack.get('command'))[:40]}", str(ack.get('message',''))[:180], ack)
        except Exception:
            log.exception('Bad MQTT message on %s', message.topic)

    def command(self, cmd: str):
        if (cmd not in ALLOWED_COMMANDS
                and not re.fullmatch(r'HOURS:(?:[0-9]{4},){3}[0-9]{4}', cmd)
                and not re.fullmatch(r'SOIL:(?:[0-9]{1,2},){3}[0-9]{1,2}',cmd)
                and not re.fullmatch(r'WATER:(?:[0-9]{1,4},){3}[0-9]{1,4}',cmd)
                and not re.fullmatch(r'WIN:(?:[01],[0-9]{1,4},[0-9]{1,4})(?:;[01],[0-9]{1,4},[0-9]{1,4}){0,3}', cmd)):
            raise ValueError('Lệnh không được hỗ trợ trong SaltGuard MVP')
        if not self.connected or not self.client:
            raise ConnectionError('Backend chưa kết nối MQTT')
        self.water_config.requested(cmd)
        info = self.client.publish(self._topics['cmd'], payload=cmd, qos=0, retain=False)
        if info.rc != 0:
            self.water_config.cancel(cmd)
            raise ConnectionError('Gửi MQTT thất bại (rc=' + str(info.rc) + ')')
        self.storage.event('command', 'info', 'Đã gửi: ' + cmd, 'Đang chờ ESP32 phản hồi')
        return {'sent': True, 'command': cmd, 'note': 'Lệnh đã được chuyển cho broker; chờ ACK từ ESP32'}

    def publish_twin(self,payload: str):
        if not self.connected or not self.client:
            raise ConnectionError('MQTT ngoại tuyến')
        if len(payload)>160 or not payload.startswith('SGT2,'):
            raise ValueError('Sai định dạng Digital Twin')
        info=self.client.publish(self._topics['twin/input'], payload=payload, qos=1, retain=False)
        if info.rc!=0:raise ConnectionError(f'Không gửi được Digital Twin (rc={info.rc})')
        return True
