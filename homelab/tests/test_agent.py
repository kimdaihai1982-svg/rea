"""Broker allowlist over real Unix HTTP socket; Docker calls are mocked."""
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('broker', ROOT / 'dashboard/agent.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'agent.sock')
        self.server = agent.Server(self.path, agent.Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        agent.JOB.update(state='idle', message='test')

    def req(self, body):
        c = http.client.HTTPConnection('localhost', timeout=5)
        c.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.sock.settimeout(5)
        c.sock.connect(self.path)
        c.request('POST', '/', json.dumps(body), {'Content-Type': 'application/json'})
        response = c.getresponse()
        result = response.status, json.loads(response.read())
        c.close()
        return result

    def test_rejects_arbitrary_service_or_exec(self):
        with patch.object(agent, 'compose') as compose:
            self.assertEqual(self.req({'action': 'stop', 'service': 'web; id'})[0], 400)
            self.assertEqual(self.req({'action': 'exec', 'command': 'id'})[0], 400)
            compose.assert_not_called()

    def test_only_fixed_compose_command(self):
        with patch.object(agent, 'compose', return_value='') as compose:
            self.assertEqual(self.req({'action': 'restart', 'service': 'web'})[0], 200)
            compose.assert_called_once_with('restart', 'web', timeout=90)

    def test_status_redacts_unknown_fields(self):
        with patch.object(agent, 'compose', return_value=json.dumps([
            {'Service': 'db', 'State': 'running', 'Environment': 'SECRET', 'Health': 'healthy'}
        ])), patch.object(agent, 'snapshots', return_value=[]):
            status, data = self.req({'action': 'status'})
            self.assertEqual(status, 200)
            self.assertEqual(data['services'][0]['Health'], 'healthy')
            self.assertNotIn('SECRET', json.dumps(data))

    def test_service_actions_blocked_during_job(self):
        agent.JOB['state'] = 'running'
        with patch.object(agent, 'compose') as compose:
            self.assertEqual(self.req({'action': 'stop', 'service': 'db'})[0], 400)
            compose.assert_not_called()


if __name__ == '__main__':
    unittest.main()
