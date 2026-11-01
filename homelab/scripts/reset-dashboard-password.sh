#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 && -f /etc/maychu247-ui/managed ]] || { echo 'Cần root và dashboard đã cài'; exit 1; }
python3 - <<'PY'
import hashlib,json,secrets
from pathlib import Path
p=Path('/etc/maychu247-ui/auth.json')
password=secrets.token_urlsafe(24)
salt=secrets.token_bytes(16)
p.write_text(json.dumps({'salt':salt.hex(),'hash':hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()}))
p.chmod(0o640)
print('Mật khẩu dashboard mới (lưu riêng): '+password)
PY
chown root:maychu247-ui /etc/maychu247-ui/auth.json
systemctl restart maychu247-dashboard.service
