#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
[[ $EUID == 0 ]] || { echo 'Chạy bằng sudo'; exit 1; }
[[ $PWD == /opt/maychu247-v2 ]] || { echo 'Timer chỉ hỗ trợ đường dẫn /opt/maychu247-v2'; exit 1; }
for f in /etc/systemd/system/maychu247-backup.{service,timer}; do
  [[ ! -e $f ]] || { echo "Đã tồn tại $f; kiểm tra thủ công, không ghi đè"; exit 1; }
done
cat > /etc/systemd/system/maychu247-backup.service <<'UNIT'
[Unit]
Description=MayChu247 consistent backup (brief maintenance)
Requires=docker.service
After=docker.service
[Service]
Type=oneshot
WorkingDirectory=/opt/maychu247-v2
ExecStart=/opt/maychu247-v2/scripts/backup-all.sh
UMask=0077
UNIT
cat > /etc/systemd/system/maychu247-backup.timer <<'UNIT'
[Unit]
Description=MayChu247 daily backup
[Timer]
OnCalendar=*-*-* 03:15:00
RandomizedDelaySec=300
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now maychu247-backup.timer
