(()=>{'use strict';const $=id=>document.getElementById(id);const api=async(p,o={})=>{const r=await fetch(p,{cache:'no-store',...o});const raw=await r.text();let j;try{j=JSON.parse(raw)}catch(e){throw Error(r.ok?'Máy chủ trả dữ liệu không hợp lệ':'Máy chủ lỗi HTTP '+r.status+'; hãy kiểm tra cửa sổ Python Backend')}if(!r.ok)throw Error(typeof j.detail==='string'?j.detail:'Không thành công (HTTP '+r.status+')');return j};async function command(path,body){$('lab-message').textContent='Đang gửi yêu cầu…';try{const o={method:'POST'};if(body){o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(body)}const answer=await api(path,o);$('lab-message').textContent=answer.delivery_status==='PUBLISHED_AWAITING_ESP32'?'Đã gửi dữ liệu MQTT; chờ ESP32 xác nhận. Kiểm tra trạng thái phản hồi bên dưới.':'Đã xử lý yêu cầu; kiểm tra phản hồi ESP32.'}catch(e){$('lab-message').textContent='Không thực hiện được: '+e.message}}$('lab-stop').onclick=()=>command('/api/twin/stop');
const customFields=[['soil1_pct','sim-z1',0,100],['soil2_pct','sim-z2',0,100],['salinity_ppt','sim-salt',0,3],['canal_pct','sim-canal',0,100],['rain_pct','sim-rain',0,100],['tank_l','sim-tank',0,2000]];
const presetInputs={BOTH_DRY:[20,25,.5,80,0,1500],ONLY_Z2:[65,25,.5,80,0,1500],SALTY_TANK:[20,25,1.5,80,0,1500],NO_SOURCE:[20,25,1.5,80,0,100],REFILL:[75,75,.5,80,0,500],BOTH_WET:[75,75,.5,80,0,1500]};
const descriptions={BOTH_DRY:'TC01: Hai vùng cùng khô, nguồn kênh an toàn.',ONLY_Z2:'TC02: Chỉ vùng 2 thiếu ẩm.',SALTY_TANK:'TC03: Kênh mặn, có thể lấy nước bồn nếu đủ điều kiện.',NO_SOURCE:'TC04: Kênh mặn và bồn cạn, phải chặn tưới.',REFILL:'TC05: Hai vùng đủ ẩm, xét nạp bồn.',BOTH_WET:'TC06: Hai vùng đủ ẩm, không cần tưới.',STALE:'TC07: Ngừng gửi dữ liệu mô phỏng để kiểm tra bảo vệ.'};
let presetEdited=true;let applySerial=0;
function markCustom(){presetEdited=true;$('sim-preset').value='CUSTOM';}
function syncControl(id,value){const input=$(id),range=$(id+'-range');input.value=value;range.value=value;}
function fillCustom(values){customFields.forEach((f,i)=>syncControl(f[1],values[i]));presetEdited=false;$('sim-message').textContent='';}
customFields.forEach(([key,id,min,max])=>{const input=$(id),range=$(id+'-range');range.addEventListener('input',()=>{input.value=range.value;markCustom()});input.addEventListener('input',()=>{const val=Number(input.value);if(input.value!==''&&Number.isFinite(val)){range.value=Math.max(min,Math.min(max,val));markCustom()}});});
$('sim-preset').addEventListener('change',()=>{const id=$('sim-preset').value;if(presetInputs[id])fillCustom(presetInputs[id]);else if(id==='CUSTOM'){presetEdited=true;}else if(id==='STALE'){$('sim-message').textContent='TC07 sẽ ngắt truyền dữ liệu đến khi ESP32 phát hiện quá hạn (tối đa 120 giây thực); không sử dụng thanh trượt.';}});
$('sim-default').onclick=()=>{const id=$('sim-preset').value;if(presetInputs[id])fillCustom(presetInputs[id]);else { fillCustom([20,25,.5,80,0,1500]);$('sim-preset').value='CUSTOM';presetEdited=true; }};
$('sim-apply').onclick=async()=>{const id=$('sim-preset').value;if(id==='STALE'){
 if(!await window.SaltGuardDialog.confirm('Thử TC07: tạm ngừng dữ liệu mô phỏng để kiểm tra cơ chế bảo vệ?'))return;
 $('sim-apply').disabled=true;$('sim-message').textContent='Đang bắt đầu TC07…';
 try{await api('/api/twin/lab/test-stale',{method:'POST'});$('sim-message').textContent='TC07 đã được yêu cầu; chờ ESP32 vào SIMULATION rồi hệ thống sẽ tạm ngừng dữ liệu đến khi ESP32 báo quá hạn.';refreshTwin()}catch(e){$('sim-message').textContent='Không chạy được TC07: '+e.message}finally{$('sim-apply').disabled=false;}return;
 }
let payload={};for(const [key,field,min,max] of customFields){const raw=$(field).value.trim(),val=Number(raw);if(raw===''||!Number.isFinite(val)||val<min||val>max){$('sim-message').textContent='Thông số không hợp lệ: '+key+' (từ '+min+' đến '+max+')';$(field).focus();return}payload[key]=val;}
if(!await window.SaltGuardDialog.confirm('Áp dụng các thông số này vào mô phỏng? Hệ thống có thể bắt đầu tưới hoặc nạp bồn khi đủ điều kiện.'))return;
$('sim-apply').disabled=true;$('sim-message').textContent='Đang gửi dữ liệu…';let baseline=null;try{baseline=await api('/api/snapshot')}catch(_e){};const applyStartedAt=Date.now()/1000;try{
// Preset nguyên bản đi qua endpoint preset để giữ cơ chế ghi nhận TC và kết quả kiểm thử cũ.
const original=presetInputs[id];const unchanged=id!=='CUSTOM' && !presetEdited && original && customFields.every((f,i)=>Number($(f[1]).value)===original[i]);
let res;if(unchanged){res=await api('/api/twin/lab/preset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preset:id})});}else{res=await api('/api/twin/lab/custom',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
const serial=++applySerial;
$('sim-message').textContent='Đã gửi; đang kiểm tra ESP32…';refreshTwin();
const started=Date.now();let verified=false;let observed=false;
const before=baseline?.latest||{};
while(Date.now()-started<15000 && serial===applySerial){
  await new Promise(r=>setTimeout(r,950));
  try{
    const snap=await api('/api/snapshot');
    const t=snap.latest||{};  // /api/snapshot stores the ESP32 payload under latest
    if(!snap.device_online || !snap.broker_connected || t.mode!=='TWIN')continue;
    const newer=Number(t.received_at)>Math.max(applyStartedAt,Number(before.received_at||0));
    const previousCount=Number(before.twin_rx_count);
    const latestCount=Number(t.twin_rx_count);
    const rebooted=Number.isFinite(Number(before.ms)) && Number(t.ms)<Number(before.ms);
    const rxNewer=Number.isFinite(latestCount) && latestCount>0 && (rebooted || !Number.isFinite(previousCount) || latestCount>previousCount);
    if(!newer || !rxNewer)continue;
    observed=true;
    const close=(k,val,tol)=>t[k]!==null && t[k]!==undefined && Number.isFinite(Number(t[k])) && Math.abs(Number(t[k])-val)<=tol;
    // Soil and tank evolve naturally; verify receipt primarily via unaffected input signals.
    if(close('salinity_ppt',payload.salinity_ppt,0.12) && close('canal_pct',payload.canal_pct,1.5) && close('rain_pct',payload.rain_pct,1.5)){
      verified=true;break;
    }
  }catch(_e){}
}
if(serial===applySerial)$('sim-message').textContent=verified?
 'ESP32 đã phản hồi dữ liệu mô phỏng mới. Giá trị đất/bồn có thể tiếp tục thay đổi.':
 observed?'ESP32 có nhận khung mô phỏng mới nhưng chưa khớp dữ liệu vừa gửi. Kiểm tra Serial.':
 'Backend đã tiếp nhận yêu cầu; chưa xác nhận được khung dữ liệu mới trên ESP32. Kiểm tra MQTT và Serial.';
}catch(e){$('sim-message').textContent='Không áp dụng được: '+e.message;}finally{$('sim-apply').disabled=false;}};
$('lab-resume').onclick=async()=>{await command('/api/twin/lab/resume-input');refreshTwin()};
async function refreshTwin(){try{const d=await api('/api/twin');$('sg-stale-recovery').hidden=!Boolean(d.twin_publish_paused||d.stale_arm_pending);$('lab-test-status').textContent='Preset: '+(d.last_preset||'Chưa chọn')+' · ESP32: '+(d.actual_state||'chưa xác nhận')+(d.stale_arm_pending?' · Đang chuẩn bị TC07':d.twin_publish_paused?' · Tạm ngừng dữ liệu còn '+d.twin_publish_pause_remaining_s+'s':'')+' · Kết quả: '+(d.preset_result==='COMPLETED'?'ĐÃ KẾT THÚC PRESET':d.preset_result==='OBSERVED'?'ĐÃ GHI NHẬN TRẠNG THÁI KỲ VỌNG':d.preset_result==='RUNNING'?'ĐANG KIỂM THỬ':d.preset_result==='NOT_VERIFIED'?'CHƯA XÁC MINH ĐẠT':'Chưa có')+' · Chế độ: '+(d.actual_mode||'chưa rõ')+' · '+(d.actual_master_enabled===false?'CÔNG TẮC TỔNG OFF – gạt ON trên Wokwi để tưới':d.actual_master_enabled===true?'Công tắc ON':'Chưa xác nhận công tắc')+' · '+(d.esp_online?'Telemetry mới':'Telemetry cũ/mất')+(d.error?' · Lỗi: '+d.error:'');}catch(e){$('sg-stale-recovery').hidden=true;$('lab-test-status').textContent='Không đọc được trạng thái mô phỏng: '+e.message}}refreshTwin();setInterval(refreshTwin,3000);async function refresh(){try{const d=await api('/api/snapshot'),on=d.device_online&&d.broker_connected;$('lab-online').textContent=on?'Kết nối':'Ngoại tuyến';$('lab-online').className='connection-pill'+(on?'':' bad');$('lab-online').title=on?'ESP32 kết nối':'ESP32 ngoại tuyến';$('lab-online').setAttribute('aria-label','Trạng thái kết nối ESP32: '+(on?'Kết nối':'Ngoại tuyến'));}catch(e){$('lab-online').textContent='Ngoại tuyến'}}refresh();setInterval(refresh,6000);document.addEventListener('scroll',()=>document.querySelector('.mobile-topbar')?.classList.toggle('is-scrolled',scrollY>6),{passive:true})})();