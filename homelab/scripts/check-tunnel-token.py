#!/usr/bin/env python3
"""Read-only local token diagnostics. Never prints credentials or decoded identifiers."""
import base64
import json
import hmac
from pathlib import Path
import subprocess


def token_shape(token):
    try:
        payload = json.loads(base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True))
        return isinstance(payload, dict) and all(
            isinstance(payload.get(k), str) and bool(payload[k]) for k in ('a', 't', 's'))
    except (ValueError, UnicodeError):
        return False


def legacy_comparison(token):
    try:
        r = subprocess.run(['docker', 'inspect', 'cloudflared'], capture_output=True, text=True, timeout=10)
        if r.returncode:
            print('Container cloudflared cũ: chưa đọc được, không kết luận token cũ sai.')
            return
        data = json.loads(r.stdout)[0]
        args = data.get('Args', [])
        old = None
        for i, value in enumerate(args):
            if value == '--token' and i + 1 < len(args):
                old = args[i + 1]
                break
            if value.startswith('--token='):
                old = value.split('=', 1)[1]
                break
        if old is None and any(v == '--token-file' or v.startswith('--token-file=') for v in args):
            print('Container cũ dùng token-file; chưa so sánh, không tự đọc file khác.')
            return
        if old is None:
            values = [v.split('=', 1)[1] for v in data.get('Config', {}).get('Env', [])
                      if v.startswith('TUNNEL_TOKEN=')]
            old = values[0] if len(values) == 1 else None
        print('Container cũ đang chạy:', bool(data.get('State', {}).get('Running')))
        if old is None:
            print('Không xác định được token cũ từ tham số/env; chưa so sánh.')
        else:
            print('Token file mới GIỐNG token container cũ:', hmac.compare_digest(token.encode(), old.encode()))
            print('Container chạy không chứng minh đã xác thực Tunnel thành công; cần đối chiếu log.')
    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        print('Chưa so sánh được với container cũ; không suy ra token nào sai.')


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
    legacy_comparison(token)
    print('Chỉ kiểm tra cấu trúc và tính khớp, không xác minh token còn hiệu lực/đúng Tunnel.')
    print('Không in token, nội dung giải mã hoặc sửa cấu hình.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
