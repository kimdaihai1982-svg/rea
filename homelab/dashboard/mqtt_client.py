"""Bounded MQTT 3.1.1 operations on the fixed local broker; no third-party client or shell."""
import base64
from pathlib import Path
import socket
import struct
import time

MAX_PACKET = 65536


def topic(value, subscribe=False):
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 256:
        raise ValueError('Topic cần 1–256 byte UTF-8')
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or value.startswith('$'):
        raise ValueError('Topic không được có ký tự điều khiển hoặc namespace hệ thống $')
    if not subscribe and ('+' in value or '#' in value):
        raise ValueError('Topic gửi không được có wildcard + hoặc #')
    if subscribe:
        levels = value.split('/')
        for i, level in enumerate(levels):
            if ('+' in level and level != '+') or ('#' in level and (level != '#' or i != len(levels)-1)):
                raise ValueError('Wildcard phải đứng riêng một cấp; # chỉ ở cuối')
    return value


def utf8(value):
    data = value.encode('utf-8')
    if len(data) > 65535 or b'\0' in data:
        raise ValueError('Chuỗi MQTT không hợp lệ')
    return struct.pack('!H', len(data)) + data


def packet(header, data):
    if len(data) > MAX_PACKET:
        raise ValueError('Gói MQTT vượt giới hạn 64 KiB')
    remaining = len(data)
    length = bytearray()
    while True:
        digit = remaining % 128
        remaining //= 128
        length.append(digit | (128 if remaining else 0))
        if not remaining:
            break
    return bytes([header]) + length + data


def exact(sock, count, deadline=None):
    chunks = bytearray()
    while len(chunks) < count:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise socket.timeout()
            sock.settimeout(remaining)
        chunk = sock.recv(count - len(chunks))
        if not chunk:
            raise RuntimeError('Broker đóng kết nối')
        chunks.extend(chunk)
    return bytes(chunks)


def receive(sock, deadline=None):
    header = exact(sock, 1, deadline)[0]
    length = 0
    for i in range(4):
        digit = exact(sock, 1, deadline)[0]
        length += (digit & 127) * (128 ** i)
        if length > MAX_PACKET:
            raise ValueError('Broker trả gói quá lớn; đã đóng phiên nhận')
        if not digit & 128:
            return header, exact(sock, length, deadline)
    raise ValueError('MQTT remaining-length không hợp lệ')


def password(root):
    values = [line.split('=', 1)[1] for line in (Path(root) / '.env').read_text().splitlines()
              if line.startswith('MQTT_PASSWORD=')]
    if len(values) != 1 or not values[0]:
        raise ValueError('Broker chưa có đúng cấu hình mật khẩu. Cần quản trị viên kiểm tra cấu hình, không hiển thị secret.')
    value = values[0]
    if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
        value = value[1:-1]
    return value


def connect(root):
    import secrets
    secret = password(root)
    sock = socket.create_connection(('127.0.0.1', 1884), timeout=3)
    try:
        sock.settimeout(3)
        # Clean session, username/password, keepalive 15 seconds.
        body = utf8('MQTT') + bytes([4, 0xC2]) + struct.pack('!H', 15)
        body += utf8('maychu247-ui-' + secrets.token_hex(6)) + utf8('mqttuser') + utf8(secret)
        sock.sendall(packet(0x10, body))
        header, reply = receive(sock, time.monotonic() + 3)
        if header != 0x20 or len(reply) != 2 or reply[1] != 0:
            raise RuntimeError('Broker không chấp nhận kết nối/xác thực; chưa gửi hoặc nhận tin')
        return sock
    except BaseException:
        sock.close()
        raise


def publish(root, name, payload):
    topic(name)
    if not isinstance(payload, str) or len(payload.encode('utf-8')) > 16384:
        raise ValueError('Payload gửi tối đa 16 KiB UTF-8')
    with connect(root) as sock:
        sock.sendall(packet(0x32, utf8(name) + b'\0\1' + payload.encode('utf-8')))
        header, reply = receive(sock, time.monotonic() + 3)
        if header != 0x40 or reply != b'\0\1':
            raise RuntimeError('Chưa nhận được PUBACK đúng. Không tự gửi lại vì có thể tạo tin trùng.')
    return {'message': 'Broker đã PUBACK tin QoS 1. Chưa xác nhận thiết bị nhận hoặc dữ liệu ghi SQL.',
            'topic': name, 'qos': 1, 'retained': False}


def sample(root, name):
    topic(name, subscribe=True)
    messages = []
    total = 0
    with connect(root) as sock:
        sock.sendall(packet(0x82, b'\0\1' + utf8(name) + b'\0'))
        header, reply = receive(sock, time.monotonic() + 3)
        if header != 0x90 or len(reply) != 3 or reply[:2] != b'\0\1' or reply[2] != 0:
            raise RuntimeError('Broker chưa xác nhận subscription QoS 0')
        deadline = time.monotonic() + 3
        while len(messages) < 20 and total < 65536:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                header, body = receive(sock, deadline)
            except socket.timeout:
                break
            if header >> 4 != 3:
                raise RuntimeError('Gói broker chưa được hỗ trợ trong phiên nhận')
            if len(body) < 2:
                raise ValueError('Gói PUBLISH thiếu topic')
            size = struct.unpack('!H', body[:2])[0]
            qos = (header >> 1) & 3
            if qos not in (0, 1) or len(body) < 2 + size + (2 if qos else 0):
                raise ValueError('PUBLISH không hợp lệ')
            name_received = body[2:2+size].decode('utf-8')
            offset = 2 + size
            if qos:
                identifier = body[offset:offset+2]
                offset += 2
                sock.sendall(packet(0x40, identifier))
            value = body[offset:]
            total += len(value)
            if total > 65536:
                break
            try:
                text = value.decode('utf-8')
            except UnicodeError:
                text = None
            messages.append({'topic': name_received, 'payload': text,
                             'binary_base64': base64.b64encode(value).decode() if text is None else None,
                             'retained': bool(header & 1), 'bytes': len(value), 'time': int(time.time())})
    return {'messages': messages, 'seconds': 3, 'limit': 20,
            'message': 'Phiên nhận tối đa 3 giây/20 tin/64 KiB; không phải subscription liên tục. Tin retained có thể là dữ liệu cũ.'}


def selftest(root):
    import secrets
    name = 'maychu247/check/' + secrets.token_hex(8)
    value = 'maychu247-connectivity-' + secrets.token_hex(8)
    with connect(root) as subscriber:
        subscriber.sendall(packet(0x82, b'\0\1' + utf8(name) + b'\0'))
        header, reply = receive(subscriber, time.monotonic() + 3)
        if header != 0x90 or reply != b'\0\1\0':
            raise RuntimeError('Broker chưa cho phép subscribe topic kiểm tra')
        publish(root, name, value)
        header, body = receive(subscriber, time.monotonic() + 3)
        if header >> 4 != 3 or len(body) < 2:
            raise RuntimeError('Chưa nhận được PUBLISH kiểm tra')
        size = struct.unpack('!H', body[:2])[0]
        # Subscription requests QoS 0; any higher QoS would violate our granted contract.
        if (header & 6) or body[2:2+size] != name.encode() or body[2+size:] != value.encode():
            raise RuntimeError('Tin nhận không khớp phép thử; chưa xác nhận roundtrip')
    return {'message': 'Gửi → broker PUBACK → subscriber nhận đúng payload: thành công. Chỉ kiểm tra broker nội bộ, không xác minh thiết bị ngoài/SQL.',
            'topic': name}
