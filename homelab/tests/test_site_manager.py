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
            sites.lifecycle(self.root,'one','site-db-start')
            self.assertEqual(run.call_args.args[0][-6:],['up','-d','--wait','--wait-timeout','90','db'])
            for call in run.call_args_list:
                self.assertNotIn('down',call.args[0]);self.assertNotIn('-v',call.args[0])
            with self.assertRaises(ValueError):sites.lifecycle(self.root,'one','exec')
            with self.assertRaises(ValueError):sites.lifecycle(self.root,'','site-start')


class PreviewTests(unittest.TestCase):
    setUp = SitesTests.setUp
    write = SitesTests.write

    def fake(self,args,**kwargs):
        import subprocess
        self.calls.append(args)
        if args[:3]==['docker','container','ls']:
            return subprocess.CompletedProcess(args,0,stdout=(b'maychu247-preview-one\n' if self.exists else b''),stderr=b'')
        if args[:3]==['docker','container','inspect']:
            info={'Config':{'Labels':{'io.maychu247.preview':self.owner},'Cmd':['tunnel','--no-autoupdate','--url','http://127.0.0.1:29990']},'HostConfig':{'NetworkMode':'host'}}
            return subprocess.CompletedProcess(args,0,stdout=json.dumps([info]).encode(),stderr=b'')
        if args[:2]==['docker','logs']:
            return subprocess.CompletedProcess(args,0,stdout=b'',stderr=b'LOG SECRET-DO-NOT-RETURN https://some-random-words.trycloudflare.com\n')
        return subprocess.CompletedProcess(args,0,stdout=b'',stderr=b'')
    def test_quick_tunnel_uses_fixed_origin_public_url_only_and_no_main_tunnel_change(self):
        self.calls=[];self.exists=False;self.owner='one'
        with patch.object(sites.subprocess,'run',side_effect=self.fake),patch.object(sites,'check',return_value={'ready':True}):
            result=sites.preview(self.root,'one','site-preview')
        self.assertEqual(result['url'],'https://some-random-words.trycloudflare.com')
        self.assertNotIn('SECRET',str(result))
        run=next(call for call in self.calls if call[:2]==['docker','run'])
        self.assertEqual(run[-4:],['tunnel','--no-autoupdate','--url','http://127.0.0.1:29990'])
        self.assertIn('--read-only',run);self.assertNotIn('-v',run)
        self.assertEqual(json.loads((self.target/'site.json').read_text())['preview_url'],result['url'])
    def test_stop_does_not_remove_or_alter_unowned_container(self):
        self.calls=[];self.exists=True;self.owner='someone-else'
        with patch.object(sites.subprocess,'run',side_effect=self.fake):
            with self.assertRaises(ValueError):sites.preview(self.root,'one','site-preview-stop')
        self.assertFalse(any(call[:2]==['docker','stop'] for call in self.calls))
    def test_stop_owned_preview_and_fail_closed_on_docker_error(self):
        import subprocess
        self.calls=[];self.exists=True;self.owner='one'
        with patch.object(sites.subprocess,'run',side_effect=self.fake):sites.preview(self.root,'one','site-preview-stop')
        self.assertIn(['docker','stop','maychu247-preview-one'],self.calls)
        with patch.object(sites.subprocess,'run',return_value=subprocess.CompletedProcess([],1,stdout=b'',stderr=b'error')):
            with self.assertRaises(RuntimeError):sites.preview(self.root,'one','site-preview-stop')
    def test_unready_origin_never_starts_public_tunnel(self):
        self.calls=[];self.exists=False;self.owner='one'
        with patch.object(sites.subprocess,'run',side_effect=self.fake),patch.object(sites,'check',return_value={'ready':False}):
            with self.assertRaises(ValueError):sites.preview(self.root,'one','site-preview')
        self.assertFalse(any(call[:2]==['docker','run'] for call in self.calls))
