"""Read-only freshness and validity diagnostics; never grants water permissions."""
from __future__ import annotations
import math
import time

def evaluate(latest, age_seconds, broker_connected, *, now=None):
    now=time.time() if now is None else now
    if latest is None:
        return {'status':'NO_DATA','label':'Chưa có dữ liệu','age_seconds':None,'signals':{},'issues':['Chưa nhận telemetry từ bộ điều khiển']}
    age=max(0,float(age_seconds or 0))
    issues=[]
    if not broker_connected:issues.append('Backend chưa kết nối MQTT')
    if age>=18:issues.append('Telemetry đã quá hạn')
    def valid_number(key, lo, hi):
        value=latest.get(key)
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and lo<=value<=hi
    checks={'Độ ẩm vùng 1':valid_number('soil1_pct',0,100),
            'Độ ẩm vùng 2':valid_number('soil2_pct',0,100),
            'Độ mặn kênh':valid_number('salinity_ppt',0,100),
            'Mức nước bồn':valid_number('tank_l',0,2000) and latest.get('tank_sensor_valid') is not False}
    for name,ok in checks.items():
        if not ok:issues.append(f'{name}: dữ liệu không hợp lệ hoặc thiếu')
    if age>=18 or not broker_connected:status='STALE'
    elif not all(checks.values()):status='INVALID'
    elif age>=10:status='DELAYED'
    else:status='FRESH'
    labels={'STALE':'Dữ liệu quá hạn','INVALID':'Dữ liệu cần kiểm tra','DELAYED':'Cập nhật chậm','FRESH':'Dữ liệu mới'}
    return {'status':status,'label':labels[status],'age_seconds':round(age,1),
            'signals':checks,'issues':issues}

ADVICE={
 'OFFLINE':'Hệ thống chưa cập nhật dữ liệu mới. Vui lòng kiểm tra nguồn điện và kết nối bộ điều khiển. Không suy đoán trạng thái bơm khi dữ liệu quá hạn.',
 'FAULT':'Kiểm tra mã lỗi và tín hiệu cảm biến. Chỉ cho chạy lại khi nguyên nhân đã được xử lý.',
 'WATER':'Kiểm tra độ mặn, mức bồn và dữ liệu đầu vào trước khi yêu cầu tưới lại.',
 'CANAL':'Kiểm tra độ mặn nước kênh và khả năng sử dụng nguồn bồn.',
 'FILL':'Kiểm tra mực bồn và điều kiện nạp nước trước khi khởi động lại.',
 'SOIL_DRY':'Kiểm tra vùng đang tạm ngưng, lịch tưới và nguồn nước; không bỏ qua điều kiện an toàn.',
 'SOIL_MONITOR':'Xem lại dữ liệu và hồ sơ canh tác trước khi thay đổi ngưỡng.'}

def advice_for(kind):return ADVICE.get(kind,'Kiểm tra trạng thái thiết bị và dữ liệu liên quan.')
