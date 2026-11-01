"""Generator boundary tests; no Docker, network services, or host changes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class CreateSiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ['php', 'config', 'projects', 'scripts']:
            shutil.copytree(SOURCE / name, self.root / name)
        shutil.copy2(SOURCE / 'packages.json', self.root / 'packages.json')

    def run_generator(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'scripts/create-site.py'),
                               *args], capture_output=True, text=True)

    def valid(self, *args):
        return self.run_generator('shop', '--domain', 'shop.example.com',
                                  '--port', '28991', *args)

    def test_preview_does_not_write(self):
        result = self.valid()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'sites').exists())

    def test_secrets_permissions_and_limits(self):
        result = self.valid('--write', '--package', 'business')
        self.assertEqual(result.returncode, 0, result.stderr)
        site = self.root / 'sites/shop'
        env = (site / '.env').read_text()
        self.assertEqual((site / '.env').stat().st_mode & 0o777, 0o600)
        self.assertEqual(site.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(env.splitlines()[0].split('=')[1], result.stdout)
        compose = (site / 'compose.yaml').read_text()
        self.assertIn('name: site-shop', compose)
        self.assertIn('127.0.0.1:28991:8080', compose)
        self.assertIn('mem_limit: 1024m', compose)
        self.assertNotIn('/var/run/docker.sock', compose)
        self.assertEqual(json.loads((site / 'site.json').read_text())['domain'], 'shop.example.com')

    def test_existing_site_unchanged(self):
        self.assertEqual(self.valid('--write').returncode, 0)
        env = (self.root / 'sites/shop/.env').read_text()
        self.assertNotEqual(self.valid('--write').returncode, 0)
        self.assertEqual(env, (self.root / 'sites/shop/.env').read_text())

    def test_invalid_inputs(self):
        cases = [('../escape', 'good.example', '28991'),
                 ('shop', 'bad.example;rm', '28991'),
                 ('shop', 'https://good.example', '28991'),
                 ('shop', '-bad.example', '28991'),
                 ('shop', 'good.example', '9090')]
        for name, domain, port in cases:
            with self.subTest(domain=domain, name=name, port=port):
                result = self.run_generator(name, '--domain', domain, '--port', port, '--write')
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'sites').exists())

    def test_duplicate_inventory(self):
        self.assertEqual(self.valid('--write').returncode, 0)
        for domain, port in [('shop.example.com', '28992'), ('other.example.com', '28991')]:
            result = self.run_generator('other', '--domain', domain, '--port', port, '--write')
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'sites/other').exists())

    def test_web_template_readable_with_agent_umask(self):
        result = subprocess.run([sys.executable,str(self.root/'scripts/create-site.py'),
                                 'shop','--domain','shop.example.com','--port','28991','--write'],
                                capture_output=True,text=True,umask=0o007)
        self.assertEqual(result.returncode,0,result.stderr)
        for relative in ('projects','projects/demo','projects/demo/public'):
            self.assertEqual((self.root/'sites/shop'/relative).stat().st_mode & 0o777,0o755)

    def test_symlink_sites_rejected(self):
        (self.root / 'outside').mkdir()
        (self.root / 'sites').symlink_to(self.root / 'outside', target_is_directory=True)
        self.assertNotEqual(self.valid('--write').returncode, 0)
        self.assertEqual(list((self.root / 'outside').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
