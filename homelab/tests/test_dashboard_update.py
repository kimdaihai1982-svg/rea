"""Execute the installer's actual bind preflight against real sockets, no systemd/root changes."""
import http.client
import http.server
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpdateSocketTests(unittest.TestCase):
    def gate(self, port):
        script = (ROOT / 'scripts/install-dashboard.sh').read_text()
        snippet = script.split("python3 - <<'PY'\nimport socket\n", 1)[1].split('\nPY', 1)[0]
        return subprocess.run([sys.executable, '-c', 'import socket\n' + snippet.replace('18000', str(port))], capture_output=True, text=True)

    def test_time_wait_does_not_leave_dashboard_stopped(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        port = server.server_port
        threading.Thread(target=server.serve_forever, daemon=True).start()
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        c.request('GET', '/')
        c.getresponse().read()
        c.close()
        server.shutdown()
        server.server_close()
        result = self.gate(port)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_listener_still_blocks_update(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            result = self.gate(listener.getsockname()[1])
            self.assertNotEqual(result.returncode, 0)

    def test_install_has_preflight_rollback_and_readiness(self):
        script = (ROOT / 'scripts/install-dashboard.sh').read_text()
        self.assertLess(script.index('import server, agent, monitor'), script.index('docker compose stop portal kuma'))
        self.assertIn('trap rollback ERR', script)
        self.assertIn("{'action':'ping'}", script)
        self.assertIn('if r.status!=200', script)
        self.assertIn('cp -a "$rollback_dir/live"', script)


if __name__ == '__main__':
    unittest.main()
