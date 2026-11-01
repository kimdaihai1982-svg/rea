#!/usr/bin/env python3
"""Read-only local token diagnostics. Never prints credentials or decoded identifiers."""
import base64
import json
from pathlib import Path
import subprocess


def token_shape(token):
    try:
        payload = json.loads(base64.b64decode(token + '=' * (-len(token) % 4), validate=True))
        return isinstance(payload, dict) and all(
            isinstance(payload.get(k), str) and bool(payload[k]) for k in ('a', 't', 's'))
    except (ValueError, UnicodeError):
        return False


def main():
    path = Path('/etc/maychu247-ui/tunnel.env')
    try:
        lines = path.read_text().splitlines()
    except OSError:
        print('Không đọc được tunnel.env. Chạy bằng sudo trên Ubuntu server, không phải CMD Windows.')
        return 1
    entries = [line for line in lines if line.startswith('TUNNEL_TOKEN=')]
    print('Số dòng TUNNEL_TOKEN:', len(entries))
    if len(entries) != 1:
        print('Cần đúng một dòng; chưa thay đổi file.')
        return 1
    token = entries[0].split('=', 1)[1]
    print('Có khoảng trắng hoặc dấu nháy:', any(c.isspace() for c in token) or '"' in token or "'" in token)
    print('Đúng cấu trúc Tunnel Token:', token_shape(token))
    try:
        result = subprocess.run(['docker', 'inspect', 'maychu247-dashboard-tunnel-connector-1'],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            env = json.loads(result.stdout)[0]['Config'].get('Env', [])
            actual = [value.split('=', 1)[1] for value in env if value.startswith('TUNNEL_TOKEN=')]
            print('Container đang dùng đúng chuỗi trong file:', actual == [token])
        else:
            print('Chưa đọc được container connector mới.')
    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        print('Chưa kiểm tra được môi trường container.')
    print('Chỉ kiểm tra cấu trúc và tính khớp, không xác minh token còn hiệu lực/đúng Tunnel.')
    print('Không in token, nội dung giải mã hoặc sửa cấu hình.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
