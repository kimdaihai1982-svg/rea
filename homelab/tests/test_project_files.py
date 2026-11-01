"""Real filesystem regression tests for the confined native manager; no Docker mocks needed."""
import base64
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_files', ROOT / 'dashboard/project_files.py')
files = importlib.util.module_from_spec(spec)
spec.loader.exec_module(files)


class FileWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'projects/demo/public').mkdir(parents=True)

    def upload(self, path, value=b'hello'):
        return files.upload(self.root, path, base64.b64encode(value).decode())

    def test_real_browse_upload_edit_download_and_history(self):
        files.mkdir(self.root, 'demo/public/images')
        self.upload('demo/public/hello.php', b'<?php echo "hello";')
        entries = files.browse(self.root, 'demo/public')['entries']
        self.assertEqual([x['kind'] for x in entries], ['directory', 'file'])
        old = files.read(self.root, 'demo/public/hello.php')
        self.assertEqual(base64.b64decode(old['content']), b'<?php echo "hello";')
        result = files.save(self.root, old['path'], '<?php echo "new";', old['version'])
        new = files.read(self.root, old['path'])
        self.assertEqual(new['version'], result['version'])
        self.assertEqual(new['text'], '<?php echo "new";')
        backups = list((self.root / 'projects/demo/public/.maychu247-history').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'<?php echo "hello";')
        self.assertNotIn('.maychu247-history', [e['name'] for e in files.browse(self.root, 'demo/public')['entries']])

    def test_duplicate_upload_and_stale_save_do_not_overwrite(self):
        self.upload('demo/public/index.html')
        old = files.read(self.root, 'demo/public/index.html')
        with self.assertRaises(FileExistsError): self.upload(old['path'], b'overwrite')
        (self.root / 'projects' / old['path']).write_text('external edit')
        with self.assertRaisesRegex(ValueError, 'thay đổi'):
            files.save(self.root, old['path'], 'stale edit', old['version'])
        self.assertEqual((self.root / 'projects' / old['path']).read_text(), 'external edit')

    def test_no_symlink_escape_or_hidden_files(self):
        outside = self.root / 'secret.txt'
        outside.write_text('secret')
        (self.root / 'projects/link').symlink_to(self.root, target_is_directory=True)
        (self.root / 'projects/demo/public/link.txt').symlink_to(outside)
        for path in ('../secret.txt', '/etc/passwd', 'demo/../secret.txt', '.env', 'demo/.env', 'a\\b'):
            with self.assertRaises(ValueError): files.read(self.root, path)
        with self.assertRaises(OSError): files.read(self.root, 'link/secret.txt')
        with self.assertRaises(OSError): files.read(self.root, 'demo/public/link.txt')
        with self.assertRaises(OSError): files.save(self.root, 'demo/public/link.txt', 'bad', '0'*64)
        with self.assertRaises(FileExistsError): self.upload('demo/public/link.txt')
        self.assertEqual(outside.read_text(), 'secret')
        self.assertEqual(files.browse(self.root, '')['entries'][1]['kind'], 'blocked')

    def test_limits_binary_and_permissions(self):
        previous = os.umask(0o007)
        try:
            files.mkdir(self.root, 'demo/public/new-dir')
            self.upload('demo/public/new-dir/image.bin', b'\x00\xff\x01')
        finally:
            os.umask(previous)
        self.assertEqual((self.root / 'projects/demo/public/new-dir').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.root / 'projects/demo/public/new-dir/image.bin').stat().st_mode & 0o777, 0o644)
        self.assertIsNone(files.read(self.root, 'demo/public/new-dir/image.bin')['text'])
        with self.assertRaises(ValueError): self.upload('demo/public/large.txt', b'a'*(files.MAX_FILE+1))
        (self.root / 'projects/demo/public/huge').write_bytes(b'a'*(files.MAX_FILE+1))
        with self.assertRaises(ValueError): files.read(self.root, 'demo/public/huge')

    def test_history_symlink_is_rejected(self):
        self.upload('demo/public/test.txt')
        old = files.read(self.root, 'demo/public/test.txt')
        (self.root / 'projects/demo/public/.maychu247-history').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): files.save(self.root, old['path'], 'new', old['version'])
        self.assertEqual((self.root / 'projects/demo/public/test.txt').read_text(), 'hello')


if __name__ == '__main__':
    unittest.main()
