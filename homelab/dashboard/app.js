'use strict';
const $ = s => document.querySelector(s);
let csrf = '', polling, busy = false, toastTimer;
function notify(text) { $('#toast').textContent=text; $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,7000); }
async function request(path, data) {
  const options={headers:{}};
  if(data!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-CSRF-Token':csrf};options.body=JSON.stringify(data);}
  const response=await fetch(path,options);
  const result=await response.json();
  if(!response.ok){if(response.status===401)showLogin();throw new Error(result.error||'Yêu cầu thất bại');}
  return result;
}
function showLogin(){clearInterval(polling);$('#login').hidden=false;$('#workspace').hidden=true;$('#logout').hidden=true;$('#connection').textContent='Chưa đăng nhập';csrf='';}
async function showWorkspace(){const s=await request('/api/session');csrf=s.csrf;$('#login').hidden=true;$('#workspace').hidden=false;$('#logout').hidden=false;clearInterval(polling);await refresh();polling=setInterval(refresh,10000);}
function bytes(n){return (n/1024**3).toFixed(1)+' GB';}
function textCell(row,value){const cell=document.createElement('td');cell.textContent=value;row.append(cell);return cell;}
async function action(data){if(busy)return;const question=data.action==='backup'?'Chạy backup thật? Web/MQTT có thể tạm dừng.':'Thực hiện '+data.action+' cho '+data.service+'? Có thể ngắt ứng dụng.';if(!confirm(question))return;busy=true;try{const r=await request('/api/action',data);notify(r.message||'Đã nhận tác vụ');await refresh();}catch(e){notify(e.message);}finally{busy=false;}}
async function refresh(){
  $('#refresh').disabled=true;
  try{
    const data=await request('/api/status'),h=data.host;
    $('#connection').textContent='● Agent đã kết nối';$('#updated').textContent='Cập nhật thật: '+new Date(h.sampled_at*1000).toLocaleString('vi-VN');
    $('#cpu').textContent=h.cpu===null?'Đang lấy mẫu':h.cpu.toFixed(1)+'%';$('#load').textContent=h.cpus+' CPU · Load 1m: '+h.load[0].toFixed(2);
    $('#memory').textContent=bytes(h.memory_used)+' / '+bytes(h.memory_total);$('#memory-bar').style.width=(100*h.memory_used/h.memory_total)+'%';
    $('#disk').textContent=bytes(h.disk_used)+' / '+bytes(h.disk_total);$('#disk-bar').style.width=(100*h.disk_used/h.disk_total)+'%';
    $('#running').textContent=data.services.filter(s=>s.State==='running').length+' / '+data.services.length;
    $('#uptime').textContent=Math.floor(h.uptime_seconds/86400)+' ngày '+Math.floor(h.uptime_seconds%86400/3600)+' giờ';
    $('#job').textContent=data.job.state+' · '+data.job.message;$('#backup').disabled=data.job.state==='running';
    $('#service-list').replaceChildren();$('#health-list').replaceChildren();
    data.services.forEach(s=>{const r=document.createElement('tr');textCell(r,s.Service);textCell(r,s.State);textCell(r,s.Health||'Không khai báo healthcheck');const c=textCell(r,'');
      if(['web','db','mqtt','adminer','files'].includes(s.Service))['start','stop','restart'].forEach(a=>{const b=document.createElement('button');b.textContent={start:'Chạy',stop:'Dừng',restart:'Khởi động lại'}[a];b.disabled=data.job.state==='running';b.onclick=()=>action({action:a,service:s.Service});c.append(b);});$('#service-list').append(r);
      const row=document.createElement('div');row.className='health';const name=document.createElement('span');name.textContent=s.Service;const badge=document.createElement('span');badge.className='badge'+(s.State!=='running'||s.Health==='unhealthy'?' warn':'');badge.textContent=s.State+' · '+(s.Health||'Không healthcheck');row.append(name,badge);$('#health-list').append(row);
    });
    renderMonitor(data.monitor);
    $('#snapshot-list').replaceChildren();data.snapshots.forEach(s=>{const r=document.createElement('tr');textCell(r,s.name);textCell(r,bytes(s.bytes));textCell(r,s.checksum);$('#snapshot-list').append(r);});
    if(!data.snapshots.length){const r=document.createElement('tr');textCell(r,'Chưa tìm thấy snapshot stack chính');$('#snapshot-list').append(r);}
  }catch(e){$('#connection').textContent='⚠ Không xác minh được trạng thái';$('#updated').textContent='Dữ liệu có thể đã cũ · '+e.message;notify(e.message);}finally{$('#refresh').disabled=false;}
}
$('#login-form').onsubmit=async e=>{e.preventDefault();try{await request('/api/login',{password:$('#password').value});$('#password').value='';await showWorkspace();}catch(err){notify(err.message);}};
$('#logout').onclick=async()=>{try{await request('/api/logout',{});}catch(e){notify(e.message);}showLogin();};
$('#refresh').onclick=refresh;$('#backup').onclick=()=>action({action:'backup'});
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.tab').forEach(x=>x.hidden=x.id!==b.dataset.tab);$('#title').textContent=b.textContent.slice(2).trim();});
showWorkspace().catch(()=>showLogin());

// Guide navigation changes only the local page; it never executes server commands.
function openGuide(id){
  const nav=document.querySelector('[data-tab="guide"]');
  nav.click();
  const step=document.getElementById(id);
  if(step){step.open=true;step.scrollIntoView({behavior:'smooth',block:'start'});}
}
document.querySelectorAll('[data-open-guide]').forEach(b=>b.onclick=()=>openGuide(b.dataset.openGuide));
document.querySelectorAll('.copy-command').forEach(b=>b.onclick=async()=>{
  const code=b.previousElementSibling;
  if(!code || code.tagName!=='PRE')return;
  try{await navigator.clipboard.writeText(code.textContent);notify('Đã sao chép. Đọc kỹ rồi tự chạy ở đúng máy; dashboard không thực thi lệnh này.');}
  catch{const range=document.createRange();range.selectNodeContents(code);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);notify('Trình duyệt chưa cho phép clipboard. Đã chọn nội dung; dùng Ctrl+C hoặc Sao chép.');}
});

function renderMonitor(m){
  $('#probe-list').replaceChildren();$('#probe-events').replaceChildren();
  if(!m){$('#probe-notice').textContent='Agent/UI chưa có dữ liệu giám sát. Không suy ra dịch vụ khỏe.';return;}
  $('#probe-notice').textContent='Chu kỳ '+m.interval_seconds+' giây. '+m.notice;
  const stateLabel=s=>({up:'Đạt',down:'Không đạt',unknown:'Chưa đo'}[s]||s);
  m.targets.forEach(t=>{const r=document.createElement('tr');textCell(r,t.name);textCell(r,t.scope);textCell(r,stateLabel(t.state));textCell(r,t.latency_ms===null?'—':t.latency_ms+' ms');textCell(r,t.checked_at?new Date(t.checked_at*1000).toLocaleTimeString('vi-VN'):'Chưa đo');$('#probe-list').append(r);});
  m.events.forEach(e=>{const r=document.createElement('tr');textCell(r,new Date(e.time*1000).toLocaleString('vi-VN'));textCell(r,e.name);textCell(r,stateLabel(e.from)+' → '+stateLabel(e.to));textCell(r,e.detail);$('#probe-events').append(r);});
  if(!m.events.length){const r=document.createElement('tr');textCell(r,'Chưa có sự kiện trong phiên này');$('#probe-events').append(r);}
}
document.querySelectorAll('[data-jump-tab]').forEach(b=>b.onclick=()=>document.querySelector('[data-tab="'+b.dataset.jumpTab+'"]').click());
