#!/usr/bin/env python3
"""Read-only fixed-target diagnostics. No configuration changes or credential output."""
import base64
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time

TOKENS = []
NAMES = ('maychu247-dashboard-tunnel-connector-1', 'cloudflared')


def run(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired):
        return 1, '', 'Lệnh không chạy được hoặc quá thời gian'


def redact(text):
    for token in TOKENS:
        if token:
            text = text.replace(token, '[TOKEN REDACTED]')
    # Also avoid printing long credential-like blobs from any error message.
    return re.sub(r'[A-Za-z0-9_+/=-]{100,}', '[LONG VALUE REDACTED]', text)


def inspect(name):
    code, out, _ = run(['docker', 'inspect', name])
    if code:
        print(name + ': không đọc được container')
        return
    try:
        d = json.loads(out)[0]
        tokens = [v.split('=', 1)[1] for v in d.get('Config', {}).get('Env', []) if v.startswith('TUNNEL_TOKEN=')]
        args = d.get('Args', [])
        for i, a in enumerate(args):
            if a == '--token' and i + 1 < len(args):
                tokens.insert(0, args[i + 1])
            elif a.startswith('--token='):
                tokens.insert(0, a.split('=', 1)[1])
        TOKENS.extend(tokens)
        state = d.get('State', {})
        print(name)
        print('  State:', state.get('Status'), '| restart count:', d.get('RestartCount'))
        print('  Network:', d.get('HostConfig', {}).get('NetworkMode'))
        for token in tokens[:1]:
            try:
                value = json.loads(base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True))
                tunnel_id = value.get('t', '')
                if re.fullmatch(r'[0-9a-fA-F-]{36}', tunnel_id):
                    print('  Tunnel ID (không phải token):', tunnel_id)
            except (ValueError, UnicodeError, AttributeError):
                print('  Không đọc được Tunnel ID từ token; không suy ra token vô hiệu chỉ từ kiểm tra này.')
    except (ValueError, KeyError, IndexError, TypeError):
        print('  Không phân tích được thông tin container')


def http(url, host=None):
    args = ['curl', '--noproxy', '*', '--max-time', '15', '-sS', '-o', '/dev/null', '-w', '%{http_code}', url]
    if host:
        args.extend(['-H', 'Host: ' + host])
    code, out, err = run(args, timeout=20)
    print('  HTTP:', out.strip() or '000', '| curl exit:', code)
    if err:
        print(' ', redact(err.strip())[:500])


def main():
    if os.geteuid() != 0:
        raise SystemExit('Chạy sudo python3 ~/diagnose-502.py trên Ubuntu, không phải Windows.')
    print('=== MAYCHU247: BAO CAO CHI DOC ===')
    print('UTC:', datetime.datetime.now(datetime.timezone.utc).isoformat())
    print('\n[1] Hostname backend được cấu hình')
    try:
        for line in Path('/etc/maychu247-ui/public.env').read_text().splitlines():
            if line.startswith('MAYCHU247_PUBLIC_ORIGIN='):
                print(' ', redact(line))
    except OSError:
        print('  Không đọc được public.env')
    print('\n[2] Dashboard nội bộ với Host maychu247.uk')
    http('http://127.0.0.1:18000/', 'maychu247.uk')
    print('\n[3] Connector và Tunnel ID để đối chiếu DNS Cloudflare')
    for name in NAMES:
        inspect(name)
    since = str(int(time.time()) - 2)
    print('\n[4] Gọi public domain KHÔNG dùng cookie, KHÔNG theo redirect')
    http('https://maychu247.uk/')
    time.sleep(2)
    print('\n[5] Log mới quanh lần gọi domain + tối đa 12 lỗi gần đây của mỗi connector')
    for name in NAMES:
        print('---', name)
        for label, args in (
            ('Quanh lần gọi public', ['docker', 'logs', '--since', since, '--tail', '50', name]),
            ('Lỗi trong 10 phút gần đây', ['docker', 'logs', '--since', '10m', '--tail', '150', name]),
        ):
            _, out, err = run(args)
            lines = (out + '\n' + err).splitlines()
            selected = [s for s in lines if re.search(r'\bERR\b|Unable to reach|connection refused|token is not valid|Registered tunnel connection', s, re.I)]
            print(' ', label + ':')
            if selected:
                for line in selected[-12:]:
                    print('   ', redact(line)[:900])
            else:
                print('    Không có dòng phù hợp. Không chứng minh request đã đi qua connector này.')
    print('\n[6] Cần đối chiếu trên Cloudflare (script không có quyền API)')
    print('  DNS CNAME @ phải trỏ Tunnel ID của connector MỚI ở mục [3] + .cfargotunnel.com.')
    print('  Không thể xác định target DNS proxied chỉ bằng DNS lookup công khai.')
    print('  Route mới: maychu247.uk -> http://127.0.0.1:18000; không override Host.')
    print('  302/403 public có thể do Access; không tự coi đó là origin hỏng.')
    print('\nKHONG SUA FILE, KHONG RESTART, KHONG IN TOKEN. Giữ nguyên cấu hình đến khi đọc báo cáo.')


if __name__ == '__main__':
    main()
