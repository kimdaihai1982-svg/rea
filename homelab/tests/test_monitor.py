"""Local monitoring behavior and real HTTP probe against loopback test server."""
import http.server
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monitor_test_module', ROOT / 'dashboard/monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class ProbeTests(unittest.TestCase):
    def test_initial_state_unknown(self):
        m = monitor.Monitor()
        self.assertTrue(all(t['state'] == 'unknown' and t['checked_at'] is None for t in m.snapshot()['targets']))

    def test_transitions_and_bounded_history(self):
        m = monitor.Monitor()
        with patch.object(monitor, 'probe', return_value=(True, 2.5, 'TCP mở')):
            m.sample()
            count = len(m.snapshot()['events'])
            m.sample()
            self.assertEqual(len(m.snapshot()['events']), count)
        with patch.object(monitor, 'probe', return_value=(False, 2, 'Timeout')):
            m.sample()
        self.assertTrue(all(t['state'] == 'down' for t in m.snapshot()['targets']))
        self.assertTrue(any(e['from'] == 'up' and e['to'] == 'down' for e in m.snapshot()['events']))
        for _ in range(30):
            with patch.object(monitor, 'probe', return_value=(True, 1, 'ok')): m.sample()
            with patch.object(monitor, 'probe', return_value=(False, 1, 'fail')): m.sample()
        self.assertEqual(len(m.snapshot()['events']), 100)

    def test_real_local_http_and_error_status(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            code = 200
            def log_message(self, *_): pass
            def do_GET(self):
                self.send_response(self.code)
                self.end_headers()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self.assertTrue(monitor.probe('http', server.server_port)[0])
            self.assertTrue(monitor.probe('tcp', server.server_port)[0])
            Handler.code = 503
            ok, _, detail = monitor.probe('http', server.server_port)
            self.assertFalse(ok)
            self.assertEqual(detail, 'HTTP 503')
        finally:
            server.shutdown(); server.server_close()

class LegacyRetirementTests(unittest.TestCase):
    def test_kuma_opt_in_only_and_not_in_backup_writers(self):
        compose = (ROOT / 'compose.yaml').read_text()
        self.assertIn('  kuma:\n    <<: *service\n    profiles: [legacy-kuma]', compose)
        script = (ROOT / 'scripts/backup.sh').read_text()
        self.assertNotIn('kuma', script)
        self.assertIn('resume+=("$svc")', script)
        ui = (ROOT / 'dashboard/index.html').read_text()
        self.assertNotIn('localhost:13001', ui)
        self.assertIn('id="monitoring"', ui)


if __name__ == '__main__':
    unittest.main()
