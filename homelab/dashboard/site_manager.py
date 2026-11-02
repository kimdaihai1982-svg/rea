"""Manage only generated local projects, never arbitrary Compose files or network origins."""
import http.client
import json
from pathlib import Path
import re
import stat
import subprocess


def project(root, name=None):
    root = Path(root)
    if name in (None, ''): return root
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
        raise ValueError('Tên site không hợp lệ')
    for path in (root / 'sites', root / 'sites' / name):
        if not stat.S_ISDIR(path.lstat().st_mode): raise ValueError('Thư mục site không hợp lệ hoặc là symlink')
    target = root / 'sites' / name
    for relative in ('site.json', 'compose.yaml', '.env'):
        path = target / relative
        if not stat.S_ISREG(path.lstat().st_mode): raise ValueError('Cấu hình site không hợp lệ hoặc là symlink')
    if not stat.S_ISDIR((target / 'projects').lstat().st_mode): raise ValueError('projects không hợp lệ')
    metadata(root, name)
    return target


def metadata(root, name):
    path = Path(root) / 'sites' / name / 'site.json'
    if path.is_symlink() or path.stat().st_size > 4096: raise ValueError('Metadata site không hợp lệ')
    value = json.loads(path.read_text())
    domain = value.get('domain')
    if (value.get('name') != name or type(value.get('port')) is not int or not 20000 <= value['port'] <= 29999
            or not isinstance(domain, str) or len(domain) > 253 or '.' not in domain
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in domain.split('.'))):
        raise ValueError('Domain/cổng trong metadata không hợp lệ')
    return value


def check(root, name):
    project(root, name)
    value = metadata(root, name)
    connection = http.client.HTTPConnection('127.0.0.1', value['port'], timeout=3)
    try:
        connection.request('GET', '/', headers={'Host': value['domain'], 'Connection': 'close'})
        response = connection.getresponse()
        # Do not follow redirects, return headers/body, or connect to supplied hostnames.
        status = response.status
    except (OSError, http.client.HTTPException):
        return {'ready': False, 'origin': 'http://127.0.0.1:' + str(value['port']), 'domain': value['domain'],
                'message': 'Chưa kết nối được HTTP origin. Không suy ra dữ liệu đã mất. Chờ tác vụ triển khai hoặc kiểm tra trạng thái dịch vụ.'}
    finally: connection.close()
    return {'ready': status == 200, 'status': status, 'origin': 'http://127.0.0.1:' + str(value['port']),
            'domain': value['domain'], 'message': 'Origin trả HTTP ' + str(status) + ' với Host domain đã cấu hình. Chưa xác minh DNS, Tunnel hay HTTPS công khai.'}


def lifecycle(root, name, operation):
    target = project(root, name)
    if not name or operation not in ('site-start', 'site-stop', 'site-db-start'): raise ValueError('Tác vụ site không hợp lệ')
    command = ['docker', 'compose', '--project-directory', str(target)]
    # No down, volume removal, arbitrary services, env files or client-supplied argv.
    if operation == 'site-db-start': command += ['up', '-d', '--wait', '--wait-timeout', '90', 'db']
    else: command += ['up', '-d', '--build', 'web', 'db'] if operation == 'site-start' else ['stop', 'web', 'db']
    try:
        result = subprocess.run(command, cwd=target, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=600)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Triển khai quá thời gian, chưa xác nhận hoàn tất. Docker có thể vẫn xử lý; kiểm tra origin trước khi thử lại.')
    if result.returncode: raise RuntimeError('Docker chưa xác nhận tác vụ thành công. Không tự chạy lại hay xóa volume; kiểm tra trạng thái origin và tài nguyên máy.')
    if operation == 'site-db-start': return {'message': 'Docker xác nhận database site đã chạy/healthy. Chưa bật web hoặc URL công khai; có thể nạp SQL.'}
    if operation == 'site-stop': return {'message': 'Docker xác nhận dừng web và db của site; giữ nguyên file và volume.'}
    result = check(root, name)
    result['message'] = 'Docker xác nhận up hoàn tất. ' + result['message']
    return result


def valid_preview(value):
    return isinstance(value, str) and bool(re.fullmatch(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com', value))


def preview(root, name, operation):
    """Opt-in public Quick Tunnel. Separate container; never alters existing host Tunnel/DNS."""
    import os
    import secrets
    import time
    target = project(root, name)
    if not name or operation not in ('site-preview', 'site-preview-stop'): raise ValueError('Tác vụ URL tạm không hợp lệ')
    value = metadata(root, name)
    container = 'maychu247-preview-' + name
    origin = 'http://127.0.0.1:' + str(value['port'])
    listing = subprocess.run(['docker', 'container', 'ls', '-a', '--filter', 'name=^/' + container + '$', '--format', '{{.Names}}'], capture_output=True, timeout=10)
    if listing.returncode: raise RuntimeError('Chưa đọc được Docker; không xác nhận URL tạm đã dừng')
    exists = container in listing.stdout.decode('utf-8').splitlines()
    inspect = subprocess.run(['docker', 'container', 'inspect', container], capture_output=True, timeout=10) if exists else None
    if exists and inspect.returncode: raise RuntimeError('Chưa xác minh được container URL tạm')
    if exists:
        try:
            info = json.loads(inspect.stdout)[0]
            if (info['Config']['Labels'].get('io.maychu247.preview') != name
                    or info['HostConfig']['NetworkMode'] != 'host'
                    or info['Config']['Cmd'] != ['tunnel', '--no-autoupdate', '--url', origin]):
                raise ValueError('Tên container URL tạm đang thuộc cấu hình khác; không thay/xóa')
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ValueError('Chưa xác minh được container URL tạm; không thay/xóa') from None
    def store(url):
        value['preview_url'] = url
        temporary = target / ('.preview-save-' + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'w') as output:
                output.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
                output.flush(); os.fsync(output.fileno())
            os.replace(temporary, target / 'site.json')
        finally:
            if temporary.exists(): temporary.unlink()
    if operation == 'site-preview-stop':
        if exists:
            result = subprocess.run(['docker', 'stop', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            if result.returncode: raise RuntimeError('Chưa xác nhận dừng URL tạm; không báo đã ngắt công khai')
        store(None)
        return {'message': 'Đã dừng/xác nhận không có container URL tạm. Không đổi Tunnel chính; website/domain riêng khác vẫn có thể công khai.'}
    if not check(root, name).get('ready'):
        raise ValueError('Origin chưa HTTP 200. Triển khai site và kiểm tra origin trước khi tạo URL công khai.')
    if not exists:
        result = subprocess.run(['docker', 'run', '-d', '--rm', '--name', container,
                                 '--label', 'io.maychu247.preview=' + name, '--network', 'host',
                                 '--read-only', '--memory', '128m', '--cpus', '0.5', '--pids-limit', '64', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                                 '--log-opt', 'max-size=1m', '--log-opt', 'max-file=1',
                                 'cloudflare/cloudflared:latest', 'tunnel', '--no-autoupdate', '--url', origin],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        if result.returncode: raise RuntimeError('Không khởi động được Quick Tunnel; chưa có URL tạm. Không đổi Tunnel chính.')
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        logs = subprocess.run(['docker', 'logs', '--tail', '60', container], capture_output=True, timeout=5)
        # Return only a strict Cloudflare-assigned URL, never raw container logs.
        matches = re.findall(rb'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com', logs.stdout + logs.stderr)
        if logs.returncode == 0 and matches:
            url = matches[-1].decode('ascii')
            store(url)
            return {'url': url, 'message': 'Quick Tunnel đã cấp URL tạm ' + url + '. Chưa kiểm tra HTTPS từ ngoài. URL công khai, không có Access của dashboard, có thể đổi/mất khi dừng. Không dùng production/dữ liệu nhạy cảm.'}
        time.sleep(1)
    raise RuntimeError('Chưa nhận URL tạm. Container có thể vẫn công khai; dùng Dừng URL tạm để ngắt hoặc thử đọc lại sau. Không ảnh hưởng Tunnel chính.')
