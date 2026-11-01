"""Real HTTP auth/CSRF tests, with a mocked privileged broker (not Docker tests)."""
import hashlib
import http.client
import http.server
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import threading
import socket
import base64
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard'))
spec = importlib.util.spec_from_file_location('dashboard_server', ROOT / 'dashboard/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = Path(self.temp.name) / 'auth.json'
        salt = b'1234567890abcdef'
        config.write_text(json.dumps({'salt': salt.hex(), 'hash': hashlib.scrypt(
            b'test-password', salt=salt, n=16384, r=8, p=1).hex()}))
        self.config = patch.object(server, 'CONFIG_PATH', config)
        self.config.start()
        self.addCleanup(self.config.stop)
        server.SESSIONS.clear()
        server.ATTEMPTS.clear()
        self.http = http.server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def req(self, method, path, data=None, cookie=None, csrf=None, host='localhost:18000', origin='http://localhost:18000'):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        headers = {'Host': host}
        if cookie:
            headers['Cookie'] = cookie
        if data is not None:
            headers.update({'Origin': origin, 'Content-Type': 'application/json'})
        if csrf:
            headers['X-CSRF-Token'] = csrf
        conn.request(method, path, None if data is None else json.dumps(data), headers)
        response = conn.getresponse()
        body = response.read()
        result = response.status, dict(response.getheaders()), body
        conn.close()
        return result

    def login(self):
        code, headers, body = self.req('POST', '/api/login', {'password': 'test-password'})
        self.assertEqual(code, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';')[0], json.loads(body)['csrf']

    def test_requires_auth_and_local_host(self):
        self.assertEqual(self.req('GET', '/api/status')[0], 401)
        self.assertEqual(self.req('GET', '/', host='attacker.example:18000')[0], 403)
        self.assertEqual(self.req('GET', '/')[0], 200)

    def test_bad_password_and_origin(self):
        self.assertEqual(self.req('POST', '/api/login', {'password': 'wrong'})[0], 401)
        self.assertEqual(self.req('POST', '/api/login', {'password': 'test-password'}, origin='https://evil.example')[0], 403)

    def test_csrf_and_action_allowlist(self):
        cookie, csrf = self.login()
        with patch.object(server, 'agent', return_value=(200, {'message': 'ok'})) as broker:
            self.assertEqual(self.req('POST', '/api/action', {'action': 'restart', 'service': 'web'}, cookie=cookie)[0], 403)
            broker.assert_not_called()
            self.assertEqual(self.req('POST', '/api/action', {'action': 'exec', 'command': 'id'}, cookie=cookie, csrf=csrf)[0], 400)
            broker.assert_not_called()
            self.assertEqual(self.req('POST', '/api/action', {'action': 'restart', 'service': 'web'}, cookie=cookie, csrf=csrf)[0], 200)
            broker.assert_called_once_with({'action': 'restart', 'service': 'web'})

    def test_create_site_requires_csrf_and_forwards_only_known_fields(self):
        cookie, csrf = self.login()
        payload = {'action': 'create-site', 'name': 'shop', 'domain': 'shop.example.com',
                   'package': 'starter', 'port': 20001, 'command': 'id', 'path': '/etc'}
        with patch.object(server, 'agent', return_value=(200, {'message': 'created'})) as broker:
            self.assertEqual(self.req('POST', '/api/action', payload, cookie=cookie)[0], 403)
            broker.assert_not_called()
            self.assertEqual(self.req('POST', '/api/action', payload, cookie=cookie, csrf=csrf)[0], 200)
            broker.assert_called_once_with({k: payload[k] for k in ('action','name','domain','package','port')})

    def test_public_domain_secure_cookie_and_origin_pairing(self):
        with patch.object(server, 'PUBLIC_ORIGIN', 'https://panel.example.com'):
            status, headers, body = self.req('POST','/api/login', {'password':'test-password'},
                                            host='panel.example.com',origin='https://panel.example.com')
            self.assertEqual(status,200)
            self.assertIn('; Secure',headers['Set-Cookie'])
            cookie=headers['Set-Cookie'].split(';')[0]
            csrf=json.loads(body)['csrf']
            self.assertEqual(self.req('POST','/api/logout',{},cookie=cookie,csrf=csrf,
                                     host='panel.example.com',origin='http://panel.example.com')[0],403)
            self.assertEqual(self.req('POST','/api/logout',{},cookie=cookie,csrf=csrf,
                                     host='panel.example.com',origin='https://panel.example.com')[0],200)
            self.assertEqual(self.req('GET','/',host='evil.example.com')[0],403)

    def test_public_origin_configuration_is_exact(self):
        self.assertEqual(server.configured_origin('https://panel.example.com'),'https://panel.example.com')
        for origin in ('http://panel.example.com','https://*.example.com','https://panel.example.com/path','https://panel.example.com:443','https://user@panel.example.com'):
            with self.assertRaises(ValueError):server.configured_origin(origin)

    def test_folder_and_database_actions_require_csrf_and_strip_extra_fields(self):
        cookie, csrf = self.login()
        for action in ('create-folder', 'create-database'):
            payload = {'action':action,'name':'my_app','path':'/etc','sql':'DROP DATABASE appdb'}
            with patch.object(server,'agent',return_value=(200,{'message':'ok'})) as broker:
                self.assertEqual(self.req('POST','/api/action',payload,cookie=cookie)[0],403)
                broker.assert_not_called()
                self.assertEqual(self.req('POST','/api/action',payload,cookie=cookie,csrf=csrf)[0],200)
                broker.assert_called_once_with({'action':action,'name':'my_app'})
        self.assertEqual(self.req('GET','/api/resources')[0],401)
        with patch.object(server,'agent',return_value=(200,{'folders':{},'databases':{}})) as broker:
            self.assertEqual(self.req('GET','/api/resources',cookie=cookie)[0],200)
            broker.assert_called_once_with({'action':'resources'})

    def test_native_files_http_to_unix_agent_real_filesystem(self):
        spec = importlib.util.spec_from_file_location('file_integration_agent', ROOT/'dashboard/agent.py')
        broker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(broker)
        root = Path(self.temp.name)/'stack'
        (root/'projects/demo/public').mkdir(parents=True)
        broker.ROOT = root
        path = str(Path(self.temp.name)/'agent.sock')
        unix = broker.Server(path,broker.Handler)
        threading.Thread(target=unix.serve_forever,daemon=True).start()
        self.addCleanup(unix.server_close)
        self.addCleanup(unix.shutdown)
        def transport(payload):
            c=http.client.HTTPConnection('localhost',timeout=5)
            c.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            c.sock.settimeout(5);c.sock.connect(path)
            c.request('POST','/',json.dumps(payload),{'Content-Type':'application/json'})
            r=c.getresponse();body=json.loads(r.read());status=r.status;c.close()
            return status,body
        cookie,csrf=self.login()
        content='xin chao '*1200
        with patch.object(server,'agent',side_effect=transport):
            self.assertEqual(self.req('GET','/api/files?path=demo')[0],401)
            code,_,body=self.req('POST','/api/action',{'action':'file-upload','path':'demo/public/test.php','content':base64.b64encode(content.encode()).decode()},cookie=cookie,csrf=csrf)
            self.assertEqual(code,200,body)
            self.assertEqual((root/'projects/demo/public/test.php').read_text(),content)
            code,_,body=self.req('GET','/api/files?path=demo%2Fpublic',cookie=cookie)
            self.assertEqual(code,200)
            self.assertEqual(json.loads(body)['entries'][0]['name'],'test.php')
            code,_,body=self.req('GET','/api/file?path=demo%2Fpublic%2Ftest.php',cookie=cookie)
            self.assertEqual(code,200);version=json.loads(body)['version']
            code,_,body=self.req('POST','/api/action',{'action':'file-save','path':'demo/public/test.php','text':'saved through HTTP','version':version},cookie=cookie,csrf=csrf)
            self.assertEqual(code,200,body)
            self.assertEqual((root/'projects/demo/public/test.php').read_text(),'saved through HTTP')
            self.assertEqual(self.req('GET','/api/file?path=..%2Fetc%2Fpasswd',cookie=cookie)[0],400)
            self.assertEqual(self.req('POST','/api/action',{'action':'file-mkdir','path':'demo/public/images'},cookie=cookie,csrf=csrf)[0],200)
            self.assertTrue((root/'projects/demo/public/images').is_dir())

    def test_mqtt_actions_require_csrf_and_never_forward_broker_password(self):
        cookie,csrf=self.login()
        for action in ('mqtt-publish','mqtt-sample','mqtt-test'):
            data={'action':action,'topic':'home/data','payload':'hello','password':'not-forwarded','host':'evil.example'}
            with patch.object(server,'agent',return_value=(200,{'message':'ok'})) as broker:
                self.assertEqual(self.req('POST','/api/action',data,cookie=cookie)[0],403)
                broker.assert_not_called()
                self.assertEqual(self.req('POST','/api/action',data,cookie=cookie,csrf=csrf)[0],200)
                broker.assert_called_once_with({k:data[k] for k in ('action','topic','payload')})

    def test_logout_revokes_session(self):
        cookie, csrf = self.login()
        self.assertEqual(self.req('POST', '/api/logout', {}, cookie=cookie, csrf=csrf)[0], 200)
        self.assertEqual(self.req('GET', '/api/session', cookie=cookie)[0], 401)

    def test_rate_limit(self):
        server.ATTEMPTS[:] = [server.time.time()] * 10
        self.assertEqual(self.req('POST', '/api/login', {'password': 'test-password'})[0], 429)

    def test_agent_failure_does_not_fake_status(self):
        cookie, _ = self.login()
        with patch.object(server, 'agent', side_effect=OSError('offline')):
            code, _, body = self.req('GET', '/api/status', cookie=cookie)
            self.assertEqual(code, 503)
            self.assertNotIn('host', json.loads(body))

    def test_path_traversal_is_not_served(self):
        cookie, _ = self.login()
        self.assertEqual(self.req('GET', '/../../.env', cookie=cookie)[0], 404)


if __name__ == '__main__':
    unittest.main()
