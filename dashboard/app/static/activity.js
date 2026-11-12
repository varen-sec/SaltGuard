(()=>{'use strict';
const $=id=>document.getElementById(id);
const escapeHTML=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateOf=ts=>new Date(Number(ts)*1000);
const stamp=ts=>dateOf(ts).toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const clock=ts=>dateOf(ts).toLocaleString('vi-VN',{hour:'2-digit',minute:'2-digit',hour12:false});
const day=ts=>dateOf(ts).toLocaleDateString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric'});
const val=(v,d=1)=>v!==null&&v!==undefined&&Number.isFinite(Number(v))?Number(v).toLocaleString('vi-VN',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const duration=v=>v===null||v===undefined?'—':`${val(v,1)} giây`;
// Smooth piecewise cubic: slopes limited to each local segment so there is no
// overshoot, invented peaks, or values beyond adjacent real observations.
function smoothPath(points){
 if(points.length<2)return '';
 let d=`M ${points[0][0].toFixed(2)} ${points[0][1].toFixed(2)}`;
 for(let i=0;i<points.length-1;i++){
  const a=points[i],b=points[i+1],dist=b[0]-a[0];
  if(dist<=0){d+=` L ${b[0].toFixed(2)} ${b[1].toFixed(2)}`;continue;}
  // Horizontal endpoint tangents yield a smooth S curve between observations.
  // This is visual interpolation only. The original data points remain unchanged.
  d+=` C ${(a[0]+dist*.42).toFixed(2)} ${a[1].toFixed(2)}, ${(b[0]-dist*.42).toFixed(2)} ${b[1].toFixed(2)}, ${b[0].toFixed(2)} ${b[1].toFixed(2)}`;
 }
 return d;
}
function lineChart(samples,field,label,unit,baseMax,color,thresholds){
 const data=samples.filter(x=>x[field]!==null&&x[field]!==undefined&&Number.isFinite(Number(x[field]))&&Number.isFinite(Number(x.ts))).sort((a,b)=>Number(a.ts)-Number(b.ts));
 if(data.length<2)return `<div class="activity-chart"><div class="activity-chart-head"><b>${escapeHTML(label)}</b></div><div class="activity-empty">Chưa đủ dữ liệu để hiển thị diễn biến.</div></div>`;
 const minTs=Number(data[0].ts),maxTs=Number(data[data.length-1].ts),spread=Math.max(1,maxTs-minTs);
 const maxObserved=Math.max(...data.map(x=>Number(x[field])));
 // Salinity must be auto-scaled; 3 ppt as a hard maximum can hide high readings.
 const axisMax=field==='salinity_ppt'?Math.max(1,Math.ceil(maxObserved*1.25*2)/2):baseMax;
 const w=720,h=225,left=55,right=22,top=21,bottom=39;
 const px=x=>left+(Number(x.ts)-minTs)/spread*(w-left-right);
 const py=v=>h-bottom-Math.min(axisMax,Math.max(0,Number(v)))/axisMax*(h-top-bottom);
 const gaps=[];for(let i=1;i<data.length;i++)if(Number(data[i].ts)>Number(data[i-1].ts))gaps.push(Number(data[i].ts)-Number(data[i-1].ts));
 const sorted=[...gaps].sort((a,b)=>a-b),median=sorted.length?sorted[Math.floor(sorted.length/2)]:60;
 // Preserve a readable continuous curve for sparse demonstration samples.
 // Only split at a real multi-day recording outage, not ordinary sparse sampling.
 const gapThreshold=Math.max(86400,median*30);
 let group=[],groups=[];
 for(const datum of data){if(group.length&&Number(datum.ts)-Number(group[group.length-1].ts)>gapThreshold){groups.push(group);group=[];}group.push(datum);}
 if(group.length)groups.push(group);
 const grid=[0,.25,.5,.75,1].map(p=>{const y=py(p*axisMax);const tick=field==='salinity_ppt'?(p*axisMax).toLocaleString('vi-VN',{maximumFractionDigits:2}):Math.round(p*axisMax);return `<line x1="${left}" y1="${y}" x2="${w-right}" y2="${y}" class="activity-grid-line"/><text x="${left-9}" y="${y+4}" class="activity-tick" text-anchor="end">${tick}</text>`;}).join('');
 const ticks=[0,.25,.5,.75,1].map(p=>{const ts=minTs+p*spread,x=left+p*(w-left-right);return `<text x="${x}" y="${h-13}" text-anchor="${p===0?'start':p===1?'end':'middle'}" class="activity-tick">${escapeHTML(spread>86400?stamp(ts):clock(ts))}</text>`;}).join('');
 const dayLabels=day(minTs)===day(maxTs)?`Ngày ${day(minTs)}`:`${day(minTs)} – ${day(maxTs)}`;
 const refs=(thresholds||[]).filter(t=>Number.isFinite(Number(t.value))&&Number(t.value)>=0&&Number(t.value)<=axisMax);
 const referenceLines=refs.map(t=>`<line x1="${left}" x2="${w-right}" y1="${py(t.value)}" y2="${py(t.value)}" stroke="${t.color}" stroke-width="1.6" stroke-dasharray="6 5" opacity=".8"/>`).join('');
 const paths=groups.map(g=>g.length===1?`<circle cx="${px(g[0])}" cy="${py(g[0][field])}" r="3" fill="${color}"/>`:`<path d="${smoothPath(g.map(x=>[px(x),py(x[field])]))}" stroke="${color}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`).join('');
 // Every observed sample is inspectable; the curved line does not add readings.
 const marks=data.map((x,i)=>{const xx=px(x),yy=py(x[field]);return `<circle class="activity-data-point" cx="${xx.toFixed(2)}" cy="${yy.toFixed(2)}" r="${data.length>70?5:6}" tabindex="0" role="img" aria-label="${escapeHTML(stamp(x.ts))}: ${escapeHTML(val(x[field],1))} ${escapeHTML(unit)}" fill="${color}" fill-opacity="${data.length>65?0.015:0.9}" stroke="${color}" stroke-opacity="${data.length>65?0:0.7}" data-index="${i}"><title>${escapeHTML(stamp(x.ts))}: ${escapeHTML(val(x[field],1))} ${escapeHTML(unit)}</title></circle>`;}).join('');
 const latest=data[data.length-1],first=data[0],diff=Number(latest[field])-Number(first[field]);
 const change=Math.abs(diff)<.05?'Không đổi':`${diff>0?'Tăng':'Giảm'} ${val(Math.abs(diff),1)} ${unit}`;
 const legend=refs.length?`<div class="activity-chart-references">${refs.map(t=>`<span><i style="border-color:${t.color}"></i>${escapeHTML(t.label)} ${val(t.value,0)}${escapeHTML(unit)}</span>`).join('')}</div>`:'';
 return `<div class="activity-chart"><div class="activity-chart-head"><div><b>${escapeHTML(label)}</b></div><strong style="color:${color}">${val(latest[field],1)} <span>${escapeHTML(unit)}</span></strong></div><div class="activity-chart-plot"><svg role="img" aria-label="${escapeHTML(label)} theo thời gian; trục ngang là giờ, trục dọc là ${escapeHTML(unit)}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet"><text x="6" y="13" class="activity-axis-label">${escapeHTML(unit)}</text>${grid}${referenceLines}${paths}${marks}${ticks}</svg></div>${legend}<div class="activity-chart-detail" aria-live="polite"></div></div>`;
}
function waterChart(days){
 if(!days.length)return '<p class="activity-empty">Chưa có dữ liệu thống kê.</p>';
 const entries=days.map(x=>({date:String(x.date||''),z1:Math.max(0,Number(x.z1)||0),z2:Math.max(0,Number(x.z2)||0),c1:Math.max(0,Number(x.z1_count)||0),c2:Math.max(0,Number(x.z2_count)||0)}));
 const max=Math.max(0,...entries.map(x=>x.z1+x.z2));
 if(max<=0)return '<p class="activity-empty">Chưa có lượng nước ước tính được xác minh trong khoảng đã chọn.</p>';
 const magnitude=Math.pow(10,Math.floor(Math.log10(max/4)));
 const step=[1,2,2.5,5,10].map(n=>n*magnitude).find(n=>n*4>=max)||10*magnitude;
 const axisMax=step*4;
 const ticks=[0,1,2,3,4].map(i=>`<span style="bottom:${i*25}%">${val(i*step,step<1?2:step<2?1:0)}</span>`).join('');
 const lines=[0,25,50,75,100].map(n=>`<span style="bottom:${n}%"></span>`).join('');
 const bars=entries.map((x,i)=>{
  const pct=v=>(v/axisMax*100).toFixed(3)+'%';
  const shortDate=x.date.slice(5).replace('-','/');
  const displayDate=entries.length>15&&i%5!==0?'':shortDate;
  const name=`${escapeHTML(shortDate)}: Z1 ${val(x.z1,2)} L; Z2 ${val(x.z2,2)} L; tổng ${val(x.z1+x.z2,2)} L`;
  return `<div class="water-bar-group"><button type="button" class="water-bar-button" aria-label="${name}" aria-expanded="false" data-date="${escapeHTML(x.date)}" data-z1="${x.z1}" data-z2="${x.z2}" ><span class="water-bar-stack"><span class="water-bar-z2" style="height:${pct(x.z2)}"></span><span class="water-bar-z1" style="height:${pct(x.z1)}"></span></span></button><span class="water-date">${escapeHTML(displayDate)}</span></div>`;
 }).join('');
 return `<div class="water-chart" aria-label="Lượng nước tưới ước tính theo ngày, đơn vị lít"><div class="water-axis-title">L</div><div class="water-chart-body"><div class="water-y-axis" aria-hidden="true">${ticks}</div><div class="water-plot"><div class="water-grid" aria-hidden="true">${lines}</div><div class="water-bars">${bars}</div></div></div><div class="water-tooltip" role="status" aria-live="polite" hidden></div></div><div class="water-legend"><span><i class="legend-z1"></i>Z1</span><span><i class="legend-z2"></i>Z2</span></div>`;
}
function waterTooltip(button){
 const wrap=button?.closest('.water-chart');if(!wrap)return;
 const tip=wrap.querySelector('.water-tooltip');
 const z1=Number(button.dataset.z1),z2=Number(button.dataset.z2);
 tip.innerHTML=`<div class="water-tooltip-row"><span>Z1</span><b>${val(z1,2)} L</b></div><div class="water-tooltip-row"><span>Z2</span><b>${val(z2,2)} L</b></div><div class="water-tooltip-total"><span>Tổng</span><b>${val(z1+z2,2)} L</b></div>`;
 tip.hidden=false;
 wrap.querySelectorAll('.water-bar-button').forEach(el=>el.setAttribute('aria-expanded',String(el===button)));
 const plot=wrap.querySelector('.water-plot');
 const center=button.getBoundingClientRect().left+button.getBoundingClientRect().width/2-wrap.getBoundingClientRect().left;
 const half=tip.offsetWidth/2;
 tip.style.left=Math.max(half+6,Math.min(wrap.clientWidth-half-6,center))+'px';
}
function hideWaterTooltip(wrap){
 if(!wrap)return;
 const tip=wrap.querySelector('.water-tooltip');if(tip)tip.hidden=true;
 wrap.querySelectorAll('.water-bar-button').forEach(b=>b.setAttribute('aria-expanded','false'));
}
function renderSegments(rows){
 if(!rows.length)return '<p class="activity-empty">Chưa có lịch sử tưới trong khoảng đã chọn.</p>';
 return `<div class="activity-scroll"><table><thead><tr><th>Thời điểm</th><th>Vùng</th><th>Nguồn</th><th>Thời lượng</th><th>Nước ước tính</th><th>Kết quả</th></tr></thead><tbody>${rows.map(x=>{
  const completed=x.status==='COMPLETED';
  return `<tr><td><strong>${escapeHTML(clock(x.started_at))}</strong><span class="activity-time-date">${escapeHTML(day(x.started_at))}</span></td><td>Vùng ${Number(x.zone)}</td><td>${x.source==='CANAL'?'Kênh':x.source==='TANK'?'Bồn':'—'}</td><td>${escapeHTML(duration(x.duration_sim_seconds))}</td><td>${x.water_estimated_l===null||x.water_estimated_l===undefined?'—':(x.water_quality==='PARTIAL'?'≥ ':'')+val(x.water_estimated_l,2)+' L'+(x.water_quality==='PARTIAL'?' (một phần)':'')}</td><td><span class="activity-tag${completed?'':' incomplete'}">${completed?'Hoàn tất':'Chưa xác minh'}</span>${x.end_reason?`<small>${escapeHTML(x.end_reason)}</small>`:''}</td></tr>`;
 }).join('')}</tbody></table></div>`;
}
async function load(){
 const days=Number($('activity-days').value),zone=Number($('activity-zone').value);
 $('activity-message').textContent='Đang cập nhật…';
 $('activity-export').href=`/api/activity/export.csv?days=${days}&zone=${zone}`;
 try{
  const resp=await fetch(`/api/activity/report?days=${days}&zone=${zone}`,{cache:'no-store'});
  if(!resp.ok)throw Error(`HTTP ${resp.status}`);
  const out=await resp.json(),s=out.summary;
  $('kpi-verified').textContent=s.verified_segments;
  $('kpi-duration').textContent=duration(s.pump_sim_seconds);
  $('kpi-unverified').textContent=s.unverified_segments;
  $('kpi-active').textContent=s.active?`Vùng ${s.active.zone}`:'Không';
  const hasWater=s.water_verified_segments>0;
  $('water-total').textContent=hasWater?`${val(s.estimated_water_l,2)} L`:'—';
  $('water-z1').textContent=hasWater?`${val(s.zone1_estimated_water_l,2)} L`:'—';
  $('water-z2').textContent=hasWater?`${val(s.zone2_estimated_water_l,2)} L`:'—';
  $('activity-water-chart').innerHTML=waterChart(out.water_daily||[]);
  const partial=$('activity-partial-water');
  if(partial){partial.textContent=s.water_partial_segments>0
    ?`Có ${s.water_partial_segments} đoạn chỉ ghi được tối thiểu ${val(s.water_partial_l,2)} L (chưa đủ dữ liệu để cộng vào tổng).`
    :'';}
  let config=null;
  try{const cfg=await fetch('/api/farm/config',{cache:'no-store'});if(cfg.ok)config=await cfg.json();}catch(_){/* Chart remains useful without config. */}
  const refs=i=>{const z=config?.zones?.[i];return z?[{label:'Tưới ≤',value:z.soil_start_pct,color:'#c27b2b'},{label:'Dừng ≥',value:z.soil_stop_pct,color:'#268c6a'}]:[];};
  $('activity-charts').innerHTML=lineChart(out.trends,'soil1_pct','Độ ẩm vùng 1','%',100,'#15875b',refs(0))+lineChart(out.trends,'soil2_pct','Độ ẩm vùng 2','%',100,'#417ebb',refs(1))+lineChart(out.trends,'salinity_ppt','Độ mặn kênh','ppt',3,'#b57425',[]);
  $('activity-table').innerHTML=renderSegments(out.segments);
  $('activity-count').textContent=`${out.segments.length} bản ghi`;
  $('activity-message').textContent='';
 }catch(e){$('activity-message').textContent='Không tải được dữ liệu. Vui lòng thử lại.';}
}
$('activity-charts').addEventListener('pointerover',showPoint);
$('activity-charts').addEventListener('focusin',showPoint);
$('activity-charts').addEventListener('click',showPoint);
function showPoint(event){
 const point=event.target.closest?.('.activity-data-point');if(!point)return;
 const chart=point.closest('.activity-chart'),detail=chart?.querySelector('.activity-chart-detail');
 if(detail)detail.textContent=point.getAttribute('aria-label')||'';
}
const waterContainer=$('activity-water-chart');
waterContainer.addEventListener('pointerover',e=>{const b=e.target.closest?.('.water-bar-button');if(b&&e.pointerType!=='touch')waterTooltip(b);});
waterContainer.addEventListener('focusin',e=>{const b=e.target.closest?.('.water-bar-button');if(b)waterTooltip(b);});
waterContainer.addEventListener('click',e=>{const b=e.target.closest?.('.water-bar-button');if(b){const open=b.getAttribute('aria-expanded')==='true';if(open&&e.detail!==0)hideWaterTooltip(b.closest('.water-chart'));else waterTooltip(b);}});
waterContainer.addEventListener('pointerleave',e=>{if(e.pointerType!=='touch'&&!waterContainer.contains(document.activeElement))hideWaterTooltip(waterContainer.querySelector('.water-chart'));});
document.addEventListener('pointerdown',e=>{if(!waterContainer.contains(e.target))hideWaterTooltip(waterContainer.querySelector('.water-chart'));});
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideWaterTooltip(waterContainer.querySelector('.water-chart'));});
$('activity-refresh').addEventListener('click',load);
$('activity-days').addEventListener('change',load);
$('activity-zone').addEventListener('change',load);
load();
})();
