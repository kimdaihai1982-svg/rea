"""Bounded native SQL console. Never run browser SQL with the MariaDB root account."""
import os
import re
import selectors
import signal
import subprocess
import time

SYSTEM = {'mysql', 'sys', 'performance_schema', 'information_schema'}


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', value) or value in SYSTEM:
        raise ValueError('Tên database ứng dụng không hợp lệ; không quản lý database hệ thống')
    return value


def bounded(command, text, cwd, seconds=10, max_bytes=256 * 1024):
    """Stream both pipes without unlimited capture, blocking writes or shell execution."""
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    output = bytearray()
    pending = memoryview(text.encode('utf-8'))
    deadline = time.monotonic() + seconds
    try:
        with selectors.DefaultSelector() as selector:
            for pipe in (process.stdin, process.stdout): os.set_blocking(pipe.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise RuntimeError('SQL quá thời gian. Có thể đã thay đổi dữ liệu; kiểm tra trước khi chạy lại, không tự thử lại.')
                for key, _ in selector.select(remaining):
                    if key.fileobj is process.stdin:
                        try:
                            sent = os.write(process.stdin.fileno(), pending[:4096])
                            pending = pending[sent:]
                        except BrokenPipeError:
                            pending = pending[:0]
                        if not pending:
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        chunk = os.read(process.stdout.fileno(), 8192)
                        if not chunk:
                            selector.unregister(process.stdout)
                        else:
                            output.extend(chunk)
                            if len(output) > max_bytes:
                                raise RuntimeError('Kết quả vượt 256 KiB, đã ngừng nhận. Dùng LIMIT/chọn ít cột hơn. Thao tác ghi có thể đã hoàn tất; không tự chạy lại.')
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise RuntimeError('SQL chưa xác nhận hoàn tất; kiểm tra dữ liệu trước khi chạy lại')
            try: code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired: raise RuntimeError('SQL chưa xác nhận hoàn tất; kiểm tra dữ liệu trước khi chạy lại')
            if code:
                raise RuntimeError('SQL thất bại hoặc không đủ quyền. Có thể một phần lệnh đã chạy; kiểm tra dữ liệu trước khi thử lại. Không trả lỗi thô để tránh lộ nội dung/secret.')
        return output.decode('utf-8', errors='replace')
    finally:
        # docker CLI disconnect does not guarantee server-side query cancellation.
        if process.poll() is None:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        process.wait()
        for pipe in (process.stdin, process.stdout): pipe.close()


def query(root, database, statement, confirmation):
    database = name(database)
    if confirmation != 'RUN ' + database:
        raise ValueError('Cần xác nhận RUN và tên database trước khi chạy SQL thật')
    if not isinstance(statement, str) or not statement.strip() or len(statement.encode('utf-8')) > 8192 or '\x00' in statement:
        raise ValueError('SQL không được trống, chứa NUL hoặc vượt 8 KiB')
    # --binary-mode disables client commands (notably \\! shell); no local infile.
    # Only constant shell source expands existing container credentials. DB is argv.
    script = 'MYSQL_PWD="$MARIADB_PASSWORD" exec mariadb --connect-timeout=3 --binary-mode=1 --local-infile=0 --skip-reconnect --default-character-set=utf8mb4 --init-command="SET SESSION max_statement_time=8" --quick --batch --column-names -uappuser --database="$1"'
    command = ['docker', 'compose', '--project-directory', str(root), 'exec', '-T', 'db',
               'sh', '-c', script, 'sql-console', database]
    output = bounded(command, statement + '\n', root)
    return {'output': output, 'message': 'MariaDB trả mã thành công. Không có dòng kết quả không có nghĩa đã thay đổi dữ liệu; COMMIT/ROLLBACK theo SQL đã nhập. User appuser dùng chung quyền trên các database đã cấp.'}


def import_file(root, database, encoded, confirmation):
    import base64
    database = name(database)
    if confirmation != 'IMPORT ' + database:
        raise ValueError('Cần xác nhận IMPORT và tên database đích')
    if not isinstance(encoded, str) or not encoded or len(encoded) > 11200000:
        raise ValueError('File .sql UTF-8 tối đa 8 MiB')
    try:
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > 8 * 1024 * 1024: raise ValueError('File .sql tối đa 8 MiB')
        text = data.decode('utf-8-sig')
    except (ValueError, UnicodeError):
        raise ValueError('Chỉ nhận file SQL UTF-8, tối đa 8 MiB; không ZIP/gzip hoặc file nhị phân') from None
    if '\x00' in text: raise ValueError('File SQL không được chứa NUL')
    # Same least-privileged client boundary as query, longer bounded import deadline.
    script = 'MYSQL_PWD="$MARIADB_PASSWORD" exec mariadb --connect-timeout=3 --binary-mode=1 --local-infile=0 --skip-reconnect --default-character-set=utf8mb4 --init-command="SET SESSION max_statement_time=45" --quick --batch -uappuser --database="$1"'
    command = ['docker', 'compose', '--project-directory', str(root), 'exec', '-T', 'db', 'sh', '-c', script, 'sql-import', database]
    output = bounded(command, text + '\n', root, seconds=60)
    return {'output': output, 'message': 'MariaDB xác nhận kết thúc import thành công. Chưa xác minh dữ liệu đúng với ứng dụng. Dump có USE/tên database khác sẽ theo quyền appuser; kiểm tra bảng/dữ liệu trước khi chạy website.'}
