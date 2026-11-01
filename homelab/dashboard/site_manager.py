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
    if not name or operation not in ('site-start', 'site-stop'): raise ValueError('Tác vụ site không hợp lệ')
    command = ['docker', 'compose', '--project-directory', str(target)]
    # No down, volume removal, arbitrary services, env files or client-supplied argv.
    command += ['up', '-d', '--build', 'web', 'db'] if operation == 'site-start' else ['stop', 'web', 'db']
    try:
        result = subprocess.run(command, cwd=target, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=600)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Triển khai quá thời gian, chưa xác nhận hoàn tất. Docker có thể vẫn xử lý; kiểm tra origin trước khi thử lại.')
    if result.returncode: raise RuntimeError('Docker chưa xác nhận tác vụ thành công. Không tự chạy lại hay xóa volume; kiểm tra trạng thái origin và tài nguyên máy.')
    if operation == 'site-stop': return {'message': 'Docker xác nhận dừng web và db của site; giữ nguyên file và volume.'}
    result = check(root, name)
    result['message'] = 'Docker xác nhận up hoàn tất. ' + result['message']
    return result
