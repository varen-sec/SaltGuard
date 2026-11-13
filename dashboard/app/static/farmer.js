(()=>{'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,d=0)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'—';
const pages=['home','zones','alerts','journal','settings'];let current='home',last=null,busy=false;
let noticeVisible=25;let journalKind='all';
const api=async(path,opts={})=>{const r=await fetch(path,{cache:'no-store',...opts});const o=await r.json();if(!r.ok)throw Error(o.detail||'Không thực hiện được');return o};
const send=(path,body,method='POST')=>api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
let toastTimer;function toast(msg){const el=$('toast');el.textContent=msg;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),3800)}
function go(page){if(!pages.includes(page))return;current=page;pages.forEach(p=>$('page-'+p).classList.toggle('active',p===page));document.querySelectorAll('.navitem').forEach(b=>{const active=b.dataset.page===page;b.classList.toggle('selected',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});$('page-title').textContent={home:'Trang chủ',zones:'Khu vực tưới',alerts:'Thông báo',journal:'Nhật ký',settings:'Cài đặt'}[page];window.scrollTo(0,0);closeSettingsView();if(page==='alerts')refreshNotices()}
document.querySelectorAll('.navitem').forEach(b=>b.onclick=()=>go(b.dataset.page));document.querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>go(b.dataset.jump));

const connected=()=>Boolean(last?.device_online&&last?.broker_connected);
// Farmer actions use a centered dialog instead of browser alert()/confirm().
// A broker publish is NOT proof the ESP32 applied the action: wait for its ACK.
const actionDialog=$('action-dialog');let dialogConfirm=null;
function openDialog(title,description,{action='',onConfirm=null,kind='info',holdOptions=false,defaultChoice='manual'}={}){
  $('action-title').textContent=title;
  $('action-detail').textContent=description;
  $('action-glyph').textContent=kind==='error'?'!':kind==='success'?'✓':'•';
  $('action-glyph').className='dialog-glyph '+kind;
  dialogConfirm=onConfirm;
  $('action-choice-wrap').hidden=!holdOptions;
  if(holdOptions)$('action-choice').value=defaultChoice;
  $('action-cancel').hidden=!onConfirm;
  $('action-confirm').textContent=action||(onConfirm?'Đồng ý':'Đóng');
  if(!actionDialog.open)actionDialog.showModal();
}
$('action-cancel').onclick=()=>actionDialog.close();
$('action-confirm').onclick=async()=>{
  const cb=dialogConfirm;
  if(!cb){actionDialog.close();return;}
  dialogConfirm=null;
  $('action-confirm').disabled=true;
  try{await cb($('action-choice').value)}finally{$('action-confirm').disabled=false;}
};
const nap=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function waitAck(cmd,oldAck){
  const previous=JSON.stringify(oldAck||{});
  for(let n=0;n<10;n++){
    await nap(450);
    const snap=await api('/api/snapshot');
    const ack=snap.last_ack;
    if(ack&&ack.command===cmd&&JSON.stringify(ack)!==previous)return ack;
  }
  return null;
}
async function command(cmd,{success='Bộ điều khiển đã nhận yêu cầu.',title='Đã xác nhận'}={}){
  if(busy)return;
  if(!connected()){
    openDialog('Thiết bị ngoại tuyến','Chưa thể gửi lệnh. Vui lòng kiểm tra kết nối.',{kind:'error'});
    return;
  }
  busy=true;updateControls();
  let previousAck=last?.last_ack;
  try{
    openDialog('Đang gửi yêu cầu','SaltGuard đang chờ xác nhận từ bộ điều khiển.',{kind:'info'});
    await send('/api/command',{command:cmd});
    const ack=await waitAck(cmd,previousAck);
    if(ack?.accepted){
      const queued=cmd.endsWith(':ONCE') && ['ONE_TIME_QUEUED','ALREADY_QUEUED'].includes(String(ack.message||''));
      openDialog(queued?'Đã xếp lượt tưới':title,queued?'Đã nhận yêu cầu. Hệ thống sẽ tự chuyển sang vùng này khi đến lượt, nếu đủ điều kiện an toàn.':success,{kind:'success'});
    }
    else if(ack){openDialog('Chưa thực hiện được', 'Bộ điều khiển đã từ chối yêu cầu. Hãy kiểm tra trạng thái hệ thống.',{kind:'error'});}
    else{openDialog('Chưa có xác nhận','Đã gửi yêu cầu nhưng chưa nhận được phản hồi từ thiết bị. Vui lòng xem lại trạng thái trước khi thao tác tiếp.',{kind:'info'});}
    await refresh();
  }catch(err){openDialog('Không gửi được yêu cầu',err.message,{kind:'error'});}
  finally{busy=false;updateControls();}
}
function updateControls(){const live=last?.live||{},ready=connected()&&!busy;document.querySelectorAll('[data-command]').forEach(b=>b.disabled=!ready||!['TWIN','DYNAMIC'].includes(live.mode));
$('refill-switch').disabled=!ready||!['TWIN','DYNAMIC'].includes(live.mode);$('refill-switch').setAttribute('aria-checked',String(Boolean(live.fill_auto)));$('fill-request').disabled=!ready||!live.master_enabled;
// HOLD/RESUME modify the zone's persistent irrigation permission, not the pump's immediate state.
// This setting remains editable with MASTER OFF, or in PRESET / TWIN / DYNAMIC.
// ONCE still requires an armed controller and a supported operating mode.
document.querySelectorAll('.zone-hold,.hold-change').forEach(b=>{const i=Number(b.dataset.zone);b.disabled=!ready||i>Number(live.zones||0)});
document.querySelectorAll('.allow-once,.home-once,.allow-once-alert').forEach(b=>{const i=Number(b.dataset.zone);b.disabled=!ready||!live.master_enabled||!['TWIN','DYNAMIC'].includes(live.mode)||i>Number(live.zones||0)});
}
const emergencyButton=$('sg-emergency-stop');
if(emergencyButton)emergencyButton.onclick=()=>openDialog('Dừng khẩn cấp?','Ngắt tưới và nạp bồn. Giữ nút ACK trên bộ điều khiển để mở khóa.',{action:'Xác nhận dừng',kind:'error',onConfirm:()=>command('EMERGENCY:STOP',{title:'Đã dừng',success:'Hệ thống đã khóa khẩn cấp.'})});
$('refill-switch').onclick=()=>command(last?.live?.fill_auto?'FILL:AUTO:OFF':'FILL:AUTO:ON');$('fill-request').onclick=()=>command('FILL:REQUEST');
document.querySelectorAll('[data-command]').forEach(b=>b.onclick=()=>command(b.dataset.command));
function soilDetails(i,info){const world=info.twin_world,z=info.farm_config?.zones?.[i-1]||{};let warning=(info.alerts||[]).some(a=>a.kind==='SOIL_MONITOR'&&a.zone===i);
const rows=[['EC đất',fmt(world?.['soil_ec_z'+i+'_ds_m'],2), 'dS/m'],['pH đất',fmt(world?.['soil_ph_z'+i],2),''],['Natri',fmt(world?.['soil_na_z'+i+'_mg_kg'],0),'mg/kg']];return `<details class="soil-detail" data-soil="${i}"><summary>${warning?'⚠ Chỉ số đất cần chú ý':'Xem chỉ số đất'}</summary><div class="quality-list">${rows.map(a=>`<div class="quality-item"><small>${a[0]}</small><b>${a[1]} ${a[2]}</b></div>`).join('')}</div></details>`;}
function hasOneTime(live,i){return live['extra_water_allowed_z'+i]===true || (live['extra_water_allowed_z1']===undefined && Number(live.extra_water_zone||0)===i);}
function soilTrigger(live,i,info){const v=live?.['soil_start_z'+i];const fallback=info?.farm_config?.zones?.[i-1]?.soil_start_pct;return Number.isInteger(v)?v:(Number.isInteger(fallback)?fallback:35);}
function statusZone(info,live,i,online){if(!online)return 'Chưa có dữ liệu';if(i>Number(live.zones||0))return 'Chưa sử dụng';if(live['zone'+i+'_hold'])return 'Tạm ngưng tưới';if(live.pump_on&&live.zone===i)return 'Đang tưới';if(hasOneTime(live,i))return live.pump_on?'Chờ đến lượt tưới':'Đã nhận yêu cầu tưới';if(live.pump_on && Number(live.zone)!==i && Number(live['soil'+i+'_pct'])<=soilTrigger(live,i,info) && live.irrigation_window)return 'Chờ đến lượt tưới';if(!live.master_enabled)return 'Đang chờ';if(live.clock_valid===false)return 'Đang chờ giờ';if(live.irrigation_window===false&&Number(live['soil'+i+'_pct'])<=soilTrigger(live,i,info))return 'Chờ giờ tưới';return 'Đang theo dõi';}
function renderZones(info,live,online){const opened=[...document.querySelectorAll('.soil-detail[open]')].map(x=>x.dataset.soil);const config=info.farm_config?.zones||[];
$('home-zones').innerHTML=[1,2].map(i=>{let name=esc(config[i-1]?.name||'Vườn '+i),status=statusZone(info,live,i,online);return `<div class="zone-brief"><div><strong>${name}</strong><small>${esc(status)}</small></div><span class="zone-status ${status==='Đang tưới'?'':'muted'}">${online&&i<=Number(live.zones||0)?fmt(live['soil'+i+'_pct'])+'%':'—'}</span></div>`}).join('');
$('detailed-zones').innerHTML=[1,2].map(i=>{const z=config[i-1]||{},enabled=online&&i<=Number(live.zones||0),val=enabled?live?.['soil'+i+'_pct']:null,held=Boolean(live?.['zone'+i+'_hold']),status=statusZone(info,live,i,online);
const profileInfo=[z.crop,z.soil_type,z.growth_stage].filter(x=>x&&x!=='Chưa thiết lập').join(' · ');
const start=soilTrigger(live,i,info),stop=Number.isInteger(live?.['soil_stop_z'+i])?live['soil_stop_z'+i]:(z.soil_stop_pct??60);
const width=typeof val==='number'?Math.max(0,Math.min(100,val)):0;return `<article class="zone-card"><div class="zone-card-head"><h3>${esc(z.name||'Vườn '+i)}</h3><button type="button" class="zone-rename" data-zone="${i}" aria-label="Đổi tên khu vực ${i}">Đổi tên</button><span class="chip ${status==='Đang tưới'?'active':''}">${esc(status)}</span></div><div class="moisture-row"><span>Độ ẩm đất</span><b>${fmt(val)}%</b></div><div class="bar"><span style="width:${width}%"></span></div>
<div style="margin:8px 0 12px;color:#506258;font-size:13px">${profileInfo?esc(profileInfo)+' · ':''}Bắt đầu tưới ≤ ${start}% · Dừng ≥ ${stop}%</div>
<div class="zone-hold-row"><div><strong>Cho phép tưới tự động</strong><small>${held?'Đang tạm ngưng':'Theo độ ẩm đất'}</small></div><button type="button" class="switch zone-hold" data-zone="${i}" role="switch" aria-checked="${enabled&&!held}" aria-label="${held?'Tiếp tục':'Tạm ngưng'} tưới ${esc(z.name||'Vườn '+i)}" ${!enabled?'disabled':''}><span></span></button></div>${soilDetails(i,info)}<div class="zone-hold-meta" ${!held?'hidden':''}><span id="hold-timer-${i}"></span><button type="button" class="hold-change" data-zone="${i}" ${!enabled?'disabled':''}>Thay đổi</button></div>${enabled && !held && Boolean(live.master_enabled) && !live.irrigation_window && live.clock_valid && val<=soilTrigger(live,i,info) && !live.fault && !live.paused && !hasOneTime(live,i)?
`<div class="urgent-control"><span>${val<=15?'Đất đang rất khô':'Đất cần nước'}</span><button type="button" class="outline-btn allow-once" data-zone="${i}">Cho phép tưới lúc này</button></div>`:''}</article>`;}).join('');document.querySelectorAll('.soil-detail').forEach(el=>{if(opened.includes(el.dataset.soil))el.open=true});
}
function friendlyEvents(events,info){
  if(!events.length)return '<div class="empty">Chưa có hoạt động nào.</div>';
  const names=[1,2].map(i=>info?.farm_config?.zones?.[i-1]?.name||'Vườn '+i);
  function commandLabel(code){
    const m=/^ZONE:(1|2):(HOLD|RESUME)$/.exec(code);
    if(m)return (m[2]==='HOLD'?'tạm ngưng tưới ':'cho phép tưới lại ')+names[Number(m[1])-1];
    const once=/^ZONE:(1|2):ONCE$/.exec(code);if(once)return 'tưới ngoài giờ một lần cho '+names[Number(once[1])-1];
    const map={'FILL:REQUEST':'yêu cầu nạp bồn','FILL:CANCEL':'dừng yêu cầu nạp bồn','FILL:AUTO:ON':'bật tự nạp bồn','FILL:AUTO:OFF':'tắt tự nạp bồn','ZONES:1':'chọn 1 khu vực tưới','ZONES:2':'chọn 2 khu vực tưới','STATUS':'cập nhật trạng thái thiết bị','TWIN:ON':'bắt đầu mô phỏng môi trường','TWIN:OFF':'dừng mô phỏng môi trường'};
    return map[code]||'';
  }
  const namesOfState={CANAL_Z1:'Bắt đầu tưới '+names[0]+' bằng nước kênh',CANAL_Z2:'Bắt đầu tưới '+names[1]+' bằng nước kênh',TANK_Z1:'Bắt đầu tưới '+names[0]+' bằng nước bồn',TANK_Z2:'Bắt đầu tưới '+names[1]+' bằng nước bồn',REFILL_TANK:'Bắt đầu nạp nước vào bồn',REST:'Bơm nghỉ giữa các phiên',FAULT:'Hệ thống đã phát hiện sự cố',IDLE:'Hệ thống đã dừng hoạt động tưới',PAUSE:'Hệ thống được tạm dừng',HOLD_NO_WATER:'Đã ngừng tưới để bảo vệ nguồn nước'};
  const acked=events.filter(e=>e.kind==='ack').map(e=>({code:String(e.title||'').replace(/^(Chấp nhận|Từ chối):\s*/,'').trim(),ts:e.ts}));
  return events.filter(e=>{
    const code=String(e.title||'').replace(/^(Chấp nhận|Từ chối|Đã gửi):\s*/,'').trim();
    if((e.kind==='command'||e.kind==='ack') && (!commandLabel(code) || /^TWIN:/.test(code) || /^ZONES:/.test(code) || code==='STATUS'))return false;
    if(e.kind==='twin')return false;
    if(e.kind==='ack'&&String(e.title).includes('CLOCK:'))return false;
    if(e.kind==='command'){
      const code=String(e.title||'').replace(/^Đã gửi:\s*/,'').trim();
      if(code.startsWith('CLOCK:'))return false;
      return !acked.some(a=>a.code===code&&Math.abs(Number(a.ts)-Number(e.ts))<12);
    }
    return true;
  }).slice(0,120).map(e=>{
    let title='',detail='',kind=e.kind;
    if(kind==='state'){
      const code=String(e.title||'').replace(/^.*?:\s*/, '').trim();
      title=namesOfState[code]||'Hệ thống thay đổi trạng thái';
      if(code==='IDLE'&&String(e.detail||'').includes('ZONE_HOLD'))title='Đã ngừng tưới theo yêu cầu';
      else if(code==='IDLE'&&String(e.detail||'').includes('MASTER_OFF'))title='Đã tắt vận hành tại bộ điều khiển';
    } else if(kind==='ack'||kind==='command'){
      const ack=kind==='ack',ref=String(e.title||'');
      const code=ref.replace(/^(Chấp nhận|Từ chối|Đã gửi):\s*/,'').trim();
      const meaning=commandLabel(code);
      if(meaning){
        title=ack?(ref.startsWith('Từ chối:')?'Thiết bị từ chối '+meaning:'Đã xác nhận '+meaning):'Đã gửi yêu cầu '+meaning;
        detail=ack?'Bộ điều khiển đã phản hồi.':'Đang chờ thiết bị xác nhận.';
      }else{title='Hoạt động kỹ thuật';detail='Xem chi tiết trong phần Kỹ thuật.';}
    } else if(kind==='irrigation_session'){const detailMatch=/Vùng ([12]) · Nguồn (CANAL|TANK) · (\d+) giây/.exec(e.detail||'');if(detailMatch){const zi=Number(detailMatch[1])-1;const sec=Number(detailMatch[3]);title='Đã tưới '+names[zi];detail=`${sec>=60?(sec/60).toFixed(1)+' phút':sec+' giây'} mô phỏng · ${detailMatch[2]==='CANAL'?'Nước kênh':'Nước dự trữ'}`;}else{title='Đã hoàn tất một phiên tưới';detail='Thời lượng chưa xác định';}
    } else if(kind==='water')title=String(e.title||'').replace('Nguồn kênh','Nước kênh');
    else if(kind==='soil_warning')title='Có chỉ số đất cần chú ý';
    else if(kind==='soil_clear')title='Cảnh báo chỉ số đất đã kết thúc';
    else if(kind==='twin')title='Đã đổi tình huống mô phỏng';
    else title=String(e.title||'Hoạt động của hệ thống');
    const date=new Date(e.ts*1000).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',hour12:false,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
    const group=kind==='irrigation_session'?'irrigation':kind==='state'?(title.includes('tưới')||title.includes('Bơm nghỉ')?'irrigation':title.includes('nạp')||title.includes('nguồn')?'water':'user'):(kind==='water'?'water':kind==='ack'||kind==='command'?'user':kind==='settings'?'user':'other');
    return `<div class="journal-item" data-kind="${group}"><b>${esc(title)}</b>${detail?`<span class="journal-detail">${esc(detail)}</span>`:''}<small>${esc(date)}</small></div>`;
  }).join('');
}


function renderHomePriority(info,live,online){
 const el=$('home-priority');if(!el)return;
 const names=info.farm_config?.zones||[];
 const close=()=>{el.hidden=true;el.innerHTML='';delete el.dataset.level;};
 const warn=(title,detail)=>{el.hidden=false;el.dataset.level='critical';el.innerHTML='<div class="home-priority-head"><span aria-hidden="true">!</span><strong>'+esc(title)+'</strong></div><p>'+esc(detail)+'</p>';};
 if(!online){const age=Number(info.age_seconds);const suffix=Number.isFinite(age)?' Lần cập nhật gần nhất: '+Math.round(age)+' giây trước.':'';warn('Tạm mất kết nối với hệ thống tưới','Ứng dụng chưa nhận được thông tin mới; trạng thái bơm và van chưa thể xác nhận.'+suffix);el.dataset.level='info';return;}
 if(live.emergency_stop){warn('Hệ thống đang dừng khẩn cấp','Bơm và van đã được yêu cầu dừng. Khôi phục bằng ACK trên bộ điều khiển.');return;}
 if(live.fault || live.state==='FAULT'){warn('Thiết bị cần kiểm tra','Có lỗi hoặc trạng thái bảo vệ. Mở mục Thông báo để xem nguyên nhân.');return;}
 if(live.state==='HOLD_NO_WATER'){
   warn(live.reason==='TWIN_INPUT_STALE'?'Dữ liệu mô phỏng đã quá hạn':'Tưới đang bị chặn vì nguồn nước',live.reason==='TWIN_INPUT_STALE'?'Kiểm tra luồng truyền SIMULATION trước khi cho phép tưới.':'Kiểm tra độ mặn kênh và mực nước bồn dự trữ.');return;
 }
 const dry=[1,2].filter(i=>i<=Number(live.zones||0) && !live['zone'+i+'_hold'] && typeof live['soil'+i+'_pct']==='number' && live['soil'+i+'_pct']<=soilTrigger(live,i,info) && !live.irrigation_window && live.clock_valid && !live.pump_on);
 if(!dry.length){close();return;}
 const canAct=Boolean(live.master_enabled && !live.paused);
 const rows=dry.map(i=>{
   const name=esc(names[i-1]?.name||'Vườn '+i);
   const permitted=hasOneTime(live,i);
   const action=permitted?'Đã được cho phép · chờ điều kiện an toàn':canAct?'<button type="button" class="outline-btn home-once" data-zone="'+i+'">Cho phép tưới '+name+'</button>':'Chưa thể cho phép tưới';
   return '<div class="priority-zone"><strong>'+name+' · '+fmt(live['soil'+i+'_pct'])+'%</strong><div>'+action+'</div></div>';
 }).join('');
 el.hidden=false;el.dataset.level='warning';
 el.innerHTML='<div class="home-priority-head"><span aria-hidden="true">!</span><strong>'+ (dry.length===2?'Hai khu vực cần tưới ngoài giờ':'Đất cần nước ngoài giờ tưới') +'</strong></div><p>Chỉ cho phép tưới nếu bạn muốn; hệ thống vẫn kiểm tra nguồn nước và an toàn.</p>'+rows;
}
function renderLiquid(live,online){
 const salt=Number(live.salinity_ppt),tank=Number(live.tank_l);
 const saltValid=online&&Number.isFinite(salt)&&live.salinity_ppt!==null&&live.salinity_ppt!==undefined;
 const tankValid=online&&live.tank_sensor_valid!==false&&Number.isFinite(tank)&&live.tank_l!==null&&live.tank_l!==undefined;
 const saltState=!saltValid?'unknown':salt>=1.0?'danger':salt>=0.7?'warning':'safe';
 const tankState=!tankValid?'unknown':tank<=20?'danger':tank<=30?'warning':'safe';
 const saltPct=saltValid?Math.min(100,Math.max(0,(salt/1.0)*100)):0;
 const tankPct=tankValid?Math.min(100,Math.max(0,tank/20)):0;
 for(const [id,state,pct] of [['salinity',saltState,saltPct],['reserve',tankState,tankPct]]){
   const card=$(id==='salinity'?'salinity-card':'reserve-card'),fill=$(id+'-fill');
   card.dataset.level=state;fill.style.height=pct+'%';
 }
 $('salinity-level').textContent=saltState==='danger'?'Đã vượt ngưỡng':saltState==='warning'?'Gần ngưỡng':'An toàn theo ngưỡng';
 if(!saltValid)$('salinity-level').textContent='Chưa có dữ liệu';
 $('reserve-level').textContent=!tankValid?'Chưa có dữ liệu':tank<=20?'Mực nước thấp':tank<=30?'Nên theo dõi':'Mực nước ổn định';
}
function setJournalFilter(){let shown=0;document.querySelectorAll('#journal-list .journal-item').forEach(el=>{const ok=journalKind==='all'||el.dataset.kind===journalKind;el.hidden=!ok;if(ok)shown++});const empty=$('journal-empty-filter');if(empty)empty.hidden=shown>0||document.querySelector('#journal-list > .empty')!==null;}
function noticeDate(ts){return new Date(ts*1000).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});}
function renderNotices(items,total){
 const live=last?.live||{},online=connected();
 const active=items.filter(n=>Boolean(n.active));
 const past=items.filter(n=>!n.active);
 $('active-notice-count').textContent=active.length?active.length+' đang có':'';
 const html=(n)=>{const i=Number(n.zone||0);const urgent=Boolean(n.active&&n.kind==='SOIL_DRY' && online && (i===1||i===2) && live.master_enabled && !live['zone'+i+'_hold'] && !live.irrigation_window && live.clock_valid && !live.fault && !live.paused && !hasOneTime(live,i));
 const date=n.active?n.started_at:n.ended_at;
 return `<article class="alert-item ${esc(n.level||'warning')} ${n.active?'':'archived'}"><div class="alert-icon" aria-hidden="true">${n.active?'!':'✓'}</div><div><h3>${esc(n.title)}</h3><p>${esc(n.detail||'')}</p>${n.active&&n.human_action?`<p class="notice-advice"><strong>Hướng xử lý:</strong> ${esc(n.human_action)}</p>`:''}<div class="notice-meta"><span class="notice-status ${n.active?'':'old'}">${n.active?'Đang cần chú ý':'Đã qua'}</span><time>${esc(noticeDate(date||n.started_at))}</time></div>${urgent?`<button type="button" class="outline-btn allow-once-alert" data-zone="${i}">Cho phép tưới một lần</button>`:''}</div></article>`;
 };
 $('alerts-active').innerHTML=active.length?active.map(html).join(''):'<div class="empty">Hiện không có việc cần chú ý.</div>';
 $('alerts-past').innerHTML=past.length?past.map(html).join(''):'<div class="empty">Chưa có thông báo trước đây.</div>';
 $('load-more-notices').hidden=items.length>=total;
}
async function refreshNotices(){try{const d=await api('/api/notifications?limit='+noticeVisible);if(current==='alerts')renderNotices(d.items||[],d.total||0)}catch(err){/* Preserve the last alert list when disconnected. */}}
$('load-more-notices').onclick=()=>{noticeVisible=Math.min(noticeVisible+25,500);refreshNotices()};
function render(data){last=data;const d=data.live||{},online=connected();
  const waterActive=online&&(d.pump_on===true||d.paused_session_pending===true);
  const sessionZone=d.pump_on?Number(d.zone):Number(d.paused_session_zone);
  const flow=Number(d['irrigation_flow_z'+sessionZone+'_lpm']);
  const target=Number(d['irrigation_target_z'+sessionZone+'_l']);
  const used=Number(d.irrigation_session_estimated_l);
  const reportedLeft=Number(d.irrigation_session_remaining_l);
  const usedMs=Number(d.irrigation_session_used_ms),budgetMs=Number(d.irrigation_session_budget_ms);
  const validSession=waterActive&&(sessionZone===1||sessionZone===2)&&Number.isFinite(flow)&&flow>0&&Number.isFinite(target)&&target>0&&Number.isFinite(used)&&used>=0&&used<=target+0.01&&Number.isFinite(reportedLeft)&&reportedLeft>=0&&reportedLeft<=target+0.01&&Math.abs((target-used)-reportedLeft)<0.05;
  $('sg-water-metrics').hidden=!validSession;
  $('sg-water-empty').hidden=validSession;
  $('sg-water-empty').textContent=waterActive?'Đang cập nhật phiên tưới':'Không có phiên tưới';
  $('sg-water-used').textContent=validSession?fmt(used,2)+' L':'—';
  $('sg-water-left').textContent=validSession?fmt(reportedLeft,2)+' L':'—';
  $('sg-water-time').textContent=validSession&&Number.isFinite(usedMs)&&Number.isFinite(budgetMs)&&usedMs>=0&&budgetMs>=usedMs?Math.ceil((budgetMs-usedMs)/1000)+' giây':'—';
  if($('sg-air-temp'))$('sg-air-temp').textContent=fmt(d.air_c,1)+' °C';
  if($('sg-air-rh'))$('sg-air-rh').textContent=fmt(d.air_rh_pct,0)+' %';
  if($('sg-water-temp'))$('sg-water-temp').textContent=fmt(d.water_c,1)+' °C';
  if($('sg-emergency-status'))$('sg-emergency-status').textContent=d.emergency_stop?'Đã khóa':'Sẵn sàng';
  if(emergencyButton){emergencyButton.disabled=!online||busy||Boolean(d.emergency_stop); emergencyButton.textContent=d.emergency_stop?'ĐÃ DỪNG':'DỪNG KHẨN CẤP';}renderPhase28(d,online);renderHomePriority(data,d,online);$('online-pill').textContent=online?'Kết nối':'Ngoại tuyến';$('online-pill').className='connection-pill'+(online?'':' bad');$('online-pill').setAttribute('aria-label','Trạng thái kết nối ESP32: '+(online?'Kết nối':'Ngoại tuyến'));$('online-pill').title=online?'ESP32 kết nối':'hệ thống tưới ngoại tuyến';
$('settings-master').textContent=!online?'Chưa rõ':d.master_enabled?'Đang bật':'Đang tắt';
$('settings-connection').textContent=online?'Kết nối':'Ngoại tuyến';$('device-last-seen').textContent=online?'Đang cập nhật':'Chưa có dữ liệu mới';
$('canal-status').textContent=!online?'Chưa rõ':d.canal_safe?'Có thể dùng':'Đã khóa nguồn kênh';$('canal-detail').textContent=online?fmt(d.salinity_ppt,2)+'‰':'—';
const tankReadingOK=online&&d.tank_sensor_valid!==false&&d.tank_l!==null&&d.tank_l!==undefined&&Number.isFinite(Number(d.tank_l));$('tank-status').textContent=!tankReadingOK?'Không có dữ liệu':d.tank_fill_on?'Đang nạp':Number(d.tank_l)<=400?'Sắp cạn':'Có nước dự trữ';$('tank-liters').textContent=tankReadingOK?fmt(d.tank_l)+' L':'—';
renderLiquid(d,online);renderZones(data,d,online);renderTimedHolds(data);updateControls();const alerts=data.alerts||[];$('alert-count').hidden=!alerts.length;$('alert-count').textContent=alerts.length;
if(noticeVisible===25)renderNotices(data.notifications||[],data.notification_total||0);
$('journal-list').innerHTML=friendlyEvents(data.events||[],data)+'<div class="empty" id="journal-empty-filter" hidden>Chưa có hoạt động thuộc nhóm này.</div>';setJournalFilter();
}
let refreshInFlight=false;
async function refresh(){if(refreshInFlight)return;refreshInFlight=true;try{render(await api('/api/farm'))}catch(e){$('sg-water-metrics').hidden=true;$('sg-water-empty').hidden=false;$('sg-water-empty').textContent='Không có phiên tưới';last=null;$('home-priority').hidden=true;$('home-priority').innerHTML='';renderHomePriority({}, {}, false);$('online-pill').textContent='Ngoại tuyến';$('online-pill').className='connection-pill bad';$('online-pill').setAttribute('aria-label','Trạng thái kết nối ESP32: Ngoại tuyến');$('online-pill').title='hệ thống tưới ngoại tuyến';$('settings-connection').textContent='Ngoại tuyến';$('settings-master').textContent='Chưa rõ';$('canal-status').textContent='Chưa rõ';$('canal-detail').textContent='';$('tank-status').textContent='Chưa rõ';$('tank-liters').textContent='—';renderLiquid({},false);$('home-zones').innerHTML='<div class="zone-brief"><small>Chưa nhận được dữ liệu mới</small></div>';updateControls()}finally{refreshInFlight=false}}
function askOneTime(i){
 const name=last?.farm_config?.zones?.[i-1]?.name||'Vườn '+i;
 openDialog('Cho phép tưới ngoài giờ?',
 `${name} sẽ được xếp lượt tưới theo độ ẩm (tối đa 2 phút mô phỏng tính từ lúc vùng bắt đầu tưới, bao gồm khoảng nghỉ). Nếu vùng kia đang tưới, hệ thống sẽ tự luân phiên và vẫn kiểm tra mọi điều kiện an toàn.`,
 {action:'Cho phép tưới',onConfirm:()=>command('ZONE:'+i+':ONCE',{
 title:'Đã cho phép một lần',success:`${name} sẽ được tưới nếu điều kiện an toàn cho phép.`})});
}
$('home-priority').addEventListener('click',e=>{const b=e.target.closest('.home-once');if(b&&!b.disabled)askOneTime(Number(b.dataset.zone));});
$('alerts-active').addEventListener('click',e=>{const b=e.target.closest('.allow-once-alert');if(b&&!b.disabled)askOneTime(Number(b.dataset.zone));});
function renderTimedHolds(data){
 const holds=data.timed_holds||[];
 for(const zone of [1,2]){
  const el=$('hold-timer-'+zone);if(!el)continue;
  const row=holds.find(h=>Number(h.zone)===zone);
  const held=Boolean(data.live?.['zone'+zone+'_hold']);
  const parent=el.closest('.zone-hold-meta');if(parent)parent.hidden=!held&&!row;
  if(!row){el.textContent=held?'Đến khi bạn bật lại':'';continue;}
  if(row.status==='ACTIVE')el.textContent='Đến '+new Date(row.until_ts*1000).toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  else if(row.status==='PENDING_HOLD')el.textContent='Đang chờ xác nhận';
  else if(row.status==='PENDING_RESUME')el.textContent='Đang chờ bật lại';
  else el.textContent='Chưa xác minh trạng thái';
 }
}
async function changeAutomatic(zone,choice){
 if(busy)return;
 busy=true;updateControls();
 const action=choice==='on'?'resume':choice==='manual'?'hold_manual':'hold_timed';
 const body={action};if(action==='hold_timed')body.minutes=Number(choice);
 try{
  const result=await send('/api/zones/'+zone+'/automatic',body);
  const text=result.confirmed?(action==='resume'?'Đã cho phép tưới tự động.':action==='hold_manual'?'Tưới tự động đã tắt cho đến khi bạn bật lại.':'Đã cập nhật thời hạn tạm ngưng.'):
   (action==='resume'?'Đã gửi yêu cầu bật lại, đang chờ ESP32 xác nhận.':'Đã gửi yêu cầu tạm ngưng, đang chờ ESP32 xác nhận.');
  openDialog(result.confirmed?'Đã cập nhật':'Đang xác nhận',text,{kind:'info'});
  await refresh();
 }catch(err){openDialog('Chưa cập nhật được',err.message,{kind:'error'});}
 finally{busy=false;updateControls();}
}
function askHoldOptions(zone,alreadyHeld=false){
 const row=(last?.timed_holds||[]).find(h=>Number(h.zone)===zone);
 const minutes=row?String(Math.round((Number(row.until_ts)-Date.now()/1000)/60)):'manual';
 const choice=['15','30','60','120','240','1440'].includes(minutes)?minutes:'manual';
 openDialog(alreadyHeld?'Thay đổi thời hạn tạm ngưng':'Tạm ngưng tưới tự động',
   'Chọn thời điểm vùng được phép hoạt động trở lại.',
   {action:'Xác nhận',holdOptions:true,defaultChoice:choice,onConfirm:choice=>changeAutomatic(zone,choice)});
}
$('detailed-zones').addEventListener('click',async e=>{
  const rename=e.target.closest('.zone-rename');
  if(rename){const i=Number(rename.dataset.zone),cfg=last?.farm_config?.zones||[];const oldName=cfg[i-1]?.name||'Vườn '+i;const next=await window.SaltGuardDialog.input('Đổi tên khu vực '+i,oldName);if(next===null)return;const name=next.trim();if(!name||name.length>36){openDialog('Tên không hợp lệ','Tên vùng phải từ 1 đến 36 ký tự.',{kind:'error'});return;}try{const names=[1,2].map(j=>j===i?name:cfg[j-1]?.name||'Vườn '+j);const r=await fetch('/api/farm/zones/names',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({names})});if(!r.ok)throw Error('Không lưu được tên vùng');refresh();}catch(err){openDialog('Không đổi được tên',err.message,{kind:'error'})}return;}
  const change=e.target.closest('.hold-change');
  if(change&&!change.disabled){askHoldOptions(Number(change.dataset.zone),true);return;}
  const once=e.target.closest('.allow-once');
  if(once&&!once.disabled){askOneTime(Number(once.dataset.zone));return;}
  const b=e.target.closest('.zone-hold');if(!b||b.disabled)return;
  const i=Number(b.dataset.zone),held=Boolean(last?.live?.['zone'+i+'_hold']);
  const name=last?.farm_config?.zones?.[i-1]?.name||'Vườn '+i;
  if(!held){askHoldOptions(i);return;}
  openDialog('Cho phép tưới lại?',`${name} sẽ được tưới tự động khi điều kiện cho phép.`,
    {action:'Cho phép tưới',onConfirm:()=>changeAutomatic(i,'on')});
});
$('reload-journal').onclick=()=>{refresh()};
document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>{journalKind=b.dataset.kind;document.querySelectorAll('[data-kind]').forEach(x=>x.classList.toggle('selected',x===b));setJournalFilter()});
const settingsTitles={hours:'Giờ tưới ưu tiên',profile:'Thông tin người dùng',device:'Thông tin thiết bị',password:'Đổi mật khẩu',terms:'Điều khoản & chính sách',logout:'Đăng xuất'};
const prefsKey='saltguard_farmer_ui_preferences_v1';
let userPrefs={};try{userPrefs=JSON.parse(localStorage.getItem(prefsKey)||'{}')||{}}catch(e){userPrefs={}}
function storeUserPrefs(){try{localStorage.setItem(prefsKey,JSON.stringify(userPrefs))}catch(e){toast('Trình duyệt không cho phép lưu thông tin')}}
function closeSettingsView(){if(!$('settings-root'))return;$('settings-root').hidden=false;$('settings-subview').hidden=true;$('page-title').textContent=current==='settings'?'Cài đặt':({home:'Trang chủ',zones:'Khu vực tưới',alerts:'Thông báo',journal:'Nhật ký'}[current]||'Trang chủ');}
function openSettingsView(key){if(!settingsTitles[key])return;
 $('settings-root').hidden=true;$('settings-subview').hidden=false;
 document.querySelectorAll('.settings-subpanel').forEach(p=>p.hidden=p.id!=='settings-panel-'+key);
 $('settings-subtitle').textContent=settingsTitles[key];$('page-title').textContent=settingsTitles[key];
 if(key==='profile'){$('profile-name').value=userPrefs.name||'';$('profile-phone').value=userPrefs.phone||'';$('profile-email').value=userPrefs.email||''}
 window.scrollTo(0,0);
}
$('settings-back').onclick=closeSettingsView;
$('settings-root').querySelector('.account-card').addEventListener('click',e=>{if(!e.target.closest('button'))openSettingsView('profile')});
$('signout-back').onclick=closeSettingsView;
document.querySelectorAll('[data-settings-view]').forEach(b=>b.onclick=()=>openSettingsView(b.dataset.settingsView));
$('profile-display-name').textContent=userPrefs.name||'Người sử dụng SaltGuard';
$('profile-demo-form').onsubmit=e=>{e.preventDefault();userPrefs.name=$('profile-name').value.trim();userPrefs.phone=$('profile-phone').value.trim();userPrefs.email=$('profile-email').value.trim();storeUserPrefs();$('profile-display-name').textContent=userPrefs.name||'Người sử dụng SaltGuard';openDialog('Đã lưu trên máy này','Thông tin được lưu trong trình duyệt, chưa kết nối tài khoản trực tuyến.',{kind:'success'})};
$('notification-pref').setAttribute('aria-checked',String(userPrefs.notifications!==false));
$('notification-pref').onclick=()=>{userPrefs.notifications=$('notification-pref').getAttribute('aria-checked')!=='true';$('notification-pref').setAttribute('aria-checked',String(userPrefs.notifications));storeUserPrefs();toast('Đã lưu lựa chọn hiển thị. Cảnh báo an toàn vẫn luôn có trong tab Thông báo.')};
document.addEventListener('scroll',()=>document.querySelector('.mobile-topbar')?.classList.toggle('is-scrolled',window.scrollY>6),{passive:true});
const initialPage=new URLSearchParams(location.search).get('page');if(pages.includes(initialPage))go(initialPage);

// Phase 2.9: all schedule slots are reported by ESP32 (including enable flags).
const SG_MAX_WINDOWS=4;
let sgWindows=[{enabled:true,start:330,end:540},{enabled:true,start:990,end:1110}];
let sgWindowsDirty=false;
let sgLastScheduleSignature='';
function minutesToTime(value){if(!Number.isInteger(value)||value<0||value>=1440)return null;return String(Math.floor(value/60)).padStart(2,'0')+':'+String(value%60).padStart(2,'0')}
function parseTimeMinutes(v){if(!/^\d{2}:\d{2}$/.test(v))return null;const [h,m]=v.split(':').map(Number);return h<=23&&m<=59?h*60+m:null}
function scheduleFromLive(live){
  if(Array.isArray(live.schedule_windows))return live.schedule_windows.filter(w=>w&&typeof w==='object').slice(0,SG_MAX_WINDOWS).map(w=>({enabled:Boolean(w.enabled),start:Number(w.start),end:Number(w.end)}));
  const keys=['schedule_am_start','schedule_am_end','schedule_pm_start','schedule_pm_end'];
  if(keys.every(k=>Number.isInteger(live[k])))return [{enabled:true,start:live.schedule_am_start,end:live.schedule_am_end},{enabled:true,start:live.schedule_pm_start,end:live.schedule_pm_end}];
  return null;
}
function renderWindowEditor(){
  const root=$('sg-hours-list');if(!root)return;
  root.innerHTML=sgWindows.map((w,i)=>`<div class="sg-hour-card ${w.enabled?'':'inactive'}" data-slot="${i}"><div class="sg-hour-head"><label class="sg-hour-toggle"><input type="checkbox" class="sg-hour-enabled" ${w.enabled?'checked':''}> Khung giờ ${i+1}</label><button type="button" class="sg-hour-delete" data-delete="${i}" aria-label="Xóa khung giờ ${i+1}">Xóa</button></div><div class="sg-hour-fields"><label>Bắt đầu<input type="time" class="sg-hour-start" value="${minutesToTime(w.start)||'05:30'}" ${w.enabled?'':'disabled'}></label><label>Kết thúc<input type="time" class="sg-hour-end" value="${minutesToTime(w.end)||'09:00'}" ${w.enabled?'':'disabled'}></label></div></div>`).join('');
  $('sg-hours-add').disabled=sgWindows.length>=SG_MAX_WINDOWS;
}
$('sg-hours-list').addEventListener('change',e=>{
  const card=e.target.closest('[data-slot]');if(!card)return;
  const idx=Number(card.dataset.slot),w=sgWindows[idx];if(!w)return;
  if(e.target.classList.contains('sg-hour-enabled')){w.enabled=e.target.checked;renderWindowEditor()}
  if(e.target.classList.contains('sg-hour-start'))w.start=parseTimeMinutes(e.target.value);
  if(e.target.classList.contains('sg-hour-end'))w.end=parseTimeMinutes(e.target.value);
  sgWindowsDirty=true;$('sg-hours-message').textContent='Chưa lưu thay đổi.';
});
$('sg-hours-list').addEventListener('click',e=>{const b=e.target.closest('[data-delete]');if(!b)return;sgWindows.splice(Number(b.dataset.delete),1);sgWindowsDirty=true;renderWindowEditor();$('sg-hours-message').textContent='Chưa lưu thay đổi.';});
$('sg-hours-add').addEventListener('click',()=>{if(sgWindows.length>=SG_MAX_WINDOWS)return;sgWindows.push({enabled:true,start:12*60,end:13*60});sgWindowsDirty=true;renderWindowEditor();$('sg-hours-message').textContent='Chưa lưu thay đổi.';});
function validateWindows(ws){
 if(ws.length===0)return 'Cần giữ ít nhất một khung giờ (có thể tắt khung giờ đó).';
 if(ws.length>SG_MAX_WINDOWS)return 'Vượt số khung giờ cho phép.';
 for(const w of ws)if(!Number.isInteger(w.start)||!Number.isInteger(w.end)||w.start<0||w.end>1439||w.start>=w.end)return 'Giờ bắt đầu phải trước giờ kết thúc trong cùng ngày.';
 const active=ws.filter(w=>w.enabled).sort((a,b)=>a.start-b.start);
 for(let i=1;i<active.length;i++)if(active[i].start<active[i-1].end)return 'Các khung giờ đang bật không được chồng nhau.';
 return null;
}
function renderPhase28(live,online){
  const windows=scheduleFromLive(live);
  if(windows){
    const signature=JSON.stringify(windows);
    if(!sgWindowsDirty && signature!==sgLastScheduleSignature){sgWindows=windows.map(w=>({...w}));renderWindowEditor();sgLastScheduleSignature=signature;}
    const active=windows.filter(w=>w.enabled);
    const names=active.map(w=>minutesToTime(w.start)+' – '+minutesToTime(w.end));
    const am=$('sg-am-hours'),pm=$('sg-pm-hours');
    if(am)am.textContent=names[0]||'Đã tắt';if(pm)pm.textContent=names.slice(1).join(' · ')||'Không có';
  }
  const root=$('sg-valve-grid');if(!root)return;
  const names=['Kênh → tưới','Bồn → tưới','Vùng Z1','Vùng Z2','Nạp bồn'];
  root.innerHTML=names.map((n,i)=>{const v=live['valve_v'+(i+1)];const known=online&&typeof v==='boolean';const open=known&&v;return '<div class="sg-valve-status '+(open?'open':'')+'"><strong>V'+(i+1)+' · '+n+'</strong><span>'+(known?(open?'Đang mở':'Đang đóng'):'Chưa có dữ liệu')+'</span></div>'}).join('');
}
$('sg-save-hours').addEventListener('click',async()=>{
  const msg=$('sg-hours-message');const error=validateWindows(sgWindows);
  if(error){msg.textContent=error;return;}
  if(!connected()){msg.textContent='hệ thống tưới ngoại tuyến, chưa thể lưu.';return;}
  const cmd='WIN:'+sgWindows.map(w=>(w.enabled?'1':'0')+','+w.start+','+w.end).join(';');
  const btn=$('sg-save-hours');btn.disabled=true;msg.textContent='Đang chờ ESP32 xác nhận…';
  try{const old=(await api('/api/snapshot')).last_ack;await send('/api/command',{command:cmd});const ack=await waitAck(cmd,old);
    if(ack?.accepted&&ack.message==='WINDOWS_SAVED'){sgWindowsDirty=false;sgLastScheduleSignature='';msg.textContent='Đã lưu trên ESP32.';await refresh()}
    else msg.textContent=ack?'ESP32 từ chối cấu hình.':'Chưa nhận xác nhận từ ESP32.';
  }catch(e){msg.textContent='Không lưu được: '+e.message}
  finally{btn.disabled=false;}
});
renderWindowEditor();

refresh();setInterval(()=>{if(document.visibilityState==='visible'&&!refreshInFlight){refresh();if(current==='alerts'&&noticeVisible>25)refreshNotices()}},1500);
})();

// QR onboarding preview only: never claim that scanning pairs a node to ESP32.
(()=>{const open=document.getElementById('qr-zone-open'),panel=document.getElementById('qr-zone-panel'),close=document.getElementById('qr-zone-close'),video=document.getElementById('qr-zone-video'),status=document.getElementById('qr-zone-status');if(!open)return;let stream=null,active=false;const stop=()=>{active=false;if(stream){stream.getTracks().forEach(t=>t.stop());stream=null}video.srcObject=null;panel.hidden=true};close.addEventListener('click',stop);document.addEventListener('visibilitychange',()=>{if(document.hidden)stop()});open.addEventListener('click',async()=>{panel.hidden=false;status.textContent='Đang xin quyền sử dụng camera...';try{if(!navigator.mediaDevices?.getUserMedia)throw Error('Trình duyệt hoặc kết nối không hỗ trợ camera (cần localhost/HTTPS).');if(!('BarcodeDetector'in window))throw Error('Trình duyệt chưa hỗ trợ đọc QR trực tiếp. Hãy sử dụng Chrome/Edge phiên bản mới.');const detector=new BarcodeDetector({formats:['qr_code']});stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});video.srcObject=stream;await video.play();active=true;status.textContent='Đưa mã QR của cảm biến vào khung hình.';async function scan(){if(!active)return;try{const codes=await detector.detect(video);if(codes.length){const raw=String(codes[0].rawValue||'');if(raw.length>2048)throw Error('Mã quá dài');status.textContent='Đã nhận diện mã QR. Vui lòng chọn khu vực lắp đặt bên dưới.';stop();panel.hidden=false;return}}catch(e){status.textContent='Không đọc được mã: '+e.message}if(active)requestAnimationFrame(scan)}requestAnimationFrame(scan)}catch(e){status.textContent=e.message;if(stream){stream.getTracks().forEach(t=>t.stop());stream=null}}})})();
