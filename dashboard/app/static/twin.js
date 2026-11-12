(()=>{
'use strict';
const $=id=>document.getElementById(id);
let scenario='NORMAL';
const num=(v,d=1)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'—';
async function request(url,opts){const r=await fetch(url,{cache:'no-store',...opts});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'HTTP '+r.status);return d;}
function say(msg){$('twin-msg').textContent=msg;}
async function submit(endpoint,body){try{say('Đang gửi lệnh đến MQTT...');await request('/api/twin/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});say('Đã gửi yêu cầu. Quan sát trạng thái ESP32 trong Serial và Dashboard.');await refresh();}catch(e){say('Lỗi: '+e.message);}}
for(const b of document.querySelectorAll('.twin-scenario'))b.addEventListener('click',()=>{
 scenario=b.dataset.scenario;document.querySelectorAll('.twin-scenario').forEach(v=>v.classList.toggle('chosen',v===b));
 if($('twin-pill').textContent==='ĐANG CHẠY')submit('scenario',{scenario});
});
$('twin-start').addEventListener('click',()=>submit('start',{scenario}));
$('twin-stop').addEventListener('click',()=>submit('stop'));
$('twin-prepare-refill').addEventListener('click',()=>submit('lab/prepare-refill'));
$('twin-prepare-irrigation').addEventListener('click',()=>submit('lab/prepare-irrigation'));

function plot(data){let c=$('twin-chart');if(!c||!c.getBoundingClientRect().width)return;
 const w=c.getBoundingClientRect().width,h=c.getBoundingClientRect().height,ratio=Math.min(window.devicePixelRatio||1,2);
 c.width=w*ratio;c.height=h*ratio;const ctx=c.getContext('2d');ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);
 let x0=42,x1=w-15,y0=12,y1=h-28;ctx.font='11px system-ui';ctx.strokeStyle='#e4ece5';ctx.fillStyle='#84978a';
 for(let i=0;i<=4;i++){let yy=y0+(y1-y0)*i/4;ctx.beginPath();ctx.moveTo(x0,yy);ctx.lineTo(x1,yy);ctx.stroke();ctx.fillText((100-25*i)+'%',4,yy+4);}
 for(let [key,color] of [['soil1_pct','#1a9a67'],['soil2_pct','#5096b5']]){
  ctx.beginPath();ctx.lineWidth=2.6;ctx.strokeStyle=color;
  data.forEach((r,i)=>{let x=x0+(x1-x0)*(data.length===1?0.5:i/(data.length-1));let y=y1-Math.max(0,Math.min(100,r[key]||0))/100*(y1-y0);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();
 }
 ctx.fillStyle='#597568';ctx.fillText('Z1 ■    Z2 ■',x0,y1+19);
}
async function refresh(){try{
 const [s,h]=await Promise.all([request('/api/twin'),request('/api/twin/history?limit=160')]);
 $('twin-pill').textContent=s.running?'ĐANG CHẠY':'CHƯA CHẠY';
 $('twin-start').disabled=s.running||!s.broker_connected||!s.esp_online||s.actual_mode==='PRESET';
 $('twin-stop').disabled=!s.running;
 $('twin-prepare-refill').disabled=!s.running||!s.esp_online||s.actual_mode!=='TWIN';
 $('twin-prepare-irrigation').disabled=!s.running||!s.esp_online||s.actual_mode!=='TWIN';
 const w=s.world||{};
 for(const [id,key,d] of [['t-salt','salinity_ppt',2],['t-ph','canal_ph',2],['t-ec','tank_salt_ppt',2],['t-flow','estimated_flow_l_min',1],['t-soil1','soil1_pct',1],['t-soil2','soil2_pct',1],['t-tank','tank_l',1],['t-total','estimated_total_l',2]])$(id).textContent=num(w[key],d);
 $('t-fill').textContent=w.filling?'Đang nạp':'Không nạp';
 $('t-filled').textContent=num(w.fill_total_l,1)+' L';
 $('t-ecsoil').textContent=num(w.soil_ec_z1_ds_m,2)+' / '+num(w.soil_ec_z2_ds_m,2);
 $('t-phsoil').textContent=num(w.soil_ph_z1,2)+' / '+num(w.soil_ph_z2,2);
 $('t-nasoil').textContent=num(w.soil_na_z1_mg_kg,1)+' / '+num(w.soil_na_z2_mg_kg,1);

 $('twin-esp-state').textContent=`Kết nối: ${s.esp_online?'TRỰC TUYẾN':'NGOẠI TUYẾN'} · ESP32 mode: ${s.actual_mode||'—'} · ${s.actual_state||'—'} / ${s.actual_source||'—'} · Bơm: ${s.actual_pump_on?'ON':'OFF'} · Dữ liệu Twin: ${w.controller_fresh?'đang cập nhật':'chờ'}${s.error?' · '+s.error:''}`;
 plot(h.data||[]);
 }catch(e){say('Không đọc được Digital Twin: '+e.message);}}
setInterval(()=>{if($('view-twin').classList.contains('active'))refresh();},2500);refresh();
})();
