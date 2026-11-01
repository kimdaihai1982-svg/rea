#!/usr/bin/env bash
# Read-only observations; not a vulnerability scanner or proof of security.
set -u
cd "$(dirname "$0")/.."
echo '=== Quan sát chỉ đọc: không thay đổi firewall/SSH, không in secrets ==='
echo '=== Thời gian / OS ==='
date -u
uname -sr
printf '\n=== Cổng đang lắng nghe (tự xem có public ngoài ý muốn) ===\n'
if command -v ss >/dev/null; then ss -lnt; else echo 'Thiếu ss'; fi
printf '\n=== Firewall ===\n'
if command -v ufw >/dev/null; then ufw status verbose || echo 'Cần sudo để đọc UFW'; fi
if command -v firewall-cmd >/dev/null; then firewall-cmd --get-active-zones || true; fi
printf '\n=== Socket Cockpit / SSH ===\n'
if command -v systemctl >/dev/null; then
  systemctl is-active cockpit.socket ssh.service sshd.service 2>/dev/null || true
fi
printf '\n=== Quyền file bí mật (chỉ tên và mode) ===\n'
if [[ -f .env ]]; then stat -c '%a %U %n' .env; fi
if [[ -d sites ]]; then find sites -maxdepth 2 -name .env -exec stat -c '%a %U %n' {} +; fi
printf '\n=== Dung lượng / backup gần nhất ===\n'
df -h .
if [[ -d backups ]]; then find backups -maxdepth 2 -name COMPLETE -printf '%TY-%Tm-%Td %TH:%TM %h\n' | sort | tail -5; fi
printf '\n=== Nhắc kiểm tra ngoài phạm vi script ===\n'
echo 'SSH effective policy: sudo sshd -T (kể cả Match blocks), MFA Access, Docker published ports/DOCKER-USER hoặc nftables tương ứng.'
echo 'Không có kết quả PASS bảo mật tổng thể. Cần kiểm tra từ máy LAN và WAN độc lập.'
