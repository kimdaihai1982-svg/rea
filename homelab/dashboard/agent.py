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
import project_files
import mqtt_client

ROOT = Path('/opt/maychu247-v2')
SOCKET = '/run/maychu247/agent.sock'
SERVICES = {'web', 'db', 'adminer', 'mqtt', 'files'}
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


def site_inventory():
    base = ROOT / 'sites'
    if base.is_symlink():
        return {'items': [], 'error': 'Thư mục sites không hợp lệ; kiểm tra qua SSH.'}
    items = []
    try:
        for folder in sorted(base.glob('*')):
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', folder.name):
                continue
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError()
            metadata = folder / 'site.json'
            if metadata.is_symlink():
                raise ValueError()
            value = json.loads(metadata.read_text())
            items.append({'name': folder.name, 'domain': value['domain'],
                          'package': value['package'], 'port': value['port'],
                          'deployment': 'Chỉ xác nhận có cấu hình; chưa kiểm tra container/DNS'})
            if len(items) >= 100:
                return {'items': items, 'error': 'Chỉ hiển thị tối đa 100 site. Kiểm tra inventory qua SSH.'}
        return {'items': items, 'error': None}
    except (OSError, ValueError, KeyError, TypeError):
        return {'items': items, 'error': 'Inventory có file không đọc được; danh sách có thể chưa đầy đủ.'}


def create_site(req):
    # Domain/package/port ownership belongs to create-site.py; do not generate shell/YAML here.
    values = {}
    for key, limit in [('name', 32), ('domain', 253), ('package', 32)]:
        value = req.get(key)
        if not isinstance(value, str) or not 0 < len(value) <= limit or value.startswith('-'):
            raise ValueError('Tên, domain hoặc cấu hình tài nguyên không hợp lệ')
        values[key] = value
    port = req.get('port')
    if type(port) is not int:
        raise ValueError('Cổng phải là số nguyên trong khoảng 20000–29999')
    if len(site_inventory()['items']) >= 100:
        raise ValueError('Đã đạt giới hạn 100 cấu hình site')
    result = subprocess.run(['python3', str(ROOT / 'scripts/create-site.py'),
                             '--domain', values['domain'], '--package', values['package'],
                             '--port', str(port), '--write', '--', values['name']],
                            cwd=ROOT, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError('Không tạo được. Kiểm tra tên (a-z, số, dấu -), domain, cấu hình, cổng và các giá trị trùng. Không ghi đè site cũ.')
    return {'message': 'Đã tạo cấu hình và mật khẩu riêng trên server. Chưa khởi động Docker, tạo DNS hoặc gắn domain công khai.'}


def database_sql(statement):
    # Fixed in-container shell only expands the existing root secret; no user shell text.
    command = ['docker', 'compose', '--project-directory', str(ROOT), 'exec', '-T', 'db',
               'sh', '-c', 'exec mariadb --connect-timeout=3 --batch --skip-column-names -uroot -p"$MARIADB_ROOT_PASSWORD"']
    result = subprocess.run(command, input=statement, cwd=ROOT, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('Database chưa sẵn sàng hoặc câu lệnh thất bại. Không tự chạy lại lệnh tạo; kiểm tra danh sách trước.')
    return result.stdout


def database_inventory():
    out = database_sql("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME NOT IN ('information_schema','performance_schema','mysql','sys') ORDER BY SCHEMA_NAME LIMIT 101;\n")
    names = out.splitlines()
    return {'items': names[:100], 'error': 'Chỉ hiển thị 100 database' if len(names) > 100 else None}


def project_folders():
    base = ROOT / 'projects'
    if base.is_symlink():
        raise ValueError('projects không được là symlink')
    items = []
    for folder in sorted(base.iterdir()):
        if folder.is_symlink():
            continue
        if folder.is_dir() and re.fullmatch(r'[a-z][a-z0-9-]{0,31}', folder.name):
            items.append({'name': folder.name, 'path': 'projects/' + folder.name,
                          'public': (folder / 'public').is_dir() and not (folder / 'public').is_symlink()})
            if len(items) >= 100:
                break
    return items


def resources():
    result = {'folders': {'items': [], 'error': None}, 'databases': {'items': [], 'error': None}}
    try:
        result['folders']['items'] = project_folders()
    except (OSError, ValueError):
        result['folders']['error'] = 'Chưa đọc được thư mục projects; không coi danh sách trống là không có dữ liệu.'
    try:
        result['databases'] = database_inventory()
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        result['databases']['error'] = 'Chưa đọc được MariaDB; kiểm tra dịch vụ db. Không suy ra database đã mất.'
    return result


def create_folder(name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
        raise ValueError('Tên thư mục: chữ thường a-z, số, dấu -, bắt đầu bằng chữ, tối đa 32 ký tự')
    # Directory-relative operations with no-follow prevent escaping via project symlinks.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with_fd = os.open(ROOT / 'projects', flags)
    folder_fd = public_fd = None
    try:
        try:
            os.mkdir(name, mode=0o755, dir_fd=with_fd)
        except FileExistsError:
            raise ValueError('Tên thư mục đã tồn tại; không ghi đè')
        folder_fd = os.open(name, flags, dir_fd=with_fd)
        os.fchmod(folder_fd, 0o755)
        os.mkdir('public', mode=0o755, dir_fd=folder_fd)
        public_fd = os.open('public', flags, dir_fd=folder_fd)
        os.fchmod(public_fd, 0o755)
        fd = os.open('index.html', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o644, dir_fd=public_fd)
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, 'w') as file:
            file.write('<!doctype html><meta charset="utf-8"><title>Project ready</title><h1>' + name + '</h1><p>Thu muc moi da duoc tao.</p>')
    finally:
        if public_fd is not None: os.close(public_fd)
        if folder_fd is not None: os.close(folder_fd)
        os.close(with_fd)
    return {'message': 'Đã tạo projects/' + name + '/public. Thấy trong File Browser ở /' + name + '/public. Chưa tạo virtual host/domain.'}


def create_database(name):
    if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', name)
            or name in ('mysql', 'sys', 'performance_schema', 'information_schema')):
        raise ValueError('Tên database: chữ thường a-z, số, dấu _, bắt đầu bằng chữ, tối đa 32 ký tự; không dùng tên hệ thống')
    # appuser@% must already exist; never implicitly create a user without a password.
    exists = database_sql("SELECT COUNT(*) FROM mysql.user WHERE User='appuser' AND Host='%';\n").strip()
    if exists != '1':
        raise ValueError('Không tìm thấy đúng tài khoản appuser@%; chưa tạo database')
    current = database_sql("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='" + name + "';\n").strip()
    if current:
        raise ValueError('Database đã tồn tại; không ghi đè')
    try:
        database_sql('CREATE DATABASE `' + name + '` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n')
        database_sql('GRANT ALL PRIVILEGES ON `' + name + "`.* TO 'appuser'@'%';\n")
    except (RuntimeError, subprocess.TimeoutExpired):
        raise RuntimeError('Tạo/cấp quyền chưa xác nhận hoàn tất, có thể database đã được tạo. Kiểm tra danh sách và quyền qua SSH trước khi thử lại; không xóa dữ liệu.')
    return {'message': 'Đã tạo database ' + name + ' và cấp quyền cho appuser. Dùng cùng DB_PASSWORD của stack chính; chưa liên kết với website.'}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1500000:
                raise ValueError('Yêu cầu không hợp lệ')
            req = json.loads(self.rfile.read(length))
            action = req.get('action')
            if action == 'ping':
                data = {'ready': True}
            elif action == 'file-list':
                data = project_files.browse(ROOT, req.get('path', ''))
            elif action == 'file-read':
                data = project_files.read(ROOT, req.get('path'))
            elif action in ('file-upload', 'file-save', 'file-mkdir'):
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đang backup hoặc thao tác khác; thử lại sau')
                try:
                    if action == 'file-upload':
                        data = project_files.upload(ROOT, req.get('path'), req.get('content'))
                    elif action == 'file-save':
                        data = project_files.save(ROOT, req.get('path'), req.get('text'), req.get('version'))
                    else:
                        data = project_files.mkdir(ROOT, req.get('path'))
                    print(json.dumps({'event': action, 'time': time.time()}), flush=True)
                finally:
                    LOCK.release()
            elif action in ('mqtt-publish', 'mqtt-sample', 'mqtt-test'):
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đang backup hoặc thao tác khác; thử lại sau')
                try:
                    if action == 'mqtt-test':
                        data = mqtt_client.selftest(ROOT)
                    elif action == 'mqtt-publish':
                        data = mqtt_client.publish(ROOT, req.get('topic'), req.get('payload'))
                    else:
                        data = mqtt_client.sample(ROOT, req.get('topic'))
                    print(json.dumps({'event': action, 'time': time.time()}), flush=True)
                finally:
                    LOCK.release()
            elif action == 'resources':
                data = resources()
            elif action == 'status':
                out = compose('ps', '--all', '--format', 'json')
                if out.strip().startswith('['):
                    rows = json.loads(out)
                else:
                    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
                # Return only selected non-secret state, never ambient environment.
                data = {'services': [{k: row.get(k, '') for k in ['Service', 'State', 'Health', 'Status']}
                                     for row in rows], 'snapshots': snapshots(), 'job': dict(JOB), 'site_inventory': site_inventory()}
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
            elif action in ('create-folder', 'create-database'):
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đang có tác vụ quản lý; thử lại sau')
                try:
                    data = create_folder(req.get('name')) if action == 'create-folder' else create_database(req.get('name'))
                    print(json.dumps({'event': action, 'time': time.time()}), flush=True)
                finally:
                    LOCK.release()
            elif action == 'create-site':
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đang có tác vụ quản lý; thử lại sau')
                try:
                    data = create_site(req)
                    print(json.dumps({'event': 'create-site', 'time': time.time()}), flush=True)
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
        except FileExistsError:
            self.reply(400, {'error': 'Tên đã tồn tại; không ghi đè. Mở file để sửa nếu cần.'})
        except OSError:
            self.reply(400, {'error': 'Không truy cập được file hoặc dịch vụ nội bộ. Nếu là MQTT: kiểm tra broker, mật khẩu và cổng; không tự gửi lại để tránh tin trùng.'})
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
