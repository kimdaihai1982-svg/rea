#!/usr/bin/env python3
"""Unprivileged loopback dashboard, stdlib only. No Docker socket or shell access."""
import hashlib
import hmac
import http.client
from http.cookies import SimpleCookie
import http.server
import json
import os
from pathlib import Path
import secrets
import re
import shutil
import socket
import threading
import time
from urllib.parse import urlsplit, parse_qs
from monitor import Monitor

def configured_origin(value):
    if not value:
        return ''
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != parsed.hostname or
        parsed.path or parsed.query or parsed.fragment or
        not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', parsed.netloc) or
        '.' not in parsed.netloc):
        raise ValueError('MAYCHU247_PUBLIC_ORIGIN phải là https://hostname cụ thể, không path/port/wildcard')
    return value


PUBLIC_ORIGIN = configured_origin(os.environ.get('MAYCHU247_PUBLIC_ORIGIN', ''))
HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get('MAYCHU247_AUTH', '/etc/maychu247-ui/auth.json'))
SESSIONS = {}
ATTEMPTS = []
AUTH_LOCK = threading.Lock()
SESSION_TTL = 3600
MONITOR = Monitor()
LAST_CPU = None
METRIC_LOCK = threading.Lock()


def cpu_sample():
    global LAST_CPU
    with METRIC_LOCK:
        fields = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        current = (sum(fields), fields[3] + fields[4])
        previous, LAST_CPU = LAST_CPU, current
        if previous is None or current[0] <= previous[0]:
            return None
        return round(100 * (1 - (current[1] - previous[1]) / (current[0] - previous[0])), 1)


def metrics():
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    disk = shutil.disk_usage('/opt')
    return {'cpu': cpu_sample(), 'load': list(os.getloadavg()), 'cpus': os.cpu_count(),
            'memory_total': memory['MemTotal'],
            'memory_used': memory['MemTotal'] - memory['MemAvailable'],
            'disk_total': disk.total, 'disk_used': disk.used,
            'uptime_seconds': int(float(Path('/proc/uptime').read_text().split()[0])),
            'sampled_at': int(time.time())}


class AgentConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/run/maychu247/agent.sock')


def agent(data):
    conn = AgentConnection('localhost', timeout=100)
    try:
        conn.request('POST', '/', body=json.dumps(data), headers={'Content-Type': 'application/json'})
        res = conn.getresponse()
        return res.status, json.loads(res.read(8500000))
    finally:
        conn.close()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # No bodies, credentials, tokens, query strings or cookies in request logs.
        pass

    def reply(self, code, data, cookie=None, content_type='application/json; charset=utf-8'):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            token = cookie['session'].value
        except (KeyError, ValueError):
            return None
        with AUTH_LOCK:
            session = SESSIONS.get(token)
            if session and session['expires'] > time.time():
                return token, session
            SESSIONS.pop(token, None)
        return None

    def valid_host(self):
        host = self.headers.get('Host', '')
        return host in ('localhost:18000', '127.0.0.1:18000') or bool(PUBLIC_ORIGIN and host == urlsplit(PUBLIC_ORIGIN).netloc)

    def secure_cookie(self):
        return '; Secure' if PUBLIC_ORIGIN and self.headers.get('Host') == urlsplit(PUBLIC_ORIGIN).netloc else ''

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': 'Hostname chưa được cho phép; dùng SSH tunnel hoặc domain đã cấu hình'})
        path = urlsplit(self.path).path
        static = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path in static:
            name, mime = static[path]
            return self.reply(200, (HERE / name).read_bytes(), content_type=mime)
        session = self.session()
        if not session:
            return self.reply(401, {'error': 'Cần đăng nhập'})
        if path == '/api/session':
            return self.reply(200, {'csrf': session[1]['csrf'], 'expires': session[1]['expires']})
        if path in ('/api/files', '/api/file'):
            query = parse_qs(urlsplit(self.path).query)
            try:
                code, data = agent({'action': 'file-list' if path == '/api/files' else 'file-read', 'path': query.get('path', [''])[0], 'site': query.get('site', [''])[0]})
                return self.reply(code, data)
            except Exception:
                return self.reply(503, {'error': 'Không đọc được file; kiểm tra agent hoặc đường dẫn.'})
        if path == '/api/resources':
            try:
                code, data = agent({'action': 'resources', 'site': parse_qs(urlsplit(self.path).query).get('site', [''])[0]})
                return self.reply(code, data)
            except Exception:
                return self.reply(503, {'error': 'Không đọc được tài nguyên; kiểm tra agent.'})
        if path == '/api/status':
            try:
                status, data = agent({'action': 'status'})
                data['host'] = metrics()
                data['offsite'] = 'Chưa tích hợp/xác minh'
                data['monitor'] = MONITOR.snapshot()
                return self.reply(status, data)
            except Exception:
                return self.reply(503, {'error': 'Không kết nối được agent; không hiển thị số liệu giả.'})
        return self.reply(404, {'error': 'Không tìm thấy'})

    def do_POST(self):
        if not self.valid_host():
            return self.reply(403, {'error': 'Host không được phép'})
        # Exact host/origin pairing. Never trust arbitrary forwarded headers.
        expected = PUBLIC_ORIGIN if PUBLIC_ORIGIN and self.headers.get('Host') == urlsplit(PUBLIC_ORIGIN).netloc else 'http://' + self.headers.get('Host', '')
        if self.headers.get('Origin') != expected:
            return self.reply(403, {'error': 'Origin không được phép'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': 'Cần JSON'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = 12000000 if self.path == '/api/action' else 4096
            if not 0 < length <= limit:
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, json.JSONDecodeError):
            return self.reply(400, {'error': 'Yêu cầu không hợp lệ'})
        if self.path == '/api/login':
            now = time.time()
            with AUTH_LOCK:
                ATTEMPTS[:] = [t for t in ATTEMPTS if now - t < 300]
                if len(ATTEMPTS) >= 10:
                    return self.reply(429, {'error': 'Thử quá nhiều lần; đợi 5 phút'})
                ATTEMPTS.append(now)
            config = json.loads(CONFIG_PATH.read_text())
            password = data.get('password', '')
            if not isinstance(password, str):
                return self.reply(400, {'error': 'Mật khẩu không hợp lệ'})
            digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(config['salt']), n=16384, r=8, p=1).hex()
            if not hmac.compare_digest(digest, config['hash']):
                return self.reply(401, {'error': 'Mật khẩu không đúng'})
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            with AUTH_LOCK:
                for old in list(SESSIONS):
                    if SESSIONS[old]['expires'] <= now:
                        del SESSIONS[old]
                if len(SESSIONS) >= 20:
                    return self.reply(429, {'error': 'Quá nhiều phiên đăng nhập'})
                SESSIONS[token] = {'csrf': csrf, 'expires': now + SESSION_TTL}
            return self.reply(200, {'csrf': csrf}, cookie=f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}' + self.secure_cookie())
        session = self.session()
        if not session:
            return self.reply(401, {'error': 'Phiên hết hạn; đăng nhập lại'})
        if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session[1]['csrf']):
            return self.reply(403, {'error': 'CSRF token không hợp lệ'})
        if self.path == '/api/logout':
            with AUTH_LOCK:
                SESSIONS.pop(session[0], None)
            return self.reply(200, {}, cookie='session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' + self.secure_cookie())
        if self.path != '/api/action':
            return self.reply(404, {'error': 'Không tìm thấy'})
        if data.get('action') not in ('start', 'stop', 'restart', 'backup', 'create-site', 'create-folder', 'create-database', 'file-upload', 'file-save', 'file-mkdir', 'file-delete', 'file-chmod', 'file-extract', 'sql-import', 'sql-query', 'delete-database', 'site-start', 'site-db-start', 'site-stop', 'site-check', 'site-preview', 'site-preview-stop', 'mqtt-publish', 'mqtt-sample', 'mqtt-test'):
            return self.reply(400, {'error': 'Thao tác chưa hỗ trợ'})
        try:
            payload = {'action': data.get('action'), 'service': data.get('service')}
            if data.get('action') == 'create-site':
                if PUBLIC_ORIGIN and str(data.get('domain', '')).lower().rstrip('.') == urlsplit(PUBLIC_ORIGIN).hostname:
                    return self.reply(400, {'error': 'Domain này đang dành cho dashboard. Không tạo website riêng trùng domain quản trị.'})
                payload = {key: data.get(key) for key in ('action', 'name', 'domain', 'domain_mode', 'package', 'port')}
            if data.get('action') in ('create-folder', 'create-database'):
                payload = {key: data.get(key) for key in ('action', 'name')}
            if data.get('action') in ('file-upload', 'file-save', 'file-mkdir', 'file-delete', 'file-chmod', 'file-extract'):
                payload = {key: data.get(key) for key in ('action', 'path', 'content', 'text', 'version', 'mode', 'confirmation', 'target')}
            if data.get('action') in ('mqtt-publish', 'mqtt-sample', 'mqtt-test'):
                payload = {key: data.get(key) for key in ('action', 'topic', 'payload')}
            if data.get('action') in ('sql-query', 'delete-database', 'sql-import'):
                payload = {key: data.get(key) for key in (('action', 'name', 'query', 'confirmation') if data.get('action') != 'sql-import' else ('action', 'name', 'content', 'confirmation'))}
            if data.get('action') in ('site-start', 'site-db-start', 'site-stop', 'site-check', 'site-preview', 'site-preview-stop'):
                payload = {key: data.get(key) for key in ('action', 'name')}
                if data.get('action') == 'site-preview': payload['confirmation'] = data.get('confirmation')
            if data.get('action') in ('file-upload', 'file-save', 'file-mkdir', 'file-delete', 'file-chmod', 'file-extract', 'sql-import', 'sql-query', 'delete-database', 'create-folder', 'create-database'):
                payload['site'] = data.get('site', '')
            status, result = agent(payload)
            return self.reply(status, result)
        except Exception:
            return self.reply(503, {'error': 'Agent không phản hồi. Chưa xác nhận thao tác hoàn tất; đọc lại trạng thái trước khi thử lại.'})


if __name__ == '__main__':
    MONITOR.start()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 18000), Handler)
    server.daemon_threads = True
    server.serve_forever()
