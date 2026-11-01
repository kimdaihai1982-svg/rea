#!/usr/bin/env bash
# New dedicated remotely managed tunnel; no deletion/modification of the old tunnel.
set -Eeuo pipefail
[[ $EUID == 0 && -f /etc/maychu247-ui/managed ]] || { echo 'Cần sudo và dashboard đã cài'; exit 1; }
[[ $# == 1 ]] || { echo 'Dùng: sudo bash configure-public.sh panel.maychu247.uk'; exit 1; }
domain=$1
python3 - "$domain" <<'CHECK'
import re,sys
s=sys.argv[1]
if len(s)>253 or '.' not in s or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',v) for v in s.split('.')):
    raise SystemExit('Cần hostname chữ thường hợp lệ, không https:// hoặc path')
CHECK
command -v docker >/dev/null
docker compose version >/dev/null
systemctl is-active --quiet maychu247-dashboard.service || { echo 'Sửa dashboard hoạt động qua SSH trước'; exit 1; }
[[ ! -e /etc/maychu247-ui/tunnel.yaml && ! -e /etc/maychu247-ui/public.env ]] || { echo 'Cấu hình public đã có; không ghi đè. Xem PUBLIC-DOMAIN.md.'; exit 1; }
echo "Hostname: $domain. Phải tạo Access Self-hosted Application cho hostname này, allow email của bạn và MFA tại IdP."
echo 'Không có API xác minh Access trong script. Xác nhận chỉ khi đã cấu hình và kiểm tra chính sách.'
read -r -p 'Gõ ACCESS-READY để tiếp tục: ' answer
[[ $answer == ACCESS-READY ]] || exit 1
umask 077
# Use getpass to avoid shell history, argv and chat/log exposure of the token.
python3 - <<'TOKEN'
import getpass,re
from pathlib import Path
p=Path('/etc/maychu247-ui/tunnel.env')
if p.exists():raise SystemExit('tunnel.env đã tồn tại; không ghi đè token cũ')
t=getpass.getpass('Token của TUNNEL MỚI RIÊNG cho dashboard (không hiện ký tự): ')
if not re.fullmatch(r'[A-Za-z0-9_+/=-]{40,}',t):raise SystemExit('Token không đúng định dạng; chưa ghi')
p.write_text('TUNNEL_TOKEN='+t+'\n');p.chmod(0o600)
TOKEN
printf 'MAYCHU247_PUBLIC_ORIGIN=https://%s\n' "$domain" > /etc/maychu247-ui/public.env
cat > /etc/maychu247-ui/tunnel.yaml <<'YAML'
services:
  connector:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    network_mode: host
    command: tunnel --no-autoupdate run
    env_file: /etc/maychu247-ui/tunnel.env
    security_opt: [no-new-privileges:true]
    cap_drop: [ALL]
    logging:
      driver: json-file
      options: {max-size: 10m, max-file: '3'}
YAML
# Do not auto-publish when backend validation fails.
systemctl restart maychu247-dashboard.service
python3 - "$domain" <<'READY'
import http.client,sys,time
for _ in range(20):
    try:
        c=http.client.HTTPConnection('127.0.0.1',18000,timeout=2)
        c.request('GET','/',headers={'Host':sys.argv[1]})
        r=c.getresponse();r.read();c.close()
        if r.status==200:break
    except OSError:pass
    time.sleep(.5)
else:raise SystemExit('Backend chưa chấp nhận hostname. Connector CHƯA được khởi động; xem journal.')
READY
docker compose -p maychu247-dashboard-tunnel -f /etc/maychu247-ui/tunnel.yaml up -d
echo "Connector đã được gửi lệnh khởi động. Trong TUNNEL MỚI đặt $domain -> HTTP -> 127.0.0.1:18000."
echo 'Không dùng HTTPS cho origin, không đổi HTTP Host Header, không bật No TLS Verify.'
echo 'Đăng nhập qua HTTPS bằng password dashboard. Giữ SSH tunnel để cứu hộ; chưa xóa tunnel cũ.'
