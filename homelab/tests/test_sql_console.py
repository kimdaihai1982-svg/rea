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
