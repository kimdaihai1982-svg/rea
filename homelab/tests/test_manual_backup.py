"""Standalone backup orchestration tests. Docker/systemd mocked, real tar/files/checksums."""
import contextlib
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'downloads/MayChu247-Backup.sh'
CODE=SCRIPT.read_text().split("exec python3 - <<'PY'\n",1)[1].rsplit('\nPY',1)[0]


class ManualBackupTests(unittest.TestCase):
    def perform(self, fail_dump=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        (root/'.env').write_text('TEST_ONLY=fixture')
        (root/'compose.yaml').write_text('name: fixture\nservices: {}\n')
        (root/'projects/demo/public').mkdir(parents=True)
        (root/'projects/demo/public/index.html').write_text('hello')
        events=[];real_run=subprocess.run
        def fake(args,**kw):
            events.append(args)
            if args[0]=='systemctl': return subprocess.CompletedProcess(args,3)
            if args[0]=='tar': return real_run(args,**kw)
            self.assertEqual(args[0],'docker')
            if 'ps' in args:
                return subprocess.CompletedProcess(args,0,stdout=b'db\nweb\nmqtt\nfiles\nadminer\n',stderr=b'')
            if 'config' in args:
                return subprocess.CompletedProcess(args,0,stdout=b'db\nweb\nmqtt\nfiles\nadminer\n',stderr=b'')
            if 'exec' in args and args[-2]=='-c':
                if fail_dump:return subprocess.CompletedProcess(args,1)
                kw['stdout'].write(b'-- test fixture SQL\n')
            if 'run' in args:
                with tarfile.open(fileobj=kw['stdout'],mode='w:gz'):pass
            return subprocess.CompletedProcess(args,0,stdout=b'',stderr=b'')
        code=CODE.replace("ROOT = Path('/opt/maychu247-v2')",'ROOT = Path('+repr(str(root))+')')
        with patch('subprocess.run',side_effect=fake),patch('shutil.which',return_value='/tool'),patch('signal.signal'),patch('os.umask'),patch.dict('os.environ',{'SUDO_UID':''}),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:exec(compile(code,str(SCRIPT),'exec'),{'__name__':'__main__'})
        return root,events,result.exception.code

    def test_success_archives_and_checksums_and_resume_only_original_services(self):
        root,events,code=self.perform()
        self.assertEqual(code,0)
        snapshots=list((root/'backups').glob('manual-*'));self.assertEqual(len(snapshots),1)
        snapshot=snapshots[0];self.assertTrue((snapshot/'COMPLETE').exists())
        for line in (snapshot/'SHA256SUMS').read_text().splitlines():
            digest,name=line.split('  ',1)
            self.assertEqual(hashlib.sha256((snapshot/name).read_bytes()).hexdigest(),digest)
        with tarfile.open(snapshot/'main/source.tgz') as archive:
            names=archive.getnames();self.assertIn('./.env',names)
            self.assertIn('./projects/demo/public/index.html',names)
            self.assertFalse(any(name.startswith('./backups') for name in names))
        stops=[args for args in events if 'stop' in args]
        starts=[args for args in events if 'start' in args]
        self.assertEqual(stops[0][-4:],['web','mqtt','files','adminer'])
        self.assertEqual(starts[0][-4:],['web','mqtt','files','adminer'])
        self.assertFalse(any('down' in args for args in events))

    def test_dump_failure_leaves_no_complete_and_restores_services(self):
        root,events,code=self.perform(fail_dump=True)
        self.assertEqual(code,1)
        self.assertFalse(list((root/'backups').glob('manual-*/COMPLETE')))
        self.assertTrue(any('start' in args for args in events))
        self.assertTrue((root/'.env').exists())
