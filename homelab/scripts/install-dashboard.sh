#!/usr/bin/env bash
# Install the real dashboard without granting the web process Docker/root access.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
[[ $EUID == 0 && $PWD == /opt/maychu247-v2 ]] || { echo 'Chạy sudo bash /opt/maychu247-v2/scripts/install-dashboard.sh'; exit 1; }
command -v python3 >/dev/null
command -v systemctl >/dev/null
docker compose version >/dev/null
# Existing unowned users/units must not be silently repurposed.
if id maychu247-ui >/dev/null 2>&1; then
  [[ -f /etc/maychu247-ui/managed ]] || { echo 'User maychu247-ui có sẵn, không rõ nguồn. Dừng.'; exit 1; }
else
  useradd --system --user-group --no-create-home --shell /usr/sbin/nologin maychu247-ui
fi
for unit in maychu247-agent.service maychu247-dashboard.service; do
  if [[ -e /etc/systemd/system/$unit && ! -f /etc/maychu247-ui/managed ]]; then
    echo "Unit $unit có sẵn, không rõ nguồn. Dừng."; exit 1
  fi
done
install -d -m 750 -o root -g maychu247-ui /etc/maychu247-ui
touch /etc/maychu247-ui/managed
chmod 600 /etc/maychu247-ui/managed
if [[ ! -e /etc/maychu247-ui/auth.json ]]; then
  python3 - <<'PY'
import hashlib,json,secrets
from pathlib import Path
password=secrets.token_urlsafe(24)
salt=secrets.token_bytes(16)
hash_=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()
p=Path('/etc/maychu247-ui/auth.json')
p.write_text(json.dumps({'salt':salt.hex(),'hash':hash_}))
p.chmod(0o640)
print('\nMẬT KHẨU DASHBOARD (lưu vào password manager): '+password+'\n')
PY
fi
chown root:maychu247-ui /etc/maychu247-ui/auth.json
chmod 640 /etc/maychu247-ui/auth.json
# Save the live release and unit files before touching them. Roll back on any later error.
rollback_dir=$(mktemp -d)
chmod 700 "$rollback_dir"
was_dashboard=0; was_agent=0
systemctl is-active --quiet maychu247-dashboard.service && was_dashboard=1
systemctl is-active --quiet maychu247-agent.service && was_agent=1
running_services=$(docker compose ps --services --status running)
if [[ -d /usr/local/lib/maychu247-dashboard ]]; then
  cp -a /usr/local/lib/maychu247-dashboard "$rollback_dir/live"
fi
for unit in maychu247-agent.service maychu247-dashboard.service; do
  if [[ -f /etc/systemd/system/$unit ]]; then cp -a "/etc/systemd/system/$unit" "$rollback_dir/$unit"; fi
done
rollback() {
  code=$?
  trap - ERR
  set +e
  echo 'Cập nhật lỗi; đang phục hồi code/unit của dashboard trước cập nhật.' >&2
  systemctl stop maychu247-dashboard.service maychu247-agent.service
  rm -rf /usr/local/lib/maychu247-dashboard
  if [[ -d $rollback_dir/live ]]; then cp -a "$rollback_dir/live" /usr/local/lib/maychu247-dashboard; fi
  for unit in maychu247-agent.service maychu247-dashboard.service; do
    if [[ -f $rollback_dir/$unit ]]; then cp -a "$rollback_dir/$unit" "/etc/systemd/system/$unit";
    else rm -f "/etc/systemd/system/$unit"; fi
  done
  systemctl daemon-reload
  systemctl reset-failed maychu247-dashboard.service maychu247-agent.service
  if [[ $was_agent == 1 ]]; then systemctl start maychu247-agent.service; fi
  if [[ $was_dashboard == 1 ]]; then systemctl start maychu247-dashboard.service; fi
  for legacy in portal kuma; do
    if grep -qx "$legacy" <<< "$running_services"; then docker compose start "$legacy"; fi
  done
  echo 'Kiểm tra systemctl/journal. Không xóa .env hoặc volume. Nếu bản cũ vốn lỗi, rollback không tự chữa bản cũ.' >&2
  exit "$code"
}
trap rollback ERR
trap 'rm -rf "$rollback_dir"' EXIT
install -d -m 755 /usr/local/lib/maychu247-dashboard
install -m 644 dashboard/{server.py,agent.py,monitor.py,index.html,app.js,style.css} /usr/local/lib/maychu247-dashboard/
# Import all runtime modules as the unprivileged user before stopping live services.
runuser -u maychu247-ui -- /usr/bin/python3 - <<'PREFLIGHT'
import sys,json
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/maychu247-dashboard')
import server, agent, monitor
config=json.loads(server.CONFIG_PATH.read_text())
assert len(bytes.fromhex(config['salt'])) >= 16
assert len(bytes.fromhex(config['hash'])) == 64
for name in ('index.html','app.js','style.css'):
    assert (server.HERE/name).read_bytes()
print('Runtime modules, assets và quyền đọc auth: OK')
PREFLIGHT
# Only stop the old link-only portal from THIS Compose project, not any other stack.
docker compose stop portal kuma
systemctl stop maychu247-dashboard.service maychu247-agent.service 2>/dev/null || true
python3 - <<'PY'
import socket
with socket.socket() as s:
    # Match HTTPServer reuse behavior: TIME_WAIT is not a live listener.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:s.bind(('127.0.0.1',18000))
    except OSError:raise SystemExit('Port 18000 đang được dùng. Không thay dịch vụ lạ.')
PY
cat > /etc/systemd/system/maychu247-agent.service <<'UNIT'
[Unit]
Description=MayChu247 local restricted Compose broker
After=docker.service
Requires=docker.service
[Service]
Type=simple
User=root
Group=maychu247-ui
RuntimeDirectory=maychu247
RuntimeDirectoryMode=0750
ExecStart=/usr/bin/python3 /usr/local/lib/maychu247-dashboard/agent.py
Restart=on-failure
UMask=0007
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/maychu247-v2 /run/maychu247
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/maychu247-dashboard.service <<'UNIT'
[Unit]
Description=MayChu247 personal dashboard (loopback only)
After=maychu247-agent.service
Requires=maychu247-agent.service
[Service]
Type=simple
User=maychu247-ui
Group=maychu247-ui
EnvironmentFile=-/etc/maychu247-ui/public.env
ExecStart=/usr/bin/python3 /usr/local/lib/maychu247-dashboard/server.py
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
RestrictSUIDSGID=true
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now maychu247-agent.service maychu247-dashboard.service
# Confirm actual HTTP response + Unix agent readiness, not only systemd's start result.
python3 - <<'READY'
import http.client,json,socket,time
last='chưa phản hồi'
for attempt in range(20):
    try:
        c=http.client.HTTPConnection('127.0.0.1',18000,timeout=2)
        c.request('GET','/',headers={'Host':'localhost:18000'})
        r=c.getresponse();r.read();c.close()
        if r.status!=200: raise RuntimeError('HTTP '+str(r.status))
        a=http.client.HTTPConnection('localhost',timeout=2)
        a.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        a.sock.settimeout(2);a.sock.connect('/run/maychu247/agent.sock')
        a.request('POST','/',json.dumps({'action':'ping'}),{'Content-Type':'application/json'})
        reply=a.getresponse();data=json.loads(reply.read());a.close()
        if reply.status!=200 or data.get('ready') is not True: raise RuntimeError('Agent chưa sẵn sàng')
        print('Readiness: HTTP 200, agent ping OK');break
    except (OSError,ValueError,RuntimeError,http.client.HTTPException) as e:
        last=type(e).__name__;time.sleep(0.5)
else:raise SystemExit('Readiness thất bại: '+last)
READY
systemctl --no-pager --full status maychu247-dashboard.service
trap - ERR
printf '\nMở qua SSH forwarding http://localhost:18000. Không public dashboard qua Cloudflare ở bản này.\n'
