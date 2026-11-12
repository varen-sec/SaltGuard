(()=>{'use strict';const $=id=>document.getElementById(id);
const next=new URLSearchParams(location.search).get('next');
const allowed=['/expert','/lab','/technical/advanced'];const target=allowed.includes(next)?next:'/expert';
$('pin').addEventListener('input',e=>{e.target.value=e.target.value.replace(/\D/g,'').slice(0,4);$('pin-error').textContent='';});
$('pin-form').addEventListener('submit',async e=>{e.preventDefault();const pin=$('pin').value;if(!/^\d{4}$/.test(pin)){$('pin-error').textContent='Nhập đủ 4 chữ số.';return;}
$('pin-submit').disabled=true;
try{const r=await fetch('/api/advanced/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin})});
if(!r.ok){const d=await r.json();throw Error(d.detail||'Mã PIN không đúng');}location.assign(target);
}catch(err){$('pin-error').textContent=err.message;$('pin').value='';$('pin').focus();$('pin-submit').disabled=false;}});
fetch('/api/advanced/session',{cache:'no-store'}).then(r=>r.json()).then(s=>{if(s.authorized)location.replace(target)}).catch(()=>{});
})();