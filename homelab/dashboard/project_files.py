"""Confined project file operations. No shell, absolute paths, symlink traversal or deletion."""
import base64
import hashlib
import os
from pathlib import Path
import stat
import secrets

MAX_FILE = 1024 * 1024
MAX_EDIT = 200 * 1024
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def parts(path, allow_root=False):
    if not isinstance(path, str) or len(path.encode('utf-8')) > 2000:
        raise ValueError('Đường dẫn không hợp lệ')
    if path == '' and allow_root:
        return []
    values = path.split('/')
    for name in values:
        if (not name or name.startswith('.') or '\\' in name or ':' in name
                or len(name.encode('utf-8')) > 240 or any(ord(c) < 32 or ord(c) == 127 for c in name)):
            raise ValueError('Chỉ dùng đường dẫn tương đối trong projects; không file ẩn, dấu .. hoặc ký tự điều khiển')
    return values


def directory(root, values):
    fd = os.open(Path(root) / 'projects', FLAGS)
    try:
        for name in values:
            child = os.open(name, FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def browse(root, path):
    values = parts(path, allow_root=True)
    fd = directory(root, values)
    try:
        names = []
        scanned = 0
        with os.scandir(fd) as iterator:
            for item in iterator:
                scanned += 1
                if not item.name.startswith('.'):
                    names.append(item.name)
                if len(names) >= 201 or scanned >= 1000:
                    break
        names.sort()
        entries = []
        for name in names[:200]:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'blocked'
            entries.append({'name': name, 'kind': kind, 'bytes': info.st_size,
                            'mtime': int(info.st_mtime)})
        entries.sort(key=lambda item: (item['kind'] != 'directory', item['name']))
        return {'path': path, 'entries': entries, 'truncated': len(names) > 200 or scanned >= 1000}
    finally:
        os.close(fd)


def read_fd(fd):
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise ValueError('Chỉ đọc file thường, không symlink/thiết bị/FIFO')
    if os.fstat(fd).st_size > MAX_FILE:
        raise ValueError('File lớn hơn 1 MiB; chưa hỗ trợ trên dashboard')
    with os.fdopen(os.dup(fd), 'rb') as file:
        value = file.read(MAX_FILE + 1)
    if len(value) > MAX_FILE:
        raise ValueError('File lớn hơn 1 MiB')
    return value


def read(root, path):
    values = parts(path)
    parent = directory(root, values[:-1])
    fd = None
    try:
        fd = os.open(values[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        content = read_fd(fd)
        try:
            text = content.decode('utf-8')
            if '\x00' in text:
                text = None
        except UnicodeError:
            text = None
        return {'path': path, 'content': base64.b64encode(content).decode(), 'text': text,
                'version': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def write_all(fd, data):
    remaining = memoryview(data)
    while remaining:
        count = os.write(fd, remaining)
        if count <= 0:
            raise OSError('Không ghi được file')
        remaining = remaining[count:]


def upload(root, path, encoded):
    values = parts(path)
    if not isinstance(encoded, str) or len(encoded) > 1400000:
        raise ValueError('File upload tối đa 1 MiB')
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ValueError('Dữ liệu upload không hợp lệ')
    if len(data) > MAX_FILE:
        raise ValueError('File upload tối đa 1 MiB')
    parent = directory(root, values[:-1])
    fd = None
    created = False
    try:
        fd = os.open(values[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent)
        created = True
        write_all(fd, data)
        os.fchmod(fd, 0o644)
        os.fsync(fd)
    except BaseException:
        if created:
            os.unlink(values[-1], dir_fd=parent)
        raise
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)
    return {'message': 'Đã tạo file thật trong projects. Không tự gắn domain hoặc giải nén.'}


def save(root, path, text, version):
    values = parts(path)
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_EDIT:
        raise ValueError('Nội dung UTF-8 tối đa 200 KiB')
    if not isinstance(version, str) or len(version) != 64:
        raise ValueError('Cần mở file trước khi lưu')
    parent = directory(root, values[:-1])
    fd = None
    try:
        fd = os.open(values[-1], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        content = read_fd(fd)
        if hashlib.sha256(content).hexdigest() != version:
            raise ValueError('File đã thay đổi từ lúc mở. Mở lại trước khi lưu, không ghi đè bản mới.')
        try:
            original_text = content.decode('utf-8')
            if '\x00' in original_text:
                raise ValueError('Không sửa file nhị phân bằng trình soạn văn bản')
        except UnicodeError:
            raise ValueError('Chỉ sửa file UTF-8 bằng trình soạn văn bản')
        # Preserve the previous file inside the same project for manual recovery.
        # Hidden .maychu247-history is not served by the shipped Nginx dotfile rule.
        try:
            os.mkdir('.maychu247-history', 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        history = os.open('.maychu247-history', FLAGS, dir_fd=parent)
        try:
            if len(os.listdir(history)) >= 50:
                raise ValueError('Đã có 50 bản lịch sử trong thư mục này; cần lưu trữ/dọn lịch sử có kiểm soát trước khi sửa tiếp.')
            backup_name = secrets.token_hex(16)
            backup = os.open(backup_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=history)
            try:
                write_all(backup, content)
                os.fsync(backup)
            finally:
                os.close(backup)
        finally:
            os.close(history)
        data = text.encode('utf-8')
        temporary = '.maychu247-save-' + secrets.token_hex(16)
        staged = None
        try:
            staged = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
            write_all(staged, data)
            os.fchmod(staged, stat.S_IMODE(os.fstat(fd).st_mode) & 0o666)
            os.fsync(staged)
            os.close(staged)
            staged = None
            # Atomic replacement avoids half-written source when the process is interrupted.
            os.replace(temporary, values[-1], src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            if staged is not None:
                os.close(staged)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        return {'message': 'Đã lưu file thật; có bản nội dung trước trong .maychu247-history của thư mục này.',
                'version': hashlib.sha256(data).hexdigest()}
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def mkdir(root, path):
    values = parts(path)
    parent = directory(root, values[:-1])
    child = None
    try:
        os.mkdir(values[-1], 0o755, dir_fd=parent)
        child = os.open(values[-1], FLAGS, dir_fd=parent)
        os.fchmod(child, 0o755)
    finally:
        if child is not None:
            os.close(child)
        os.close(parent)
    return {'message': 'Đã tạo thư mục thật trong projects.'}
