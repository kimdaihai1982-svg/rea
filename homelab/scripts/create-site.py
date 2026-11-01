#!/usr/bin/env python3
"""Generate an isolated Compose project; never executes Docker or modifies DNS."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import tempfile

ROOT = Path(__file__).resolve().parent.parent
RESERVED_PORTS = {18000, 18080, 18081, 18082, 13001, 1884, 19001}


def domain_name(value):
    value = value.lower().rstrip('.')
    if len(value) > 253 or '.' not in value or not all(
        re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
        for label in value.split('.')
    ):
        raise argparse.ArgumentTypeError('Domain DNS hợp lệ, không gồm https:// hoặc đường dẫn; dùng punycode cho IDN')
    return value


def main():
    packages = json.loads((ROOT / 'packages.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', help='Tên nội bộ chữ thường, số, dấu -; tối đa 32 ký tự')
    parser.add_argument('--domain', required=True, type=domain_name)
    parser.add_argument('--package', choices=packages, default='starter')
    parser.add_argument('--port', type=int, required=True, help='Cổng loopback riêng, 20000..29999')
    parser.add_argument('--write', action='store_true', help='Phê duyệt tạo file, không khởi động dịch vụ')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', args.name):
        parser.error('Tên website không hợp lệ')
    if not 20000 <= args.port <= 29999 or args.port in RESERVED_PORTS:
        parser.error('Chọn port từ 20000 đến 29999')
    sites = ROOT / 'sites'
    if sites.is_symlink():
        parser.error('sites không được là symlink')
    target = sites / args.name
    if target.exists() or target.is_symlink():
        parser.error('Website đã tồn tại: không ghi đè')
    for metadata in sites.glob('*/site.json'):
        old = json.loads(metadata.read_text())
        if old['port'] == args.port or old['domain'] == args.domain:
            parser.error('Domain hoặc port trùng website đã tạo')
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', args.port))
        except OSError:
            parser.error('Port đã được sử dụng trên máy này')
    p = packages[args.package]
    print(f'Kế hoạch: {target}\nDomain: {args.domain}\nGói: {args.package}\nOrigin: 127.0.0.1:{args.port}')
    print('Mỗi site: PHP + MariaDB + volume/network riêng. Không tạo DNS, không mở firewall.')
    if not args.write:
        print('Chưa ghi file. Thêm --write để xác nhận.')
        return
    sites.mkdir(mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='.create-', dir=sites))
    try:
        os.chmod(work, 0o700)
        shutil.copytree(ROOT / 'php', work / 'php')
        (work / 'config').mkdir()
        shutil.copy2(ROOT / 'config/nginx.conf', work / 'config/nginx.conf')
        # Agent runs with restrictive umask; the PHP container must still read public code.
        for relative in ('projects', 'projects/demo', 'projects/demo/public'):
            folder = work / relative
            folder.mkdir(mode=0o755)
            folder.chmod(0o755)
        shutil.copy2(ROOT / 'projects/demo/public/index.php', work / 'projects/demo/public/index.php')
        env = 'DB_PASSWORD=' + secrets.token_hex(24) + '\nDB_ROOT_PASSWORD=' + secrets.token_hex(24) + '\nTUNNEL_TOKEN=\n'
        (work / '.env').write_text(env)
        os.chmod(work / '.env', 0o600)
        (work / 'site.json').write_text(json.dumps(vars(args) | {'write': False}, indent=2) + '\n')
        (work / 'config/mariadb.cnf').write_text(
            '[mariadb]\ncharacter-set-server=utf8mb4\ncollation-server=utf8mb4_unicode_ci\n'
            f'innodb_buffer_pool_size={p["db_buffer_mb"]}M\nmax_connections={p["db_connections"]}\n')
        (work / 'compose.yaml').write_text(f'''name: site-{args.name}
x-logging: &logging
  driver: json-file
  options: {{max-size: 10m, max-file: '3'}}
services:
  web:
    build: ./php
    restart: unless-stopped
    logging: *logging
    cpus: '{p['web_cpu']}'
    mem_limit: {p['web_memory_mb']}m
    pids_limit: 128
    security_opt: [no-new-privileges:true]
    ports: ['127.0.0.1:{args.port}:8080']
    volumes:
      - ./projects:/var/www/projects:ro
      - ./config/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    environment:
      DB_USERNAME: appuser
      DB_PASSWORD: ${{DB_PASSWORD:?Missing DB password}}
    depends_on:
      db: {{condition: service_healthy}}
  db:
    image: mariadb:11.4
    restart: unless-stopped
    logging: *logging
    cpus: '{p['db_cpu']}'
    mem_limit: {p['db_memory_mb']}m
    pids_limit: 256
    security_opt: [no-new-privileges:true]
    environment:
      MARIADB_DATABASE: appdb
      MARIADB_USER: appuser
      MARIADB_PASSWORD: ${{DB_PASSWORD:?Missing DB password}}
      MARIADB_ROOT_PASSWORD: ${{DB_ROOT_PASSWORD:?Missing root password}}
    volumes: [db:/var/lib/mysql, './config/mariadb.cnf:/etc/mysql/conf.d/tuning.cnf:ro']
    healthcheck:
      test: [CMD, healthcheck.sh, --connect, --innodb_initialized]
      interval: 10s
      timeout: 5s
      retries: 15
  tunnel:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    logging: *logging
    profiles: [tunnel]
    command: tunnel --no-autoupdate run
    environment: {{TUNNEL_TOKEN: '${{TUNNEL_TOKEN:-}}'}}
volumes:
  db:
''')
        work.rename(target)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    print(f'Đã tạo. Tiếp theo: cd {target} && docker compose config --quiet && docker compose up -d --build')
    print('Đọc MULTISITE.md để gắn domain, backup, SQL và cách ly. Chưa chạy Docker.')


if __name__ == '__main__':
    main()
