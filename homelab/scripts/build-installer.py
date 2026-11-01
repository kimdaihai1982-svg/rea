#!/usr/bin/env python3
"""Package only explicitly allowed source files; never package secrets or backups."""
import base64
import hashlib
import io
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parent.parent
allowed = ['compose.yaml', '.env.example', '.gitignore', 'README.md', 'SECURITY.md',
           'MULTISITE.md', 'packages.json', 'preview.html']
for directory in ['config', 'php', 'portal', 'scripts', 'projects/demo/public']:
    allowed.extend(str(p.relative_to(root)) for p in (root / directory).rglob('*')
                   if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts
                   and p.suffix != '.pyc')
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
    for name in sorted(set(allowed)):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f'Unsafe source: {name}')
        archive.add(path, arcname=name, recursive=False)
payload = buffer.getvalue()
digest = hashlib.sha256(payload).hexdigest()
header = r'''#!/usr/bin/env bash
# MayChu247 portable installer. Contains source configuration, no credentials.
# Does NOT overwrite /opt/stack, migrate data, change firewall/DNS, or install host packages.
set -Eeuo pipefail
TARGET=/opt/maychu247-v2
MODE=${1:---help}
if [[ $# -gt 1 ]]; then echo 'Chỉ dùng một tùy chọn: --help, --check hoặc --install'; exit 1; fi
case "$MODE" in
  --help|-h)
    echo 'MayChu247 — một file cài song song, KHÔNG ghi đè server cũ.'
    echo 'Kiểm tra gói: bash MayChu247-Install.sh --check'
    echo 'Cài và khởi động: sudo bash MayChu247-Install.sh --install'
    echo 'Cần Ubuntu, Python 3, Docker Engine/Compose v2, dung lượng và tài nguyên dự phòng.'
    echo 'Không tự cài Cockpit/firewall, không tự mở domain, không tự chuyển dữ liệu cũ.'
    exit 0;;
  --check|--install) ;;
  *) echo 'Tùy chọn không hợp lệ; dùng --help'; exit 1;;
esac
for cmd in python3 base64 sha256sum tar mktemp; do command -v "$cmd" >/dev/null || { echo "Thiếu $cmd"; exit 1; }; done
work=$(mktemp -d)
chmod 700 "$work"
trap 'rm -rf "$work"' EXIT
payload() {
cat <<'MAYCHU247_EMBEDDED_PAYLOAD'
'''
footer = r'''MAYCHU247_EMBEDDED_PAYLOAD
}
payload | base64 --decode > "$work/bundle.tgz"
printf '%s  %s\n' '__DIGEST__' "$work/bundle.tgz" | sha256sum --check --status || { echo 'File bị hỏng, không triển khai'; exit 1; }
# Validate member names/types before extracting; package includes no symlinks/devices.
python3 - "$work/bundle.tgz" <<'VALIDATE'
import sys, tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1], 'r:gz') as a:
    for m in a.getmembers():
        p = PurePosixPath(m.name)
        if p.is_absolute() or '..' in p.parts or not m.isfile():
            raise SystemExit('Unsafe archive member: ' + m.name)
print('Checksum và cấu trúc gói hợp lệ. Không chứa dữ liệu máy chủ cũ.')
VALIDATE
[[ $MODE == --install ]] || exit 0
[[ $EUID == 0 ]] || { echo 'Dùng sudo bash MayChu247-Install.sh --install'; exit 1; }
[[ -f /etc/os-release ]] || { echo 'Cần Ubuntu'; exit 1; }
. /etc/os-release
[[ ${ID:-} == ubuntu ]] || { echo 'Bộ cài này chỉ dành cho Ubuntu'; exit 1; }
[[ ! -e $TARGET && ! -L $TARGET ]] || { echo "$TARGET đã tồn tại: từ chối ghi đè. Đọc README để cập nhật có backup."; exit 1; }
command -v docker >/dev/null || { echo 'Chưa có Docker, không tự cài trên máy đang chạy.'; exit 1; }
docker compose version >/dev/null
docker info >/dev/null
[[ -z $(docker ps -aq --filter label=com.docker.compose.project=maychu247-v2) ]] || { echo 'Đã có container project maychu247-v2: cần kiểm tra thủ công'; exit 1; }
[[ -z $(docker volume ls -q --filter label=com.docker.compose.project=maychu247-v2) ]] || { echo 'Đã có volume project maychu247-v2: từ chối tái sử dụng dữ liệu không rõ nguồn'; exit 1; }
python3 - <<'PORTS'
import socket
for port in [18000,18080,18081,18082,13001,1884,19001]:
    with socket.socket() as s:
        try: s.bind(('127.0.0.1', port))
        except OSError: raise SystemExit(f'Port {port} đang dùng: không triển khai')
PORTS
echo 'Kế hoạch: tạo /opt/maychu247-v2; pull/build Docker và chạy 7 dịch vụ chính.'
echo 'Không sửa /opt/stack, firewall, SSH, DNS hoặc Cloudflare. SQL mới ban đầu rỗng.'
echo 'Mặc định UI chỉ nghe 127.0.0.1. Có thể tăng tải CPU/RAM/đĩa của server.'
echo 'Nên backup hệ thống hiện tại trước khi tiếp tục.'
read -r -p 'Gõ CAI-SONG-SONG để xác nhận: ' answer
[[ $answer == CAI-SONG-SONG ]] || { echo 'Đã hủy, không thay đổi máy chủ.'; exit 1; }
mkdir -m 700 "$TARGET"
tar xzf "$work/bundle.tgz" -C "$TARGET" --no-same-owner
chmod 700 "$TARGET"/scripts/*.sh "$TARGET"/scripts/*.py
cd "$TARGET"
if ! bash scripts/setup.sh; then
  echo "Khởi động chưa hoàn tất. Giữ nguyên $TARGET để kiểm tra; KHÔNG xóa .env hoặc volume."
  echo "Đọc README; xem docker compose ps và docker compose logs --tail 100."
  exit 1
fi
cat <<'DONE'
Bộ mới đã gửi lệnh khởi động; CHƯA xác nhận ứng dụng khỏe hoặc production-ready.
Kiểm tra: cd /opt/maychu247-v2 && sudo docker compose ps
Đọc hướng dẫn: /opt/maychu247-v2/README.md
Mật khẩu mới: .env; File Browser: sudo docker compose logs files (đổi ngay).
Trên PC mở SSH forwarding:
ssh -L 18000:127.0.0.1:18000 -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 -L 18082:127.0.0.1:18082 -L 13001:127.0.0.1:13001 kimdaihai@192.168.1.11
Sau đó mở http://localhost:18000 trên PC.
Chạy thử backup trước khi bật lịch:
sudo bash /opt/maychu247-v2/scripts/backup-all.sh
sudo bash /opt/maychu247-v2/scripts/install-backup-timer.sh
Không tự migrate SQL/worker/domain. Giữ stack cũ cho đến khi nghiệm thu.
DONE
'''.replace('__DIGEST__', digest)
output = root / 'downloads/MayChu247-Install.sh'
output.parent.mkdir(exist_ok=True)
output.write_text(header + base64.encodebytes(payload).decode('ascii') + footer)
output.chmod(0o755)
print(f'Created {output} ({output.stat().st_size} bytes); payload SHA256: {digest}')
