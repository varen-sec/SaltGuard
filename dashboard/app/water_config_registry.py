"""SQLite-backed water plan verified by BOTH MQTT ACK and fresh telemetry."""
from __future__ import annotations
import json
import math
import threading
import time


class WaterConfigRegistry:
    FIELDS = (
        'irrigation_flow_z1_lpm', 'irrigation_target_z1_l',
        'irrigation_flow_z2_lpm', 'irrigation_target_z2_l',
    )

    def __init__(self, storage):
        self.storage = storage
        self.lock = threading.RLock()
        self.pending = None
        self.last_result = 'NO_REQUEST'
        with storage._lock:
            storage.conn.execute(
                'CREATE TABLE IF NOT EXISTS water_config_verified '
                '(id INTEGER PRIMARY KEY CHECK(id=1), vals TEXT NOT NULL, verified_at REAL NOT NULL)'
            )
            row = storage.conn.execute(
                'SELECT vals,verified_at FROM water_config_verified WHERE id=1'
            ).fetchone()
            storage.conn.commit()
        self.saved = (
            {'values': json.loads(row['vals']), 'verified_at': row['verified_at']}
            if row else None
        )

    @staticmethod
    def parse(command):
        if not isinstance(command,str) or not command.startswith('WATER:'):
            return None
        try:
            nums=[int(x) for x in command[6:].split(',')]
        except ValueError:
            return None
        if len(nums)!=4 or not (10<=nums[0]<=1000 and 10<=nums[2]<=1000 and
                              10<=nums[1]<=5000 and 10<=nums[3]<=5000):
            return None
        return [n/10.0 for n in nums]

    @classmethod
    def read(cls, data):
        if not isinstance(data,dict):
            return None
        vals=[data.get(k) for k in cls.FIELDS]
        if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v)
               for v in vals):
            return None
        return [float(v) for v in vals]

    def requested(self,command):
        vals=self.parse(command)
        if vals is None:
            return
        with self.lock:
            self.pending={'command':command,'values':vals,'created':time.time(),'ack_ms':None}
            self.last_result='PUBLISHED_AWAITING_ACK'

    def cancel(self,command):
        with self.lock:
            if self.pending and self.pending['command']==command:
                self.pending=None
                self.last_result='SEND_FAILED'

    def on_ack(self,ack):
        if not isinstance(ack,dict):
            return
        with self.lock:
            p=self.pending
            if not p or p['command']!=ack.get('command'):
                return
            if not ack.get('accepted') or ack.get('message')!='WATER_CONFIG_SAVED':
                self.pending=None
                self.last_result='REJECTED'
            else:
                p['ack_ms']=ack.get('ms')
                self.last_result='ACKED_AWAITING_TELEMETRY'

    def on_telemetry(self,data):
        vals=self.read(data)
        if vals is None:
            return
        with self.lock:
            p=self.pending
            if p is None or p['ack_ms'] is None:
                return
            if time.time()-p['created']>45:
                self.pending=None
                self.last_result='EXPIRED'
                return
            ms=data.get('ms')
            if isinstance(ms,(float,int)) and isinstance(p['ack_ms'],(float,int)) and ms<p['ack_ms']:
                return
            if any(abs(a-b)>0.051 for a,b in zip(vals,p['values'])):
                return
            now=time.time()
            with self.storage._lock:
                self.storage.conn.execute(
                    'INSERT INTO water_config_verified(id,vals,verified_at) VALUES(1,?,?) '
                    'ON CONFLICT(id) DO UPDATE SET vals=excluded.vals,verified_at=excluded.verified_at',
                    (json.dumps(p['values']),now),
                )
                self.storage.conn.commit()
            self.saved={'values':list(p['values']),'verified_at':now}
            self.pending=None
            self.last_result='VERIFIED'

    def status(self,latest,online):
        with self.lock:
            saved=dict(self.saved) if self.saved else None
            pending=bool(self.pending)
            result=self.last_result
        actual=self.read(latest)
        mismatch=bool(online and saved and actual and
                      any(abs(a-b)>0.051 for a,b in zip(actual,saved['values'])))
        return {'saved':saved,'actual':actual if online else None,
                'online':bool(online),'pending':pending,'mismatch':mismatch,
                'last_result':result}
