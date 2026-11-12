'use strict';
// SaltGuard 2.3 • Dashboard is powered by local FastAPI + SQLite; no fake values.
(()=>{
 const $=id=>document.getElementById(id);
 const state={snap:null,events:[],history:[],view:'overview',lastError:'',requesting:false};
 const viState={IDLE:'Đang chờ tưới',CANAL_Z1:'Đang tưới vùng Z1',CANAL_Z2:'Đang tưới vùng Z2',TANK_Z1:'Đang tưới vùng Z1',TANK_Z2:'Đang tưới vùng Z2',REST:'Đang nghỉ giữa phiên',HOLD_NO_WATER:'Không có nguồn nước',FAULT:'Lỗi cảm biến',PAUSE:'Đã tạm dừng'};
 const viReason={SOIL_OK:'Đất đã đủ ẩm',CANAL_SAFE:'Nguồn kênh đáp ứng điều kiện',USE_TANK:'Đang sử dụng nước dự trữ',SALINITY_OR_CANAL_LOW:'Nguồn kênh không phù hợp',SENSOR_FAULT:'Bộ điều khiển phát hiện lỗi',USER_PAUSE:'Đã nhận lệnh tạm dừng',REMOTE_RESUME:'Đang kiểm tra lại sau tiếp tục',REST:'Chờ hết thời gian nghỉ',FAULT_RECOVERY:'Chờ khôi phục an toàn'};
 const statusCaption=s=>viState[s]||s||'—';
 const fixed=(n,d=1)=>typeof n==='number'&&Number.isFinite(n)?n.toFixed(d):'—';
 const perc=(n)=>Math.max(0,Math.min(100,Number(n)||0));
 const fmt=(ts)=>typeof ts==='number'?new Date(ts*1000).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';
 const stamp=(ts)=>typeof ts==='number'?new Date(ts*1000).toLocaleString('vi-VN'):'—';
 const text=(id,v)=>{if($(id))$(id).textContent=(v??'—')};
 const mark=(id,width)=>{const e=$(id);if(e)e.style.width=perc(width)+'%'};
 const toast=(message)=>{const el=$('toast');el.textContent=message;el.classList.add('show');clearTimeout(toast.handle);toast.handle=setTimeout(()=>el.classList.remove('show'),4000)};
 const api=async(path,opts)=>{
   const response=await fetch(path,{cache:'no-store',...opts});
   if(!response.ok){let d={};try{d=await response.json()}catch{}throw Error(d.detail||`HTTP ${response.status}`)}
   return response.json();
 };
 function resetControlAvailability(){
   const s=state.snap;
   const ready=!!(s&&s.broker_connected&&s.device_online);
   for(const btn of document.querySelectorAll('[data-command]')){
     let allow=ready;
     if(btn.dataset.command.startsWith('ZONES:')) allow=allow && ['DYNAMIC','TWIN'].includes(s.latest?.mode);
     btn.disabled=!allow;
     btn.title=!ready?'Cần kết nối MQTT và nhận dữ liệu ESP32 mới':(!allow?'Chỉ được đổi số vùng ở DYNAMIC':'');
   }
 }
 function renderSnapshot(s){
   state.snap=s;
   const d=s.latest||{},live=!!s.device_online,connected=!!s.broker_connected;
   const active=live&&d.pump_on===true;
   const displayState=live?statusCaption(d.state):'Không có dữ liệu trực tiếp';
   const badge=$('live-badge');
   badge.innerHTML='';const dot=document.createElement('span');dot.className='dot '+(connected&&live?'online':connected?'warn':'');badge.appendChild(dot);
   badge.appendChild(document.createTextNode(connected&&live?'HỆ THỐNG TRỰC TUYẾN':connected?'ESP32 NGOẠI TUYẾN':'MQTT CHƯA KẾT NỐI'));
   badge.classList.toggle('online',connected&&live);
   $('side-led').className='dot '+(connected&&live?'online':connected?'warn':'');
   text('side-network',connected&&live?'ESP32 trực tuyến':connected?'ESP32 chưa gửi dữ liệu':'MQTT không kết nối');
   text('last-seen',d.received_at?fmt(d.received_at):'Chưa có dữ liệu');
   text('hero-heading',displayState);
   text('hero-description',!live?'Không có dữ liệu ESP32 gần đây. Mạch vẫn có thể tự hoạt động; hãy kiểm tra Wokwi và MQTT.':
     d.state==='FAULT'?'Bộ điều khiển đã ngắt bơm do lỗi. Kiểm tra cảm biến trước khi khôi phục.':
     d.state==='HOLD_NO_WATER'?'Không có nguồn nước đáp ứng điều kiện. SaltGuard đang bảo vệ bơm và cây trồng.':
     active?`Đang cấp nước từ ${d.source==='CANAL'?'kênh':'bồn dự trữ'} cho vùng Z${d.zone||'—'}. ESP32 tự quyết định theo điều kiện an toàn.`:
     d.state==='PAUSE'?'Bộ điều khiển đang được tạm dừng. Bơm và các van tưới không hoạt động.':'Hệ thống đang theo dõi nhu cầu tưới và kiểm tra nguồn nước.');
   const showing=live&&(d.pump_on||d.paused_session_pending);
   text('sg-tech-used',showing?fixed(d.irrigation_session_estimated_l,2)+' L':'—');
   text('sg-tech-left',showing?fixed(d.irrigation_session_remaining_l,2)+' L':'—');
   text('sg-tech-remaining',showing?Math.max(0,Math.ceil((Number(d.irrigation_session_budget_ms)-Number(d.irrigation_session_used_ms))/1000))+' giây':'—');
   text('hero-source',live?`Nguồn: ${d.source==='CANAL'?'Kênh':d.source==='TANK'?'Bồn dự trữ':'Không sử dụng'}`:'Nguồn: —');
   text('hero-mode',live?`Chế độ: ${d.mode||'—'}`:'Chế độ: —');
   text('m-salt',fixed(d.salinity_ppt,2)); text('m-tank',fixed(d.tank_l));
   text('m-z1',fixed(d.soil1_pct)); text('m-z2',fixed(d.soil2_pct));
   text('m-salt-note',d.canal_safe===false?'Kênh không an toàn':'Đại lượng độ mặn giả lập');
   text('m-tank-note',`Dung tích bồn: 2000 L${d.tank_ok===false?' · Nước thấp':''}`);
   text('m-z1-note',`Độ ẩm vùng 1 · ${d.zones||'—'} vùng đang hoạt động`);
   text('m-z2-note',d.zones===1?'Vùng Z2 đang vô hiệu hóa':'Độ ẩm vùng 2');
   mark('tank-bar',Number(d.tank_l)/20);mark('z1-bar',d.soil1_pct);mark('z2-bar',d.soil2_pct);
   const flow=$('flow-scene');flow.classList.toggle('pumping',active);
   for(const id of ['canal-node','tank-node','pump-node','flow-z1','flow-z2'])$(id).classList.remove('active');
   if(active){$(d.source==='CANAL'?'canal-node':'tank-node').classList.add('active');$('pump-node').classList.add('active');
     if(d.zone===1)$('flow-z1').classList.add('active');if(d.zone===2)$('flow-z2').classList.add('active');}
   text('flow-pill',active?'ĐANG CẤP NƯỚC':live?'BƠM TẮT':'NGOẠI TUYẾN');
   text('flow-canal',fixed(d.canal_pct)+'% mực nước');text('flow-tank',fixed(d.tank_l)+' L còn lại');
   text('flow-pump',active?'Đang bật':'Đang tắt');
   text('flow-z1-text',active&&d.zone===1?'Van đang mở':'Van đóng');
   text('flow-z2-text',active&&d.zone===2?'Van đang mở':'Van đóng');
   text('control-state',displayState);text('control-reason',viReason[d.reason]||d.reason||'—');
   text('mode-pill',live?d.mode:'—');
   text('setting-broker',s.broker);text('setting-root',s.topic_root);
   text('setting-mqtt',connected?'Đã kết nối':'Mất kết nối');
   text('setting-device',live?'Nhận dữ liệu':'Mất tín hiệu / Chưa chạy');
   text('setting-mode',d.mode||'—');text('setting-last',stamp(d.received_at));
   renderZones(d,live);renderAlert(d,live,connected);
   resetControlAvailability();
 }
 function renderZones(d,live){
   const html=[1,2].map(i=>{
     const humidity=d['soil'+i+'_pct'];
     const disabled=i>Number(d.zones||0)&&live;
     const irrigating=live&&d.pump_on&&d.zone===i;
     const label=!live?'Chưa nhận dữ liệu':disabled?'Đã tắt vùng':irrigating?'Đang được tưới':'Đang theo dõi';
     return `<div class="zone-card"><div class="zone-top"><div class="zone-label">ZONE 0${i} / KHU VỰC TƯỚI</div><span class="zone-status ${disabled?'disabled':''}">${label}</span></div><div class="zone-headline"><strong>${fixed(humidity)}<small>%</small></strong><span class="zone-sub">Độ ẩm<br>đất</span></div><div class="progress"><i style="width:${perc(humidity)}%"></i></div><div class="zone-details"><div>Van tưới: <strong>${irrigating?'MỞ':'ĐÓNG'}</strong></div><div>Điều khiển: <strong>${disabled?'Vô hiệu hóa':'ESP32'}</strong></div></div></div>`;
   }).join('');$('zone-cards').innerHTML=html;
 }
 function renderAlert(d,live,connected){
   const el=$('alert-banner');el.className='alert-banner';
   if(!connected){el.textContent='Python chưa kết nối MQTT. Bạn vẫn có thể xem dữ liệu đã lưu, nhưng không thể điều khiển từ xa.';el.classList.add('warning');return;}
   if(!live){el.textContent='Chưa có bản tin ESP32 mới trong 18 giây. Hãy kiểm tra Wokwi và mạng; dữ liệu đang hiển thị chỉ là lần nhận trước đó.';el.classList.add('warning');return;}
   if(d.state==='FAULT'){el.textContent='CẢNH BÁO: ESP32 báo FAULT. Bơm phải tắt cho đến khi kiểm tra và khôi phục lỗi.';el.classList.add('critical');return;}
   if(d.state==='HOLD_NO_WATER'){el.textContent='CẢNH BÁO: Nguồn nước khả dụng không đủ để tưới. SaltGuard đang tạm ngừng cấp nước.';el.classList.add('warning');return;}
   if(d.canal_safe===false){el.textContent='Nguồn kênh đang bị khóa do điều kiện độ mặn hoặc mực nước. Hệ thống sẽ cân nhắc nước dự trữ theo luật điều khiển.';el.classList.add('warning');return;}
   el.textContent='Chưa phát hiện trạng thái FAULT hoặc HOLD_NO_WATER trong bản tin mới nhất. Các cảm biến đang hoạt động trong môi trường mô phỏng.';
 }
 function renderEvents(events){
   const html=(events||[]).map(e=>{
     const dot=e.severity==='critical'?'critical':e.severity==='warning'?'warning':'';
     const title=escapeHTML(e.title||'Sự kiện');const detail=escapeHTML(e.detail||'');
     return `<div class="event"><span class="event-dot ${dot}"></span><div><div class="event-title">${title}</div><div class="event-detail">${detail}</div></div><span class="event-time">${fmt(e.ts)}</span></div>`;
   });
   $('recent-events').innerHTML=html.slice(0,6).join('')||'<div class="empty">Chưa có sự kiện.</div>';
   $('all-events').innerHTML=html.join('')||'<div class="empty">Chưa có sự kiện nào.</div>';
 }
 function escapeHTML(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
 function plot(id,data,series,{min=null,max=null,unit='',emptyId=null}={}){
   const canvas=$(id);if(!canvas)return;
   const box=canvas.getBoundingClientRect();if(box.width<10)return;
   const ratio=Math.min(window.devicePixelRatio||1,2),w=box.width,h=box.height;
   canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
   const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);
   const pts=(data||[]).filter(r=>typeof r.ts==='number');
   const plotX=46,plotY=14,plotW=w-61,plotH=h-45;
   let vals=[];for(const s of series){for(const r of pts){const v=r[s.key];if(typeof v==='number'&&Number.isFinite(v))vals.push(v)}}
   if(emptyId)$(emptyId).style.display=vals.length?'none':'block';
   if(vals.length===0){ctx.strokeStyle='#f1f4f1';for(let j=0;j<5;j++){let y=plotY+plotH*j/4;ctx.beginPath();ctx.moveTo(plotX,y);ctx.lineTo(w-10,y);ctx.stroke()}return;}
   let lo=min===null?Math.min(...vals):min,hi=max===null?Math.max(...vals):max;
   if(lo===hi){lo-=1;hi+=1}if(min===null)lo-=Math.max(.2,(hi-lo)*.12);if(max===null)hi+=Math.max(.2,(hi-lo)*.12);
   ctx.font='10px DM Sans,system-ui,sans-serif';ctx.textAlign='right';ctx.fillStyle='#96a79a';ctx.strokeStyle='#edf2ef';ctx.lineWidth=1;
   for(let j=0;j<5;j++){const v=hi-(hi-lo)*j/4,y=plotY+plotH*j/4;ctx.beginPath();ctx.moveTo(plotX,y);ctx.lineTo(w-9,y);ctx.stroke();ctx.fillText(v.toFixed(hi-lo<5?1:0)+unit,plotX-8,y+3)}
   const t0=pts[0].ts,t1=pts[pts.length-1].ts;
   const x=(t)=>plotX+(t1===t0?0.5:(t-t0)/(t1-t0))*plotW;
   const y=(v)=>plotY+(hi-v)/(hi-lo)*plotH;
   for(const s of series){
     ctx.strokeStyle=s.color;ctx.lineWidth=2.5;ctx.lineJoin='round';ctx.lineCap='round';
     ctx.beginPath();let started=false;
     for(const p of pts){const v=p[s.key];if(typeof v!=='number'||!Number.isFinite(v)){started=false;continue}if(!started){ctx.moveTo(x(p.ts),y(v));started=true}else ctx.lineTo(x(p.ts),y(v));}
     ctx.stroke();
   }
   ctx.textAlign='left';ctx.fillStyle='#9aa99f';
   if(pts.length){ctx.fillText(fmt(t0).slice(0,5),plotX,h-9);ctx.textAlign='right';ctx.fillText(fmt(t1).slice(0,5),w-10,h-9)}
   let lx=plotX+8;
   for(const s of series){ctx.fillStyle=s.color;ctx.fillRect(lx,1,8,5);lx+=13;ctx.fillStyle='#72867b';ctx.textAlign='left';ctx.fillText(s.name,lx,8);lx+=ctx.measureText(s.name).width+20;}
 }
 const seriesSoil=[{key:'soil1_pct',name:'Z1',color:'#179c6b'},{key:'soil2_pct',name:'Z2',color:'#6aa0bc'}];
 function drawAllCharts(){
   plot('overview-chart',state.history,seriesSoil,{min:0,max:100,unit:'%',emptyId:'overview-empty'});
   plot('soil-chart',state.history,seriesSoil,{min:0,max:100,unit:'%'});
   plot('salinity-chart',state.history,[{key:'salinity_ppt',name:'Độ mặn',color:'#bc905a'}],{min:0,unit:'‰'});
   plot('tank-chart',state.history,[{key:'tank_l',name:'Nước bồn',color:'#429cba'}],{min:0,max:2000,unit:'L'});
   plot('temperature-chart',state.history,[{key:'air_c',name:'Không khí',color:'#d89c5a'},{key:'water_c',name:'Nước',color:'#5b91b4'}],{unit:'°'});
 }
 async function refreshSnapshot(){try{const s=await api('/api/snapshot');renderSnapshot(s);state.lastError=''}catch(err){if(state.lastError!==err.message){toast('Không liên lạc được với Python Backend: '+err.message);state.lastError=err.message}renderSnapshot({latest:null,broker_connected:false,device_online:false,broker:'—',topic_root:'—'})}}
 async function refreshHistory(){try{const range=Number($('history-range').value);const res=await api(`/api/history?minutes=${range}&limit=700`);state.history=res.data;drawAllCharts()}catch(err){console.warn('history',err)}}
 async function refreshEvents(){try{const res=await api('/api/events?limit=70');state.events=res.events;renderEvents(state.events)}catch(err){console.warn('events',err)}}
 function view(name){state.view=name;for(const v of document.querySelectorAll('.view'))v.classList.toggle('active',v.id==='view-'+name);
   for(const btn of document.querySelectorAll('.nav-link'))btn.classList.toggle('selected',btn.dataset.view===name);
   const names={overview:'Tổng quan',zones:'Vùng tưới',history:'Biểu đồ & lịch sử',alerts:'Cảnh báo & sự kiện',settings:'Hệ thống & MQTT'};
   text('page-breadcrumb',names[name]||name);if(name==='history'||name==='overview')requestAnimationFrame(drawAllCharts);
   if(innerWidth<760)window.scrollTo({top:0,behavior:'smooth'});
 }
 async function sendCommand(cmd){
   if(state.requesting)return;
   if(!state.snap?.device_online||!state.snap?.broker_connected){toast('ESP32 hoặc MQTT chưa kết nối');return;}
   if(cmd.startsWith('ZONES:')&&state.snap.latest?.mode!=='DYNAMIC'){toast('Chỉ thay đổi số vùng ở DYNAMIC');return;}
   state.requesting=true;text('cmd-feedback','Đang gửi '+cmd+'…');
   try{const res=await api('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmd})});
      text('cmd-feedback',`Đã gửi ${cmd}. Chờ phản hồi ACK từ ESP32…`);toast(res.note||('Đã gửi '+cmd));
   }catch(e){toast('Không gửi được '+cmd+': '+e.message);text('cmd-feedback',e.message)}finally{state.requesting=false;}
 }
 function exportCSV(){
   const data=state.history;
   if(!data.length){toast('Chưa có dữ liệu để xuất');return}
   const fields=['ts','device_ms','state','source','zone','pump_on','salinity_ppt','soil1_pct','soil2_pct','tank_l','air_c','water_c'];
   const rows=[fields.join(',')];for(const d of data){rows.push(fields.map(k=>{
      const v=k==='ts'?new Date(d.ts*1000).toISOString():d[k];
      const str=v===null||v===undefined?'':String(v);
      return '"'+str.replace(/"/g,'""')+'"';
   }).join(','))}
   const blob=new Blob(['\uFEFF'+rows.join('\r\n')],{type:'text/csv;charset=utf-8'});
   const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='SaltGuard_history_'+new Date().toISOString().slice(0,10)+'.csv';a.click();URL.revokeObjectURL(url);
 }
 document.querySelectorAll('.nav-link').forEach(b=>b.addEventListener('click',()=>view(b.dataset.view)));
 document.querySelectorAll('[data-goto]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.goto)));
 document.querySelectorAll('[data-command]').forEach(b=>b.addEventListener('click',()=>sendCommand(b.dataset.command)));
 $('history-range').addEventListener('change',refreshHistory);$('export-csv').addEventListener('click',exportCSV);
 window.addEventListener('resize',()=>drawAllCharts());
 setInterval(()=>text('header-clock',new Date().toLocaleTimeString('vi-VN')),1000);text('header-clock',new Date().toLocaleTimeString('vi-VN'));
 resetControlAvailability();refreshSnapshot();refreshHistory();refreshEvents();
 setInterval(refreshSnapshot,2500);setInterval(refreshHistory,10000);setInterval(refreshEvents,6500);
})();
