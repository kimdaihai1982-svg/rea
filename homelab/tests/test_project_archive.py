"""Real ZIP/filesystem regression tests: confinement, limits and rollback."""
import base64
import importlib.util
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('archive_files',ROOT/'dashboard/project_files.py')
files=importlib.util.module_from_spec(spec);spec.loader.exec_module(files)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'projects/demo/public').mkdir(parents=True)
    def zip(self,entries):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,value in entries:archive.writestr(name,value)
        files.upload(self.root,'demo/code.zip',base64.b64encode(data.getvalue()).decode())
    def test_extract_nested_files_empty_dirs_and_permissions(self):
        self.zip([('index.php','<?php echo "ok";'),('css/site.css','body{}'),('empty/',b'')])
        result=files.extract(self.root,'demo/code.zip','demo/public')
        self.assertEqual(result['files'],2)
        target=self.root/'projects/demo/public'
        self.assertEqual((target/'index.php').read_text(),'<?php echo "ok";')
        self.assertTrue((target/'empty').is_dir())
        self.assertEqual((target/'css').stat().st_mode & 0o777,0o755)
        self.assertEqual((target/'index.php').stat().st_mode & 0o777,0o644)
    def test_existing_collision_is_detected_before_any_write(self):
        self.zip([('new/a.txt','new'),('index.php','overwrite')])
        target=self.root/'projects/demo/public';(target/'index.php').write_text('old')
        with self.assertRaises(ValueError):files.extract(self.root,'demo/code.zip','demo/public')
        self.assertEqual((target/'index.php').read_text(),'old');self.assertFalse((target/'new').exists())
    def test_symlink_traversal_hidden_absolute_and_internal_conflicts(self):
        for name in ('../escape','/tmp/escape','a/../escape','.env','x/.git/config','a\\b','a:b'):
            with self.subTest(name=name):
                self.zip([(name,'bad')])
                with self.assertRaises(ValueError):files.extract(self.root,'demo/code.zip','demo/public')
                (self.root/'projects/demo/code.zip').unlink()
        link=zipfile.ZipInfo('link');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
        self.zip([(link,'/etc/passwd')])
        with self.assertRaises(ValueError):files.extract(self.root,'demo/code.zip','demo/public')
        (self.root/'projects/demo/code.zip').unlink()
        self.zip([('x','file'),('x/child','conflict')])
        with self.assertRaises(ValueError):files.extract(self.root,'demo/code.zip','demo/public')
    def test_existing_parent_symlink_never_followed(self):
        outside=self.root/'outside';outside.mkdir()
        (self.root/'projects/demo/public/link').symlink_to(outside,target_is_directory=True)
        self.zip([('link/evil.php','bad')])
        with self.assertRaises((ValueError,OSError)):files.extract(self.root,'demo/code.zip','demo/public')
        self.assertFalse((outside/'evil.php').exists())
    def test_mid_write_error_rolls_back_only_new_files_and_directories(self):
        self.zip([('new/one','hello'),('new/two','world')])
        (self.root/'projects/demo/public/keep').write_text('keep')
        actual=files.write_all;count=0
        def fail(fd,data):
            nonlocal count
            count+=1
            if count==2:raise OSError('disk full fixture')
            actual(fd,data)
        with patch.object(files,'write_all',side_effect=fail):
            with self.assertRaises(OSError):files.extract(self.root,'demo/code.zip','demo/public')
        self.assertFalse((self.root/'projects/demo/public/new').exists())
        self.assertEqual((self.root/'projects/demo/public/keep').read_text(),'keep')
    def test_entry_size_depth_and_count_limits(self):
        for entries in ([('huge',b'a'*(8*1024*1024+1))], [('a/'*33+'f','x')], [(str(i),'x') for i in range(1001)]):
            self.zip(entries)
            with self.assertRaises(ValueError):files.extract(self.root,'demo/code.zip','demo/public')
            (self.root/'projects/demo/code.zip').unlink()
        self.assertEqual(list((self.root/'projects/demo/public').iterdir()),[])
