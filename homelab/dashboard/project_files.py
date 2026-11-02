"""Confined project file operations. No shell, absolute paths, symlink traversal or system paths."""
import base64
import hashlib
import os
from pathlib import Path
import stat
import secrets

MAX_FILE = 1024 * 1024
MAX_UPLOAD = 8 * 1024 * 1024
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
                            'mode': format(stat.S_IMODE(info.st_mode), '04o'), 'mtime': int(info.st_mtime)})
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
    if not isinstance(encoded, str) or len(encoded) > 11200000:
        raise ValueError('File upload tối đa 8 MiB')
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ValueError('Dữ liệu upload không hợp lệ')
    if len(data) > MAX_UPLOAD:
        raise ValueError('File upload tối đa 8 MiB')
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


def chmod(root, path, mode):
    """Only safe non-executable presets, no recursive chmod or ownership changes."""
    values = parts(path)
    parent = directory(root, values[:-1])
    fd = None
    try:
        fd = os.open(values[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        info = os.fstat(fd)
        allowed = ('0700', '0755') if stat.S_ISDIR(info.st_mode) else ('0600', '0644') if stat.S_ISREG(info.st_mode) else ()
        if mode not in allowed or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise ValueError('Chỉ cho phép file 0600/0644, thư mục 0700/0755; không hardlink, symlink hoặc thiết bị')
        os.fchmod(fd, int(mode, 8))
        return {'message': 'Đã đổi quyền ' + path + ' thành ' + mode + '. Không áp dụng đệ quy.'}
    finally:
        if fd is not None: os.close(fd)
        os.close(parent)


def delete(root, path, confirmation):
    """Move into private, hidden trash. Never recursively unlink project data."""
    import json
    values = parts(path)
    if confirmation != path:
        raise ValueError('Phải nhập lại đầy đủ đường dẫn để xác nhận xóa')
    parent = directory(root, values[:-1])
    base = trash = entry = None
    try:
        info = os.stat(values[-1], dir_fd=parent, follow_symlinks=False)
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError('Không xóa symlink/thiết bị')
        base = directory(root, [])
        try: os.mkdir('.maychu247-trash', 0o700, dir_fd=base)
        except FileExistsError: pass
        trash = os.open('.maychu247-trash', FLAGS, dir_fd=base)
        os.fchmod(trash, 0o700)
        if len(os.listdir(trash)) >= 100:
            raise ValueError('Thùng rác đã có 100 mục; cần quản trị viên lưu trữ/dọn trước khi xóa tiếp')
        identifier = secrets.token_hex(16)
        os.mkdir(identifier, 0o700, dir_fd=trash)
        entry = os.open(identifier, FLAGS, dir_fd=trash)
        fd = os.open('info.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=entry)
        try:
            write_all(fd, json.dumps({'path': path}, ensure_ascii=False).encode())
            os.fsync(fd)
        finally: os.close(fd)
        os.rename(values[-1], 'item', src_dir_fd=parent, dst_dir_fd=entry)
        os.fsync(entry)
        os.fsync(parent)
        return {'message': 'Đã chuyển ' + path + ' vào thùng rác riêng. Website có thể ngừng hoạt động. Chưa có nút phục hồi/xóa vĩnh viễn.', 'trash_id': identifier}
    finally:
        for fd in (entry, trash, base, parent):
            if fd is not None: os.close(fd)


def extract(root, path, target):
    """Bounded ZIP extraction into an existing directory, exclusive files; rollback new entries."""
    import io
    import zipfile
    import zlib
    source = parts(path)
    destination = parts(target, allow_root=True)
    parent = directory(root, source[:-1])
    fd = None
    try:
        fd = os.open(source[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_UPLOAD:
            raise ValueError('ZIP phải là file thường tối đa 8 MiB')
        content = bytearray()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk: break
            content.extend(chunk)
            if len(content) > MAX_UPLOAD: raise ValueError('ZIP vượt 8 MiB')
    finally:
        if fd is not None: os.close(fd)
        os.close(parent)
    check = directory(root, destination)
    os.close(check)
    created_files, created_dirs = [], []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if not members or len(members) > 1000: raise ValueError('ZIP cần 1–1000 mục')
            files, folders, seen = [], set(), set()
            total = 0
            for member in members:
                raw = member.filename
                values = parts(raw[:-1] if member.is_dir() else raw)
                if len(values) > 32 or member.orig_filename != raw:
                    raise ValueError('ZIP có đường dẫn quá sâu hoặc chứa NUL')
                parts('/'.join(destination + values))
                # ZIP uses trailing slash directories; no links/devices/hidden/traversal.
                kind = stat.S_IFMT(member.external_attr >> 16)
                if (raw in seen or member.flag_bits & 1 or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                        or (kind == stat.S_IFDIR and not member.is_dir())):
                    raise ValueError('ZIP trùng tên, mã hóa, symlink/thiết bị hoặc kiểu nén chưa hỗ trợ')
                seen.add(raw)
                if member.file_size > MAX_UPLOAD: raise ValueError('Mỗi file giải nén tối đa 8 MiB')
                total += member.file_size
                if total > 32 * 1024 * 1024: raise ValueError('ZIP giải nén tối đa 32 MiB')
                for i in range(1, len(values)): folders.add(tuple(values[:i]))
                if member.is_dir(): folders.add(tuple(values))
                else: files.append((member, values))
                if len(folders) + len(files) > 1000: raise ValueError('ZIP vượt 1000 mục tính cả thư mục cha')
            file_names = {tuple(values) for _, values in files}
            if len(file_names) != len(files) or file_names & folders: raise ValueError('ZIP có tên file/thư mục xung đột')
            # Preflight all collisions before writing; never overwrite existing content.
            for values, is_file in [(list(folder), False) for folder in folders] + [(values, True) for _, values in files]:
                try: parent = directory(root, destination + values[:-1])
                except FileNotFoundError: continue
                try:
                    try: info = os.stat(values[-1], dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError: continue
                    if is_file or not stat.S_ISDIR(info.st_mode): raise ValueError('Tên đã tồn tại hoặc bị chặn: ' + '/'.join(values) + '. Không ghi đè; đổi thư mục đích hoặc xử lý file cũ trước.')
                finally: os.close(parent)
            for values in sorted(folders, key=lambda item: (len(item), item)):
                full = destination + list(values)
                parent = directory(root, full[:-1])
                try:
                    try:
                        os.mkdir(full[-1], 0o755, dir_fd=parent)
                        created_dirs.append(full)
                    except FileExistsError: pass
                    child = os.open(full[-1], FLAGS, dir_fd=parent)
                    try:
                        if full in created_dirs: os.fchmod(child, 0o755)
                    finally: os.close(child)
                finally: os.close(parent)
            actual = 0
            for member, values in files:
                full = destination + values
                parent = directory(root, full[:-1])
                try:
                    fd = os.open(full[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent)
                    created_files.append(full)
                    try:
                        size = 0
                        with archive.open(member) as stream:
                            while True:
                                chunk = stream.read(65536)
                                if not chunk: break
                                size += len(chunk); actual += len(chunk)
                                if size > MAX_UPLOAD or actual > 32 * 1024 * 1024: raise ValueError('Vượt giới hạn dữ liệu giải nén')
                                write_all(fd, chunk)
                        os.fchmod(fd, 0o644)
                        os.fsync(fd)
                    finally: os.close(fd)
                finally: os.close(parent)
            return {'message': 'Đã giải nén ' + str(len(files)) + ' file vào projects/' + target + '. Không ghi đè, không tự chạy mã hoặc import SQL.', 'files': len(files)}
    except BaseException as error:
        failed = False
        for values, is_file in [(values, True) for values in reversed(created_files)] + [(values, False) for values in reversed(created_dirs)]:
            try:
                parent = directory(root, values[:-1])
                try:
                    if is_file: os.unlink(values[-1], dir_fd=parent)
                    else: os.rmdir(values[-1], dir_fd=parent)
                finally: os.close(parent)
            except OSError: failed = True
        if failed: raise ValueError('Giải nén lỗi và chưa dọn hết mục mới; đọc lại thư mục trước khi thử lại') from None
        if isinstance(error, (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError)):
            raise ValueError('ZIP hỏng hoặc kiểu nén/mã hóa chưa hỗ trợ; không giải nén thành công') from None
        raise
