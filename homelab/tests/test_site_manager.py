"""Actual loopback HTTP origin checks, mocked Docker lifecycle; no live deployment claim."""
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
import site_manager as sites


class SitesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.target=self.root/'sites/one';(self.target/'projects').mkdir(parents=True)
        (self.target/'compose.yaml').write_text('services: {}')
        (self.target/'.env').write_text('TEST_ONLY=not-a-real-secret')
        self.metadata={'name':'one','domain':'one.example.com','port':29990}
        self.write()
    def write(self): (self.target/'site.json').write_text(json.dumps(self.metadata))

    def test_scope_validation_and_no_symlink_or_arbitrary_root(self):
        self.assertEqual(sites.project(self.root),self.root)
        self.assertEqual(sites.project(self.root,'one'),self.target)
        for name in ('../one','/etc','one;id'):
            with self.assertRaises(ValueError):sites.project(self.root,name)
        (self.target/'.env').unlink();(self.target/'.env').symlink_to(self.root/'secret')
        with self.assertRaises(ValueError):sites.project(self.root,'one')

    def test_only_fixed_loopback_http_and_host_no_redirect_following(self):
        seen=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.append(self.headers['Host']);self.send_response(302)
                self.send_header('Location','http://169.254.169.254/');self.end_headers()
        for port in range(29000,29100):
            try:server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);break
            except OSError:continue
        else:self.fail('No available loopback test port')
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.metadata['port']=port;self.write()
        result=sites.check(self.root,'one')
        self.assertEqual(result['status'],302);self.assertFalse(result['ready']);self.assertEqual(seen,['one.example.com'])
        self.metadata['port']=18000;self.write()
        with self.assertRaises(ValueError):sites.check(self.root,'one')

    def test_lifecycle_fixed_argv_no_down_or_volume_removal(self):
        with patch.object(sites.subprocess,'run') as run,patch.object(sites,'check',return_value={'message':'HTTP 200','ready':True}):
            run.return_value.returncode=0
            sites.lifecycle(self.root,'one','site-start')
            self.assertEqual(run.call_args.args[0][-5:],['up','-d','--build','web','db'])
            sites.lifecycle(self.root,'one','site-stop')
            self.assertEqual(run.call_args.args[0][-3:],['stop','web','db'])
            for call in run.call_args_list:
                self.assertNotIn('down',call.args[0]);self.assertNotIn('-v',call.args[0])
            with self.assertRaises(ValueError):sites.lifecycle(self.root,'one','exec')
            with self.assertRaises(ValueError):sites.lifecycle(self.root,'','site-start')
