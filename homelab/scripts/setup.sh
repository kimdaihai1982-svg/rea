#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'Cần cài Docker Engine + Compose plugin trước (xem README).'; exit 1; }
docker compose version >/dev/null
[[ ! -e .env && ! -e secrets/mqtt.passwd ]] || { echo 'Đã có cấu hình: không ghi đè. Dùng docker compose up -d --build.'; exit 1; }
umask 077
mkdir -p secrets backups
python3 - <<'PY'
import secrets
from pathlib import Path
keys = ['DB_PASSWORD', 'DB_ROOT_PASSWORD', 'MQTT_PASSWORD']
Path('.env').write_text('BIND_IP=127.0.0.1\n' + ''.join(k+'='+secrets.token_hex(24)+'\n' for k in keys) + 'TUNNEL_TOKEN=\n')
PY
# Container receives only the MQTT password, not root/database credentials.
MQTT_PASSWORD=$(sed -n 's/^MQTT_PASSWORD=//p' .env)
docker run --rm -e MQTT_PASSWORD="$MQTT_PASSWORD" -v "$PWD/secrets:/out" eclipse-mosquitto:2 sh -c 'mosquitto_passwd -b -c /out/mqtt.passwd mqttuser "$MQTT_PASSWORD"; chmod 644 /out/mqtt.passwd'
unset MQTT_PASSWORD
docker compose config --quiet
docker compose up -d --build
echo 'Tiếp theo: sudo bash scripts/install-dashboard.sh để có giao diện ở cổng 18000.'
echo 'Đã gửi lệnh khởi động. Kiểm tra: docker compose ps; docker compose logs --tail 50'
echo 'Mật khẩu: .env. Filebrowser admin ban đầu: docker compose logs files (đổi ngay).'
