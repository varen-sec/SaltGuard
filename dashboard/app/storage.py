"""SQLite storage for Wokwi MQTT telemetry, state transitions, and commands.
All database operations are protected by one lock; receives MQTT in a worker thread.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from pathlib import Path

class Storage:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA busy_timeout=10000')
            self.conn.executescript('''
              CREATE TABLE IF NOT EXISTS telemetry (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 ts REAL NOT NULL, device_ms INTEGER, state TEXT, source TEXT,
                 zone INTEGER, pump_on INTEGER, salinity_ppt REAL, soil1_pct REAL,
                 soil2_pct REAL, tank_l REAL, payload TEXT NOT NULL
              );
              CREATE INDEX IF NOT EXISTS ix_telemetry_ts ON telemetry(ts);
              CREATE TABLE IF NOT EXISTS events (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 ts REAL NOT NULL, kind TEXT NOT NULL, severity TEXT NOT NULL,
                 title TEXT NOT NULL, detail TEXT NOT NULL, payload TEXT
              );
              CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
              CREATE TABLE IF NOT EXISTS twin_samples (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 ts REAL NOT NULL,
                 scenario TEXT NOT NULL,
                 payload TEXT NOT NULL
              );
              CREATE INDEX IF NOT EXISTS ix_twin_ts ON twin_samples(ts);
              CREATE TABLE IF NOT EXISTS notifications (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 alert_key TEXT NOT NULL,
                 level TEXT NOT NULL,
                 kind TEXT NOT NULL,
                 zone INTEGER,
                 title TEXT NOT NULL,
                 detail TEXT NOT NULL,
                 started_at REAL NOT NULL,
                 ended_at REAL,
                 active INTEGER NOT NULL DEFAULT 1
              );
              CREATE INDEX IF NOT EXISTS ix_notifications_active ON notifications(active, alert_key);
              CREATE INDEX IF NOT EXISTS ix_notifications_latest ON notifications(id DESC);
              CREATE TABLE IF NOT EXISTS soil_alert_state (
                 alert_key TEXT PRIMARY KEY, title TEXT NOT NULL,
                 detail TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS timed_zone_holds (
                 zone INTEGER PRIMARY KEY CHECK(zone IN (1,2)),
                 until_ts REAL NOT NULL,
                 created_at REAL NOT NULL,
                 status TEXT NOT NULL DEFAULT 'PENDING_HOLD',
                 request_id TEXT NOT NULL,
                 last_attempt REAL
              );
              CREATE TABLE IF NOT EXISTS irrigation_schedules (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 zone INTEGER NOT NULL, start_date TEXT NOT NULL,
                 time_hm TEXT NOT NULL, interval_days INTEGER NOT NULL,
                 duration_minutes INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                 last_slot TEXT, last_result TEXT,
                 created_at REAL NOT NULL
              );
              CREATE TABLE IF NOT EXISTS crop_profiles (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 crop TEXT NOT NULL, soil_type TEXT NOT NULL, growth_stage TEXT NOT NULL,
                 soil_start_pct INTEGER NOT NULL, soil_stop_pct INTEGER NOT NULL,
                 updated_at REAL NOT NULL,
                 UNIQUE(crop,soil_type,growth_stage)
              );
              CREATE TABLE IF NOT EXISTS farm_config (
                 id INTEGER PRIMARY KEY CHECK (id=1), payload TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS app_preferences (
                 id INTEGER PRIMARY KEY CHECK (id=1), farm_name TEXT NOT NULL
              );
              CREATE TABLE IF NOT EXISTS active_irrigation (
                 id INTEGER PRIMARY KEY CHECK (id=1), zone INTEGER NOT NULL,
                 source TEXT NOT NULL, started_ms INTEGER NOT NULL, started_at REAL NOT NULL
              );
              CREATE TABLE IF NOT EXISTS irrigation_segments (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 started_at REAL NOT NULL, ended_at REAL NOT NULL,
                 zone INTEGER NOT NULL CHECK(zone IN (1,2)),
                 source TEXT NOT NULL,
                 duration_sim_seconds REAL,
                 status TEXT NOT NULL,
                 end_reason TEXT NOT NULL,
                 start_soil_pct REAL, end_soil_pct REAL
              );
              CREATE INDEX IF NOT EXISTS ix_irrigation_segments_ts ON irrigation_segments(started_at);
              CREATE INDEX IF NOT EXISTS ix_irrigation_segments_zone ON irrigation_segments(zone,started_at);
            ''')
            # Backwards-compatible extension for databases created by Phase 4.0.1.
            columns={r['name'] for r in self.conn.execute('PRAGMA table_info(active_irrigation)')}
            for column,ddl in {'last_ms':'INTEGER','last_seen_at':'REAL','start_soil_pct':'REAL','last_soil_pct':'REAL','water_start_total_l':'REAL','water_last_total_l':'REAL','water_valid':'INTEGER DEFAULT 0'}.items():
                if column not in columns:
                    self.conn.execute(f'ALTER TABLE active_irrigation ADD COLUMN {column} {ddl}')
            segment_columns={r['name'] for r in self.conn.execute('PRAGMA table_info(irrigation_segments)')}
            if 'water_estimated_l' not in segment_columns:
                self.conn.execute('ALTER TABLE irrigation_segments ADD COLUMN water_estimated_l REAL')
            if 'water_quality' not in segment_columns:
                self.conn.execute('ALTER TABLE irrigation_segments ADD COLUMN water_quality TEXT')
            # A process restart cannot prove a previously active session ended.
            # Close the orphan as unverified; do not guess a runtime.
            stale=self.conn.execute('SELECT * FROM active_irrigation WHERE id=1').fetchone()
            if stale:
                self.conn.execute("""INSERT INTO irrigation_segments
                  (started_at,ended_at,zone,source,duration_sim_seconds,status,end_reason,start_soil_pct,end_soil_pct)
                  VALUES(?,?,?,?,NULL,?,?,?,?)""",
                  (stale['started_at'],stale['last_seen_at'] or stale['started_at'],
                   stale['zone'],stale['source'],'UNVERIFIED','BACKEND_RESTART',
                   stale['start_soil_pct'],stale['last_soil_pct']))
                self.conn.execute('DELETE FROM active_irrigation WHERE id=1')
            self.conn.commit()

    def retire_schedules(self):
        """One-time backwards-compatible MVP migration: old schedules cannot execute."""
        with self._lock:
            self.conn.execute('UPDATE irrigation_schedules SET enabled=0 WHERE enabled!=0')
            row=self.conn.execute('SELECT payload FROM farm_config WHERE id=1').fetchone()
            if row:
                cfg=json.loads(row['payload'])
                for z in cfg.get('zones',[]):
                    z['irrigation_mode']='MOISTURE'
                self.conn.execute('UPDATE farm_config SET payload=? WHERE id=1',
                                  (json.dumps(cfg,ensure_ascii=False),))
            self.conn.commit()

    def timed_hold_set(self, zone:int, until_ts:float, request_id:str):
        with self._lock:
            self.conn.execute("""INSERT INTO timed_zone_holds(zone,until_ts,created_at,status,request_id,last_attempt)
                VALUES(?,?,?,'PENDING_HOLD',?,NULL)
                ON CONFLICT(zone) DO UPDATE SET until_ts=excluded.until_ts,
                created_at=excluded.created_at,status='PENDING_HOLD',request_id=excluded.request_id,
                last_attempt=NULL""",(zone,until_ts,time.time(),request_id))
            self.conn.commit()

    def timed_hold_update(self,zone:int,request_id:str,status:str):
        with self._lock:
            self.conn.execute('UPDATE timed_zone_holds SET status=?,last_attempt=? WHERE zone=? AND request_id=?',
                              (status,time.time(),zone,request_id))
            self.conn.commit()

    def timed_hold_delete(self,zone:int):
        with self._lock:
            self.conn.execute('DELETE FROM timed_zone_holds WHERE zone=?',(zone,))
            self.conn.commit()

    def timed_holds(self):
        with self._lock:
            return [dict(x) for x in self.conn.execute('SELECT * FROM timed_zone_holds ORDER BY zone')]

    def event(self, kind: str, severity: str, title: str, detail: str = '', data=None):
        with self._lock:
            self.conn.execute(
                'INSERT INTO events(ts,kind,severity,title,detail,payload) VALUES(?,?,?,?,?,?)',
                (time.time(), kind, severity, title, detail,
                 json.dumps(data, ensure_ascii=False) if data is not None else None)
            )
            self.conn.commit()

    def sync_notifications(self, alerts:list[dict]):
        """Persist alert episodes on transition, never overwrite older notifications."""
        now=time.time()
        observed={}
        for item in alerts:
            key=str(item.get('alert_key') or f"{item.get('kind','UNKNOWN')}:{item.get('zone') or 'global'}")
            observed[key]=item
        with self._lock:
            active={r['alert_key']:dict(r) for r in self.conn.execute(
                'SELECT * FROM notifications WHERE active=1')}
            dirty=False
            for key,item in observed.items():
                title=str(item.get('title') or 'Thông báo')
                detail=str(item.get('detail') or '')
                if key not in active:
                    self.conn.execute("""INSERT INTO notifications
                      (alert_key,level,kind,zone,title,detail,started_at,active)
                      VALUES(?,?,?,?,?,?,?,1)""",
                      (key,item.get('level','warning'),item.get('kind','OTHER'),item.get('zone'),title,detail,now))
                    dirty=True
                elif title!=active[key]['title'] or detail!=active[key]['detail']:
                    self.conn.execute('UPDATE notifications SET title=?,detail=? WHERE id=?',
                                      (title,detail,active[key]['id']))
                    dirty=True
            for key,item in active.items():
                if key not in observed:
                    self.conn.execute('UPDATE notifications SET active=0,ended_at=? WHERE id=?',
                                      (now,item['id']))
                    dirty=True
            if dirty:self.conn.commit()

    def notifications(self,limit:int=35,offset:int=0):
        with self._lock:
            rows=self.conn.execute("""SELECT id,alert_key,level,kind,zone,title,detail,started_at,
                       ended_at,active FROM notifications ORDER BY active DESC,
                       CASE WHEN active=1 THEN started_at ELSE ended_at END DESC,id DESC LIMIT ? OFFSET ?""",
                       (limit,offset)).fetchall()
        return [dict(r) for r in rows]

    def notification_count(self):
        with self._lock:
            return int(self.conn.execute('SELECT COUNT(*) FROM notifications').fetchone()[0])

    def ingest(self, data: dict, ts: float | None = None):
        ts = ts if ts is not None else time.time()
        old = self.latest()
        # MQTT QoS0 packets may arrive out of order. A backward ms alone is not
        # evidence of a reboot: keep the last accepted telemetry and active session.
        # A reboot is supported by counters rolling back, or a new low uptime.
        current_ms = data.get('ms')
        previous_ms = old.get('ms') if isinstance(old, dict) else None
        if (isinstance(current_ms,(int,float)) and not isinstance(current_ms,bool)
                and isinstance(previous_ms,(int,float)) and not isinstance(previous_ms,bool)
                and current_ms < previous_ms):
            counters_reset = any(
                self._water_counter(data,z) is not None
                and self._water_counter(old,z) is not None
                and self._water_counter(data,z) + .002 < self._water_counter(old,z)
                for z in (1,2))
            likely_reboot = ((current_ms <= 100 and previous_ms >= 2000)
                             or (current_ms <= 10000 and previous_ms >= 30000
                                 and previous_ms-current_ms >= 20000))
            if ((previous_ms-current_ms <= 5000 and not likely_reboot)
                    or (not counters_reset and not likely_reboot)):
                return  # delayed/out-of-order sample: never rewrite latest state
        def number(k):
            v = data.get(k)
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        with self._lock:
            self.conn.execute('''
                INSERT INTO telemetry (ts,device_ms,state,source,zone,pump_on,salinity_ppt,
                    soil1_pct,soil2_pct,tank_l,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ''', (ts, number('ms'), data.get('state'), data.get('source'), number('zone'),
                  int(bool(data.get('pump_on'))), number('salinity_ppt'),
                  number('soil1_pct'), number('soil2_pct'), number('tank_l'),
                  json.dumps(data, ensure_ascii=False, separators=(',', ':'))))
            self.conn.commit()
        self._update_irrigation_session(data,ts,old)
        if not old or old['state'] != data.get('state'):
            current = str(data.get('state') or 'UNKNOWN')
            severity = 'critical' if current == 'FAULT' else ('warning' if current == 'HOLD_NO_WATER' else 'info')
            self.event('state', severity, 'Trạng thái: ' + current,
                       f"Nguồn: {data.get('source','—')} · Lý do: {data.get('reason','—')}")
        if old and old.get('canal_safe') != data.get('canal_safe'):
            if data.get('canal_safe') is False:
                self.event('water', 'warning', 'Nguồn kênh không an toàn', 'Không sử dụng nguồn kênh khi bị khóa')
            elif data.get('canal_safe') is True:
                self.event('water', 'info', 'Nguồn kênh được mở lại', 'Bộ điều khiển đã đánh giá kênh an toàn')


    @staticmethod
    def _water_counter(data:dict | None, zone:int):
        """ESP32's cumulative per-zone litres, never a local wall-clock estimate."""
        if not isinstance(data,dict) or zone not in (1,2):
            return None
        value=data.get(f'irrigation_zone{zone}_estimated_total_l')
        if isinstance(value,bool) or not isinstance(value,(float,int)):
            return None
        value=float(value)
        return round(value,3) if 0 <= value <= 100000 and math.isfinite(value) else None

    def _update_irrigation_session(self, data:dict, ts:float, previous:dict | None=None):
        """Track verified pump-on segments, using only ESP32 cumulative counters.

        Counter deltas do not tick during PAUSE/REST. Any reboot, telemetry gap,
        missing/rolling-back counter or backend restart leaves volume unverified;
        no invented flow-based or wall-clock based litres are saved.
        """
        zone=data.get('zone') if data.get('zone') in (1,2) else 0
        on=bool(data.get('pump_on')) and zone>0
        ms=data.get('ms')
        if isinstance(ms,bool) or not isinstance(ms,(int,float)):
            return
        ms=int(ms)
        source=str(data.get('source') or 'NONE').upper()
        if source not in ('CANAL','TANK'):on=False
        soil_key='soil1_pct' if zone==1 else 'soil2_pct'
        current_soil=data.get(soil_key)
        if isinstance(current_soil,bool) or not isinstance(current_soil,(int,float)):
            current_soil=None
        with self._lock:
            old=self.conn.execute('SELECT * FROM active_irrigation WHERE id=1').fetchone()
            close_reason=None
            if old:
                prior_ms=old['last_ms'] if old['last_ms'] is not None else old['started_ms']
                if ms < prior_ms:close_reason='ESP32_RESTART'
                elif ms-prior_ms>20000:close_reason='TELEMETRY_GAP'
                elif not on:close_reason=str(data.get('reason') or data.get('state') or 'STOPPED')[:80]
                elif old['zone']!=zone:close_reason='ZONE_CHANGE'
                elif old['source']!=source:close_reason='SOURCE_CHANGE'
                if close_reason:
                    verified=close_reason not in ('ESP32_RESTART','TELEMETRY_GAP')
                    duration=round((ms-old['started_ms'])/1000,3) if verified else None
                    if duration is not None and (duration<0 or duration>86400):duration=None
                    status='COMPLETED' if duration is not None else 'UNVERIFIED'
                    start_total=old['water_start_total_l']
                    latest_total=self._water_counter(data,old['zone']) if verified else None
                    water=None
                    quality='UNVERIFIED'
                    # Closed segment's final counter may be in the idle/REST
                    # packet; PAUSE time does not increase the hardware counter.
                    # Never use the new packet's counter after a confirmed reboot.
                    if (duration is not None and start_total is not None
                            and latest_total is not None and bool(old['water_valid'])
                            and latest_total+0.002>=start_total):
                        water=round(max(0.0,latest_total-start_total),3)
                        quality='ESTIMATED'
                    elif (duration is not None and not bool(old['water_valid'])
                          and old['water_last_total_l'] is not None
                          and old['water_start_total_l'] is not None
                          and latest_total is not None
                          and latest_total+0.002>=old['water_last_total_l']
                          and latest_total+0.002>=start_total):
                        # First frame was already pumping, so only a LOWER BOUND
                        # is observable. Do not label it as a full verified volume.
                        water=round(max(0.0,latest_total-start_total),3)
                        quality='PARTIAL' if water>0 else 'UNVERIFIED'
                        if quality=='UNVERIFIED':water=None
                    self.conn.execute("""INSERT INTO irrigation_segments
                        (started_at,ended_at,zone,source,duration_sim_seconds,status,
                         end_reason,start_soil_pct,end_soil_pct,water_estimated_l,water_quality)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (old['started_at'],ts if verified else (old['last_seen_at'] or old['started_at']),
                         old['zone'],old['source'],duration,status,close_reason,
                         old['start_soil_pct'],old['last_soil_pct'] if not verified else
                         data.get('soil1_pct' if old['zone']==1 else 'soil2_pct'),
                         water,quality))
                    if duration is not None:
                        self.conn.execute('INSERT INTO events(ts,kind,severity,title,detail,payload) VALUES(?,?,?,?,?,?)',
                            (ts,'irrigation_session','info','Đã kết thúc đoạn tưới',
                             f"Vùng {old['zone']} · Nguồn {old['source']} · {duration:g} giây mô phỏng",
                             json.dumps({'zone':old['zone'],'source':old['source'],
                                         'duration_seconds':duration,'estimated_liters':water},ensure_ascii=False)))
                    self.conn.execute('DELETE FROM active_irrigation WHERE id=1')
                    old=None
            if on:
                counter=self._water_counter(data,zone)
                if old:
                    prior_counter=old['water_last_total_l']
                    valid=bool(old['water_valid'])
                    if counter is None or prior_counter is None or counter+0.002<prior_counter:
                        valid=False
                    self.conn.execute("""UPDATE active_irrigation SET
                        last_ms=?,last_seen_at=?,last_soil_pct=?,water_last_total_l=?,water_valid=? WHERE id=1""",
                        (ms,ts,current_soil,counter,int(valid)))
                else:
                    # Use the last telemetry frame as the baseline only when
                    # it is from the same ESP32 uptime and close in time.
                    prior_counter=self._water_counter(previous,zone)
                    old_ms=previous.get('ms') if isinstance(previous,dict) else None
                    old_ts=previous.get('received_at') if isinstance(previous,dict) else None
                    reliable=(prior_counter is not None and isinstance(old_ms,(int,float))
                              and not isinstance(old_ms,bool) and ms>=old_ms and ms-old_ms<=20000
                              and isinstance(old_ts,(int,float)) and 0<=ts-old_ts<=60
                              and counter is not None and counter+0.002>=prior_counter)
                    baseline=prior_counter if reliable else counter
                    self.conn.execute("""INSERT INTO active_irrigation
                        (id,zone,source,started_ms,started_at,last_ms,last_seen_at,start_soil_pct,last_soil_pct,
                         water_start_total_l,water_last_total_l,water_valid)
                        VALUES(1,?,?,?,?,?,?,?,?,?,?,?)""",
                        (zone,source,ms,ts,ms,ts,current_soil,current_soil,baseline,counter,int(reliable)))
            self.conn.commit()

    def activity_segments(self, days:int=7, zone:int=0, limit:int=250):
        if days not in (1,7,30):raise ValueError('Khoảng thời gian không hợp lệ')
        if zone not in (0,1,2):raise ValueError('Vùng không hợp lệ')
        cutoff=time.time()-days*86400
        query="""SELECT id,started_at,ended_at,zone,source,duration_sim_seconds,status,
                 end_reason,start_soil_pct,end_soil_pct,water_estimated_l,water_quality FROM irrigation_segments
                 WHERE started_at>=? AND (?=0 OR zone=?) ORDER BY id DESC LIMIT ?"""
        with self._lock:
            rows=self.conn.execute(query,(cutoff,zone,zone,max(1,min(limit,1000)))).fetchall()
        return [dict(r) for r in rows]

    def activity_report(self,days:int=7,zone:int=0):
        if days not in (1,7,30):raise ValueError('Khoảng thời gian không hợp lệ')
        if zone not in (0,1,2):raise ValueError('Vùng không hợp lệ')
        cutoff=time.time()-days*86400
        with self._lock:
            r=self.conn.execute("""SELECT COUNT(*) AS total, SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) AS verified,
               SUM(CASE WHEN status='UNVERIFIED' THEN 1 ELSE 0 END) AS unverified,
               COALESCE(SUM(CASE WHEN status='COMPLETED' THEN duration_sim_seconds ELSE 0 END),0) AS seconds,
               SUM(CASE WHEN status='COMPLETED' AND source='CANAL' THEN duration_sim_seconds ELSE 0 END) AS canal_seconds,
               SUM(CASE WHEN status='COMPLETED' AND source='TANK' THEN duration_sim_seconds ELSE 0 END) AS tank_seconds,
               COUNT(CASE WHEN water_quality='ESTIMATED' AND status='COMPLETED' THEN 1 END) AS water_records,
               COUNT(CASE WHEN water_quality='PARTIAL' AND status='COMPLETED' THEN 1 END) AS partial_records,
               COALESCE(SUM(CASE WHEN water_quality='PARTIAL' AND status='COMPLETED' THEN water_estimated_l ELSE 0 END),0) AS partial_water,
               COALESCE(SUM(CASE WHEN water_quality='ESTIMATED' AND status='COMPLETED' THEN water_estimated_l ELSE 0 END),0) AS water_sum,
               COALESCE(SUM(CASE WHEN zone=1 AND water_quality='ESTIMATED' AND status='COMPLETED' THEN water_estimated_l ELSE 0 END),0) AS z1_water,
               COALESCE(SUM(CASE WHEN zone=2 AND water_quality='ESTIMATED' AND status='COMPLETED' THEN water_estimated_l ELSE 0 END),0) AS z2_water
               FROM irrigation_segments WHERE started_at>=? AND (?=0 OR zone=?)""", (cutoff,zone,zone)).fetchone()
            active=self.conn.execute('SELECT zone,source,started_at FROM active_irrigation WHERE id=1').fetchone()
        return {'days':days,'zone':zone,'segments':int(r['total']),
                'verified_segments':int(r['verified'] or 0),'unverified_segments':int(r['unverified'] or 0),
                'pump_sim_seconds':round(r['seconds'],2),
                'canal_sim_seconds':round(r['canal_seconds'] or 0,2),
                'tank_sim_seconds':round(r['tank_seconds'] or 0,2),
                'active':dict(active) if active and (zone==0 or active['zone']==zone) else None,
                'water_liters':round(r['water_sum'],3) if r['water_records'] else None,
                'estimated_water_l':round(r['water_sum'],3),
                'zone1_estimated_water_l':round(r['z1_water'],3),
                'zone2_estimated_water_l':round(r['z2_water'],3),
                'water_verified_segments':int(r['water_records'] or 0),
                'water_partial_segments':int(r['partial_records'] or 0),
                'water_partial_l':round(r['partial_water'],3),
                'water_volume_note':'Lượng nước ước tính từ bộ đếm ESP32, không phải số đo lưu lượng thực.'}

    def activity_water_daily(self, days:int=7, zone:int=0):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        if days not in (1,7,30) or zone not in (0,1,2):
            raise ValueError('Khoảng thời gian hoặc vùng không hợp lệ')
        tz=ZoneInfo('Asia/Ho_Chi_Minh')
        now=time.time()
        cutoff=now-days*86400
        today=datetime.fromtimestamp(now,tz).date()
        first_day=datetime.fromtimestamp(cutoff,tz).date()
        dates=[(first_day+timedelta(days=i)).isoformat() for i in range((today-first_day).days+1)]
        totals={d:{'date':d,'z1':0.0,'z2':0.0,'z1_count':0,'z2_count':0} for d in dates}
        with self._lock:
            rows=self.conn.execute("""SELECT started_at,zone,water_estimated_l
                FROM irrigation_segments WHERE started_at>=? AND status='COMPLETED'
                AND water_quality='ESTIMATED' AND (?=0 OR zone=?)""",(cutoff,zone,zone)).fetchall()
        for row in rows:
            day=datetime.fromtimestamp(row['started_at'],tz).date().isoformat()
            if day in totals:
                totals[day]['z'+str(row['zone'])]+=row['water_estimated_l']
                totals[day]['z'+str(row['zone'])+'_count']+=1
        for item in totals.values():
            item['z1']=round(item['z1'],3);item['z2']=round(item['z2'],3)
        return list(totals.values())

    def latest(self):
        with self._lock:
            row = self.conn.execute('SELECT ts,payload FROM telemetry ORDER BY id DESC LIMIT 1').fetchone()
        if row is None:
            return None
        data = json.loads(row['payload'])
        data['received_at'] = row['ts']
        return data

    def history(self, minutes: int = 30, limit: int = 320):
        cutoff = time.time() - minutes * 60
        # Get the latest samples; reverse back to chronological order.
        with self._lock:
            rows = self.conn.execute('''
              SELECT ts,device_ms,state,source,zone,pump_on,salinity_ppt,soil1_pct,soil2_pct,tank_l,payload
              FROM telemetry WHERE ts >= ? ORDER BY id DESC LIMIT ?
            ''', (cutoff, limit)).fetchall()
        result = []
        for row in reversed(rows):
            d = json.loads(row['payload'])
            result.append({'ts': row['ts'], 'device_ms': row['device_ms'],
                'state': row['state'], 'source': row['source'], 'zone': row['zone'],
                'pump_on': bool(row['pump_on']), 'salinity_ppt': row['salinity_ppt'],
                'soil1_pct': row['soil1_pct'], 'soil2_pct': row['soil2_pct'],
                'tank_l': row['tank_l'], 'air_c': d.get('air_c'),
                'water_c': d.get('water_c')})
        return result

    def events(self, limit: int = 50):
        with self._lock:
            rows = self.conn.execute('SELECT id,ts,kind,severity,title,detail FROM events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]

    def record_twin(self, frame: dict):
        with self._lock:
            self.conn.execute('INSERT INTO twin_samples(ts,scenario,payload) VALUES(?,?,?)',
                 (frame['ts'], frame['scenario'], json.dumps(frame, ensure_ascii=False, separators=(',',':'))))
            self.conn.commit()

    def twin_history(self, limit: int = 200):
        with self._lock:
            rows=self.conn.execute('SELECT payload FROM twin_samples ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [json.loads(row['payload']) for row in reversed(rows)]


    def sync_soil_alerts(self, alerts: list[dict]):
        """Track ONLY warning/recovery transitions; no events emitted every 2 s.

        Soil thresholds are informational. 'Resolved' simply means the condition
        no longer triggers under current configuration, NOT that soil was treated.
        """
        observed={a['alert_key']:a for a in alerts if a.get('kind')=='SOIL_MONITOR' and a.get('alert_key')}
        with self._lock:
            prior={r['alert_key']:dict(r) for r in self.conn.execute('SELECT * FROM soil_alert_state')}
            for key,a in observed.items():
                if key not in prior:
                    self.conn.execute('INSERT INTO soil_alert_state(alert_key,title,detail) VALUES(?,?,?)',
                                      (key,a['title'],a['detail']))
                    self.conn.execute('INSERT INTO events(ts,kind,severity,title,detail) VALUES(?,?,?,?,?)',
                                      (time.time(),'soil_warning','warning',a['title'],a['detail']+' Chỉ theo dõi, không điều khiển tưới.'))
                else:
                    self.conn.execute('UPDATE soil_alert_state SET title=?,detail=? WHERE alert_key=?',
                                      (a['title'],a['detail'],key))
            for key,a in prior.items():
                if key not in observed:
                    self.conn.execute('DELETE FROM soil_alert_state WHERE alert_key=?',(key,))
                    self.conn.execute('INSERT INTO events(ts,kind,severity,title,detail) VALUES(?,?,?,?,?)',
                                      (time.time(),'soil_clear','info',
                                       'Không còn cảnh báo: '+a['title'],
                                       'Chỉ số hoặc cấu hình theo dõi đã thay đổi; không khẳng định đất đã được xử lý.'))
            self.conn.commit()

    def get_farm_config(self):
        with self._lock:
            row=self.conn.execute('SELECT payload FROM farm_config WHERE id=1').fetchone()
        data=json.loads(row['payload']) if row else {
            'zones':[{'name':'Vườn 1','crop':'Chưa thiết lập','soil_ec_max':None,
                       'soil_ph_min':None,'soil_ph_max':None,'soil_na_max':None,
                       'irrigation_mode':'MOISTURE','soil_high_warn_pct':None},
                     {'name':'Vườn 2','crop':'Chưa thiết lập','soil_ec_max':None,
                       'soil_ph_min':None,'soil_ph_max':None,'soil_na_max':None,
                       'irrigation_mode':'MOISTURE','soil_high_warn_pct':None}]}

        for z in data['zones']:
            z['irrigation_mode']='MOISTURE'
            z.setdefault('soil_high_warn_pct',None)
            z.setdefault('soil_type','Chưa thiết lập')
            z.setdefault('growth_stage','Chưa thiết lập')
            z.setdefault('soil_start_pct',35)
            z.setdefault('soil_stop_pct',60)
        return data

    def save_farm_config(self, data):
        with self._lock:
            self.conn.execute('INSERT INTO farm_config(id,payload) VALUES(1,?) '
                              'ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                              (json.dumps(data,ensure_ascii=False),))
            self.conn.commit()
        self.event('config','info','Đã cập nhật cấu hình vườn',
                   'Ngưỡng tưới được gửi ESP32 và cần xác nhận bằng telemetry')
        return self.get_farm_config()


    def list_crop_profiles(self):
        with self._lock:
            rows=self.conn.execute('SELECT crop,soil_type,growth_stage,soil_start_pct,soil_stop_pct,updated_at FROM crop_profiles ORDER BY crop,soil_type,growth_stage').fetchall()
        return [dict(row) for row in rows]

    def save_crop_profile(self, profile):
        with self._lock:
            self.conn.execute('''INSERT INTO crop_profiles(crop,soil_type,growth_stage,soil_start_pct,soil_stop_pct,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(crop,soil_type,growth_stage)
                DO UPDATE SET soil_start_pct=excluded.soil_start_pct,soil_stop_pct=excluded.soil_stop_pct,updated_at=excluded.updated_at''',
                (profile['crop'],profile['soil_type'],profile['growth_stage'],profile['soil_start_pct'],profile['soil_stop_pct'],time.time()))
            self.conn.commit()
        self.event('profile','info','Đã lưu hồ sơ canh tác thử nghiệm',profile['crop']+' / '+profile['soil_type']+' / '+profile['growth_stage'])
        return profile

    def get_app_preferences(self):
        with self._lock:
            row=self.conn.execute('SELECT farm_name FROM app_preferences WHERE id=1').fetchone()
        return {'farm_name':row['farm_name'] if row else 'Vườn của tôi'}

    def set_app_preferences(self,farm_name:str):
        farm_name=farm_name.strip()
        if not 1<=len(farm_name)<=45:
            raise ValueError('Tên vườn phải từ 1 đến 45 ký tự')
        with self._lock:
            self.conn.execute('INSERT INTO app_preferences(id,farm_name) VALUES(1,?) '
                'ON CONFLICT(id) DO UPDATE SET farm_name=excluded.farm_name',(farm_name,))
            self.conn.commit()
        self.event('settings','info','Đã đổi tên trang trại',farm_name)
        return self.get_app_preferences()

    def trends(self, days:int=1, limit:int=120):
        """Evenly sample telemetry across the requested period (not just newest N rows)."""
        if days not in (1,7,30):raise ValueError('Chỉ hỗ trợ 1, 7, 30 ngày')
        start=time.time()-days*86400
        step=max(1.0,days*86400/max(1,min(limit,240)))
        with self._lock:
            rows=self.conn.execute("""
                SELECT t.ts,t.salinity_ppt,t.soil1_pct,t.soil2_pct,t.tank_l
                FROM telemetry t JOIN (
                    SELECT MAX(id) id FROM telemetry WHERE ts>=?
                    GROUP BY CAST((ts - ?) / ? AS INTEGER)
                ) b ON t.id=b.id ORDER BY t.ts ASC LIMIT ?
            """,(start,start,step,limit)).fetchall()
        return [dict(r) for r in rows]

    def schedules(self):
        with self._lock:
            rows=self.conn.execute('SELECT * FROM irrigation_schedules ORDER BY time_hm,id').fetchall()
        return [dict(r) for r in rows]

    def add_schedule(self, zone:int, start_date:str, time_hm:str, interval_days:int, duration_minutes:int):
        with self._lock:
            if self.conn.execute('SELECT COUNT(*) FROM irrigation_schedules').fetchone()[0]>=12:
                raise ValueError('Tối đa 12 lịch tưới')
            c=self.conn.execute('''INSERT INTO irrigation_schedules
                (zone,start_date,time_hm,interval_days,duration_minutes,enabled,created_at)
                VALUES(?,?,?,?,?,1,?)''', (zone,start_date,time_hm,interval_days,duration_minutes,time.time()))
            self.conn.commit()
        self.event('schedule','info','Đã tạo lịch tưới',f'Vùng {zone}: {time_hm}, mỗi {interval_days} ngày')
        return c.lastrowid

    def set_schedule_enabled(self, schedule_id:int, enabled:bool):
        with self._lock:
            c=self.conn.execute('UPDATE irrigation_schedules SET enabled=? WHERE id=?',
                (int(enabled),schedule_id))
            self.conn.commit()
        if not c.rowcount:raise ValueError('Không tìm thấy lịch tưới')
        self.event('schedule','info','Đã '+('bật' if enabled else 'tắt')+' lịch tưới',f'Mã {schedule_id}')

    def delete_schedule(self,schedule_id:int):
        with self._lock:
            c=self.conn.execute('DELETE FROM irrigation_schedules WHERE id=?',(schedule_id,))
            self.conn.commit()
        if not c.rowcount:raise ValueError('Không tìm thấy lịch tưới')
        self.event('schedule','info','Đã xóa lịch tưới',f'Mã {schedule_id}')

    def claim_schedule(self,schedule_id:int,slot:str):
        # Claim once; survives process restarts.
        with self._lock:
            c=self.conn.execute('''UPDATE irrigation_schedules SET last_slot=?,last_result='Đang xử lý'
               WHERE id=? AND enabled=1 AND (last_slot IS NULL OR last_slot<>?)''',
               (slot,schedule_id,slot))
            self.conn.commit()
            return c.rowcount==1

    def schedule_result(self,schedule_id:int,result:str):
        with self._lock:
            self.conn.execute('UPDATE irrigation_schedules SET last_result=? WHERE id=?',(result,schedule_id))
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()
