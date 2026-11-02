#!/usr/bin/env bash
# Standalone MayChu247 backup. No install, updates, DNS changes or retention deletion.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Cần quyền quản trị: sudo bash MayChu247-Backup.sh'; exit 1; }
command -v python3 >/dev/null || { echo 'Thiếu Python 3'; exit 1; }
exec python3 - <<'PY'
import contextlib
import datetime
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys

ROOT = Path('/opt/maychu247-v2')
UNITS = ('maychu247-agent.service', 'maychu247-dashboard.service')


def run(args, output=None, timeout=120):
    # Never print raw Docker output: it may contain credentials/config.
    result = subprocess.run(args, stdout=output if output is not None else subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Tác vụ thất bại: ' + Path(args[0]).name + '. Không đánh dấu bản sao lưu hoàn tất.')


def capture(args):
    result = subprocess.run(args, capture_output=True, timeout=30)
    if result.returncode: raise RuntimeError('Không đọc được trạng thái Docker; chưa sao lưu.')
    return result.stdout.decode('utf-8').splitlines()


def compose(project, *args):
    return ['docker', 'compose', '--project-directory', str(project), *args]


def check_job():
    path = '/run/maychu247/agent.sock'
    if not Path(path).exists(): return
    connection = http.client.HTTPConnection('localhost', timeout=10)
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(10)
    try:
        connection.sock.connect(path)
        connection.request('POST', '/', json.dumps({'action': 'status'}), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = json.loads(response.read(1024 * 1024))
        if response.status != 200 or data.get('job', {}).get('state') == 'running':
            raise RuntimeError('Dashboard đang có tác vụ hoặc chưa xác minh được trạng thái. Đợi hoàn tất rồi sao lưu.')
    finally: connection.close()


def stopped_by_signal(signum, frame):
    raise RuntimeError('Đã nhận yêu cầu dừng. Bản sao lưu chưa hoàn tất.')


os.umask(0o077)
work = None
success = False
resume_services = []
resume_units = []
restore_errors = []
locks = contextlib.ExitStack()
try:
    for executable in ('docker', 'tar', 'systemctl'):
        if not shutil.which(executable): raise RuntimeError('Thiếu công cụ hệ thống: ' + executable)
    if ROOT.is_symlink() or not ROOT.is_dir(): raise RuntimeError('Không có stack hợp lệ tại /opt/maychu247-v2.')
    for name in ('.env', 'compose.yaml'):
        if (ROOT / name).is_symlink() or not (ROOT / name).is_file(): raise RuntimeError('Thiếu cấu hình stack hợp lệ; không sao lưu nhầm thư mục.')
    projects = [('main', ROOT)]
    sites = ROOT / 'sites'
    if sites.is_symlink(): raise RuntimeError('sites là symlink; dừng để tránh sao lưu nhầm dữ liệu.')
    if sites.exists():
        for folder in sorted(sites.iterdir()):
            if folder.name.startswith('.'): continue
            if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', folder.name):
                raise RuntimeError('Có mục sites không hợp lệ; cần quản trị viên kiểm tra trước.')
            for name in ('.env', 'compose.yaml', 'site.json'):
                if (folder / name).is_symlink() or not (folder / name).is_file(): raise RuntimeError('Site thiếu cấu hình hợp lệ: ' + folder.name)
            projects.append((folder.name, folder))
    # Coordinate with existing backup/restore scripts. Keep all locks until completion.
    for label, project in projects:
        backups = project / 'backups'
        if backups.is_symlink(): raise RuntimeError('backups không được là symlink.')
        backups.mkdir(mode=0o700, exist_ok=True)
        lock_path = backups / '.lock'
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        handle = locks.enter_context(os.fdopen(fd, 'a'))
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Đang backup/restore khác; chưa chạy bản mới.')
    check_job()
    signal.signal(signal.SIGTERM, stopped_by_signal)
    signal.signal(signal.SIGINT, stopped_by_signal)
    # Stop native panel writers before final job check and any source/data capture.
    for unit in UNITS:
        active = subprocess.run(['systemctl', 'is-active', '--quiet', unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if active: resume_units.append(unit)
    if 'maychu247-agent.service' in resume_units and not Path('/run/maychu247/agent.sock').exists():
        raise RuntimeError('Agent đang chạy nhưng chưa đọc được socket/job; không dừng tác vụ chưa rõ trạng thái.')
    if 'maychu247-dashboard.service' in resume_units:
        run(['systemctl', 'stop', 'maychu247-dashboard.service'])
    check_job()  # Catches a job started during the first check / UI shutdown window.
    if 'maychu247-agent.service' in resume_units:
        run(['systemctl', 'stop', 'maychu247-agent.service'])
    # Preflight every database before pausing web. A stopped DB is not an empty DB.
    states = []
    for label, project in projects:
        running = capture(compose(project, 'ps', '--services', '--status', 'running'))
        existing = capture(compose(project, 'ps', '--all', '--services'))
        config_only = False
        if 'db' not in running:
            volumes = capture(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=site-' + label]) if label != 'main' else ['main-requires-db']
            if label != 'main' and not existing and not volumes:
                config_only = True
            else:
                raise RuntimeError('Database chưa chạy ở ' + label + '. Không tự khởi động hoặc coi dữ liệu trống. Chưa tạo bản sao lưu hoàn tất.')
        if not config_only:
            run(compose(project, 'exec', '-T', 'db', 'healthcheck.sh', '--connect', '--innodb_initialized'), timeout=30)
        states.append({'name': label, 'project': project, 'running': running, 'configuration_only': config_only})
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    work = ROOT / 'backups' / ('manual-' + stamp + '-' + secrets.token_hex(3))
    work.mkdir(mode=0o700)
    print('Đang sao lưu. Không đóng cửa sổ; web/MQTT có thể tạm dừng.', flush=True)
    for state in states:
        project, label = state['project'], state['name']
        destination = work / label
        destination.mkdir(mode=0o700)
        # Stop only writers actually running, never turn on previously stopped services.
        writers = [name for name in state['running'] if name not in ('db', 'tunnel', 'portal', 'kuma')]
        if writers:
            resume_services.append((project, writers))
            run(compose(project, 'stop', *writers))
        if not state['configuration_only']:
            dump = 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-dump -uroot --all-databases --single-transaction --routines --events --triggers --hex-blob'
            with (destination / 'database.sql').open('wb') as output:
                run(compose(project, 'exec', '-T', 'db', 'sh', '-c', dump), output=output, timeout=1800)
            if not (destination / 'database.sql').stat().st_size: raise RuntimeError('SQL dump rỗng: ' + label)
        # Do not include prior backups or recursively include sites in main source archive.
        args = ['tar', '-czf', str(destination / 'source.tgz'), '--exclude=./backups', '--exclude=./.git']
        if label == 'main': args.append('--exclude=./sites')
        run(args + ['-C', str(project), '.'], timeout=1800)
        if label == 'main':
            available = capture(compose(project, 'config', '--services'))
            for service, mount in (('mqtt', '/mosquitto/data'), ('files', '/database')):
                if service not in available: continue
                with (destination / (service + '.tgz')).open('wb') as output:
                    run(compose(project, 'run', '--rm', '--no-deps', '-T', '--user', '0', '--entrypoint', 'tar', service, 'czf', '-', '-C', mount, '.'), output=output, timeout=1800)
        print('Đã chụp: ' + label + (' (chỉ cấu hình, chưa có container/volume)' if state['configuration_only'] else ' (source + SQL)'), flush=True)
    # Auth/password + host Tunnel config outside /opt must be backed up too.
    system_paths = [name for name in ('etc/maychu247-ui', 'usr/local/lib/maychu247-dashboard',
                    'etc/systemd/system/maychu247-agent.service', 'etc/systemd/system/maychu247-dashboard.service',
                    'etc/systemd/system/maychu247-backup.service', 'etc/systemd/system/maychu247-backup.timer') if Path('/' + name).exists()]
    if system_paths: run(['tar', '-czf', str(work / 'dashboard-system.tgz'), '-C', '/', *system_paths])
    manifest = {'format': 'maychu247-manual-v1', 'utc': stamp,
                'projects': [{key: value for key, value in state.items() if key != 'project'} for state in states],
                'scope': 'MayChu247 stack, site source/SQL, main MQTT/files volumes, dashboard/auth/Tunnel configuration; not whole Ubuntu or unrelated Docker volumes',
                'warning': 'Contains secrets. No automated restore tool for this manual bundle. External SQL/SFTP/worker writers must be paused separately.'}
    (work / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    sums = []
    for path in sorted(work.rglob('*')):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''): digest.update(chunk)
            sums.append(digest.hexdigest() + '  ' + str(path.relative_to(work)))
    (work / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    for archive in work.rglob('*.tgz'):
        run(['tar', '-tzf', str(archive)], timeout=120)
    (work / 'COMPLETE').write_text('maychu247-manual-v1\n')
    success = True
except Exception as error:
    print('SAO LƯU CHƯA HOÀN TẤT: ' + (str(error) if isinstance(error, RuntimeError) else 'Lỗi hệ thống/quyền/dung lượng hoặc quá thời gian. Không đánh dấu COMPLETE.'), file=sys.stderr)
finally:
    # Do not let a second Ctrl+C interrupt service restoration.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    for project, services in reversed(resume_services):
        try: run(compose(project, 'start', *services), timeout=120)
        except Exception: restore_errors.append('dịch vụ của ' + project.name)
    for unit in resume_units:  # agent first, dashboard second
        try: run(['systemctl', 'start', unit])
        except Exception: restore_errors.append(unit)
    locks.close()
if work:
    print('Thư mục: ' + str(work), flush=True)
if restore_errors:
    print('CẢNH BÁO: chưa bật lại được ' + ', '.join(restore_errors) + '. Cần quản trị viên kiểm tra, không chạy cập nhật tiếp.', file=sys.stderr)
if success and not restore_errors and os.environ.get('SUDO_UID', '').isdigit():
    # Make a private downloadable copy owned by the SSH user, not public-readable.
    import pwd
    uid = int(os.environ['SUDO_UID'])
    if uid >= 1000 and uid != 65534:
        export = None
        try:
            account = pwd.getpwuid(uid)
            home = Path(account.pw_dir)
            if home.is_symlink() or not home.is_dir() or home.stat().st_uid != uid:
                raise RuntimeError('Home người dùng không hợp lệ')
            export = home / ('MayChu247-Backup-' + work.name.removeprefix('manual-') + '.tar.gz')
            fd = os.open(export, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as output:
                run(['tar', '-czf', '-', '-C', str(work.parent), work.name], output=output, timeout=1800)
                output.flush()
                os.fsync(output.fileno())
                os.fchown(output.fileno(), uid, account.pw_gid)
            print('FILE TẢI VỀ BẰNG WINSCP: ' + str(export), flush=True)
        except Exception:
            print('Đã có snapshot trong backups nhưng chưa tạo được file tải về trong home. Có thể thiếu dung lượng; cần quản trị viên hỗ trợ quyền tải.', file=sys.stderr)
            success = False
if success:
    print('ĐÃ TẠO BẢN SAO LƯU + SHA256SUMS. Chưa thử khôi phục; không phải bản sao toàn bộ Ubuntu.')
    print('Dùng WinSCP tải nguyên thư mục trên về PC an toàn. Có mật khẩu/token; không gửi lên chat hoặc đặt trong public web.')
    print('Định dạng manual-v1: KHÔNG đưa vào restore.sh hiện có. Không tự xóa bản sao lưu cũ.')
sys.exit(0 if success and not restore_errors else 1)
PY
