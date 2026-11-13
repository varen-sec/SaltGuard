(()=>{'use strict';const $=id=>document.getElementById(id);const ids=['water-f1','water-v1','water-f2','water-v2'];const form=$('water-config-form');if(!form)return;
let dirty=false;
// Formula: minutes = litres / litresPerMinute.
const showPreview=()=>{const a=Number($('water-f1').value),b=Number($('water-v1').value),c=Number($('water-f2').value),d=Number($('water-v2').value);const time=(l,q)=>{if(!q||!Number.isFinite(l/q))return '—';const secs=Math.min(1800,Math.round(l/q*60));return secs<60?secs+' giây':(secs/60).toFixed(1)+' phút';};$('water-plan-preview').textContent='Dự kiến: Z1 '+time(b,a)+' · Z2 '+time(d,c);};
ids.forEach(id=>$(id).addEventListener('input',()=>{dirty=true;showPreview()}));showPreview();
async function refresh(){if(dirty)return;try{const r=await fetch('/api/snapshot',{cache:'no-store'}),s=await r.json(),d=s.latest||{};if(!s.device_online)return;const fields=[d.irrigation_flow_z1_lpm,d.irrigation_target_z1_l,d.irrigation_flow_z2_lpm,d.irrigation_target_z2_l];if(fields.every(x=>typeof x==='number'&&Number.isFinite(x))){fields.forEach((x,i)=>$(ids[i]).value=x);showPreview();}}catch{}}refresh();setInterval(refresh,8000);
form.addEventListener('submit',async e=>{e.preventDefault();const vals=ids.map(id=>Number($(id).value));if(vals.some((v,i)=>!Number.isFinite(v)||v<1||v>(i%2?500:100))){$('water-config-result').textContent='Thông số phải nằm trong giới hạn cho phép.';return;}const since=Date.now()/1000;const cmd='WATER:'+vals.map(v=>Math.round(v*10)).join(',');const btn=form.querySelector('button');btn.disabled=true;$('water-config-result').textContent='Đang gửi đến ESP32…';try{const r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmd})});const j=await r.json();if(!r.ok)throw Error(j.detail||'Gửi thất bại');$('water-config-result').textContent='Đã gửi định mức; chờ thiết bị xác nhận.';dirty=false;
let finished=false;
for(let attempt=0;attempt<14;attempt++){
 await new Promise(done=>setTimeout(done,850));
 try {
  const response=await fetch('/api/water/config',{cache:'no-store'}),status=await response.json();
  if(status.saved && status.saved.verified_at>=since && status.saved.values.every((value,i)=>Math.abs(value-vals[i])<=.051)){
   $('water-config-result').textContent='Đã lưu và xác nhận trên thiết bị.';finished=true;break;
  }
  if(['REJECTED','SEND_FAILED'].includes(status.last_result)){
   $('water-config-result').textContent='Thiết bị đã từ chối hoặc không nhận lệnh.';finished=true;break;
  }
 } catch(_e){}
}
if(!finished)$('water-config-result').textContent='Chưa xác nhận được kết quả. Kiểm tra kết nối và thử lại.';}catch(err){$('water-config-result').textContent=err.message;}finally{btn.disabled=false;}});
})();