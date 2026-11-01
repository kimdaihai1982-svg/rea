"""Broker allowlist over real Unix HTTP socket; Docker calls are mocked."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import shutil
import tempfile
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dashboard'))
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

    def test_create_site_real_generator_and_private_inventory(self):
        root = Path(self.temp.name) / 'stack'
        root.mkdir()
        for name in ('scripts', 'config', 'projects', 'php'):
            shutil.copytree(ROOT / name, root / name)
        shutil.copy2(ROOT / 'packages.json', root / 'packages.json')
        with patch.object(agent, 'ROOT', root):
            status, result = self.req({'action': 'create-site', 'name': 'my-shop',
                                      'domain': 'shop.example.com', 'package': 'starter', 'port': 28991})
            self.assertEqual(status, 200, result)
            folder = root / 'sites/my-shop'
            self.assertTrue((folder / 'compose.yaml').is_file())
            self.assertEqual((folder / '.env').stat().st_mode & 0o777, 0o600)
            secret = (folder / '.env').read_text().splitlines()[0].split('=')[1]
            inventory = agent.site_inventory()
            self.assertEqual(inventory['items'][0]['name'], 'my-shop')
            self.assertNotIn(secret, json.dumps(inventory) + json.dumps(result))
            status, _ = self.req({'action': 'create-site', 'name': 'my-shop',
                                 'domain': 'shop.example.com', 'package': 'starter', 'port': 28991})
            self.assertEqual(status, 400)
            self.assertEqual((folder / '.env').read_text().splitlines()[0].split('=')[1], secret)
            status, _ = self.req({'action': 'create-site', 'name': '../escape',
                                 'domain': 'other.example.com', 'package': 'starter', 'port': 28992})
            self.assertEqual(status, 400)
            self.assertFalse((root / 'escape').exists())

    def test_folder_creation_readable_and_no_escape(self):
        root = Path(self.temp.name) / 'folder-stack'
        (root / 'projects').mkdir(parents=True)
        with patch.object(agent, 'ROOT', root):
            previous = os.umask(0o007)
            try:
                result = agent.create_folder('web-one')
            finally:
                os.umask(previous)
            folder = root / 'projects/web-one'
            self.assertTrue((folder / 'public/index.html').is_file())
            self.assertEqual(folder.stat().st_mode & 0o777, 0o755)
            self.assertEqual((folder / 'public/index.html').stat().st_mode & 0o777, 0o644)
            self.assertIn('Chưa tạo virtual host', result['message'])
            for name in ('web-one', '../escape', 'a/b', 'bad name', '<script>'):
                with self.assertRaises(ValueError): agent.create_folder(name)
            self.assertFalse((root / 'escape').exists())
            (root / 'projects/link').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError): agent.create_folder('link')
            self.assertEqual(agent.project_folders()[0]['name'], 'web-one')
        other = Path(self.temp.name) / 'linked-stack'
        other.mkdir()
        (other / 'projects').symlink_to(root / 'projects', target_is_directory=True)
        with patch.object(agent, 'ROOT', other):
            with self.assertRaises(OSError): agent.create_folder('blocked')

    def test_sql_creation_validates_identifier_and_uses_existing_user(self):
        with patch.object(agent, 'database_sql', side_effect=['1\n', '', '', '']) as query:
            result = agent.create_database('new_app')
            statements = [c.args[0] for c in query.call_args_list]
            self.assertIn('CREATE DATABASE `new_app`', statements[2])
            self.assertIn("TO 'appuser'@'%'", statements[3])
            self.assertIn('appuser', result['message'])
        for name in ('mysql', 'sys', 'x`;DROP DATABASE appdb;--', 'a/b', 'name-with-hyphen'):
            with patch.object(agent, 'database_sql') as query:
                with self.assertRaises(ValueError): agent.create_database(name)
                query.assert_not_called()
        with patch.object(agent, 'database_sql', side_effect=['1', 'already_exists']) as query:
            with self.assertRaises(ValueError): agent.create_database('already_exists')
            self.assertEqual(query.call_count, 2)
        with patch.object(agent, 'database_sql', side_effect=['0']) as query:
            with self.assertRaises(ValueError): agent.create_database('new_app')
            self.assertEqual(query.call_count, 1)

    def test_grant_failure_reports_partial_creation_without_drop(self):
        with patch.object(agent, 'database_sql', side_effect=['1', '', '', RuntimeError('grant fail')]) as query:
            with self.assertRaisesRegex(RuntimeError, 'có thể database đã được tạo'):
                agent.create_database('partial_db')
            self.assertFalse(any('DROP' in c.args[0] for c in query.call_args_list))

    def test_resource_lists_keep_folder_data_when_db_offline(self):
        with patch.object(agent, 'project_folders', return_value=[{'name':'demo'}]), patch.object(agent, 'database_inventory', side_effect=RuntimeError()):
            value = agent.resources()
            self.assertEqual(value['folders']['items'][0]['name'], 'demo')
            self.assertIsNotNone(value['databases']['error'])

    def test_delete_database_exact_confirmation_and_no_system_drop(self):
        with patch.object(agent,'database_sql',side_effect=['my_app','']) as query:
            result=agent.delete_database('my_app','DELETE my_app')
            self.assertIn('đã xóa',result['message'])
            self.assertEqual(query.call_args_list[-1].args[0],'DROP DATABASE `my_app`;\n')
        with patch.object(agent,'database_sql') as query:
            for name,confirmation in [('my_app','wrong'),('mysql','DELETE mysql'),('sys','DELETE sys')]:
                with self.assertRaises(ValueError):agent.delete_database(name,confirmation)
            query.assert_not_called()
        with patch.object(agent,'database_sql',return_value='') as query:
            with self.assertRaises(ValueError):agent.delete_database('my_app','DELETE my_app')
            self.assertEqual(query.call_count,1)

    def test_all_create_database_steps_use_same_selected_project(self):
        selected=Path('/selected/site')
        with patch.object(agent,'database_sql',side_effect=['1','','','']) as query:
            agent.create_database('new_app',selected)
            self.assertTrue(all(call.args[1]==selected for call in query.call_args_list))

    def test_site_lifecycle_is_real_queued_work_with_lock_and_no_claim_of_completion(self):
        with patch.object(agent.site_manager,'project',return_value=Path('/selected')),patch.object(agent.site_manager,'lifecycle',return_value={'message':'Docker accepted'}) as lifecycle:
            status,data=self.req({'action':'site-start','name':'one','command':'id'})
            self.assertEqual(status,200)
            self.assertIn('chưa xác nhận',data['message'])
            self.assertTrue(agent.LOCK.acquire(timeout=2))
            agent.LOCK.release()
            lifecycle.assert_called_once_with(agent.ROOT,'one','site-start')
            self.assertEqual(agent.JOB['state'],'done')

    def test_service_actions_blocked_during_job(self):
        agent.JOB['state'] = 'running'
        with patch.object(agent, 'compose') as compose:
            self.assertEqual(self.req({'action': 'stop', 'service': 'db'})[0], 400)
            compose.assert_not_called()


if __name__ == '__main__':
    unittest.main()
