/* SaltGuard IoT V5 UI: independent zone expanders, three farmer journal tabs. */
(()=>{'use strict';
const $=(sel,root=document)=>root.querySelector(sel);
const $$=(sel,root=document)=>[...root.querySelectorAll(sel)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function sharedDialog(){
 let root=$('#sg-shared-dialog');
 if(!root){root=document.createElement('dialog');root.id='sg-shared-dialog';root.className='sg-v5-dialog';document.body.append(root);}
 const ask=(title,body,kind,initial='')=>new Promise(resolve=>{
  root.innerHTML='<form method="dialog"><h2>'+esc(title)+'</h2><p>'+esc(body)+'</p>'+
   (kind==='input'?'<input id="sg-v5-input" maxlength="36" required value="'+esc(initial)+'" aria-label="'+esc(title)+'">':'')+
   '<div class="sg-v5-dialog-actions"><button type="button" data-cancel>Hủy</button><button type="submit">'+(kind==='input'?'Lưu thay đổi':'Xác nhận')+'</button></div></form>';
  const field=$('#sg-v5-input',root);
  let done=false;
  const finish=value=>{if(done)return;done=true;root.removeEventListener('close',closed);if(root.open)root.close();resolve(value);};
  const closed=()=>finish(null);
  root.addEventListener('close',closed,{once:true});
  $('[data-cancel]',root).onclick=()=>finish(null);
  $('form',root).onsubmit=e=>{e.preventDefault();if(field&&!field.value.trim())return;finish(field?field.value.trim():true);};
  root.showModal();if(field){field.focus();field.select();}
 });
 window.SaltGuardDialog={
  input:(title,value)=>ask(title,'Nhập tên khu vực mới.','input',value),
  confirm:message=>ask('Xác nhận thao tác',message,'confirm')
 };
}
function makeDetails(title,subtitle,icon){
 const d=document.createElement('details');d.className='sg-v5-zone';
 const summary=document.createElement('summary');
 summary.innerHTML='<span class="sg-v5-zone-head"><span class="sg-v5-zone-icon">'+(icon||'♧')+'</span><span><strong>'+esc(title)+'</strong><small>'+esc(subtitle||'Nhấn để xem thiết lập')+'</small></span></span><span class="sg-v5-chevron" aria-hidden="true"></span>';
 d.append(summary);return d;
}
function expert(){
 const crop=$('#crop-config-form'),water=$('#water-config-form');
 if(!crop||!water)return;
 const zoneRoot=$('#crop-config-zones');
 const enhance=()=>{
  if(!zoneRoot)return;
  $$('#crop-config-zones fieldset').forEach((fieldset,i)=>{
   if(fieldset.closest('.sg-v5-zone'))return;
   const d=makeDetails('Vùng '+(i+1),'Hồ sơ canh tác · Ngưỡng độ ẩm');
   if(i===0)d.open=true;
   fieldset.parentElement.insertBefore(d,fieldset);
   d.append(fieldset);
   const legend=$('legend',fieldset);
   if(legend)legend.classList.add('sg-v5-visually-hidden');
   const update=()=>{const val=$('.e-crop-pick',fieldset)?.value;
     const sub=$('summary small',d);if(sub)sub.textContent=val&&val!=='Chưa thiết lập'?val+' · Chỉnh sửa thiết lập':'Hồ sơ canh tác · Ngưỡng độ ẩm';};
   fieldset.addEventListener('change',update);update();
   const use=$('.e-profile-use',fieldset),save=$('.e-profile-store',fieldset);
   if(use)use.textContent='Nạp hồ sơ';
   if(save)save.textContent='Lưu thành hồ sơ';
  });
 };
 if(zoneRoot){const obs=new MutationObserver(enhance);obs.observe(zoneRoot,{childList:true});enhance();}
 const waterFields=$('.water-fields',water);
 if(waterFields&&!waterFields.dataset.sgV5){
  waterFields.dataset.sgV5='1';
  const labels=$$('label',waterFields);
  if(labels.length===4){
   const sections=[makeDetails('Vùng 1','Lưu lượng và hạn mức nước','◈'),makeDetails('Vùng 2','Lưu lượng và hạn mức nước','◈')];
   sections[0].open=true;
   labels.forEach((label,i)=>sections[Math.floor(i/2)].append(label));
   waterFields.replaceChildren(...sections);
   const ids=[['#water-f1','#water-v1'],['#water-f2','#water-v2']];
   ids.forEach((pair,i)=>{const update=()=>{const a=$(pair[0]),b=$(pair[1]);if(a&&b)
      $('summary small',sections[i]).textContent=a.value+' L/phút · '+b.value+' L/phiên (ước tính)';};
      pair.forEach(id=>$(id)?.addEventListener('input',update));update();});
  }
 }
 const cropTitle=$('h2',crop.closest('.tech-panel'));
 if(cropTitle)cropTitle.textContent='Thiết lập vùng canh tác';
 // Important: Keep the form submit OUTSIDE collapsible regions.
 const note=document.createElement('p');note.className='sg-v5-note';
 note.textContent='Ngưỡng 35/60% và độ mặn khóa kênh 1 ppt (1‰) là ngưỡng mô phỏng, cần hiệu chuẩn theo loại cây và đất trước khi áp dụng thực tế.';
 zoneRoot?.before(note);
 // Restore only after the ESP32 ACK and a matching telemetry frame.
 const section=document.createElement('details');section.className='sg-v5-extra';
 section.innerHTML='<summary><span>Định mức đã lưu trên hệ thống</span><span class="sg-v5-chevron"></span></summary><div class="sg-v5-extra-body"><p id="sg-v5-restored" class="sg-v5-note">Đang tải cấu hình...</p><button type="button" id="sg-v5-restore-btn" class="outline-btn" hidden>Khôi phục định mức gần nhất</button></div>';
 water.after(section);
 async function refreshRestore(){
  const output=$('#sg-v5-restored',section),button=$('#sg-v5-restore-btn',section);
  try {
   const response=await fetch('/api/water/config',{cache:'no-store'});
   if(!response.ok)throw Error('Không đọc được');
   const s=await response.json();
   if(!s.saved){output.textContent='Chưa có định mức được xác nhận và lưu trên máy chủ.';button.hidden=true;return;}
   const v=s.saved.values;
   output.textContent='Đã lưu: V1 '+v[0]+' L/phút, '+v[1]+' L; V2 '+v[2]+' L/phút, '+v[3]+' L. '+(s.mismatch?'Thiết bị đang dùng giá trị khác.':s.online?'Đã đồng bộ.':'Chờ kết nối lại.');
   button.hidden=!s.online||!s.mismatch||s.pending;
  } catch(_err){output.textContent='Chưa đọc được định mức đã lưu.';button.hidden=true;}
 }
 $('#sg-v5-restore-btn',section).onclick=async()=>{
  if(!await window.SaltGuardDialog.confirm('Gửi lại định mức đã xác nhận cho bộ điều khiển?'))return;
  try{
   const r=await fetch('/api/water/config/restore',{method:'POST'});const d=await r.json();
   if(!r.ok)throw Error(d.detail||'Không thể khôi phục');
   $('#sg-v5-restored',section).textContent='Đã gửi yêu cầu, đang chờ thiết bị xác nhận...';
   setTimeout(refreshRestore,4500);
  }catch(e){$('#sg-v5-restored',section).textContent='Chưa khôi phục: '+e.message;}
 };
 refreshRestore();setInterval(refreshRestore,12000);
 // Non-actuating illustrative area/nozzle calculator (not silently changing firmware limits).
 const calc=document.createElement('details');calc.className='sg-v5-extra';
 calc.innerHTML='<summary><span>Tính toán nước tưới theo diện tích (tham khảo)</span><span class="sg-v5-chevron"></span></summary><div class="sg-v5-extra-body sg-v5-calculator">'+
 '<label>Diện tích (m²)<input id="sg-area" type="number" min="1" value="1000"></label><label>Lớp nước (mm)<input id="sg-depth" type="number" min="0.1" step="0.1" value="5"></label>'+
 '<label>Hiệu suất (%)<input id="sg-eff" type="number" min="1" max="100" value="80"></label><label>Số đầu tưới<input id="sg-nozzles" type="number" min="1" value="100"></label>'+
 '<label>Lưu lượng mỗi đầu (L/giờ)<input id="sg-nozzle-flow" type="number" min="0.1" value="2"></label><label>Giới hạn bơm (L/phút)<input id="sg-pump" type="number" min="1" value="60"></label>'+
 '<p id="sg-calc-output" class="sg-v5-note"></p></div>';
 section.after(calc);
 const updateCalc=()=>{
  const v=id=>Number($(id,calc).value),area=v('#sg-area'),depth=v('#sg-depth'),eff=v('#sg-eff'),n=v('#sg-nozzles'),q=v('#sg-nozzle-flow'),pump=v('#sg-pump');
  const out=$('#sg-calc-output',calc);
  if(![area,depth,eff,n,q,pump].every(x=>x>0)||eff>100){out.textContent='Kiểm tra lại thông số đã nhập.';return;}
  const vol=area*depth/(eff/100),rate=n*q/60,actual=Math.min(rate,pump);
  out.textContent='Nước cấp ước tính: '+vol.toLocaleString('vi-VN',{maximumFractionDigits:1})+' L. Tổng lưu lượng đầu tưới: '+rate.toFixed(1)+' L/phút. Thời gian lý thuyết: '+(vol/actual).toFixed(1)+' phút. Chỉ là tính toán tham khảo, không áp dụng lên ESP32; giới hạn phiên mô phỏng hiện tại vẫn giữ nguyên.';
 };
 calc.addEventListener('input',updateCalc);updateCalc();
}
function lab(){
 const panel=$('.sg-custom-panel');if(!panel)return;
 const d=document.createElement('section');d.className='tech-panel sg-v5-diagnostics';
 d.innerHTML='<h2>Kiểm tra sự cố thiết bị</h2><p class="sg-v5-note">Chỉ sử dụng trong mô phỏng, không tác động ngoài môi trường demo.</p>'+
 '<div class="sg-v5-diag-actions"><button type="button" data-sg-fault="TEST:FLOW:ZERO">Mất lưu lượng</button><button type="button" data-sg-fault="TEST:VALVE:STUCK">Van kẹt</button><button type="button" data-sg-fault="TEST:SENSOR:BAD">Lỗi cảm biến</button><button type="button" data-sg-fault="TEST:CLEAR">Xóa lỗi</button></div><p id="sg-v5-diag-result" role="status"></p>';
 panel.after(d);
 d.addEventListener('click',async e=>{
  const btn=e.target.closest('[data-sg-fault]');if(!btn)return;
  const buttons=$$('[data-sg-fault]',d);buttons.forEach(b=>b.disabled=true);
  const output=$('#sg-v5-diag-result',d);output.textContent='Đang gửi lệnh...';
  try{
   const before=await(await fetch('/api/snapshot',{cache:'no-store'})).json();
   const prev=JSON.stringify(before.last_ack||{});
   const r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:btn.dataset.sgFault})});
   const j=await r.json();if(!r.ok)throw Error(j.detail||'Gửi thất bại');
   let ack=null;for(let k=0;k<12;k++){await wait(500);const snap=await(await fetch('/api/snapshot',{cache:'no-store'})).json();
    if(snap.last_ack?.command===btn.dataset.sgFault&&JSON.stringify(snap.last_ack)!==prev){ack=snap.last_ack;break;}}
   output.textContent=ack?(ack.accepted?'Thiết bị đã xác nhận thao tác thử nghiệm.':'Thiết bị đã từ chối lệnh.'):'Đã gửi, chưa nhận được xác nhận từ bộ điều khiển.';
  }catch(err){output.textContent='Không thực hiện được: '+err.message;}finally{buttons.forEach(b=>b.disabled=false);}
 });
}
function farmer(){
 const journal=$('#page-journal');if(!journal)return;
 const heading=$('.section-row h2',journal);if(heading)heading.textContent='Nhật ký & thống kê';
 const tabs=document.createElement('div');tabs.className='sg-v5-journal-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Loại báo cáo');
 const names=[['overview','Tổng quan'],['irrigation','Lịch sử tưới'],['sensors','Cảm biến & sự kiện']];
 tabs.innerHTML=names.map(([key,name],i)=>'<button type="button" role="tab" data-sg-view="'+key+'" aria-selected="'+(i===0?'true':'false')+'" tabindex="'+(i===0?'0':'-1')+'">'+name+'</button>').join('');
 const frameBox=document.createElement('div');frameBox.className='sg-v5-report-wrap';
 frameBox.innerHTML='<iframe id="sg-v5-report" src="/activity?embed=1&view=overview" title="Báo cáo hoạt động của vườn" loading="lazy"></iframe><p class="sg-v5-note">Lượng nước được tính ước lượng vì chưa có đồng hồ đo lưu lượng thực.</p>';
 const events=document.createElement('div');events.id='sg-v5-events';
 const filters=$('.journal-filter',journal),eventList=$('#journal-list',journal);
 if(filters)events.append(filters);if(eventList)events.append(eventList);
 const row=$('.section-row',journal);row.after(tabs,frameBox,events);
 const iframe=$('#sg-v5-report',frameBox);
 function changeView(view){
  $$('button[data-sg-view]',tabs).forEach(b=>{const active=b.dataset.sgView===view;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
  events.hidden=view!=='sensors';
  iframe.src='/activity?embed=1&view='+encodeURIComponent(view);
 }
 tabs.onclick=e=>{const b=e.target.closest('[data-sg-view]');if(b)changeView(b.dataset.sgView);};
 tabs.onkeydown=e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;const buttons=$$('button[data-sg-view]',tabs);let index=buttons.findIndex(b=>b.getAttribute('aria-selected')==='true');index=(index+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;changeView(buttons[index].dataset.sgView);buttons[index].focus();};
 window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==iframe.contentWindow||event.data?.source!=='saltguard-report-resize')return;
  const n=Number(event.data.height);if(Number.isFinite(n)&&n>170&&n<12000)iframe.style.height=Math.ceil(n+18)+'px';
 });
 changeView('overview');
 // Preserve the actual camera scanner. The QR scan is not a fake device pairing.
 const qr=$('#qr-zone-panel'),status=$('#qr-zone-status');
 if(qr&&status){
  const observer=new MutationObserver(()=>{
   if(status.textContent.includes('Đã nhận diện mã QR')&&!$('#sg-v5-qr-step',qr)){
    const step=document.createElement('div');step.id='sg-v5-qr-step';step.className='sg-v5-qr-step';
    step.innerHTML='<strong>Đã nhận diện mã cảm biến</strong><label>Chọn khu vực<select><option>Vùng 1</option><option>Vùng 2</option></select></label><p>Thiết bị mới cần được đăng ký với bộ điều khiển trước khi có thể kích hoạt.</p>';
    qr.append(step);
   }
  });observer.observe(status,{childList:true,characterData:true,subtree:true});
 }
}
function activity(){
 if(!$('#activity-days'))return;
 const params=new URLSearchParams(location.search);
 if(params.get('embed')!=='1')return;
 document.body.classList.add('sg-v5-embedded');
 const view=['overview','irrigation','sensors'].includes(params.get('view'))?params.get('view'):'overview';
 document.body.dataset.sgView=view;
 const communicate=()=>{
  const height=Math.max(document.body.scrollHeight,document.documentElement.scrollHeight);
  parent.postMessage({source:'saltguard-report-resize',height},location.origin);
 };
 if('ResizeObserver'in window)new ResizeObserver(communicate).observe(document.body);
 window.addEventListener('load',communicate);setTimeout(communicate,500);setTimeout(communicate,1700);
}
sharedDialog();expert();lab();farmer();activity();
})();