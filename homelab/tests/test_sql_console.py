"""SQL command boundary + real subprocess pipe limits; no MariaDB installed here."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
import sql_console as sql


class SQLTests(unittest.TestCase):
    def test_appuser_fixed_shell_and_secrets_not_in_browser_or_sql_argv(self):
        with patch.object(sql,'bounded',return_value='id\n1\n') as run:
            r=sql.query(Path('/stack'),'appdb','SELECT 1;','RUN appdb')
        command,text,cwd=run.call_args.args
        self.assertEqual(command[-1],'appdb')
        self.assertIn('--binary-mode=1',command[-3])
        self.assertIn('--local-infile=0',command[-3])
        self.assertIn('-uappuser',command[-3]);self.assertNotIn('-uroot',command[-3])
        self.assertNotIn('SELECT 1;',command[-3]);self.assertEqual(text,'SELECT 1;\n')
        self.assertEqual(r['output'],'id\n1\n')

    def test_input_validation_before_any_process(self):
        with patch.object(sql,'bounded') as run:
            for name in ('mysql','sys','performance_schema','information_schema','a`;DROP DATABASE appdb;--','../a'):
                with self.assertRaises(ValueError):sql.query(Path('/stack'),name,'SELECT 1;','RUN '+name)
            for statement in ('','x'*8193,'SELECT\x00 1'):
                with self.assertRaises(ValueError):sql.query(Path('/stack'),'appdb',statement,'RUN appdb')
            with self.assertRaises(ValueError):sql.query(Path('/stack'),'appdb','SELECT 1;','wrong')
            run.assert_not_called()

    def test_real_process_streamed_input_and_output(self):
        text='đầu vào\n'*600
        out=sql.bounded([sys.executable,'-c','import sys; sys.stdout.write(sys.stdin.read())'],text,Path.cwd())
        self.assertEqual(text,out)

    def test_real_process_limits_timeout_and_redacts_stderr(self):
        with self.assertRaisesRegex(RuntimeError,'256 KiB'):
            sql.bounded([sys.executable,'-c','import sys;sys.stdout.write("x"*500000)'],'x',Path.cwd())
        with self.assertRaisesRegex(RuntimeError,'thời gian'):
            sql.bounded([sys.executable,'-c','import time;time.sleep(20)'],'x',Path.cwd(),seconds=.1)
        with self.assertRaises(RuntimeError) as error:
            sql.bounded([sys.executable,'-c','import sys;sys.stderr.write("SECRET");sys.exit(1)'],'x',Path.cwd())
        self.assertNotIn('SECRET',str(error.exception))


class SQLImportTests(unittest.TestCase):
    def test_import_uses_appuser_stdin_binary_mode_no_local_infile_and_selected_root(self):
        import base64
        text='CREATE TABLE sample(id INT);\nINSERT INTO sample VALUES(1);'
        with patch.object(sql,'bounded',return_value='') as run:
            result=sql.import_file(Path('/selected/site'),'appdb',base64.b64encode(text.encode()).decode(),'IMPORT appdb')
        command,statement,root=run.call_args.args
        self.assertEqual(root,Path('/selected/site'));self.assertEqual(statement,text+'\n')
        self.assertEqual(command[-1],'appdb');self.assertIn('-uappuser',command[-3])
        self.assertIn('--binary-mode=1',command[-3]);self.assertIn('--local-infile=0',command[-3])
        self.assertEqual(run.call_args.kwargs['seconds'],60)
        self.assertNotIn(text,' '.join(command));self.assertIn('thành công',result['message'])
    def test_import_rejects_system_db_binary_bad_base64_and_confirmation(self):
        import base64
        with patch.object(sql,'bounded') as run:
            for database,content,confirmation in [('mysql','eA==','IMPORT mysql'),('appdb','eA==','RUN appdb'),('appdb','!','IMPORT appdb'),('appdb',base64.b64encode(b'\x00bad').decode(),'IMPORT appdb'),('appdb','/w==','IMPORT appdb')]:
                with self.assertRaises(ValueError):sql.import_file(Path('/stack'),database,content,confirmation)
            run.assert_not_called()


class SQLExportTests(unittest.TestCase):
    def test_dump_appuser_exact_schema_no_secret_or_database_contents_in_argv(self):
        import base64,hashlib
        data=b'CREATE TABLE sample(id INT);\nINSERT INTO sample VALUES(1);\n'
        with patch.object(sql,'bounded',return_value=data) as run:
            result=sql.export_file(Path('/selected/site'),'appdb','EXPORT appdb')
        command,text,root=run.call_args.args
        self.assertEqual(command[-1],'appdb');self.assertEqual(root,Path('/selected/site'));self.assertEqual(text,'')
        self.assertIn('mariadb-dump -uappuser',command[-3]);self.assertNotIn('-uroot',command[-3]);self.assertNotIn('--all-databases',command[-3])
        self.assertIn('--single-transaction',command[-3]);self.assertIn('--skip-lock-tables',command[-3])
        self.assertEqual(run.call_args.kwargs,{'seconds':60,'max_bytes':8*1024*1024,'binary':True})
        self.assertEqual(base64.b64decode(result['content']),data)
        self.assertEqual(result['sha256'],hashlib.sha256(data).hexdigest())
        self.assertRegex(result['filename'],r'^appdb-\d{8}T\d{6}Z\.sql$')
    def test_export_invalid_names_confirmations_empty_or_failed_dump_no_fake_file(self):
        with patch.object(sql,'bounded') as run:
            for database,confirmation in [('mysql','EXPORT mysql'),('appdb','wrong'),('../x','EXPORT ../x')]:
                with self.assertRaises(ValueError):sql.export_file(Path('/stack'),database,confirmation)
            run.assert_not_called()
        with patch.object(sql,'bounded',return_value=b''):
            with self.assertRaises(RuntimeError):sql.export_file(Path('/stack'),'appdb','EXPORT appdb')
        with patch.object(sql,'bounded',side_effect=RuntimeError('dump failed')):
            with self.assertRaises(RuntimeError):sql.export_file(Path('/stack'),'appdb','EXPORT appdb')
    def test_real_subprocess_binary_output_preserved_without_utf8_replacement(self):
        data=sql.bounded([sys.executable,'-c','import sys;sys.stdout.buffer.write(bytes([0,255,195,169]))'],'',Path.cwd(),binary=True)
        self.assertEqual(data,b'\x00\xff\xc3\xa9')
