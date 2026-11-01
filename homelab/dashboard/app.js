'use strict';
const $ = s => document.querySelector(s);
let activeSite = '', authEpoch=0;
let csrf = '', polling, busy = false, toastTimer;
function notify(text) { $('#toast').textContent=text; $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,7000); }
async function request(path, data) {
  const epoch=authEpoch;
  const scoped=['file-upload','file-save','file-mkdir','file-delete','file-chmod','sql-query','delete-database','create-folder','create-database'];
  if(data && scoped.includes(data.action))data={...data,site:activeSite};
  if(path==='/api/resources')path+='?site='+encodeURIComponent(activeSite);
  const options={headers:{}};
  if(data!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-CSRF-Token':csrf};options.body=JSON.stringify(data);}
  const response=await fetch(path,options);
  const result=await response.json();
  if(!response.ok){if(response.status===401)showLogin();throw new Error(result.error||'Yêu cầu thất bại');}
  if(epoch!==authEpoch)throw new Error('Phiên đăng nhập đã thay đổi; bỏ kết quả cũ.');
  return result;
}
function showLogin(){authEpoch++;clearFileSession();clearInterval(polling);$('#login').hidden=false;$('#workspace').hidden=true;$('#logout').hidden=true;$('#connection').textContent='Chưa đăng nhập';csrf='';}
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
    renderSites(data.site_inventory);
    const mqtt=data.services.find(s=>s.Service==='mqtt');
    $('#mqtt-state').textContent=mqtt?(mqtt.State+' · '+(mqtt.Health||'Không healthcheck')):'Chưa thấy container MQTT';
    document.querySelectorAll('[data-service-action]').forEach(b=>b.disabled=data.job.state==='running');
    $('#snapshot-list').replaceChildren();data.snapshots.forEach(s=>{const r=document.createElement('tr');textCell(r,s.name);textCell(r,bytes(s.bytes));textCell(r,s.checksum);$('#snapshot-list').append(r);});
    if(!data.snapshots.length){const r=document.createElement('tr');textCell(r,'Chưa tìm thấy snapshot stack chính');$('#snapshot-list').append(r);}
  }catch(e){$('#connection').textContent='⚠ Không xác minh được trạng thái';$('#updated').textContent='Dữ liệu có thể đã cũ · '+e.message;notify(e.message);}finally{$('#refresh').disabled=false;}
}
$('#login-form').onsubmit=async e=>{e.preventDefault();try{await request('/api/login',{password:$('#password').value});$('#password').value='';await showWorkspace();}catch(err){notify(err.message);}};
$('#logout').onclick=async()=>{try{await request('/api/logout',{});}catch(e){notify(e.message);}showLogin();};
$('#refresh').onclick=refresh;$('#backup').onclick=()=>action({action:'backup'});
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.tab').forEach(x=>x.hidden=x.id!==b.dataset.tab);if(['sql','files'].includes(b.dataset.tab))refreshResources();if(b.dataset.tab==='files')loadFiles(filePath);$('#title').textContent=b.textContent.replace(/^[^\p{L}\p{N}]+/u,'').trim();document.querySelectorAll('[data-tab]').forEach(x=>{if(x===b)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');});});
showWorkspace().catch(()=>showLogin());

// Guide navigation changes only the local page; it never executes server commands.
function openGuide(id){
  const nav=document.querySelector('[data-tab="guide"]');
  nav.click();
  const step=document.getElementById(id);
  if(step){step.open=true;step.scrollIntoView({behavior:'smooth',block:'start'});}
}
document.querySelectorAll('[data-open-guide]').forEach(b=>b.onclick=()=>openGuide(b.dataset.openGuide));

document.querySelectorAll('.copy-command').forEach(button=>button.onclick=async()=>{
  const code=button.previousElementSibling;if(!code||code.tagName!=='PRE')return;
  try{await navigator.clipboard.writeText(code.textContent);notify('Đã sao chép nội dung mã nguồn. Dán vào trình soạn file trong dashboard.');}catch{notify('Trình duyệt chưa cho phép clipboard; chọn nội dung mã nguồn rồi sao chép.');}
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

function showSiteCommands(site){
  if(!/^[a-z][a-z0-9-]{0,31}$/.test(site.name)){notify('Tên site không hợp lệ. Đọc lại danh sách website trước khi thử lại.');return;}
  $('#site-next').hidden=false;
  $('#site-next-title').textContent='Cấu hình dự án: '+site.name;
  $('#site-next-code').textContent='Thư mục cấu hình trên server: sites/'+site.name+' · Chưa xác minh deployment hoặc DNS.';
  $('#site-next').scrollIntoView({behavior:'smooth',block:'start'});
}
function renderSites(inventory){
  $('#site-inventory').replaceChildren();
  if(!inventory){$('#inventory-note').textContent='Chưa nhận inventory. Cần cập nhật cả UI và agent.';$('#site-count').textContent='Chưa xác minh';return;}
  $('#site-count').textContent=inventory.items.length+' cấu hình';
  $('#inventory-note').textContent=inventory.error||'Đọc từ metadata trên server. Không suy ra site đang chạy hoặc domain đã kết nối.';
  renderScopes(inventory.items);
  inventory.items.forEach(site=>{const r=document.createElement('tr');textCell(r,site.name);textCell(r,site.domain);textCell(r,site.package);textCell(r,site.port);const c=textCell(r,'');const b=document.createElement('button');b.textContent='Chi tiết cấu hình';b.onclick=()=>showSiteCommands(site);c.append(b);[['site-start','Chạy / triển khai'],['site-stop','Dừng'],['site-check','Kiểm tra origin']].forEach(([op,label])=>{const control=document.createElement('button');control.textContent=label;control.disabled=busy;control.onclick=()=>siteOperation(site,op);c.append(control);});$('#site-inventory').append(r);});
  if(!inventory.items.length){const r=document.createElement('tr');textCell(r,'Chưa có cấu hình site riêng. Bấm Tạo website mới để bắt đầu.');$('#site-inventory').append(r);}
}
document.querySelectorAll('[data-service-action]').forEach(b=>b.onclick=()=>action({action:b.dataset.serviceAction,service:b.dataset.service}));
$('#new-site').onclick=()=>{$('#site-form-error').textContent='';$('#site-dialog').showModal();};
$('#close-site').onclick=()=>{if(!$('#site-submit').disabled)$('#site-dialog').close();};
$('#site-dialog').addEventListener('cancel',e=>{if($('#site-submit').disabled)e.preventDefault();});
$('#site-form').onsubmit=async e=>{
  e.preventDefault();if(busy)return;
  const form=new FormData(e.currentTarget);
  const data={action:'create-site',name:String(form.get('name')).trim(),domain:String(form.get('domain')).trim().toLowerCase(),package:String(form.get('package')),port:Number(form.get('port'))};
  if(!confirm('Tạo cấu hình thật cho '+data.name+'? Chưa chạy website hoặc tạo DNS.'))return;
  busy=true;$('#site-submit').disabled=true;$('#site-form-error').textContent='';
  try{const result=await request('/api/action',data);$('#site-dialog').close();$('#site-form').reset();notify(result.message);await refresh();showSiteCommands(data);}
  catch(err){$('#site-form-error').textContent=err.message;}
  finally{busy=false;$('#site-submit').disabled=false;}
};

// Public dashboard does not expose the SQL/file/website loopback ports of a visitor's PC.
if(location.protocol==='https:' && !['localhost','127.0.0.1'].includes(location.hostname)){
  document.querySelectorAll('a[href^="http://localhost:"],a[href^="http://127.0.0.1:"]').forEach(a=>{
    a.removeAttribute('href');a.setAttribute('aria-disabled','true');a.textContent='Dùng SSH tunnel để mở công cụ này';
    a.onclick=e=>{e.preventDefault();notify('Dashboard qua domain chỉ quản lý API. SQL/File Browser/website vẫn cần SSH forwarding riêng.');};
  });
}

let resourcesBusy=false, resourcesPending=false;
async function refreshResources(){
  if(resourcesBusy){resourcesPending=true;return;}resourcesBusy=true;
  try{
    const scope=activeSite,data=await request('/api/resources');
    if(scope!==activeSite)return;
    $('#folder-error').textContent=data.folders.error||'Dữ liệu thật trong projects/ (tối đa 100 thư mục trong phạm vi đang chọn).';
    $('#database-error').textContent=data.databases.error||'Database ứng dụng trong MariaDB đang chọn (tối đa 100).';
    $('#folder-list').replaceChildren();$('#database-list').replaceChildren();
    data.folders.items.forEach(f=>{const r=document.createElement('tr');textCell(r,f.path);textCell(r,f.public?'Có thư mục public':'Chưa có');$('#folder-list').append(r);});
    const selected=$('#sql-database').value;$('#sql-database').replaceChildren(new Option('Chọn database',''));
    data.databases.items.forEach(name=>{const r=document.createElement('tr');textCell(r,name);const cell=textCell(r,'');const open=document.createElement('button');open.textContent='Mở SQL';open.onclick=()=>{$('#sql-database').value=name;$('#sql-query').focus();};const drop=document.createElement('button');drop.textContent='Xóa vĩnh viễn';drop.onclick=()=>deleteDatabase(name);cell.append(open,drop);$('#database-list').append(r);$('#sql-database').append(new Option(name,name));});
    if(data.databases.items.includes(selected))$('#sql-database').value=selected;
    if(!data.folders.items.length&&!data.folders.error){const r=document.createElement('tr');textCell(r,'Chưa có thư mục hợp lệ');$('#folder-list').append(r);}
    if(!data.databases.items.length&&!data.databases.error){const r=document.createElement('tr');textCell(r,'Chưa có database ứng dụng');$('#database-list').append(r);}
  }catch(e){$('#folder-error').textContent='Chưa đọc lại được; dữ liệu có thể đã cũ. '+e.message;$('#database-error').textContent='Chưa đọc lại được; dữ liệu có thể đã cũ. '+e.message;}
  finally{resourcesBusy=false;if(resourcesPending){resourcesPending=false;refreshResources();}}
}
document.querySelectorAll('.reload-resources').forEach(b=>b.onclick=refreshResources);
function bindCreationForm(id,actionName,label){
  const form=document.getElementById(id);
  form.onsubmit=async e=>{
    e.preventDefault();if(busy)return;
    const input=form.querySelector('input'),button=form.querySelector('button[type="submit"]'),result=form.querySelector('.form-result');
    const name=input.value.trim();
    if(!confirm('Tạo '+label+' thật: '+name+'? Không ghi đè tên đã tồn tại.'))return;
    busy=true;button.disabled=true;result.textContent='Đang tạo…';
    try{const data=await request('/api/action',{action:actionName,name});result.textContent=data.message;input.value='';notify(data.message);}
    catch(e){result.textContent=e.message;}
    finally{busy=false;button.disabled=false;await refreshResources();if(id==='folder-form')loadFiles(filePath);}
  };
}
bindCreationForm('folder-form','create-folder','thư mục');
bindCreationForm('database-form','create-database','database');

// Native file workspace: same-origin session/CSRF APIs, no external file-manager login.
let filePath='', fileData=null, fileSequence=0, fileLoading=false;
function joined(base,name){return base?base+'/'+name:name;}
function dirtyEditor(){return fileData&&fileData.text!==null&&!$('#file-editor-text').readOnly&&$('#file-editor-text').value!==fileData.text;}
function leaveEditor(){
  if(dirtyEditor()&&!confirm('File đang sửa chưa lưu. Bỏ thay đổi trong trình soạn thảo?'))return false;
  $('#file-editor').hidden=true;$('#file-editor-text').value='';fileData=null;return true;
}
function readableSize(n){return n<1024?n+' B':n<1024**2?(n/1024).toFixed(1)+' KiB':(n/1024**2).toFixed(1)+' MiB';}
function breadCrumbs(path){
  const holder=$('#file-breadcrumb');holder.replaceChildren();
  const root=document.createElement('button');root.textContent='projects';root.onclick=()=>loadFiles('');holder.append(root);
  let accumulated='';path.split('/').filter(Boolean).forEach(part=>{accumulated=joined(accumulated,part);const target=accumulated;const sep=document.createElement('span');sep.textContent='/';const b=document.createElement('button');b.textContent=part;b.onclick=()=>loadFiles(target);holder.append(sep,b);});
}
async function loadFiles(path){
  if(busy){notify('Đang ghi file hoặc quản lý dịch vụ; đợi hoàn tất trước.');return;}
  if(!leaveEditor())return;
  const sequence=++fileSequence;fileLoading=true;$('#file-message').textContent='Đang đọc thư mục thật…';
  try{
    const data=await request('/api/files?path='+encodeURIComponent(path)+'&site='+encodeURIComponent(activeSite));if(sequence!==fileSequence)return;
    filePath=data.path;breadCrumbs(filePath);$('#native-file-list').replaceChildren();$('#file-up').disabled=!filePath;
    data.entries.forEach(item=>{const row=document.createElement('tr'),cell=textCell(row,'');const b=document.createElement('button');b.className='file-entry';b.textContent=(item.kind==='directory'?'▱ ':item.kind==='file'?'▤ ':'⛔ ')+item.name;b.disabled=item.kind==='blocked';b.onclick=()=>item.kind==='directory'?loadFiles(joined(filePath,item.name)):openProjectFile(joined(filePath,item.name));cell.append(b);textCell(row,{directory:'Thư mục',file:'File',blocked:'Không cho truy cập'}[item.kind]);textCell(row,item.kind==='file'?readableSize(item.bytes):'—');textCell(row,new Date(item.mtime*1000).toLocaleString('vi-VN'));const tools=textCell(row,item.mode||'');if(item.kind!=='blocked'){const path=joined(filePath,item.name);[['file-chmod','Đổi quyền'],['file-delete','Xóa']].forEach(([op,label])=>{const control=document.createElement('button');control.textContent=label;control.onclick=()=>fileManage(path,item.kind,op,item.mode);tools.append(control);});}$('#native-file-list').append(row);});
    if(!data.entries.length){const row=document.createElement('tr');textCell(row,'Thư mục chưa có file. Dùng Tải file lên hoặc File văn bản.');$('#native-file-list').append(row);}
    $('#file-message').textContent=data.truncated?'Chỉ hiển thị 200 mục đầu; hãy chia thành các thư mục nhỏ.':'Đang mở: projects'+(filePath?'/'+filePath:'')+' · '+data.entries.length+' mục';
  }catch(e){if(sequence===fileSequence){$('#file-message').textContent='Không đọc được thư mục mới; đường dẫn đang mở chưa thay đổi. '+e.message;notify(e.message);}}
  finally{if(sequence===fileSequence)fileLoading=false;}
}
async function openProjectFile(path){
  if(busy||fileLoading){notify('Đang xử lý, thử lại sau.');return;}
  if(!leaveEditor())return;const sequence=++fileSequence;
  try{
    const data=await request('/api/file?path='+encodeURIComponent(path)+'&site='+encodeURIComponent(activeSite));if(sequence!==fileSequence)return;
    fileData=data;$('#file-editor-title').textContent=data.path;$('#file-editor').hidden=false;
    const editable=data.text!==null&&new TextEncoder().encode(data.text).length<=200*1024;
    $('#file-editor-text').value=editable?data.text:'';$('#file-editor-text').readOnly=!editable;$('#file-editor-save').disabled=!editable;
    $('#file-editor-info').textContent=readableSize(data.bytes)+(editable?' · Sửa nội dung rồi bấm Lưu.':' · File nhị phân hoặc quá giới hạn soạn thảo. Có thể tải xuống.');
    $('#file-editor').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){notify(e.message);}
}
async function uploadProjectFile(name,bytes){
  if(!name||name.includes('/')||name.includes('\\')||name.startsWith('.'))throw new Error('Tên file không hợp lệ; không dùng file ẩn hoặc đường dẫn.');
  if(bytes.length>1024*1024)throw new Error('Chỉ upload file tối đa 1 MiB.');
  let binary='';for(let start=0;start<bytes.length;start+=8192)binary+=String.fromCharCode(...bytes.subarray(start,start+8192));
  const result=await request('/api/action',{action:'file-upload',path:joined(filePath,name),content:btoa(binary)});
  notify(result.message);
}
$('#file-root').onclick=()=>loadFiles('');$('#file-up').onclick=()=>loadFiles(filePath.split('/').slice(0,-1).join('/'));$('#file-refresh').onclick=()=>loadFiles(filePath);
$('#file-editor-close').onclick=()=>leaveEditor();
$('#file-editor-save').onclick=async()=>{
  if(busy||!fileData)return;const text=$('#file-editor-text').value;
  if(new TextEncoder().encode(text).length>200*1024){notify('Nội dung soạn thảo tối đa 200 KiB.');return;}
  if(!confirm('Lưu thay đổi thật vào '+fileData.path+'? Có thể ảnh hưởng website đang chạy.'))return;
  busy=true;$('#file-editor-save').disabled=true;$('#file-editor-text').readOnly=true;
  try{const result=await request('/api/action',{action:'file-save',path:fileData.path,text,version:fileData.version});fileData.version=result.version;fileData.text=text;fileData.content=null;fileData.bytes=new TextEncoder().encode(text).length;$('#file-editor-info').textContent='Đã lưu lúc '+new Date().toLocaleTimeString('vi-VN')+' · '+readableSize(fileData.bytes);notify(result.message);}
  catch(e){notify(e.message);$('#file-editor-info').textContent='Chưa xác nhận lưu thành công: '+e.message;}
  finally{busy=false;$('#file-editor-save').disabled=false;$('#file-editor-text').readOnly=false;}
};
$('#file-download').onclick=()=>{
  if(!fileData)return;let data;
  if(fileData.content===null){data=new TextEncoder().encode(fileData.text);}else{const raw=atob(fileData.content);data=Uint8Array.from(raw,c=>c.charCodeAt(0));}
  const url=URL.createObjectURL(new Blob([data],{type:'application/octet-stream'}));const a=document.createElement('a');a.href=url;a.download=fileData.path.split('/').pop();a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('#file-upload').onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  if(busy||fileLoading){e.target.value='';notify('Đợi tác vụ hiện tại hoàn tất.');return;}
  if(file.size>1024*1024){e.target.value='';notify('Chỉ upload file tối đa 1 MiB.');return;}
  if(!confirm('Upload file thật '+file.name+' vào projects/'+filePath+'? Không ghi đè tên trùng.')){e.target.value='';return;}
  busy=true;$('#file-message').textContent='Đang tải file lên…';
  try{await uploadProjectFile(file.name,new Uint8Array(await file.arrayBuffer()));}catch(err){notify(err.message);}
  finally{busy=false;e.target.value='';loadFiles(filePath);}
};
$('#file-mkdir').onclick=async()=>{
  if(busy||fileLoading)return;const name=prompt('Tên thư mục mới bên trong projects/'+filePath+':');if(!name)return;
  if(name.includes('/')||name.includes('\\')){notify('Chỉ nhập tên một thư mục, không nhập đường dẫn.');return;}
  busy=true;try{const result=await request('/api/action',{action:'file-mkdir',path:joined(filePath,name)});notify(result.message);}catch(e){notify(e.message);}finally{busy=false;loadFiles(filePath);}
};
$('#file-new').onclick=()=>{if(busy||fileLoading)return;$('#new-file-result').textContent='';$('#new-file-dialog').showModal();};
$('#new-file-close').onclick=()=>{if(!busy)$('#new-file-dialog').close();};
$('#new-file-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
$('#new-file-form').onsubmit=async e=>{
  e.preventDefault();if(busy)return;const name=$('#new-file-name').value.trim();const content=new TextEncoder().encode($('#new-file-content').value);
  if(content.length>200*1024){$('#new-file-result').textContent='File văn bản tối đa 200 KiB.';return;}
  busy=true;$('#new-file-submit').disabled=true;$('#new-file-result').textContent='Đang tạo file thật…';
  try{await uploadProjectFile(name,content);$('#new-file-dialog').close();$('#new-file-form').reset();}
  catch(err){$('#new-file-result').textContent=err.message;}
  finally{busy=false;$('#new-file-submit').disabled=false;loadFiles(filePath);}
};

function clearFileSession(){
  fileSequence++;fileData=null;activeSite='';filePath='';
  document.querySelectorAll('[data-project-scope]').forEach(select=>select.replaceChildren(new Option('Stack chính','')));
  $('#sql-query').value='';$('#sql-output').textContent='';$('#sql-status').textContent='';$('#sql-database').replaceChildren(new Option('Chọn database',''));
  $('#mqtt-messages').replaceChildren();
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
  $('#file-editor').hidden=true;$('#file-editor-text').value='';
  $('#new-file-content').value='';$('#new-file-name').value='';
}

// Real MQTT operations: no password field and no client-side broker credentials.
$('#mqtt-publish-form').onsubmit=async e=>{
  e.preventDefault();if(busy)return;
  const topic=$('#mqtt-publish-topic').value,payload=$('#mqtt-payload').value;
  if(new TextEncoder().encode(payload).length>16384){$('#mqtt-publish-result').textContent='Payload tối đa 16 KiB.';return;}
  if(!confirm('Gửi tin MQTT THẬT tới '+topic+'? Thiết bị subscribe có thể thực thi nội dung này.'))return;
  const button=e.currentTarget.querySelector('button[type="submit"]');busy=true;button.disabled=true;$('#mqtt-publish-result').textContent='Đang gửi, đợi broker PUBACK…';
  try{const r=await request('/api/action',{action:'mqtt-publish',topic,payload});$('#mqtt-publish-result').textContent=r.message;}
  catch(err){$('#mqtt-publish-result').textContent='Chưa xác nhận gửi thành công: '+err.message;}
  finally{busy=false;button.disabled=false;}
};
$('#mqtt-sample-form').onsubmit=async e=>{
  e.preventDefault();if(busy)return;
  const button=e.currentTarget.querySelector('button[type="submit"]');busy=true;button.disabled=true;$('#mqtt-sample-result').textContent='Đang kết nối và nhận tối đa 3 giây sau SUBACK…';$('#mqtt-messages').replaceChildren();
  try{
    const r=await request('/api/action',{action:'mqtt-sample',topic:$('#mqtt-sample-topic').value});
    $('#mqtt-sample-result').textContent=r.messages.length+' tin nhận được. '+r.message;
    r.messages.forEach(m=>{const row=document.createElement('tr');textCell(row,new Date(m.time*1000).toLocaleTimeString('vi-VN'));textCell(row,m.topic);textCell(row,m.payload===null?'Binary (base64): '+m.binary_base64:m.payload);textCell(row,m.retained?'Có · có thể là tin cũ':'Không');$('#mqtt-messages').append(row);});
    if(!r.messages.length){const row=document.createElement('tr');textCell(row,'Không có tin trong cửa sổ nhận. Không đồng nghĩa broker bị lỗi.');$('#mqtt-messages').append(row);}
  }catch(err){$('#mqtt-sample-result').textContent='Nhận tin thất bại: '+err.message;}
  finally{busy=false;button.disabled=false;}
};
$('#mqtt-test').onclick=async()=>{
  if(busy)return;busy=true;$('#mqtt-test').disabled=true;$('#mqtt-test-result').textContent='Đang tự subscribe, publish và đối chiếu nội dung…';
  try{const r=await request('/api/action',{action:'mqtt-test'});$('#mqtt-test-result').textContent=r.message+' Topic: '+r.topic;}
  catch(e){$('#mqtt-test-result').textContent='Chưa đạt kiểm tra: '+e.message;}
  finally{busy=false;$('#mqtt-test').disabled=false;}
};


function renderScopes(sites){
  document.querySelectorAll('[data-project-scope]').forEach(select=>{
    select.replaceChildren(new Option('Stack chính',''));
    sites.forEach(site=>select.append(new Option(site.name+' · '+site.domain,site.name)));
    if(activeSite&&!sites.some(site=>site.name===activeSite))select.append(new Option(activeSite+' · chưa đọc được inventory',activeSite));
    select.value=activeSite;
  });
}
document.querySelectorAll('[data-project-scope]').forEach(select=>select.onchange=()=>{
  if(busy||!leaveEditor()){select.value=activeSite;notify('Chưa đổi phạm vi; hoàn tất thao tác hoặc lưu file trước.');return;}
  activeSite=select.value;filePath='';fileSequence++;
  document.querySelectorAll('[data-project-scope]').forEach(other=>other.value=activeSite);
  $('#sql-query').value='';$('#sql-output').textContent='';$('#sql-status').textContent='';
  $('#sql-database').replaceChildren(new Option('Chọn database',''));
  refreshResources();if(!$('#files').hidden)loadFiles('');
});
async function fileManage(path,kind,op,currentMode){
  if(busy||fileLoading||!leaveEditor())return;
  const data={action:op,path};
  if(op==='file-delete'){
    data.confirmation=prompt('Xóa khỏi projects/'+path+' trong '+(activeSite||'Stack chính')+'? Có thể làm website ngừng chạy. Chuyển vào thùng rác riêng, chưa có nút phục hồi. Nhập lại chính xác đường dẫn: '+path);
    if(data.confirmation!==path)return;
  }else{
    data.mode=prompt('Quyền hiện tại '+currentMode+'. '+(kind==='directory'?'Thư mục: nhập 0755 (web đọc được) hoặc 0700 (riêng tư).':'File: nhập 0644 (web đọc được) hoặc 0600 (riêng tư).')+' Không đệ quy; quyền riêng tư có thể làm website lỗi.',currentMode);
    if(!data.mode)return;
  }
  busy=true;
  try{const result=await request('/api/action',data);notify(result.message);}
  catch(e){notify(e.message);}
  finally{busy=false;loadFiles(filePath);refreshResources();}
}
async function deleteDatabase(name){
  if(busy)return;
  const confirmation=prompt('XÓA VĨNH VIỄN database '+name+' trong '+(activeSite||'Stack chính')+'. Mất toàn bộ bảng/dữ liệu, có thể làm website ngừng hoạt động. Sao lưu trước. Nhập DELETE '+name+' để xác nhận:');
  if(confirmation!=='DELETE '+name)return;
  busy=true;
  try{const result=await request('/api/action',{action:'delete-database',name,confirmation});notify(result.message);$('#sql-status').textContent=result.message;$('#sql-output').textContent='';}
  catch(e){notify(e.message);}
  finally{busy=false;await refreshResources();}
}
$('#sql-form').onsubmit=async e=>{
  e.preventDefault();if(busy)return;
  const name=$('#sql-database').value,query=$('#sql-query').value;
  if(new TextEncoder().encode(query).length>8192){notify('SQL tối đa 8 KiB.');return;}
  const confirmation=prompt('Chạy SQL THẬT trong '+(activeSite||'Stack chính')+' / '+name+'? Có thể thay đổi/xóa dữ liệu, appuser dùng chung quyền trong stack này. Nhập RUN '+name+' để xác nhận:');
  if(confirmation!=='RUN '+name)return;
  const button=e.currentTarget.querySelector('button[type="submit"]');busy=true;button.disabled=true;$('#sql-status').textContent='Đang chạy SQL…';$('#sql-output').textContent='';
  try{const result=await request('/api/action',{action:'sql-query',name,query,confirmation});$('#sql-status').textContent=result.message;$('#sql-output').textContent=result.output;}
  catch(err){$('#sql-status').textContent=err.message;}
  finally{busy=false;button.disabled=false;await refreshResources();}
};
async function siteOperation(site,op){
  if(busy)return;
  if(op!=='site-check'&&!confirm((op==='site-start'?'Build/khởi động web + database':'Dừng web + database')+' cho '+site.name+'? Có thể gián đoạn site. Không xóa volume.'))return;
  busy=true;
  try{
    const result=await request('/api/action',{action:op,name:site.name});
    showSiteCommands(site);$('#site-next-code').textContent=result.message+' '+(result.origin?'Origin: '+result.origin:'Origin dự kiến: http://127.0.0.1:'+site.port)+' · Domain: '+site.domain;
    notify(result.message);
  }catch(e){notify(e.message);}
  finally{busy=false;await refresh();}
}
