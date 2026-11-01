"""MayChu247 local probes: fixed loopback targets, no plugins or arbitrary URL input."""
from collections import deque
import http.client
import socket
import threading
import time

TARGETS = (
    ('web', 'Website PHP', 'http', 18080, 'HTTP 200; kiểm tra DB chỉ khi trang ứng dụng có kiểm tra DB'),
    ('mqtt', 'MQTT TCP', 'tcp', 1884, 'Chỉ kiểm tra TCP mở; chưa xác thực/pub-sub'),
    ('files', 'File Manager', 'tcp', 18082, 'Chỉ kiểm tra TCP mở; chưa kiểm tra đăng nhập'),
    ('adminer', 'SQL Admin', 'tcp', 18081, 'Chỉ kiểm tra giao diện SQL mở; không truy vấn database'),
)


def probe(kind, port):
    start = time.monotonic()
    try:
        if kind == 'http':
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            try:
                conn.request('GET', '/')
                response = conn.getresponse()
                ok, detail = response.status == 200, f'HTTP {response.status}'
            finally:
                conn.close()
        else:
            with socket.create_connection(('127.0.0.1', port), timeout=2):
                pass
            ok, detail = True, 'TCP mở'
        return ok, round((time.monotonic() - start) * 1000, 1), detail
    except (OSError, http.client.HTTPException):
        return False, round((time.monotonic() - start) * 1000, 1), 'Không kết nối được hoặc hết thời gian'


class Monitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = deque(maxlen=100)
        self.rows = {key: {'id': key, 'name': name, 'kind': kind, 'port': port,
                          'scope': scope, 'state': 'unknown', 'checked_at': None,
                          'latency_ms': None, 'detail': 'Chưa có mẫu kiểm tra'}
                     for key, name, kind, port, scope in TARGETS}
        self.stop = threading.Event()
        self.thread = None

    def sample(self):
        for key, _, kind, port, _ in TARGETS:
            ok, latency, detail = probe(kind, port)
            now, state = int(time.time()), 'up' if ok else 'down'
            with self.lock:
                row = self.rows[key]
                previous = row['state']
                row.update(state=state, checked_at=now, latency_ms=latency, detail=detail)
                if previous != state:
                    self.events.appendleft({'time': now, 'name': row['name'],
                                            'from': previous, 'to': state, 'detail': detail})

    def run(self):
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(30)

    def start(self):
        self.thread = threading.Thread(target=self.run, name='local-monitor', daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return {'interval_seconds': 30, 'targets': [dict(row) for row in self.rows.values()],
                    'events': [dict(e) for e in self.events],
                    'notice': 'Sự kiện lưu trong RAM, tối đa 100; mất khi UI restart. Không có cảnh báo ngoài máy.'}
