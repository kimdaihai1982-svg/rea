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
import sql_console
import site_manager

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
        raise RuntimeError('Docker chưa xác nhận thành công. Đọc lại trạng thái dịch vụ trước khi thử lại; không tự xóa dữ liệu.')
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
        return {'items': [], 'error': 'Thư mục sites không hợp lệ; không quản lý site cho đến khi quản trị viên kiểm tra.'}
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
                          'temporary': bool(value.get('temporary')),
                          'preview_url': value.get('preview_url') if site_manager.valid_preview(value.get('preview_url')) else None,
                          'deployment': 'Chỉ xác nhận có cấu hình; chưa kiểm tra container/DNS'})
            if len(items) >= 100:
                return {'items': items, 'error': 'Chỉ hiển thị tối đa 100 site. Danh sách chưa đầy đủ.'}
        return {'items': items, 'error': None}
    except (OSError, ValueError, KeyError, TypeError):
        return {'items': items, 'error': 'Inventory có file không đọc được; danh sách có thể chưa đầy đủ.'}


def create_site(req):
    # Domain/package/port ownership belongs to create-site.py; do not generate shell/YAML here.
    if req.get('domain_mode') == 'temporary':
        if not isinstance(req.get('name'), str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', req['name']):
            raise ValueError('Tên site không hợp lệ')
        req = dict(req, domain=req['name'] + '.preview.invalid')
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
                             '--port', str(port), '--write', *(['--temporary'] if req.get('domain_mode') == 'temporary' else []), '--', values['name']],
                            cwd=ROOT, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError('Không tạo được. Kiểm tra tên (a-z, số, dấu -), domain, cấu hình, cổng và các giá trị trùng. Không ghi đè site cũ.')
    return {'message': 'Đã tạo cấu hình và mật khẩu riêng trên server. Chưa khởi động Docker, tạo DNS hoặc gắn domain công khai.'}


def database_sql(statement, root=None):
    root = root or ROOT
    # Fixed in-container shell only expands the existing root secret; no user shell text.
    command = ['docker', 'compose', '--project-directory', str(root), 'exec', '-T', 'db',
               'sh', '-c', 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb --connect-timeout=3 --binary-mode=1 --local-infile=0 --batch --skip-column-names -uroot']
    result = subprocess.run(command, input=statement, cwd=root, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('Database chưa sẵn sàng hoặc câu lệnh thất bại. Không tự chạy lại lệnh tạo; kiểm tra danh sách trước.')
    return result.stdout


def database_inventory(root=None):
    out = database_sql("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME NOT IN ('information_schema','performance_schema','mysql','sys') ORDER BY SCHEMA_NAME LIMIT 101;\n", root)
    names = out.splitlines()
    return {'items': names[:100], 'error': 'Chỉ hiển thị 100 database' if len(names) > 100 else None}


def project_folders(root=None):
    base = (root or ROOT) / 'projects'
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


def resources(root=None):
    result = {'folders': {'items': [], 'error': None}, 'databases': {'items': [], 'error': None}}
    try:
        result['folders']['items'] = project_folders(root)
    except (OSError, ValueError):
        result['folders']['error'] = 'Chưa đọc được thư mục projects; không coi danh sách trống là không có dữ liệu.'
    try:
        result['databases'] = database_inventory(root)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        result['databases']['error'] = 'Chưa đọc được MariaDB; kiểm tra dịch vụ db. Không suy ra database đã mất.'
    return result


def create_folder(name, root=None):
    root = root or ROOT
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
        raise ValueError('Tên thư mục: chữ thường a-z, số, dấu -, bắt đầu bằng chữ, tối đa 32 ký tự')
    # Directory-relative operations with no-follow prevent escaping via project symlinks.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with_fd = os.open(root / 'projects', flags)
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
    return {'message': 'Đã tạo projects/' + name + '/public. Mở trong tab Tập tin ở /' + name + '/public. Chưa tạo virtual host/domain.'}


def create_database(name, root=None):
    if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', name)
            or name in ('mysql', 'sys', 'performance_schema', 'information_schema')):
        raise ValueError('Tên database: chữ thường a-z, số, dấu _, bắt đầu bằng chữ, tối đa 32 ký tự; không dùng tên hệ thống')
    # appuser@% must already exist; never implicitly create a user without a password.
    exists = database_sql("SELECT COUNT(*) FROM mysql.user WHERE User='appuser' AND Host='%';\n", root).strip()
    if exists != '1':
        raise ValueError('Không tìm thấy đúng tài khoản appuser@%; chưa tạo database')
    current = database_sql("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='" + name + "';\n", root).strip()
    if current:
        raise ValueError('Database đã tồn tại; không ghi đè')
    try:
        database_sql('CREATE DATABASE `' + name + '` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n', root)
        database_sql('GRANT ALL PRIVILEGES ON `' + name + "`.* TO 'appuser'@'%';\n", root)
    except (RuntimeError, subprocess.TimeoutExpired):
        raise RuntimeError('Tạo/cấp quyền chưa xác nhận hoàn tất, có thể database đã được tạo. Đọc lại danh sách và kiểm tra quyền trước khi thử lại; không xóa dữ liệu.')
    return {'message': 'Đã tạo database ' + name + ' và cấp quyền cho appuser. Dùng mật khẩu appuser hiện có của stack/site đang chọn; chưa liên kết với website.'}


def delete_database(name, confirmation, root=None):
    name = sql_console.name(name)
    if confirmation != 'DELETE ' + name:
        raise ValueError('Phải xác nhận DELETE và tên database; xóa vĩnh viễn, không có hoàn tác')
    current = database_sql("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='" + name + "';\n", root).strip()
    if current != name:
        raise ValueError('Database không tồn tại hoặc chưa xác minh được; chưa xóa')
    database_sql('DROP DATABASE `' + name + '`;\n', root)
    return {'message': 'MariaDB xác nhận đã xóa database ' + name + '. Không có hoàn tác. Quyền appuser cũ trên tên này có thể vẫn còn; tạo lại cùng tên không tạo cách ly mới.'}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 12000000:
                raise ValueError('Yêu cầu không hợp lệ')
            req = json.loads(self.rfile.read(length))
            action = req.get('action')
            if action == 'ping':
                data = {'ready': True}
            elif action == 'file-list':
                data = project_files.browse(site_manager.project(ROOT, req.get('site')), req.get('path', ''))
            elif action == 'file-read':
                data = project_files.read(site_manager.project(ROOT, req.get('site')), req.get('path'))
            elif action in ('file-upload', 'file-save', 'file-mkdir', 'file-delete', 'file-chmod', 'file-extract'):
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đang backup hoặc thao tác khác; thử lại sau')
                try:
                    if action == 'file-upload':
                        data = project_files.upload(site_manager.project(ROOT, req.get('site')), req.get('path'), req.get('content'))
                    elif action == 'file-save':
                        data = project_files.save(site_manager.project(ROOT, req.get('site')), req.get('path'), req.get('text'), req.get('version'))
                    elif action == 'file-extract':
                        data = project_files.extract(site_manager.project(ROOT, req.get('site')), req.get('path'), req.get('target', ''))
                    elif action == 'file-delete':
                        data = project_files.delete(site_manager.project(ROOT, req.get('site')), req.get('path'), req.get('confirmation'))
                    elif action == 'file-chmod':
                        data = project_files.chmod(site_manager.project(ROOT, req.get('site')), req.get('path'), req.get('mode'))
                    else:
                        data = project_files.mkdir(site_manager.project(ROOT, req.get('site')), req.get('path'))
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
            elif action in ('sql-query', 'delete-database', 'sql-import', 'sql-export'):
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đang có tác vụ quản lý; thử lại sau')
                try:
                    if action == 'sql-export':
                        data = sql_console.export_file(site_manager.project(ROOT, req.get('site')), req.get('name'), req.get('confirmation'))
                    elif action == 'sql-import':
                        data = sql_console.import_file(site_manager.project(ROOT, req.get('site')), req.get('name'), req.get('content'), req.get('confirmation'))
                    elif action == 'sql-query':
                        data = sql_console.query(site_manager.project(ROOT, req.get('site')), req.get('name'), req.get('query'), req.get('confirmation'))
                    else:
                        data = delete_database(req.get('name'), req.get('confirmation'), site_manager.project(ROOT, req.get('site')))
                    print(json.dumps({'event': action, 'time': time.time()}), flush=True)
                finally:
                    LOCK.release()
            elif action == 'site-check':
                data = site_manager.check(ROOT, req.get('name'))
            elif action in ('site-start', 'site-db-start', 'site-stop', 'site-preview', 'site-preview-stop'):
                site_manager.project(ROOT, req.get('name'))
                if action == 'site-preview' and req.get('confirmation') != 'PUBLIC ' + str(req.get('name')):
                    raise ValueError('Cần xác nhận PUBLIC và tên site trước khi công khai URL tạm')
                if not req.get('name'):
                    raise ValueError('Chỉ quản lý site riêng; stack chính dùng tab Dịch vụ')
                if JOB['state'] == 'running' or not LOCK.acquire(blocking=False):
                    raise ValueError('Đang có tác vụ quản lý; thử lại sau')
                JOB.update(state='running', message='Đang ' + action + ' cho ' + req['name'] + '. Có thể cần tải image/build trong vài phút.')
                def work(name=req['name'], operation=action):
                    try:
                        result = site_manager.preview(ROOT, name, operation) if operation in ('site-preview', 'site-preview-stop') else site_manager.lifecycle(ROOT, name, operation)
                        JOB.update(state='done', message=name + ': ' + result['message'])
                    except Exception:
                        JOB.update(state='error', message=name + (': chưa xác nhận URL tạm. Container có thể vẫn công khai; bấm Dừng URL tạm để ngắt. Không ảnh hưởng Tunnel chính.' if operation in ('site-preview', 'site-preview-stop') else ': chưa xác nhận tác vụ hoàn tất. Kiểm tra origin/trạng thái trước khi thử lại; không xóa dữ liệu.'))
                    finally:
                        LOCK.release()
                try:
                    threading.Thread(target=work, daemon=True).start()
                except Exception:
                    JOB.update(state='error', message='Chưa khởi động được tác vụ site')
                    LOCK.release()
                    raise
                print(json.dumps({'event': action, 'time': time.time()}), flush=True)
                data = {'message': 'Đã tiếp nhận tác vụ, chưa xác nhận triển khai thành công. Theo dõi trạng thái tác vụ và bấm Kiểm tra origin.'}
            elif action == 'resources':
                data = resources(site_manager.project(ROOT, req.get('site')))
            elif action == 'status':
                out = compose('ps', '--all', '--format', 'json')
                if out.strip().startswith('['):
                    rows = json.loads(out)
                else:
                    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
                # Return only selected non-secret state, never ambient environment.
                data = {'services': [{k: row.get(k, '') for k in ['Service', 'State', 'Health', 'Status']}
                                     for row in rows], 'snapshots': snapshots(), 'job': (dict(JOB) if not LOCK.locked() or JOB['state'] == 'running' else {'state': 'running', 'message': 'Đang xử lý file/SQL/MQTT. Đợi hoàn tất trước khi backup hoặc cập nhật.'}), 'site_inventory': site_inventory()}
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
                    root = site_manager.project(ROOT, req.get('site'))
                    data = create_folder(req.get('name'), root) if action == 'create-folder' else create_database(req.get('name'), root)
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
