"""SaltGuard 2.5 software-only closed-loop digital twin. Educational, uncalibrated model.

Data path: simulated environment -> MQTT twin/input -> Wokwi ESP32 controller
-> telemetry MQTT -> this model (water/soil feedback). All chemistry/flow estimates are virtual.
"""
from __future__ import annotations
import math
import threading
import time
from dataclasses import dataclass, asdict
from .alerts import soil_alerts

SCENARIOS = {'NORMAL', 'SALINITY', 'DROUGHT', 'RAIN'}

TEST_PRESETS = {
    'BOTH_DRY': {'soil1_pct':20., 'soil2_pct':25., 'salinity_ppt':0.5, 'canal_pct':80., 'rain_pct':0., 'tank_l':1500.},
    'ONLY_Z2': {'soil1_pct':65., 'soil2_pct':25., 'salinity_ppt':0.5, 'canal_pct':80., 'rain_pct':0., 'tank_l':1500.},
    'SALTY_TANK': {'soil1_pct':20., 'soil2_pct':25., 'salinity_ppt':1.5, 'canal_pct':80., 'rain_pct':0., 'tank_l':1500.},
    'NO_SOURCE': {'soil1_pct':20., 'soil2_pct':25., 'salinity_ppt':1.5, 'canal_pct':80., 'rain_pct':0., 'tank_l':100.},
    'REFILL': {'soil1_pct':75., 'soil2_pct':75., 'salinity_ppt':0.5, 'canal_pct':80., 'rain_pct':0., 'tank_l':500.},
    'BOTH_WET': {'soil1_pct':75., 'soil2_pct':75., 'salinity_ppt':0.5, 'canal_pct':80., 'rain_pct':0., 'tank_l':1500.},
}


def bounded(x: float, low: float, high: float):
    return round(max(low, min(high, x)), 3)

def approach(current: float, target: float, step: float) -> float:
    return current + max(-step, min(step, target-current))

@dataclass
class FarmWorld:
    elapsed_s: float = 0
    salinity_ppt: float = 0.5
    canal_pct: float = 80.0
    rain_pct: float = 0.0
    soil1_pct: float = 24.0
    soil2_pct: float = 49.0
    tank_l: float = 1500.0
    tank_salt_ppt: float = 0.3  # independently simulated stored-water quality
    filling: bool = False
    fill_total_l: float = 0.0
    # Software-only soil health channels: never control irrigation, no sensor in Wokwi.
    soil_ec_z1_ds_m: float = 1.10
    soil_ec_z2_ds_m: float = 0.95
    soil_ph_z1: float = 6.40
    soil_ph_z2: float = 6.55
    soil_na_z1_mg_kg: float = 65.0
    soil_na_z2_mg_kg: float = 60.0
    canal_ph: float = 7.2    # software scenario, not sensor
    tank_ph: float = 7.1
    tank_ec_ms_cm: float = 0.7
    soil_salt_risk_z1: float = 12.0  # toy index 0-100, NOT measured ECe
    soil_salt_risk_z2: float = 10.0
    estimated_flow_l_min: float = 0.0
    estimated_total_l: float = 0.0
    irrigating: bool = False
    scenario: str = 'NORMAL'
    controller_fresh: bool = False
    def advance(self, dt: float, actual: dict | None, fresh: bool):
        dt=max(0., min(float(dt), 5.))
        self.elapsed_s+=dt
        self.controller_fresh=bool(fresh)
        s=self.scenario
        salt_target={'NORMAL':0.5,'SALINITY':1.8,'DROUGHT':1.2,'RAIN':0.3}[s]
        canal_target={'NORMAL':80,'SALINITY':72,'DROUGHT':9,'RAIN':93}[s]
        rain_target={'NORMAL':0,'SALINITY':0,'DROUGHT':0,'RAIN':78}[s]
        # A test preset must retain its controlled environmental inputs until completed.
        # Soil moisture and tank volume still evolve in response to actual ESP32 telemetry.
        preset_active = getattr(self, 'test_inputs_locked', False)
        if not preset_active:
            self.salinity_ppt=bounded(approach(self.salinity_ppt,salt_target,0.09*dt),0,3)
            self.canal_pct=bounded(approach(self.canal_pct,canal_target,0.8*dt),0,100)
            self.rain_pct=bounded(approach(self.rain_pct,rain_target,4*dt),0,100)
        # pH simulation is informational only: never used to permit/deny irrigation.
        self.canal_ph=bounded(approach(self.canal_ph,7.1 if s=='RAIN' else 7.25,0.002*dt),0,14)
        actual=actual or {}
        safe_pump=fresh and actual.get('mode')=='TWIN' and actual.get('pump_on') is True
        source=actual.get('source') if safe_pump else None
        zone=actual.get('zone') if safe_pump else None
        self.irrigating=bool(safe_pump and source in {'CANAL','TANK'} and zone in {1,2})
        self.estimated_flow_l_min=120.0 if self.irrigating else 0.0
        moved=self.estimated_flow_l_min*dt/60.0
        self.estimated_total_l=bounded(self.estimated_total_l+moved,0,100000)
        # Rain does not magically replenish the closed canal-fed reserve tank.
        fill_on = fresh and actual.get('mode')=='TWIN' and actual.get('tank_fill_on') is True
        self.filling = bool(fill_on and not self.irrigating)
        added = (25.0*dt if self.filling else 0.0)  # accelerated virtual fill rate for demo
        old_tank=self.tank_l
        next_tank=bounded(old_tank + added - (moved if source=='TANK' and self.irrigating else 0),0,2000)
        actual_added=max(0,next_tank-old_tank) if self.filling else 0
        if actual_added:
            # Mixed salinity is a simple mass balance; no claim of measured treatment.
            self.tank_salt_ppt=bounded((old_tank*self.tank_salt_ppt+actual_added*self.salinity_ppt)/max(next_tank,0.01),0,3)
            self.fill_total_l=bounded(self.fill_total_l+actual_added,0,100000)
        self.tank_l=next_tank
        for i in (1,2):
            v=getattr(self,f'soil{i}_pct')
            v+=(-0.12 if s=='DROUGHT' else -0.06)*dt
            # Rain actually moistens soil, not merely slowing drying.
            v+=0.28*self.rain_pct/100*dt
            if self.irrigating and zone==i:
                v+=0.85*dt
                risk=getattr(self,f'soil_salt_risk_z{i}')
                risk+=((self.salinity_ppt*1.0) if source=='CANAL' else 0.04)*dt*0.07
                setattr(self,f'soil_salt_risk_z{i}',bounded(risk,0,100))
            setattr(self,f'soil{i}_pct',bounded(v,0,100))
            # Educational chemical trend only. No automatic soil treatment or watering lock.
            ec=getattr(self,f'soil_ec_z{i}_ds_m')
            ec+= (0.0009*dt if s=='DROUGHT' else -0.0006*self.rain_pct/100*dt)
            if self.irrigating and zone==i: ec+=max(0.,self.salinity_ppt-0.4)*0.0008*dt
            setattr(self,f'soil_ec_z{i}_ds_m',bounded(ec,0,20))
            # Na and pH remain nearly stable without a modeled chemical process.
        return asdict(self)

    def wire_input(self):
        """Versioned CSV: fixed 6 floats, mandatory protocol marker.
        NO JSON parser library required in ESP32 firmware.
        """
        return 'SGT2,{:.2f},{:.1f},{:.1f},{:.1f},{:.1f},{:.1f},{:.2f}'.format(
            self.salinity_ppt,self.canal_pct,self.rain_pct,
            self.soil1_pct,self.soil2_pct,self.tank_l,self.tank_salt_ppt)

class TwinService:
    def __init__(self, mqtt_bridge, storage, clock=time.time):
        self.bridge=mqtt_bridge
        self.storage=storage
        self.clock=clock
        self.world=FarmWorld()
        self.running=False
        self._lock=threading.RLock()
        self._thread=None
        self._stop=threading.Event()
        self._last_tick=None
        self.last_publish=None
        self.last_step=None
        self._soil_test_original=None
        self.last_error=None
        self._mute_until=0.0
        self.last_preset=None
        self._demo_permission_zones=set()
        self._demo_pending_zones=set()
        self._demo_last_attempt=0.0
        self._demo_ended=False
        self._custom_apply_rx_baseline=None
        self._custom_apply_requested_at=0.0
        self._observed_zones=set()
        self._observed_preset_frame=False

    def _end_demo_permissions(self):
        """Cancel only test-issued temporary permissions, never change MASTER/PAUSE."""
        pending=tuple(sorted(self._demo_permission_zones))
        self._demo_permission_zones.clear()
        self._demo_pending_zones.clear()
        for zi in pending:
            try:self.bridge.command(f'ZONE:{zi}:CANCEL_ONCE')
            except ConnectionError as e:self.last_error=str(e)
        self._demo_ended=True

    def _tick_demo_permissions(self,actual,fresh,now):
        if not self._demo_pending_zones or not fresh or not self.bridge.connected:return
        if actual.get('mode')!='TWIN' or not actual.get('master_enabled'):
            return
        if not actual.get('clock_valid'):return
        # ESP32 still makes all safety decisions and returns an ACK.
        if now-self._demo_last_attempt<3:return
        for zi in sorted(tuple(self._demo_pending_zones)):
            if actual.get(f'zone{zi}_hold') or actual.get('paused') or actual.get('fault'):
                continue
            if actual.get('irrigation_window'):
                self._demo_pending_zones.discard(zi)
                continue
            try:
                self.bridge.command(f'ZONE:{zi}:ONCE')
                self._demo_permission_zones.add(zi)
                self._demo_pending_zones.discard(zi)
                self._demo_last_attempt=now
            except ConnectionError as e:self.last_error=str(e)
            break

    def _custom_frame_confirmed(self,actual,now):
        """Wait for a *new* ESP32 SGT2 frame matching the latest CUSTOM values.

        A broker publication alone is not proof of receipt. One-time irrigation
        requests are therefore queued only after the controller reports fresh
        telemetry for the current application, never for the previous scenario.
        """
        if self.last_preset!='CUSTOM' or not actual or actual.get('mode')!='TWIN':
            return False
        if actual.get('received_at',0)<=self._custom_apply_requested_at:
            return False
        rx=actual.get('twin_rx_count')
        base=self._custom_apply_rx_baseline
        if isinstance(base,(int,float)) and not isinstance(base,bool):
            if not isinstance(rx,(int,float)) or isinstance(rx,bool) or rx<=base:
                return False
        elif not isinstance(rx,(int,float)) or isinstance(rx,bool):
            return False
        # The backend holds the freshly applied CUSTOM world steady briefly.
        # Use a small tolerance for telemetry float rounding / MQTT latency.
        for key,tolerance in (('soil1_pct',1.0),('soil2_pct',1.0),
                              ('salinity_ppt',0.11),('canal_pct',1.0),
                              ('rain_pct',1.0),('tank_l',12.0)):
            value=actual.get(key)
            if not isinstance(value,(int,float)) or not math.isfinite(value):
                return False
            if abs(value-getattr(self.world,key))>tolerance:return False
        return True

    def start_background(self):
        if self._thread and self._thread.is_alive():return
        self._stop.clear()
        self._thread=threading.Thread(target=self._loop,daemon=True,name='saltguard-twin')
        self._thread.start()

    def shutdown(self):
        self._stop.set()
        if self._thread:self._thread.join(timeout=3)

    def _loop(self):
        while not self._stop.wait(2.0):
            if not self.running:continue
            try:self.step()
            except Exception as e:
                self.last_error=str(e)[:200]

    def _fresh_latest(self):
        actual=self.storage.latest()
        if not actual:return None,False
        return actual,(self.clock()-actual['received_at']) < 15

    def enable(self,scenario='NORMAL'):
        if scenario not in SCENARIOS:raise ValueError('Kịch bản không hợp lệ')
        actual,fresh=self._fresh_latest()
        if not self.bridge.connected or not fresh:raise ConnectionError('Cần MQTT và ESP32 trực tuyến')
        if actual.get('mode')=='PRESET':raise ValueError('Hãy nhập D trên Wokwi trước khi bật Digital Twin')
        with self._lock:
            self.world=FarmWorld(scenario=scenario)
            self._soil_test_original=None
            self._mute_until=0.0
            self._stale_arm_pending=False
            self._end_demo_permissions()
            self.last_preset=None
            self._last_tick=self.clock()
            self.bridge.command('TWIN:ON')
            self.running=True
            self.last_error=None
            self.storage.event('twin','info','Digital Twin bắt đầu',f'Kịch bản: {scenario}')
        # Send initial input immediately; controller applies the shortened safety REST on receipt.
        self.step(initial=True)
        return self.snapshot()

    def disable(self):
        with self._lock:
            if self.last_preset == 'CUSTOM' and self.bridge.connected:
                try:self.bridge.command('DEMO:CUSTOM:END')
                except ConnectionError as e:self.last_error=str(e)
            self._end_demo_permissions()
            self.running=False
            self.world.test_inputs_locked=False
            self._soil_test_original=None
            self._mute_until=0.0
            self._stale_arm_pending=False
            self._last_tick=None
            if self.bridge.connected:
                try:self.bridge.command('TWIN:OFF')
                except ConnectionError as e:self.last_error=str(e)
            self.storage.event('twin','info','Digital Twin đã dừng','ESP32 trở lại DYNAMIC nếu nhận TWIN:OFF')
        return self.snapshot()

    def set_scenario(self,scenario):
        if scenario not in SCENARIOS:raise ValueError('Kịch bản không hợp lệ')
        with self._lock:
            self.world.scenario=scenario
            self.world.test_inputs_locked=False
            self.storage.event('twin','info','Đổi kịch bản Digital Twin',scenario)
        return self.snapshot()

    def apply_test_preset(self, preset: str):
        """Start Digital Twin if necessary, publish genuine input; ESP32 remains authoritative.

        MQTT QoS0 publication is not proof of controller receipt or actuator movement.
        """
        if preset not in TEST_PRESETS:
            raise ValueError('Preset kiểm thử không hợp lệ')
        actual, fresh=self._fresh_latest()
        if not self.bridge.connected or not fresh:
            raise ConnectionError('MQTT/ESP32 chưa trực tuyến. Hãy chạy Wokwi và kiểm tra kết nối trước.')
        if actual.get('mode')=='PRESET':
            raise ValueError('ESP32 đang ở chế độ PRESET. Nhập D trong Serial Wokwi để trở về DYNAMIC.')
        if not self.running:
            self.enable('NORMAL')
        with self._lock:
            if self.last_preset == 'CUSTOM':
                try:self.bridge.command('DEMO:CUSTOM:END')
                except ConnectionError as e:self.last_error=str(e)
            if getattr(self,'_demo_marker_issued',False) and getattr(self,'preset_result',None)!='COMPLETED' and self.last_preset in ('BOTH_DRY','ONLY_Z2','SALTY_TANK','NO_SOURCE','REFILL','BOTH_WET'):
                try:self.bridge.command(f"DEMO:TC{['BOTH_DRY','ONLY_Z2','SALTY_TANK','NO_SOURCE','REFILL','BOTH_WET'].index(self.last_preset)+1:02d}:END")
                except ConnectionError as e:self.last_error=str(e)
            self._end_demo_permissions()
            self._demo_ended=False
            self._observed_zones=set()
            self._observed_preset_frame=False
            self._demo_last_attempt=0.0
            self._demo_pending_zones=({1,2} if preset in ("BOTH_DRY","SALTY_TANK","NO_SOURCE") else {2} if preset=="ONLY_Z2" else set())
            self._mute_until=0.0
            self.world.scenario='NORMAL'
            self._soil_test_original=None
            for field, value in TEST_PRESETS[preset].items():
                setattr(self.world,field,value)
            self.world.tank_salt_ppt=0.3
            self.last_preset=preset
            self.world.test_inputs_locked=True
            self._demo_marker_issued=False
            # Display marker must come from ESP32 only after a valid SGT2 frame.
            # MQTT ordering is preserved for publications on this same client.
            try:
                if hasattr(self.bridge, 'command'):
                    self.bridge.command(f"DEMO:TC{['BOTH_DRY','ONLY_Z2','SALTY_TANK','NO_SOURCE','REFILL','BOTH_WET'].index(preset)+1:02d}:START")
                self._demo_marker_issued=hasattr(self.bridge, 'command')
            except ConnectionError as e:self.last_error=str(e)
            self.preset_started_at=self.clock()
            self.preset_result="RUNNING"
            self.storage.event('twin','info','Áp dụng preset kiểm thử',
                               f'{preset}: đã gửi đầu vào mô phỏng; chờ xác nhận ESP32')
            self.step(initial=True)
            result=self.snapshot()
            result['delivery_status']='PUBLISHED_AWAITING_ESP32'
            return result

    def apply_custom_inputs(self, values: dict):
        """Use the existing TWIN transport for a custom simulation scenario.

        Does not command pumps or valves directly. The authoritative controller
        reacts to the SGT2 frame and continues publishing its own telemetry.
        """
        allowed = ('soil1_pct', 'soil2_pct', 'salinity_ppt', 'canal_pct', 'rain_pct', 'tank_l')
        limits = {'soil1_pct': (0., 100.), 'soil2_pct': (0., 100.),
                  'salinity_ppt': (0., 3.), 'canal_pct': (0., 100.),
                  'rain_pct': (0., 100.), 'tank_l': (0., 2000.)}
        if set(values) != set(allowed):
            raise ValueError('Cần cung cấp đủ 6 thông số mô phỏng')
        for key in allowed:
            val = values[key]
            if isinstance(val, bool) or not isinstance(val, (float, int)) or not math.isfinite(val):
                raise ValueError(f'Thông số {key} không hợp lệ')
            lo, hi = limits[key]
            if not lo <= val <= hi:
                raise ValueError(f'Thông số {key} phải từ {lo:g} đến {hi:g}')
        actual, fresh = self._fresh_latest()
        if not self.bridge.connected or not fresh:
            raise ConnectionError('Cần kết nối MQTT và ESP32 để áp dụng thông số')
        if actual.get('mode') == 'PRESET':
            raise ValueError('ESP32 đang ở PRESET nội bộ; nhập D trong Serial trước')
        if not self.running:
            self.enable('NORMAL')
        elif actual.get('mode') != 'TWIN':
            # The ESP32 can be switched back to LOCAL with Serial 'D' without
            # changing TwinService.running. Re-arm the controller explicitly
            # before sending CUSTOM markers and its new SGT2 frame.
            # MQTT publication is not proof of receipt; confirmation below
            # still requires fresh TWIN telemetry with a matching input frame.
            self.bridge.command('TWIN:ON')
        with self._lock:
            was_custom=(self.last_preset == 'CUSTOM')
            self._end_demo_permissions()
            self._mute_until = 0.0
            self._stale_arm_pending=False
            self._demo_ended = False
            self.world.scenario = 'NORMAL'
            self.world.test_inputs_locked = True
            self.last_preset = 'CUSTOM'
            self._custom_hold_until = self.clock() + 5.0
            self.preset_result = 'RUNNING'
            self.preset_started_at = self.clock()
            self._demo_marker_issued = False
            self._observed_preset_frame = False
            # CUSTOM uses the same one-time permission bridge as presets.
            # Request permission for both zones; only ESP32 decides whether a
            # zone needs water from its independently stored soil thresholds.
            self._demo_pending_zones = {1,2}
            self._custom_apply_requested_at = self.clock()
            self._custom_apply_rx_baseline = actual.get('twin_rx_count')
            self._demo_last_attempt = 0.0
            self._observed_zones = set()
            for key in allowed:
                setattr(self.world, key, bounded(float(values[key]), *limits[key]))
            self.storage.event('twin', 'info', 'Thiết lập môi trường tùy chỉnh',
                               'Đã gửi đầu vào mô phỏng; chờ ESP32 xác nhận rồi xét cấp quyền tưới thử ngoài giờ')
            # Serial markers are requested, but successful delivery still requires
            # the ESP32 to receive the following SGT2 input frame.
            try:
                self.bridge.command('DEMO:CUSTOM:UPDATE' if was_custom else 'DEMO:CUSTOM:START')
            except ConnectionError as e:
                self.last_error=str(e)
        self.step(initial=True)
        result = self.snapshot()
        result['delivery_status'] = 'PUBLISHED_AWAITING_ESP32'
        return result

    def test_stale_input(self):
        """Run TC07 from either LOCAL or SIMULATION, without a second test button.

        In LOCAL mode, first switch the device into TWIN and wait for a fresh
        TWIN telemetry frame before arming the 22-second interruption.
        """
        actual, fresh=self._fresh_latest()
        if not self.bridge.connected or not fresh:
            raise ConnectionError('Cần MQTT và ESP32 trực tuyến để thử TC07')
        if actual.get('mode')=='PRESET':
            raise ValueError('ESP32 đang ở PRESET nội bộ; nhập D trong Serial trước')
        if not self.running:
            self.enable('NORMAL')
        with self._lock:
            if self.last_preset == 'CUSTOM':
                try:self.bridge.command('DEMO:CUSTOM:END')
                except ConnectionError as e:self.last_error=str(e)
            self._end_demo_permissions()
            now=self.clock()
            self.last_preset='STALE_INPUT'
            self.preset_result='RUNNING'
            self.preset_started_at=now
            self._stale_observed=False
            self._stale_log_closed=False
            self._stale_arm_pending=actual.get('mode')!='TWIN'
            self._stale_requested_at=now
            if not self._stale_arm_pending:
                self._arm_stale_test(now)
            else:
                self._mute_until=0.0
                self.storage.event('twin','info','TC07 đang chuẩn bị',
                                   'Chờ ESP32 vào chế độ TWIN trước khi tạm dừng dữ liệu')
            return self.snapshot()

    def _arm_stale_test(self, now):
        self._stale_arm_pending=False
        self._mute_until=now+120.0
        try:self.bridge.command('DEMO:TC07:START')
        except (ConnectionError,AttributeError) as e:self.last_error=str(e)
        self.storage.event('twin','warning','Thử mất dữ liệu TWIN',
                           'Tạm ngừng đến khi ESP32 xác nhận TWIN_INPUT_STALE; tự phục hồi, tối đa 120 giây thực')

    def resume_test_input(self):
        with self._lock:
            if self.last_preset=='STALE_INPUT':
                try:self.bridge.command('DEMO:TC07:END')
                except (ConnectionError,AttributeError) as e:self.last_error=str(e)
            self._mute_until=0.0
            self._stale_arm_pending=False
            if self.last_preset=='STALE_INPUT':
                self.preset_result='COMPLETED' if getattr(self,'_stale_observed',False) else 'NOT_VERIFIED'
            if self.running:
                self.step(initial=True)
            return self.snapshot()

    def prepare_fill_test(self):
        """Technical-only repeatable test fixture, not an agricultural control command."""
        with self._lock:
            actual, fresh=self._fresh_latest()
            if not self.running or not self.bridge.connected or not fresh or actual.get('mode')!='TWIN':
                raise ConnectionError('Chỉ chuẩn bị thử nạp bồn khi Digital Twin và ESP32 TWIN trực tuyến')
            self.world.scenario='NORMAL'
            self.world.soil1_pct=75.0
            self.world.soil2_pct=75.0
            self.world.tank_l=500.0
            self.world.tank_salt_ppt=0.3
            self.world.salinity_ppt=0.5
            self.world.canal_pct=80.0
            self.world.rain_pct=0.0
            self.storage.event('twin','info','Chuẩn bị kiểm thử nạp bồn',
                              'Đặt độ ẩm 75% mỗi vùng, bồn 500 L trên dung tích 2.000 L; chỉ là dữ liệu mô phỏng')
            self.step(initial=True)
            return self.snapshot()

    def prepare_irrigation_priority_test(self):
        """Technical-only: create urgent soil demand while a simulated fill may be running."""
        with self._lock:
            actual,fresh=self._fresh_latest()
            if not self.running or not self.bridge.connected or not fresh or actual.get('mode')!='TWIN':
                raise ConnectionError('Chỉ kiểm thử ưu tiên tưới khi Digital Twin và ESP32 TWIN trực tuyến')
            self.world.soil1_pct=20.0
            self.world.canal_pct=80.0
            self.world.salinity_ppt=0.5
            self.storage.event('twin','info','Kiểm thử tưới ưu tiên','Gây nhu cầu tưới Z1 trong mô hình')
            self.step(initial=True)
            return self.snapshot()


    def prepare_soil_alert_test(self, config: dict):
        """Induce alarms in Python-only EC/pH/Na channels; NEVER change irrigation.

        Thresholds must have been set manually by an administrator. Saves current
        values for later restore. Does not publish any soil chemistry to ESP32.
        """
        with self._lock:
            if not self.running:
                raise ValueError('Cần bật Digital Twin trước khi thử cảnh báo đất')
            fields=('soil_ec_z1_ds_m','soil_ec_z2_ds_m', 'soil_ph_z1','soil_ph_z2',
                    'soil_na_z1_mg_kg','soil_na_z2_mg_kg')
            if self._soil_test_original is None:
                self._soil_test_original={k:getattr(self.world,k) for k in fields}
            # Restore previous values first; repeated test presses are idempotent.
            for k,v in self._soil_test_original.items():
                setattr(self.world,k,v)
            count=0
            for i,z in enumerate(config['zones'],1):
                lim=z.get('soil_ec_max')
                if lim is not None and lim<20:
                    setattr(self.world,f'soil_ec_z{i}_ds_m',bounded(lim+0.25,0,20)); count+=1
                lim=z.get('soil_na_max')
                if lim is not None and lim<100000:
                    setattr(self.world,f'soil_na_z{i}_mg_kg',bounded(lim+5,0,100000)); count+=1
                phmin=z.get('soil_ph_min'); phmax=z.get('soil_ph_max')
                if phmin is not None and phmin>0:
                    setattr(self.world,f'soil_ph_z{i}',bounded(phmin-0.3,0,14));count+=1
                elif phmax is not None and phmax<14:
                    setattr(self.world,f'soil_ph_z{i}',bounded(phmax+0.3,0,14));count+=1
            if count==0:
                for k,v in self._soil_test_original.items():setattr(self.world,k,v)
                self._soil_test_original=None
                raise ValueError('Hãy cấu hình ít nhất một ngưỡng đất có thể kiểm thử tại mục Cấu hình')
            self.storage.event('twin','info','Bắt đầu kiểm thử cảnh báo đất',
                               'Chỉ thay đổi các chỉ số đất mô phỏng; không điều khiển bơm hoặc van')
            self.step(initial=True)
            return self.snapshot()

    def restore_soil_alert_test(self):
        with self._lock:
            if not self.running or self._soil_test_original is None:
                raise ValueError('Không có tình huống cảnh báo đất đang cần khôi phục')
            for k,v in self._soil_test_original.items():
                setattr(self.world,k,v)
            self._soil_test_original=None
            self.storage.event('twin','info','Khôi phục chỉ số đất sau kiểm thử',
                               'Chỉ số trở về giá trị lưu trước kiểm thử; không có thao tác canh tác thực tế')
            self.step(initial=True)
            return self.snapshot()

    def step(self,initial=False):
        with self._lock:
            if not self.running:return None
            now=self.clock()
            dt=0 if initial else min(5.,max(0., now-(self._last_tick or now)))
            self._last_tick=now
            actual,fresh=self._fresh_latest()
            if getattr(self,'_stale_arm_pending',False) and fresh and actual.get('mode')=='TWIN' and actual.get('received_at',0)>self._stale_requested_at:
                self._arm_stale_test(now)
            # Briefly hold newly applied CUSTOM input steady so the controller can observe
            # the requested values before simulated irrigation changes soil/tank.
            if self.last_preset == 'CUSTOM' and now < getattr(self, '_custom_hold_until', 0):
                dt = 0.0
            frame=self.world.advance(dt,actual,fresh)
            if self.last_preset=='STALE_INPUT' and getattr(self,'_stale_log_closed',False) is False and self._mute_until>0 and now>=self._mute_until:
                try:self.bridge.command('DEMO:TC07:END')
                except (ConnectionError,AttributeError) as e:self.last_error=str(e)
                self._stale_log_closed=True
                self.preset_result='COMPLETED' if getattr(self,'_stale_observed',False) else 'NOT_VERIFIED'
            if self.last_preset=='STALE_INPUT' and getattr(self,'preset_result',None)=='RUNNING' and fresh and actual.get('mode')=='TWIN' and actual.get('state')=='HOLD_NO_WATER' and actual.get('reason')=='TWIN_INPUT_STALE':
                if not getattr(self,'_stale_observed',False):
                    # Allow telemetry to report the fail-safe state before resuming.
                    self._mute_until=min(self._mute_until,now+5.0)
                self._stale_observed=True
            # CUSTOM must first be acknowledged via fresh, matching SGT2
            # telemetry. Presets retain their existing eligibility checks.
            if getattr(self,'preset_result',None)=='RUNNING':
                if self.last_preset in TEST_PRESETS:
                    self._tick_demo_permissions(actual,fresh,now)
                elif self.last_preset=='CUSTOM' and self._custom_frame_confirmed(actual,now):
                    self._tick_demo_permissions(actual,fresh,now)
            if getattr(self,'preset_result',None)=='RUNNING' and fresh and self.last_preset in TEST_PRESETS:
                ps=self.last_preset; state=str(actual.get('state') or '')
                source=actual.get('source')
                # Require telemetry values consistent with the applied test frame.
                # This prevents stale prior-state telemetry from passing the next preset.
                mode_ok=actual.get('mode')=='TWIN'
                salinity=actual.get('salinity_ppt')
                tank=actual.get('tank_l')
                frame_ok=(mode_ok and isinstance(salinity,(int,float)) and isinstance(tank,(int,float))
                          and abs(salinity-TEST_PRESETS[ps]['salinity_ppt'])<=0.11
                          and (ps=='REFILL' or abs(tank-TEST_PRESETS[ps]['tank_l'])<=80))
                if frame_ok and actual.get('pump_on') is True and actual.get('zone') in (1,2):
                    self._observed_zones.add(actual.get('zone'))
                passed=frame_ok and (
                    (ps=='BOTH_DRY' and self._observed_zones=={1,2}) or
                    (ps=='ONLY_Z2' and actual.get('zone')==2 and actual.get('pump_on') is True and 1 not in self._observed_zones) or
                    (ps=='SALTY_TANK' and source=='TANK' and actual.get('pump_on') is True and actual.get('canal_safe') is False) or
                    (ps=='NO_SOURCE' and state=='HOLD_NO_WATER' and actual.get('canal_safe') is False and actual.get('tank_ok') is False and actual.get('pump_on') is False) or
                    (ps=='REFILL' and state=='REFILL_TANK' and actual.get('tank_fill_on') is True and actual.get('pump_on') is False) or
                    (ps=='BOTH_WET' and state=='IDLE' and actual.get('pump_on') is False and actual.get('soil1_pct',0)>=60 and actual.get('soil2_pct',0)>=60))
                if passed:
                    self.preset_result='OBSERVED'
                    self.storage.event('twin','info','Preset đạt trạng thái quan sát',str(ps))
            if getattr(self,'preset_result',None)=='OBSERVED' and getattr(self,'preset_started_at',None) is not None and now-self.preset_started_at >= (40 if self.last_preset in ('BOTH_DRY','ONLY_Z2','SALTY_TANK') else 20):
                # Demo finishes by removing the artificial water demand, without bypassing ESP32 control.
                if self.last_preset in ('BOTH_DRY','ONLY_Z2','SALTY_TANK','NO_SOURCE'):
                    self.world.soil1_pct=75.0;self.world.soil2_pct=75.0
                self.preset_result='COMPLETED'
                self.world.test_inputs_locked=False
                if getattr(self,'_demo_marker_issued',False):
                    try:self.bridge.command(f"DEMO:TC{['BOTH_DRY','ONLY_Z2','SALTY_TANK','NO_SOURCE','REFILL','BOTH_WET'].index(self.last_preset)+1:02d}:END")
                    except ConnectionError as e:self.last_error=str(e)
                self._end_demo_permissions()
                self.storage.event('twin','info','Đã kết thúc preset demo',str(self.last_preset)+'; theo dõi bộ điều khiển trở về trạng thái chờ')

            frame['ts']=now
            frame['origin']='PYTHON_DIGITAL_TWIN_MODEL'
            # Database persists virtual values separately from ESP32 telemetry.
            self.storage.record_twin(frame)
            self.last_step=now
            self.storage.sync_soil_alerts(soil_alerts(self.storage.get_farm_config(),frame))
            if self.bridge.connected and now >= self._mute_until:
                try:
                    self.bridge.publish_twin(self.world.wire_input())
                    self.last_publish=now
                    self.last_error=None
                except ConnectionError as e:self.last_error=str(e)
            elif not self.bridge.connected:self.last_error='Broker MQTT ngoại tuyến; ESP32 sẽ tự ngừng tưới nếu dữ liệu quá hạn'
            return frame

    def snapshot(self):
        with self._lock:
            actual,fresh=self._fresh_latest()
            return {'running':self.running,'scenario':self.world.scenario,
               'world':asdict(self.world),'actual_mode':actual.get('mode') if fresh else None,
               'actual_state':actual.get('state') if fresh else None,
               'actual_source':actual.get('source') if fresh else None,
               'actual_zone':actual.get('zone') if fresh else None,
               'actual_pump_on':actual.get('pump_on') if fresh else None,
               'actual_master_enabled':actual.get('master_enabled') if fresh else None,
               'esp_online':fresh,'broker_connected':self.bridge.connected,
               'last_publish':self.last_publish,'last_step':self.last_step,
               'soil_test_active':self._soil_test_original is not None,'error':self.last_error,
               'last_preset':self.last_preset,'preset_result':getattr(self,'preset_result',None),
               'stale_arm_pending':bool(getattr(self,'_stale_arm_pending',False)),
               'demo_permission_pending':sorted(self._demo_pending_zones),
               'demo_permission_issued':sorted(self._demo_permission_zones),'twin_publish_paused':self.running and self.clock()<self._mute_until,
               'twin_publish_pause_remaining_s':round(max(0,self._mute_until-self.clock()),1),
               'warning':'pH, EC đất, Na đất, chất lượng nước bồn và lưu lượng là số liệu MÔ PHỎNG, không phải cảm biến hay khuyến cáo cải tạo đất.'}
