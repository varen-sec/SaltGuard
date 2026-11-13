"""SaltGuard 2.5.1 Farmer Dashboard, local-only web app + MQTT + SQLite."""
from __future__ import annotations

import logging
import asyncio
import csv
import io
import os
import re
import time
import uuid
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .mqtt_service import MqttService, ALLOWED_COMMANDS
from .storage import Storage
from . import access
from .data_quality import evaluate, advice_for
from urllib.parse import quote
from .twin import TwinService, SCENARIOS

BASE = Path(__file__).resolve().parent
DEFAULT_DB = str(BASE.parent / 'data' / 'saltguard.db')
ROOT = os.getenv('SALTGUARD_TOPIC_ROOT', 'saltguard/demo/sgfarm-19cadbfde5').strip().strip('/')
if not re.fullmatch(r'[A-Za-z0-9_/-]{1,140}', ROOT):
    raise RuntimeError('SALTGUARD_TOPIC_ROOT chứa ký tự không hợp lệ')
BROKER = os.getenv('SALTGUARD_MQTT_HOST', 'broker.emqx.io')
PORT = int(os.getenv('SALTGUARD_MQTT_PORT', '1883'))
DB = os.getenv('SALTGUARD_DB', DEFAULT_DB)
logger = logging.getLogger('saltguard')

storage = Storage(DB)
bridge = MqttService(storage, BROKER, PORT, ROOT)
twin=TwinService(bridge,storage)
# Backend only confirms a save after ESP32 publishes a *new* matching telemetry frame.
soil_sync_pending_since=0.0
zone_schedule_lock=threading.RLock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.retire_schedules()  # legacy scheduled tasks are DISABLED, not merely hidden
    bridge.start()
    twin.start_background()
    async def track_alerts():
        while True:
            try:
                await asyncio.to_thread(farmer_summary)
                await asyncio.to_thread(reconcile_timed_holds)
            except Exception:
                logger.exception('Background notification check failed')
            await asyncio.sleep(5)
    monitor = asyncio.create_task(track_alerts())
    try:
        yield
    finally:
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass
        twin.shutdown()
        bridge.stop()
        storage.close()

app = FastAPI(title='SaltGuard MVP 1.1', docs_url='/api/docs', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=str(BASE / 'static')), name='static')

@app.middleware('http')
async def advanced_guard(request: Request, call_next):
    path=request.url.path
    if path in {'/expert','/lab','/technical/advanced','/static/expert.html','/static/lab.html','/static/index.html'} and not access.authenticated(request):
        target = '/expert' if path.startswith('/static/expert') else ('/lab' if path.startswith('/static/lab') else ('/technical/advanced' if path.startswith('/static/index') else path))
        return RedirectResponse('/advanced-login?next='+quote(target, safe=''),status_code=303)
    if request.method in {'POST','PATCH','PUT','DELETE'} and (path == '/api/farm/config' or path.startswith('/api/twin/')) and not access.authenticated(request):
        return JSONResponse(status_code=403,content={'detail':'Cần nhập PIN trong Cài đặt nâng cao.'})
    return await call_next(request)

class PinPayload(BaseModel):
    pin: str

@app.get('/advanced-login')
def advanced_login():
    return FileResponse(BASE / 'static' / 'advanced-login.html')

@app.get('/api/advanced/session')
def advanced_session(request:Request):
    return {'authorized':access.authenticated(request)}

@app.post('/api/advanced/login')
def advanced_login_post(body:PinPayload, request:Request):
    ip=request.client.host if request.client else 'local'
    token, wait=access.verify(body.pin,ip)
    if not token:
        raise HTTPException(429 if wait else 401,
            'Nhập sai quá nhiều lần. Thử lại sau 60 giây.' if wait else 'Mã PIN chưa đúng.')
    response=JSONResponse({'authorized':True,'next':'/expert'})
    response.set_cookie('sg_advanced',token,max_age=access.SESSION_SECONDS,
                        httponly=True,samesite='lax',secure=False,path='/')
    return response

@app.post('/api/advanced/logout')
def advanced_logout(request:Request):
    access.revoke(request)
    response=JSONResponse({'authorized':False})
    response.delete_cookie('sg_advanced',path='/')
    return response


class CommandPayload(BaseModel):
    command: str

@app.get('/')
def index():
    return FileResponse(BASE / 'static' / 'farmer.html')

@app.get('/technical')
def technical():
    # Legacy address retained for existing bookmarks.
    return RedirectResponse('/expert', status_code=302)

@app.get('/expert')
def expert():
    return FileResponse(BASE / 'static' / 'expert.html')

@app.get('/activity')
def activity_page():
    return FileResponse(BASE / 'static' / 'activity.html')

@app.get('/lab')
def lab():
    return FileResponse(BASE / 'static' / 'lab.html')

@app.get('/technical/advanced')
def technical_advanced():
    return FileResponse(BASE / 'static' / 'index.html')

@app.get('/api/snapshot')
def snapshot():
    latest = storage.latest()
    age = max(0, time.time() - latest['received_at']) if latest else None
    # Telemetry is normally published at 3-second intervals; consider it stale after 18 s.
    return {
        'latest': latest, 'age_seconds': age,
        'device_online': bool(latest and age < 18),
        'broker_connected': bridge.connected,
        'esp_status': bridge.last_status,
        'last_ack': bridge.last_ack,
        'mqtt_error': bridge.error,
        'topic_root': ROOT,
        'broker': BROKER + ':' + str(PORT),
        'server_time': time.time(),
        'simulation_only': True,
    }

class TimedHoldPayload(BaseModel):
    minutes: int


def reconcile_timed_holds(now=None):
    """Only resume a hold we installed, after telemetry confirmed it.

    A lost broker publish is not ACK. A non-timed farmer action cancels the schedule.
    """
    with zone_schedule_lock:
        now=time.time() if now is None else now
        latest=storage.latest()
        age=now-latest['received_at'] if latest else 999999
        if not bridge.connected or not latest or age>=18:return
        for hold in storage.timed_holds():
            zone=hold['zone'];flag=bool(latest.get('zone'+str(zone)+'_hold'))
            cmd='ZONE:'+str(zone)+':HOLD' if hold['status']=='PENDING_HOLD' else 'ZONE:'+str(zone)+':RESUME'
            ack=bridge.last_ack or {}
            if hold['status']=='PENDING_HOLD':
                if flag and ack.get('command')=='ZONE:'+str(zone)+':HOLD' and ack.get('accepted'):
                    storage.timed_hold_update(zone,hold['request_id'],'ACTIVE')
                elif now-hold['created_at']>90:
                    # Never infer it succeeded from MQTT publish alone.
                    storage.timed_hold_update(zone,hold['request_id'],'UNCERTAIN')
            elif hold['status']=='ACTIVE' and now>=hold['until_ts']:
                if not flag:
                    storage.timed_hold_delete(zone)
                else:
                    try:
                        bridge.command('ZONE:'+str(zone)+':RESUME')
                        storage.timed_hold_update(zone,hold['request_id'],'PENDING_RESUME')
                    except ConnectionError:pass
            elif hold['status']=='PENDING_RESUME':
                if not flag and ack.get('command')=='ZONE:'+str(zone)+':RESUME' and ack.get('accepted'):
                    storage.timed_hold_delete(zone)
                elif ack.get('command')=='ZONE:'+str(zone)+':RESUME' and ack.get('accepted') is False:
                    storage.timed_hold_update(zone,hold['request_id'],'UNCERTAIN')
                elif (hold['last_attempt'] or 0)+25<now and flag:
                    try:
                        bridge.command('ZONE:'+str(zone)+':RESUME')
                        storage.timed_hold_update(zone,hold['request_id'],'PENDING_RESUME')
                    except ConnectionError:pass

@app.get('/api/monitoring')
def monitoring():
    snap=snapshot()
    return {'quality':evaluate(snap['latest'],snap['age_seconds'],snap['broker_connected']),
            'holds':storage.timed_holds(),'server_time':time.time()}

class AutoIrrigationPayload(BaseModel):
    action: str
    minutes: int | None = None

@app.post('/api/zones/{zone}/automatic')
def set_zone_automatic(zone:int, body:AutoIrrigationPayload):
    """One farmer control: resume, manual hold or time-limited hold.

    Timed records are canceled/replaced under the same lock as reconciliation.
    A queued MQTT publish is never presented as confirmed actuation.
    """
    if zone not in (1,2):
        raise HTTPException(400,'Chỉ hỗ trợ vùng 1 hoặc 2')
    if body.action not in ('resume','hold_manual','hold_timed'):
        raise HTTPException(400,'Lựa chọn tưới tự động không hợp lệ')
    if body.action=='hold_timed' and body.minutes not in (15,30,60,120,240,1440):
        raise HTTPException(400,'Thời hạn không hợp lệ')
    with zone_schedule_lock:
        snap=snapshot()
        if not snap['device_online'] or not snap['broker_connected']:
            raise HTTPException(503,'Thiết bị chưa kết nối; chưa thể xác nhận trạng thái tưới')
        current=snap['latest'] or {}
        held=bool(current.get(f'zone{zone}_hold'))
        old=next((h for h in storage.timed_holds() if h['zone']==zone),None)
        if body.action=='resume':
            if not held and not old:
                return {'status':'ALREADY_ON','confirmed':True,'zone':zone}
            try:
                if held:bridge.command(f'ZONE:{zone}:RESUME')
            except (ConnectionError,ValueError) as err:
                raise HTTPException(503,str(err)) from err
            # Never retain an old timer which could later issue a second RESUME.
            storage.timed_hold_delete(zone)
            return {'status':'PENDING_RESUME' if held else 'ALREADY_ON','confirmed':not held,'zone':zone}
        if body.action=='hold_manual':
            if held:
                # Switch from timed -> indefinite without re-sending HOLD.
                storage.timed_hold_delete(zone)
                return {'status':'HELD_MANUAL','confirmed':True,'zone':zone}
            try:bridge.command(f'ZONE:{zone}:HOLD')
            except (ConnectionError,ValueError) as err:
                raise HTTPException(503,str(err)) from err
            storage.timed_hold_delete(zone)
            return {'status':'PENDING_HOLD','confirmed':False,'zone':zone}
        # hold_timed: replace any previous schedule; if already held,
        # do not send a redundant HOLD or lose the verified state.
        if not held:
            try:bridge.command(f'ZONE:{zone}:HOLD')
            except (ConnectionError,ValueError) as err:
                raise HTTPException(503,str(err)) from err
        until=time.time()+body.minutes*60
        request_id=uuid.uuid4().hex
        storage.timed_hold_set(zone,until,request_id)
        if held:storage.timed_hold_update(zone,request_id,'ACTIVE')
        return {'status':'ACTIVE' if held else 'PENDING_HOLD',
                'confirmed':held,'zone':zone,'until_ts':until}

@app.post('/api/zones/{zone}/timed-hold')
def timed_hold(zone:int,body:TimedHoldPayload):
    """Backward-compatible endpoint; same state machine as the single switch."""
    return set_zone_automatic(zone,AutoIrrigationPayload(action='hold_timed',minutes=body.minutes))

@app.get('/api/farm/trends')
def farmer_trends(days:int=Query(1)):
    if days not in (1,7,30):
        raise HTTPException(400,'Chọn 1, 7 hoặc 30 ngày')
    return {'days':days,'data':storage.trends(days,120),'simulation_only':True}

@app.get('/api/farm/preferences')
def farm_preferences():
    return storage.get_app_preferences()

class FarmPreferencesPayload(BaseModel):
    farm_name: str

@app.patch('/api/farm/preferences')
def farm_preferences_save(body:FarmPreferencesPayload):
    try:return storage.set_app_preferences(body.farm_name)
    except ValueError as err:raise HTTPException(400,str(err)) from err

@app.get('/api/history')
def history(minutes: int = Query(30, ge=1, le=10080), limit: int = Query(320, ge=1, le=1500)):
    return {'minutes': minutes, 'data': storage.history(minutes, limit)}

@app.get('/api/notifications')
def notifications(limit: int=Query(35,ge=1,le=500),offset:int=Query(0,ge=0)):
    return {'items':storage.notifications(limit,offset),
            'total':storage.notification_count(), 'limit':limit,'offset':offset}

@app.get('/api/events')
def events(limit: int = Query(60, ge=1, le=200)):
    return {'events': storage.events(limit)}

@app.get('/api/activity/report')
def activity_report(days:int=Query(7),zone:int=Query(0)):
    if days not in (1,7,30) or zone not in (0,1,2):
        raise HTTPException(400,'Chọn 1/7/30 ngày và vùng 0/1/2')
    return {'summary':storage.activity_report(days,zone),
            'segments':storage.activity_segments(days,zone,500),
            'trends':storage.trends(days,180),'water_daily':storage.activity_water_daily(days,zone),'simulation_only':True,
            'volume_measured':False}

@app.get('/api/activity/export.csv')
def activity_csv(days:int=Query(7),zone:int=Query(0)):
    """UTF-8 BOM, RFC 4180 CSV, ISO 8601 timestamps in Vietnam timezone.

    Durations are valid only when ESP32 reported a completed segment. Unverified
    durations remain empty, never zero or a fabricated estimate.
    """
    if days not in (1,7,30) or zone not in (0,1,2):
        raise HTTPException(400,'Chọn 1/7/30 ngày và vùng 0/1/2')
    tz=ZoneInfo('Asia/Ho_Chi_Minh')
    def iso(ts):
        return datetime.fromtimestamp(float(ts),tz=tz).isoformat(timespec='seconds') if ts is not None else ''
    def number(v):
        return '' if v is None else v
    # CSV cells must not allow spreadsheet formulas when opened in Excel.
    def safe_text(v):
        value=str(v or '')
        return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
    out=io.StringIO(newline='')
    writer=csv.writer(out,dialect='excel',lineterminator='\r\n')
    writer.writerow(['segment_id','started_at_iso8601','ended_at_iso8601',
                     'zone','water_source','duration_seconds','status',
                     'end_reason','soil_start_pct','soil_end_pct','estimated_water_l','water_quality'])
    for r in storage.activity_segments(days,zone,1000):
        writer.writerow([r['id'],iso(r['started_at']),iso(r['ended_at']),
                         r['zone'],r['source'],number(r['duration_sim_seconds']),
                         r['status'],safe_text(r['end_reason']),
                         number(r['start_soil_pct']),number(r['end_soil_pct']),number(r['water_estimated_l']),safe_text(r['water_quality'])])
    data='\ufeff'+out.getvalue()
    return Response(data,media_type='text/csv; charset=utf-8',headers={
       'Content-Disposition':f'attachment; filename="saltguard_nhat_ky_{days}ngay_vung{zone}.csv"',
       'Cache-Control':'no-store'})

@app.post('/api/command')
def command(body: CommandPayload, request: Request):
    cmd = body.command.strip().upper()
    if cmd not in ALLOWED_COMMANDS and not (re.fullmatch(r'HOURS:(?:[0-9]{4},){3}[0-9]{4}',cmd) or re.fullmatch(r'SOIL:(?:[0-9]{1,2},){3}[0-9]{1,2}',cmd) or re.fullmatch(r'WATER:(?:[0-9]{1,4},){3}[0-9]{1,4}',cmd) or re.fullmatch(r'WIN:(?:[01],[0-9]{1,4},[0-9]{1,4})(?:;[01],[0-9]{1,4},[0-9]{1,4}){0,3}',cmd)):
        raise HTTPException(400,'Lệnh không được hỗ trợ trong SaltGuard MVP')
    # User-facing actions may be used without specialist PIN; all other commands are restricted.
    farmer_command = (cmd == 'EMERGENCY:STOP' or cmd.startswith(('HOURS:','WIN:'))
                      or re.fullmatch(r'ZONE:[12]:(?:HOLD|RESUME|ONCE)',cmd) is not None
                      or cmd in {'FILL:REQUEST','FILL:CANCEL','FILL:AUTO:ON','FILL:AUTO:OFF'})
    if not farmer_command and not access.authenticated(request):
        raise HTTPException(403,'Cần PIN để gửi lệnh kỹ thuật.')
    try:
        with zone_schedule_lock:
            result=bridge.command(cmd)
            if re.fullmatch(r'ZONE:[12]:(?:HOLD|RESUME)',cmd):
                storage.timed_hold_delete(int(cmd.split(':')[1]))
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

@app.get('/api/health')
def health():
    return {'ok': True, 'broker_connected': bridge.connected, 'topic_root': ROOT}


class TwinRequest(BaseModel):
    scenario: str = 'NORMAL'

@app.get('/api/twin')
def twin_status():
    return twin.snapshot()

@app.get('/api/twin/history')
def twin_history(limit: int = Query(200, ge=1, le=1000)):
    return {'data': storage.twin_history(limit)}

@app.post('/api/twin/start')
def twin_start(body: TwinRequest):
    try:return twin.enable(body.scenario.strip().upper())
    except ValueError as e:raise HTTPException(400,str(e)) from e
    except ConnectionError as e:raise HTTPException(503,str(e)) from e

@app.post('/api/twin/lab/prepare-refill')
def twin_prepare_refill():
    try:return twin.prepare_fill_test()
    except ConnectionError as e:raise HTTPException(503,str(e)) from e

@app.post('/api/twin/lab/prepare-irrigation')
def twin_prepare_irrigation():
    try:return twin.prepare_irrigation_priority_test()
    except ConnectionError as e:raise HTTPException(503,str(e)) from e


class TwinPresetRequest(BaseModel):
    preset: str

@app.post('/api/twin/lab/preset')
def twin_lab_preset(body: TwinPresetRequest):
    try:return twin.apply_test_preset(body.preset.strip().upper())
    except ValueError as e:raise HTTPException(400,str(e)) from e
    except ConnectionError as e:raise HTTPException(503,str(e)) from e

class CustomSimInputs(BaseModel):
    soil1_pct: float
    soil2_pct: float
    salinity_ppt: float
    canal_pct: float
    rain_pct: float
    tank_l: float

@app.post('/api/twin/lab/custom')
def twin_lab_custom(body: CustomSimInputs):
    try:
        return twin.apply_custom_inputs(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except ConnectionError as e:
        raise HTTPException(503, str(e)) from e

@app.post('/api/twin/lab/test-stale')
def twin_lab_test_stale():
    try:return twin.test_stale_input()
    except ConnectionError as e:raise HTTPException(503,str(e)) from e

@app.post('/api/twin/lab/resume-input')
def twin_lab_resume_input():
    return twin.resume_test_input()

@app.post('/api/twin/lab/soil-warning')
def twin_soil_warning():
    try:
        return twin.prepare_soil_alert_test(storage.get_farm_config())
    except (ValueError, ConnectionError) as e:
        raise HTTPException(400, str(e)) from e

@app.post('/api/twin/lab/soil-restore')
def twin_soil_restore():
    try:
        return twin.restore_soil_alert_test()
    except (ValueError, ConnectionError) as e:
        raise HTTPException(400, str(e)) from e

@app.post('/api/twin/stop')
def twin_stop():
    return twin.disable()

@app.post('/api/twin/scenario')
def twin_scenario(body: TwinRequest):
    try:return twin.set_scenario(body.scenario.strip().upper())
    except ValueError as e:raise HTTPException(400,str(e)) from e


# FARMER EXPERIENCE -- summary and alerts, with no agronomic treatment advice.
from typing import Optional, Literal
from pydantic import Field

class ZoneConfig(BaseModel):
    name: str = Field(min_length=1,max_length=36)
    crop: str = Field(min_length=1,max_length=60)
    soil_ec_max: Optional[float] = Field(default=None, ge=0, le=20)
    soil_ph_min: Optional[float] = Field(default=None, ge=0, le=14)
    soil_ph_max: Optional[float] = Field(default=None, ge=0, le=14)
    soil_na_max: Optional[float] = Field(default=None, ge=0, le=100000)
    irrigation_mode: Literal["MOISTURE"] = "MOISTURE"
    soil_high_warn_pct: Optional[float] = Field(default=None, ge=0, le=100)
    soil_type: str = Field(default='Chưa thiết lập', min_length=1, max_length=60)
    growth_stage: str = Field(default='Chưa thiết lập', min_length=1, max_length=60)
    soil_start_pct: int = Field(default=35, ge=5, le=80)
    soil_stop_pct: int = Field(default=60, ge=10, le=95)

class FarmConfigPayload(BaseModel):
    zones: list[ZoneConfig] = Field(min_length=2,max_length=2)

from .alerts import soil_alerts

@app.get('/api/farm/config')
def farm_config_get():
    return storage.get_farm_config()

class CropProfilePayload(BaseModel):
    crop: str = Field(min_length=1,max_length=60)
    soil_type: str = Field(min_length=1,max_length=60)
    growth_stage: str = Field(min_length=1,max_length=60)
    soil_start_pct: int = Field(ge=5,le=80)
    soil_stop_pct: int = Field(ge=10,le=95)

@app.get('/api/farm/profiles')
def crop_profiles_get():
    return {'items':storage.list_crop_profiles(),'simulation_only':True}

@app.post('/api/farm/profiles')
def crop_profiles_save(body:CropProfilePayload,request:Request):
    if not access.authenticated(request):
        raise HTTPException(403,'Cần PIN chuyên môn để lưu hồ sơ cây trồng')
    if body.soil_stop_pct-body.soil_start_pct<5:
        raise HTTPException(400,'Ngưỡng dừng phải cao hơn ngưỡng bắt đầu ít nhất 5%')
    return storage.save_crop_profile(body.model_dump())

@app.get('/api/farm/config/sync')
def farm_config_sync():
    cfg=storage.get_farm_config()
    live=storage.latest()
    age=time.time()-live['received_at'] if live else float('inf')
    if not live or age>=18:
        return {'status':'OFFLINE','synced':False,'note':'Không có telemetry mới từ ESP32'}
    keys=('soil_start_z1','soil_stop_z1','soil_start_z2','soil_stop_z2')
    if not all(isinstance(live.get(k),int) for k in keys):
        return {'status':'UNKNOWN','synced':False,'note':'Firmware chưa phản hồi cấu hình Phase 4.0'}
    if soil_sync_pending_since and live['received_at'] <= soil_sync_pending_since:
        return {'status':'PENDING','synced':False,'note':'Đang chờ ESP32 phát telemetry sau lệnh cập nhật'}
    expected=[v for z in cfg['zones'] for v in (z['soil_start_pct'],z['soil_stop_pct'])]
    actual=[live[k] for k in keys]
    return {'status':'SYNCED' if actual==expected else 'MISMATCH',
            'synced':actual==expected,'expected':expected,'actual':actual,
            'note':'So sánh ngưỡng đã lưu với telemetry ESP32 mới'}

@app.post('/api/farm/config')
def farm_config_save(body: FarmConfigPayload):
    data=body.model_dump()
    existing=storage.get_farm_config()
    # Technical editor may have been open in another tab; only the dedicated mode endpoint changes this policy.
    for z in data['zones']:
        z['irrigation_mode']='MOISTURE' 
    for z in data['zones']:
        if z['soil_ph_min'] is not None and z['soil_ph_max'] is not None and z['soil_ph_min']>z['soil_ph_max']:
            raise HTTPException(400,'Khoảng pH không hợp lệ')
    for z in data['zones']:
        if z['soil_stop_pct']-z['soil_start_pct'] < 5:
            raise HTTPException(400,'Ngưỡng dừng phải cao hơn ngưỡng bắt đầu ít nhất 5%')
    vals=[v for z in data['zones'] for v in (z['soil_start_pct'],z['soil_stop_pct'])]
    cmd='SOIL:'+','.join(str(v) for v in vals)
    global soil_sync_pending_since
    try:
        sent=bridge.command(cmd)  # Never claim ESP32 updated just because DB was saved.
    except (ValueError,ConnectionError) as exc:
        raise HTTPException(503,'Không gửi được ngưỡng đến ESP32; cấu hình chưa được lưu: '+str(exc)) from exc
    soil_sync_pending_since=time.time()
    result=storage.save_farm_config(data)
    result['sync_status']='PENDING_ESP32_TELEMETRY'
    result['command']=cmd
    twin_state=twin.snapshot()
    if twin_state['running'] and twin_state.get('last_step') and time.time()-twin_state['last_step']<15:
        storage.sync_soil_alerts(soil_alerts(result,twin_state['world']))
    return result

class ZoneNames(BaseModel):
    names: list[str] = Field(min_length=2,max_length=2)

@app.patch('/api/farm/zones/names')
def update_zone_names(body: ZoneNames):
    names=[n.strip() for n in body.names]
    if any(not n or len(n)>36 for n in names):
        raise HTTPException(400,'Tên khu vực phải từ 1 đến 36 ký tự')
    cfg=storage.get_farm_config()
    for i,name in enumerate(names):
        cfg['zones'][i]['name']=name
    return storage.save_farm_config(cfg)

@app.get('/api/farm')
def farmer_summary():
    snap=snapshot()
    config=storage.get_farm_config()
    latest=snap['latest'] if snap['device_online'] else None
    twin_state=twin.snapshot()
    w=twin_state['world'] if twin_state['running'] and twin_state.get('last_step') and time.time()-twin_state['last_step']<15 else None
    alerts=[]
    if latest is None:
        alerts.append({'level':'warning','kind':'OFFLINE',
            'title':'Mất kết nối với bộ điều khiển',
            'detail':'Không nhận được thông tin mới từ ESP32. Trạng thái bơm hiện chưa xác định.'})
    elif latest.get('fault') or latest.get('state')=='FAULT':
        alerts.append({'level':'critical','kind':'FAULT','title':'Hệ thống báo sự cố',
                       'detail':'Bộ điều khiển đã yêu cầu ngừng bơm tưới. Cần kiểm tra thiết bị.'})
    elif latest.get('state')=='HOLD_NO_WATER':
        alerts.append({'level':'warning','kind':'WATER',
                       'title':'Tưới đang tạm dừng vì nguồn nước hoặc dữ liệu không phù hợp',
                       'detail':'Kiểm tra trạng thái nguồn nước và kết nối của mô hình.'})
    if latest and latest.get('canal_safe') is False:
        tank_available=bool(latest.get('tank_ok'))
        alerts.append({'level':'warning' if tank_available else 'critical','kind':'CANAL',
                       'title':'Nước kênh nhiễm mặn hoặc không đủ điều kiện',
                       'detail':'Đã ngừng lấy nước kênh. '+('Có thể dùng bồn dự trữ khi cần tưới.' if tank_available else 'Chưa có nguồn thay thế đủ điều kiện.')})
    # 2.5 Core: tank salinity is a reference measurement only, not an interlock.
    # Do not present historic/legacy tank_quality_safe as an active protection rule.
    if latest and latest.get('fill_fault'):
        alerts.append({'level':'warning','kind':'FILL','title':'Nạp nước bồn quá thời gian cho phép',
                       'detail':'Bơm nạp đã được tắt. Cần kiểm tra nguyên nhân.'})
    if w is not None:
        alerts.extend(soil_alerts(config,w))
    if latest is not None:
        # 15% is a DEMO warning threshold, not crop-specific agronomic guidance.
        for i,z in enumerate(config['zones'],1):
            moist=latest.get(f'soil{i}_pct')
            if not isinstance(moist,(int,float)) or moist>latest.get(f'soil_start_z{i}',35):
                continue
            if latest.get(f'zone{i}_hold'):
                msg='Khu vực đang tạm ngưng tưới. Hệ thống không tự bật lại.'
            elif not latest.get('master_enabled',False):
                msg='Hệ thống đang tắt vận hành tại bộ điều khiển.'
            elif not latest.get('irrigation_window',False):
                msg='Đang ngoài giờ tưới ưu tiên; hệ thống vẫn theo dõi.'
            else:
                continue
            alerts.append({'level':'warning','kind':'SOIL_DRY','zone':i,
                    'title':f'{z["name"]}: '+('Đất rất khô, cần chú ý' if moist<=15 else 'Đất cần tưới'),'detail':msg})
    storage.sync_notifications(alerts)
    notices=storage.notifications(25,0)
    for notice in notices:notice['human_action']=advice_for(notice.get('kind')) if notice['active'] else ''
    state=(latest or {}).get('state')
    if latest is None:headline='Chưa xác định trạng thái vườn'
    elif not latest.get('master_enabled', False):headline='Đang chờ bật công tắc tại bộ điều khiển'
    elif state=='REFILL_TANK':headline='Đang bổ sung nước dự trữ'
    elif (latest or {}).get('pump_on'):headline='Hệ thống đang tưới cây'
    elif state=='PAUSE':headline='Hệ thống đang tạm dừng'
    elif state=='FAULT':headline='Hệ thống phát hiện sự cố'
    elif state=='HOLD_NO_WATER':headline='Đang tạm dừng tưới để bảo vệ nguồn nước'
    elif state=='REST':headline='Đang chờ giữa các phiên tưới'
    else:headline='Hệ thống đang theo dõi vườn'
    quality=evaluate(snap['latest'],snap['age_seconds'],snap['broker_connected'])
    for a in alerts:a['human_action']=advice_for(a.get('kind'))
    return {'data_quality':quality,'timed_holds':storage.timed_holds(),
            'simulation_only':True,'device_online':snap['device_online'],
            'broker_connected':snap['broker_connected'],'age_seconds':snap['age_seconds'],
            'headline':headline,'latest':snap['latest'],'live':latest,
            'farm_config':config,'app_preferences':storage.get_app_preferences(),'twin_world':w,'twin_running':twin_state['running'],
            'alerts':alerts,'notifications':notices,
            'notification_total':storage.notification_count(),'last_ack':snap['last_ack'],'events':storage.events(35),
            'server_time':time.time()}


# Fixed-time schedules and timed manual WATER requests are intentionally absent
# from MVP. Legacy database schedules are disabled in lifespan() before MQTT starts.


# Confirmed water-plan storage: never auto-restore on reconnect.
@app.get('/api/water/config')
def water_config_status():
    s = snapshot()
    return bridge.water_config.status(s['latest'], s['device_online'] and s['broker_connected'])

@app.post('/api/water/config/restore')
def restore_water_config(request: Request):
    if not access.authenticated(request):
        raise HTTPException(status_code=403, detail='Cần quyền Chuyên môn')
    s = snapshot()
    if not (s['device_online'] and s['broker_connected']):
        raise HTTPException(status_code=503, detail='Hệ thống tưới chưa kết nối')
    d = s['latest'] or {}
    if d.get('pump_on') or d.get('paused') or d.get('paused_session_pending') or d.get('tank_fill_on'):
        raise HTTPException(status_code=409, detail='Chờ phiên hoạt động kết thúc')
    info = bridge.water_config.status(d, True)
    if info['pending']:
        raise HTTPException(status_code=409, detail='Có lệnh đang chờ xác nhận')
    if not info['saved']:
        raise HTTPException(status_code=404, detail='Chưa có định mức đã xác nhận')
    if not info['mismatch']:
        return {'confirmed': True, 'status': 'ALREADY_SYNCED'}
    cmd = 'WATER:' + ','.join(str(int(round(x * 10))) for x in info['saved']['values'])
    try:
        outcome = bridge.command(cmd)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {'confirmed': False, 'status': 'PUBLISHED_AWAITING_CONFIRMATION', **outcome}
