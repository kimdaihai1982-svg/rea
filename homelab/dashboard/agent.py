#!/usr/bin/env python3
"""Local privileged broker. Unix socket only; fixed Compose commands, no shell/API exec."""
import grp
import http.server
import json
import os
from pathlib import Path
import re
import socketserver
import subprocess
import threading
import time

ROOT = Path('/opt/maychu247-v2')
SOCKET = '/run/maychu247/agent.sock'
SERVICES = {'web', 'db', 'adminer', 'mqtt', 'kuma', 'files'}
LOCK = threading.Lock()
JOB = {'state': 'idle', 'message': 'Chưa chạy backup trong phiên agent này'}


def compose(*args, timeout=45):
    r = subprocess.run(['docker', 'compose', '--project-directory', str(ROOT), *args],
                       cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        # Do not expose command stderr: it can contain credentials/config values.
        raise RuntimeError('Docker báo lỗi. Kiểm tra journal và compose logs qua SSH.')
    return r.stdout[-100000:]


def backup():
    try:
        subprocess.run(['bash', str(ROOT / 'scripts/backup-all.sh')], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, start_new_session=True)
        JOB.update(state='done', message='Backup script hoàn tất; kiểm tra snapshot và offsite riêng.')
    except Exception:
        JOB.update(state='error', message='Backup lỗi. Kiểm tra qua SSH trước khi chạy lại.')
    finally:
        LOCK.release()


def snapshots():
    results = []
    for marker in sorted((ROOT / 'backups').glob('*/COMPLETE'), reverse=True)[:20]:
        if re.fullmatch(r'20\d{6}T\d{6}Z', marker.parent.name):
            results.append({'name': marker.parent.name,
                            'bytes': sum(p.stat().st_size for p in marker.parent.iterdir() if p.is_file()),
                            'checksum': 'Chưa kiểm tra lại'})
    return results


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError('Yêu cầu không hợp lệ')
            req = json.loads(self.rfile.read(length))
            action = req.get('action')
            if action == 'status':
                out = compose('ps', '--all', '--format', 'json')
                if out.strip().startswith('['):
                    rows = json.loads(out)
                else:
                    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
                # Return only selected non-secret state, never ambient environment.
                data = {'services': [{k: row.get(k, '') for k in ['Service', 'State', 'Health', 'Status']}
                                     for row in rows], 'snapshots': snapshots(), 'job': dict(JOB)}
            elif action in ('start', 'stop', 'restart'):
                svc = req.get('service')
                if svc not in SERVICES:
                    raise ValueError('Dịch vụ không được phép')
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đang có tác vụ quản lý; thử lại sau')
                try:
                    compose(action, svc, timeout=90)
                    print(json.dumps({'event': action, 'service': svc, 'time': time.time()}), flush=True)
                    data = {'message': f'Đã gửi lệnh {action} cho {svc}; kiểm tra trạng thái.'}
                finally:
                    LOCK.release()
            elif action == 'backup':
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đã có tác vụ đang chạy')
                JOB.update(state='running', message='Backup đang chạy. Web/MQTT có thể tạm dừng.')
                threading.Thread(target=backup, daemon=True).start()
                print(json.dumps({'event': 'backup', 'time': time.time()}), flush=True)
                data = dict(JOB)
            else:
                raise ValueError('Chức năng chưa được hỗ trợ')
            self.reply(200, data)
        except (ValueError, RuntimeError) as e:
            self.reply(400, {'error': str(e)})
        except Exception:
            self.reply(503, {'error': 'Agent không đọc được trạng thái. Kiểm tra qua SSH.'})

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == '__main__':
    os.umask(0o007)
    if os.path.exists(SOCKET):
        os.unlink(SOCKET)
    with Server(SOCKET, Handler) as server:
        os.chown(SOCKET, 0, grp.getgrnam('maychu247-ui').gr_gid)
        os.chmod(SOCKET, 0o660)
        server.serve_forever()
