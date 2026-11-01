#!/usr/bin/env bash
# Standalone repair for an already installed public-capable MayChu247 dashboard.
# No reinstall, token rotation, firewall edit, arbitrary process kill or data deletion.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Chạy: sudo bash MayChu247-Fix.sh'; exit 1; }
domain=maychu247.uk
config=/etc/maychu247-ui
live=/usr/local/lib/maychu247-dashboard
[[ -f $config/managed && -f $config/tunnel.yaml && -f $config/tunnel.env ]] || {
  echo 'Không tìm thấy cấu hình dashboard/tunnel riêng đã cài. Dừng, không cài đè.'; exit 1;
}
[[ -f $live/server.py && -f $live/monitor.py ]] || { echo 'Thiếu code dashboard; cần xem log trước'; exit 1; }
python3 - "$live/server.py" <<'CHECK'
import ast,sys
p=ast.parse(open(sys.argv[1]).read())
if not any(isinstance(n,ast.FunctionDef) and n.name=='configured_origin' for n in p.body):
    raise SystemExit('Code chưa hỗ trợ public domain. Không tắt kiểm tra Host để bỏ qua.')
CHECK
systemctl cat maychu247-dashboard.service | grep -Fq 'EnvironmentFile=-/etc/maychu247-ui/public.env' || {
  echo 'Unit dashboard chưa hỗ trợ public.env; cần cập nhật unit đúng phiên bản trước.'; exit 1;
}
echo 'Sửa hostname dashboard thành https://maychu247.uk; dùng connector riêng đã có.'
echo 'Trước khi tiếp tục: Access Application phải bảo vệ toàn bộ maychu247.uk, Allow email quản trị, không Bypass/Everyone.'
echo 'Giữ SSH cứu hộ. Không chạy khi backup/deploy đang hoạt động. UI restart sẽ đăng xuất các phiên.'
read -r -p 'Gõ MAYCHU247 để xác nhận: ' confirm
[[ $confirm == MAYCHU247 ]] || { echo 'Đã hủy, chưa sửa gì.'; exit 1; }
umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$config/public.env.before-fix-$stamp"
if [[ -e $config/public.env ]]; then cp -a "$config/public.env" "$backup"; fi
printf 'MAYCHU247_PUBLIC_ORIGIN=https://%s\n' "$domain" > "$config/public.env"
chmod 600 "$config/public.env"
diagnose() {
  echo '=== DICH VU ==='
  systemctl --no-pager -l status maychu247-dashboard.service maychu247-agent.service || true
  echo '=== CONG ==='
  ss -lntp 'sport = :18000' || true
  echo '=== LOG DASHBOARD ==='
  journalctl -u maychu247-dashboard.service -n 35 --no-pager || true
  echo 'Không xóa dữ liệu hoặc token. Gửi kết quả kiểm tra, không gửi file tunnel.env.'
}
if ! systemctl start maychu247-agent.service || ! systemctl restart maychu247-dashboard.service; then
  diagnose
  exit 1
fi
if ! python3 - <<'READY'
import http.client,time
for _ in range(20):
    try:
        c=http.client.HTTPConnection('127.0.0.1',18000,timeout=2)
        c.request('GET','/',headers={'Host':'maychu247.uk'})
        r=c.getresponse();r.read();c.close()
        if r.status==200:
            print('BACKEND OK: Host maychu247.uk -> HTTP 200');break
    except OSError:pass
    time.sleep(.5)
else:raise SystemExit('BACKEND chưa trả HTTP 200. Không tuyên bố đã sửa xong.')
READY
then
  # Restore only hostname configuration; don't overwrite application/data.
  if [[ -f $backup ]]; then
    cp -a "$backup" "$config/public.env"
    systemctl restart maychu247-dashboard.service || true
    echo 'Đã trả public.env về bản trước; vẫn cần xử lý lỗi dịch vụ.'
  fi
  diagnose
  exit 1
fi
if ! docker compose -p maychu247-dashboard-tunnel -f "$config/tunnel.yaml" up -d; then
  echo 'Backend hoạt động nhưng connector chưa khởi động được. Không cần cài lại dashboard.'
  exit 1
fi
docker compose -p maychu247-dashboard-tunnel -f "$config/tunnel.yaml" ps
cat <<'DONE'
ĐÃ XÁC NHẬN BACKEND NỘI BỘ, CHƯA XÁC NHẬN ĐƯỜNG INTERNET.
Trên đúng Tunnel mới dùng token đã nhập, chỉ để một route:
  Destination: maychu247.uk
  Type: HTTP
  URL: 127.0.0.1:18000
  Path: trống; không đổi HTTP Host Header.
Không dùng origin HTTPS, không bật No TLS Verify. Không trỏ về container web PHP.
Access Application cũng phải là maychu247.uk (không còn panel.maychu247.uk).
Mở cửa sổ riêng tư: https://maychu247.uk -> Access -> login dashboard.
Đường domain không cần mở SSH trên PC. SQL/File Browser vẫn dùng SSH riêng.
Nếu 502: cần xem connector logs/route. Nếu 403: kiểm tra Access/Host; không tắt bảo vệ.
DONE
