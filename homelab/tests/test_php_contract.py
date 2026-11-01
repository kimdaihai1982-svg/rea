"""Static guard for the pinned upstream base-image contract, not runtime validation.

Upstream 3.8.0 Dockerfile/config/fpm-pool.conf: PHP 8.4, PHP_INI_DIR
/etc/php84, FPM listens at /run/php-fpm.sock; inherited healthcheck /fpm-ping.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PhpBaseContractTests(unittest.TestCase):
    def test_php_extensions_match_base(self):
        dockerfile = (ROOT / 'php/Dockerfile').read_text()
        self.assertIn('FROM trafex/php-nginx:3.8.0', dockerfile)
        self.assertIn('apk add --no-cache php84-pdo_mysql', dockerfile)
        self.assertIn('"$PHP_INI_DIR/php-fpm.d/zz-app-env.conf"', dockerfile)
        self.assertIn('clear_env = yes', dockerfile)
        self.assertNotIn('php83', dockerfile)

    def test_nginx_uses_base_socket_and_healthcheck(self):
        nginx = (ROOT / 'config/nginx.conf').read_text()
        self.assertEqual(nginx.count('fastcgi_pass unix:/run/php-fpm.sock;'), 2)
        self.assertNotIn('127.0.0.1:9000', nginx)
        self.assertIn('location = /fpm-ping', nginx)
        self.assertIn('allow 127.0.0.1;', nginx)
        self.assertIn('deny all;', nginx)
