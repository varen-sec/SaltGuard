(()=>{'use strict';const box=document.getElementById('crop-config-zones'),form=document.getElementById('crop-config-form'),message=document.getElementById('crop-config-result');if(!form)return;
let currentZones=[];const h=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Hồ sơ cây trồng: loại cây được ghi nhận, các ngưỡng chỉ tự điền nếu có hồ sơ được kiểm chứng.
const cropLibrary={
 'Lúa':{ph:[5.5,7.5],source:'FAO · Plant nutrition for food security'},
 'Cà chua':{ph:[6.0,6.8],source:'Oregon State University Extension · Managing soil pH'},
 'Ngô (bắp)':{ph:[5.8,6.8],source:'Oregon State University Extension · Managing soil pH'},
 'Khoai tây':{ph:[5.0,5.5],source:'Oregon State University Extension · Managing soil pH'},
 'Bắp cải':{ph:[5.8,7.0],source:'FAO · Plant nutrition for food security'},
 'Đậu tương':{ph:[5.5,7.0],source:'FAO · Plant nutrition for food security'},
 'Cà rốt':{ph:[6.0,6.8],source:'Oregon State University Extension · Managing soil pH'},
 'Cây khác':{ph:null,source:''}
};
const eceFAO={'Lúa':3.0,'Cà chua':2.5,'Ngô (bắp)':1.7,'Khoai tây':1.7,'Bắp cải':1.8,'Đậu tương':5.0,'Cà rốt':1.0};
let serverProfiles=[];
const cropChoices=['Chưa thiết lập',...Object.keys(cropLibrary)];
async function init(){try{const cfg=await(await fetch('/api/farm/config')).json();const profilesResult=await(await fetch('/api/farm/profiles')).json();serverProfiles=profilesResult.items||[];if(!Array.isArray(cfg.zones))throw Error('Thiếu dữ liệu vùng');currentZones=cfg.zones;
box.innerHTML=cfg.zones.map((z,i)=>`<fieldset style="margin:14px 0;padding:18px;border:1px solid #d9e5d8;border-radius:12px"><legend style="font-weight:700">Vùng ${i+1}</legend><div class="setting-line"><label>Loại cây</label><div class="sg-crop-picker"><select class="e-crop-pick" aria-label="Loại cây" tabindex="-1">${cropChoices.map(x=>`<option value="${h(x)}" ${(z.crop===x||(x==='Cây khác'&&!cropChoices.includes(z.crop)))?'selected':''}>${h(x)}</option>`).join('')}</select><button class="sg-crop-trigger" type="button" aria-expanded="false">${h(cropChoices.includes(z.crop)?z.crop:(z.crop?'Cây khác':'Chưa thiết lập'))} ▾</button><div class="sg-crop-menu" hidden>${cropChoices.map(x=>`<button type="button" class="sg-crop-option" data-crop="${h(x)}">${h(x)}</button>`).join('')}</div></div></div><div class="setting-line"><label>Tên cây cụ thể (nếu chọn Cây khác)</label><input class="e-crop-custom" maxlength="60" value="${h(cropChoices.includes(z.crop)?'':z.crop)}" placeholder="Nhập tên cây"></div><div class="setting-line"><label>Loại đất</label><select class="e-soil-type"><option>Chưa thiết lập</option>${['Đất cát','Đất thịt','Đất sét','Giá thể','Khác'].map(x=>`<option ${z.soil_type===x?'selected':''}>${h(x)}</option>`).join('')}</select></div><div class="setting-line"><label>Giai đoạn sinh trưởng</label><select class="e-growth-stage"><option>Chưa thiết lập</option>${['Cây con','Sinh trưởng','Ra hoa','Nuôi quả/hạt','Thu hoạch','Khác'].map(x=>`<option ${z.growth_stage===x?'selected':''}>${h(x)}</option>`).join('')}</select></div><div class="setting-line"><label>Hồ sơ tưới đã lưu</label><select class="e-profile-choice"><option value="">— Chọn hồ sơ —</option>${serverProfiles.map((p,k)=>`<option value="${k}">${h(p.crop)} · ${h(p.soil_type)} · ${h(p.growth_stage)} (${p.soil_start_pct}/${p.soil_stop_pct}%)</option>`).join('')}</select></div><div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 14px"><button type="button" class="outline-btn e-profile-use">Áp dụng hồ sơ vào vùng</button><button type="button" class="outline-btn e-profile-store">Lưu hồ sơ từ vùng này</button></div><div class="setting-line"><label>Bắt đầu tưới khi độ ẩm ≤ (%)</label><input type="number" class="e-start" min="5" max="80" step="1" required value="${z.soil_start_pct??35}"></div><div class="setting-line"><label>Dừng tưới khi độ ẩm ≥ (%)</label><input type="number" class="e-stop" min="10" max="95" step="1" required value="${z.soil_stop_pct??60}"></div>${[['e-ec','EC đất tối đa (dS/m)' ,'soil_ec_max'],['e-na','Na tối đa (mg/kg)','soil_na_max'],['e-phmin','pH đất tối thiểu','soil_ph_min'],['e-phmax','pH đất tối đa','soil_ph_max'],['e-wet','Độ ẩm cao cảnh báo (%)','soil_high_warn_pct']].map(a=>`<div class="setting-line"><label>${a[1]}</label><input type="number" step="any" min="0" class="${a[0]}" value="${z[a[2]]??''}" placeholder="Chưa cấu hình"></div>`).join('')}<div class="e-crop-reference" aria-live="polite"></div></fieldset>`).join('');box.querySelectorAll('fieldset').forEach(f=>{f.querySelector('.e-crop-custom').closest('.setting-line').hidden=f.querySelector('.e-crop-pick').value!=='Cây khác';});}
catch(e){message.textContent='Không tải được cấu hình: '+e.message}}
// Hồ sơ ngưỡng do chính kỹ sư lưu tại trình duyệt; không phát sinh ngưỡng mặc định giả định.
const profileFields=['e-ec','e-na','e-phmin','e-phmax','e-wet'];
const profileKey='saltguard.cropProfiles.v1';
const getProfiles=()=>{try{return JSON.parse(localStorage.getItem(profileKey)||'{}')}catch{return {}}};
function applyCrop(f,crop){const profile=getProfiles()[crop],reference=cropLibrary[crop];profileFields.forEach((cls,i)=>{let value=profile?.[i]??'';if(!profile && reference?.ph && (i===2||i===3))value=reference.ph[i-2];f.querySelector('.'+cls).value=value;});f.querySelector('.e-crop-custom').closest('.setting-line').hidden=crop!=='Cây khác';
const ref=f.querySelector('.e-crop-reference');if(ref)ref.textContent=eceFAO[crop]!==undefined?'FAO: ECe ngưỡng giảm năng suất ≈ '+eceFAO[crop]+' dS/m (chiết bão hòa). KHÔNG tự áp dụng vào ngưỡng EC đất nếu cảm biến không đo ECe. Na và độ ẩm cần hiệu chuẩn theo đất/giai đoạn cây.':'';
message.textContent=profile?'Đã điền hồ sơ đã lưu cho '+crop+'.':reference?.ph?'Đã điền khoảng pH tham khảo cho '+crop+'; có thể chỉnh sửa.':'Chưa có ngưỡng tham khảo cho cây này.';}
box.addEventListener('click',e=>{const trigger=e.target.closest('.sg-crop-trigger'),option=e.target.closest('.sg-crop-option');if(trigger){const picker=trigger.closest('.sg-crop-picker'),menu=picker.querySelector('.sg-crop-menu'),opening=menu.hidden;box.querySelectorAll('.sg-crop-menu').forEach(m=>m.hidden=true);box.querySelectorAll('.sg-crop-trigger').forEach(b=>b.setAttribute('aria-expanded','false'));menu.hidden=!opening;trigger.setAttribute('aria-expanded',String(opening));return;}if(option){const picker=option.closest('.sg-crop-picker'),sel=picker.querySelector('.e-crop-pick'),crop=option.dataset.crop;sel.value=crop;picker.querySelector('.sg-crop-trigger').textContent=crop+' ▾';picker.querySelector('.sg-crop-menu').hidden=true;picker.querySelector('.sg-crop-trigger').setAttribute('aria-expanded','false');applyCrop(picker.closest('fieldset'),crop);}});
box.addEventListener('click',async e=>{
  const f=e.target.closest('fieldset');if(!f)return;
  if(e.target.closest('.e-profile-use')){
    const id=f.querySelector('.e-profile-choice').value;
    if(id===''){message.textContent='Hãy chọn một hồ sơ trước.';return;}
    const p=serverProfiles[Number(id)];if(!p)return;
    const sel=f.querySelector('.e-crop-pick');sel.value=cropChoices.includes(p.crop)?p.crop:'Cây khác';
    f.querySelector('.e-crop-custom').value=cropChoices.includes(p.crop)?'':p.crop;
    f.querySelector('.e-crop-custom').closest('.setting-line').hidden=sel.value!=='Cây khác';
    f.querySelector('.sg-crop-trigger').textContent=(cropChoices.includes(p.crop)?p.crop:'Cây khác')+' ▾';
    f.querySelector('.e-soil-type').value=p.soil_type;
    f.querySelector('.e-growth-stage').value=p.growth_stage;
    f.querySelector('.e-start').value=p.soil_start_pct;
    f.querySelector('.e-stop').value=p.soil_stop_pct;
    message.textContent='Đã nạp hồ sơ vào vùng; nhấn Lưu và gửi ngưỡng đến ESP32 để kích hoạt.';
  }
  if(e.target.closest('.e-profile-store')){
    const crop=f.querySelector('.e-crop-pick').value==='Cây khác'?f.querySelector('.e-crop-custom').value.trim():f.querySelector('.e-crop-pick').value;
    const profile={crop,soil_type:f.querySelector('.e-soil-type').value,growth_stage:f.querySelector('.e-growth-stage').value,
      soil_start_pct:Number(f.querySelector('.e-start').value),soil_stop_pct:Number(f.querySelector('.e-stop').value)};
    try{const r=await fetch('/api/farm/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(profile)});
      const v=await r.json();if(!r.ok)throw Error(typeof v.detail==='string'?v.detail:'Ngưỡng/hồ sơ không hợp lệ');
      const data=await(await fetch('/api/farm/profiles')).json();serverProfiles=data.items||[];
      box.querySelectorAll('.e-profile-choice').forEach(sel=>{sel.innerHTML='<option value="">— Chọn hồ sơ —</option>'+serverProfiles.map((x,k)=>`<option value="${k}">${h(x.crop)} · ${h(x.soil_type)} · ${h(x.growth_stage)} (${x.soil_start_pct}/${x.soil_stop_pct}%)</option>`).join('');});
      message.textContent='Đã lưu hồ sơ tưới vào Backend. Ngưỡng chưa đổi trên ESP32 cho đến khi lưu cấu hình vùng.';
    }catch(err){message.textContent='Không lưu được hồ sơ: '+err.message;}
  }
});
document.addEventListener('click',e=>{if(!e.target.closest('.sg-crop-picker')){box.querySelectorAll('.sg-crop-menu').forEach(m=>m.hidden=true);box.querySelectorAll('.sg-crop-trigger').forEach(b=>b.setAttribute('aria-expanded','false'));}});

form.addEventListener('submit',async e=>{e.preventDefault();let zones=[...box.querySelectorAll('fieldset')].map((f,i)=>{let n=c=>f.querySelector('.'+c).value.trim(),v=c=>{let s=n(c);return s?Number(s):null};return {name:currentZones[i].name,crop:(n('e-crop-pick')==='Cây khác'?(n('e-crop-custom')||'Cây khác'):n('e-crop-pick')),irrigation_mode:currentZones?.[i]?.irrigation_mode||'MOISTURE',soil_high_warn_pct:v('e-wet'),soil_type:n('e-soil-type'),growth_stage:n('e-growth-stage'),soil_start_pct:Number(n('e-start')),soil_stop_pct:Number(n('e-stop')),soil_ec_max:v('e-ec'),soil_na_max:v('e-na'),soil_ph_min:v('e-phmin'),soil_ph_max:v('e-phmax')}});try{let r=await fetch('/api/farm/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({zones})});let d=await r.json();if(!r.ok)throw Error(JSON.stringify(d.detail));const profiles=getProfiles();[...box.querySelectorAll('fieldset')].forEach(f=>{const crop=f.querySelector('.e-crop-pick').value;if(crop!=='Chưa thiết lập'&&crop!=='Cây khác')profiles[crop]=profileFields.map(cls=>f.querySelector('.'+cls).value.trim())});localStorage.setItem(profileKey,JSON.stringify(profiles));message.textContent='Đã gửi ngưỡng đến ESP32; đang chờ telemetry xác nhận…';
  const deadline=Date.now()+45000;
  async function verify(){try{const r=await fetch('/api/farm/config/sync',{cache:'no-store'});const v=await r.json();
    if(v.synced){message.textContent='ESP32 đã xác nhận đủ 4 ngưỡng tưới. Hồ sơ canh tác đã lưu.';return;}
    if(Date.now()<deadline){setTimeout(verify,1500);return;}
    message.textContent='Đã lưu hồ sơ, nhưng ESP32 chưa xác nhận ngưỡng: '+v.status+'. Kiểm tra Wokwi/MQTT.';
  }catch(err){message.textContent='Không xác minh được ESP32: '+err.message;}}
  verify();}catch(x){message.textContent='Không lưu được: '+x.message}});

async function lab(path,ok){const result=document.getElementById('soil-test-result');
 const buttons=['soil-warning-test','soil-warning-restore'].map(id=>document.getElementById(id));
 buttons.forEach(b=>b.disabled=true);
 try{const r=await fetch(path,{method:'POST',cache:'no-store'});const d=await r.json();
  if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Không thực hiện được');
  result.textContent=ok+' · Mở giao diện nông dân → Thông báo để xem kết quả. Không có lệnh tưới nào được gửi.';
 }catch(e){result.textContent='Chưa hoàn thành: '+e.message}
 finally{buttons.forEach(b=>b.disabled=false)}
}
const btnWarn=document.getElementById('soil-warning-test');
const btnReset=document.getElementById('soil-warning-restore');
if(btnWarn)btnWarn.addEventListener('click',()=>lab('/api/twin/lab/soil-warning','Đã tạo tình huống đất vượt ngưỡng'));
if(btnReset)btnReset.addEventListener('click',()=>lab('/api/twin/lab/soil-restore','Đã khôi phục chỉ số đất mô phỏng'));

init();})();